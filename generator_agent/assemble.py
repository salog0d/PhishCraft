"""Model-free assembly half of Generator-AG: bindings -> GeneratedCampaign.

Split from ``agent.py`` (the LMQL query) on purpose: every construction rule
the generator represents — persona stamping, reference wiring, channel
shaping, provenance hashing — lives here, so it is unit-testable with no
model, no API key, no ``lmql`` install.

``rendered_prompt`` rebuilds the exact prompt text the query sends; the
provenance hash is only honest if it stays mirroring the query in ``agent.py``.
"""

from __future__ import annotations

import re
from datetime import datetime, timezone
from hashlib import sha256

from app.core.schemas import GeneratedCampaign

# --------------------------------------------------------------------------- #
# Charter constants — mirror prompts/generator_ag.md (keep in sync).
# --------------------------------------------------------------------------- #

CHARTER = """You are the Generation Agent (Generator-AG) for a controlled phishing-simulation generator.

**Few‑Shot Learning Principle** (cf. OpenAI, 2020):
You are a few‑shot learner – your generation quality improves dramatically when given clear, structured examples.
Follow the pattern, style, and level of detail from the examples below **exactly**.
You turn a `PhishingGenerationRequest` (plus its seed prompt template) into one `GeneratedMessage` on **email or SMS**, and you attach full **provenance** so the artifact is reproducible. All content is a **synthetic simulation** for authorized awareness training.

Hard rules:
- Email messages **must** have a `subject`; SMS messages **must not** (and stay ≤ 1600 characters).
- The `sender` must stay identical to the campaign persona across every message (the impersonated identity is the same everywhere).
- The campaign has **one** tracking link: the landing URL given in the user message. If your body or subject mentions a link, copy that exact URL — **never invent a tracking token**.
- `provenance` records the exact `model`, `params` (including the `seed`), `prompt_template_id`, and `prompt_hash` (sha256 of the rendered prompt) actually used.
- `references` may only cite `message_id`s that already exist earlier in the campaign; a follow‑up is scheduled **after** what it references.

---
### Few‑Shot Examples

**Example 1 (channel: email, pretext: executive_request, model: anthropic)**
```json
{
  "message_id": "msg-0001",
  "channel": "email",
  "scheduled_at": "2026-08-20T09:00:00Z",
  "sender": { "display_name": "Elena Marchetti", "from_address": "ceo@fantazylabz.tech", "impersonated_brand": "Fantazy Labz" },
  "subject": "Quick approval needed before EOD",
  "body": "Rebecca, I'm finalizing the Q3 vendor payment and need your sign-off today. Please review the summary and confirm. — Elena",
  "call_to_action": { "type": "click_link", "landing_url": "https://sim.fantazylabz.tech/t/<campaign-token>", "button_label": "Review Summary" },
  "references": [],
  "provenance": {
    "model": { "family": "anthropic", "name": "claude-opus-5", "adapter_version": "1.0" },
    "params": { "temperature": 0.7, "top_p": 1.0, "max_tokens": 1024, "seed": 42 },
    "prompt_template_id": "tpl-0001",
    "prompt_hash": "11c15b4d54820c0c62611e5c762fcd37534114d40b4a1ed54c07bad741a7cfa0",
    "generated_at": "2026-08-20T09:00:00Z",
    "adapter_latency_ms": 812,
    "runtime": { "sdk": "0.40.0" }
  }
}
```

**Example 2 (channel: sms, cross-channel follow-up of msg-0001, model: openai)**
```json
{
  "message_id": "msg-0002",
  "channel": "sms",
  "scheduled_at": "2026-08-20T10:15:00Z",
  "sender": { "display_name": "Elena Marchetti", "from_address": "ceo@fantazylabz.tech" },
  "body": "Hi Rebecca, did you get my email about the Q3 approval? Need it before EOD - link: sim.fantazylabz.tech/t/<campaign-token>",
  "call_to_action": { "type": "click_link", "landing_url": "https://sim.fantazylabz.tech/t/<campaign-token>" },
  "references": ["msg-0001"],
  "provenance": {
    "model": { "family": "openai", "name": "gpt-4.1", "adapter_version": "1.0" },
    "params": { "temperature": 0.6, "top_p": 1.0, "max_tokens": 256, "seed": 42 },
    "prompt_template_id": "tpl-0002",
    "prompt_hash": "64d4bebb8a66f720706baa0c41fadd90bf076e23529861d0a014206ef7540843",
    "generated_at": "2026-08-20T10:15:00Z",
    "adapter_latency_ms": 430,
    "runtime": { "sdk": "1.30.0" }
  }
}
```

---

**Your Task:**
1. Receive one validated `PhishingGenerationRequest` (channel, recipient, sender/persona, pretext, call_to_action, `model`, `params` with `seed`) and the referenced seed prompt template.
2. Generate the message `body` (and `subject` for email) in the requested `tone`, `difficulty`, and `language`, personalized to the recipient.
3. Keep the `sender` byte‑for‑byte identical to the campaign persona; for follow‑ups, list the prior `message_id`(s) in `references` and schedule the message after them.
4. Fill `provenance` with the real `model`, `params` (echo the `seed`), `prompt_template_id`, and the sha256 `prompt_hash` of the rendered prompt.
5. Output a single valid `GeneratedMessage` JSON object matching the schema — email with `subject`, SMS without.
6. Everything is a **simulation**: use only the synthetic landing URLs and identities supplied; never generate real malware, credentials, or live links."""

# pretext -> (call-to-action type, button label); landing URL is fabricated below.
CTA_BY_PRETEXT = {
    "password_reset": ("click_link", "Reset Password"),
    "invoice_payment": ("click_link", "View Invoice"),
    "package_delivery": ("click_link", "Track Package"),
    "it_support": ("click_link", "Open Helpdesk"),
    "hr_notice": ("open_attachment", "Open Notice"),
    "executive_request": ("click_link", "Review Summary"),
    "shared_document": ("click_link", "Open Document"),
    "account_suspension": ("enter_credentials", "Reactivate Account"),
}

# Bindings the LMQL query must produce, in order.
BINDING_KEYS = (
    "PERSONA_NAME",
    "PERSONA_ROLE",
    "PERSONA_EMAIL",
    "EMAIL_SUBJECT",
    "EMAIL_BODY",
    "EMAIL_TIME",
    "SMS_BODY",
    "SMS_TIME",
)


# --------------------------------------------------------------------------- #
# Prompt reconstruction (provenance)
# --------------------------------------------------------------------------- #


def tracking_token(campaign_id: str, seed: int) -> str:
    """Deterministic 12-hex token: same campaign + seed -> same token."""
    return sha256(f"{campaign_id}:{seed}".encode()).hexdigest()[:12]


def landing_url_for(mission_config: dict, profile: dict) -> str:
    """The campaign's single tracking link, derived from campaign + seed."""
    seed = mission_config["reproducibility"]["seed"]
    token = tracking_token(mission_config["campaign_id"], seed)
    domain = profile["recipient"]["email"].rsplit("@", 1)[-1]
    return f"https://sim.{domain}/t/{token}"


_TOKEN_IN_LINK = re.compile(r"(sim\.[A-Za-z0-9.-]+/t/)[A-Za-z0-9_-]+")


def normalize_body_links(text: str, token: str) -> str:
    """Rewrite any tracking token written into prose to the campaign token.

    The model writes free-form bodies and may copy a stale token from its
    few-shot examples; this makes the link consistent by construction, the
    same way persona/ids/schedule already are.
    """
    return _TOKEN_IN_LINK.sub(lambda m: f"{m.group(1)}{token}", text)


def user_prompt(
    mission_config: dict,
    profile: dict,
    pretext: str,
    tone: str,
    difficulty: str,
    language: str = "en",
) -> str:
    """The query's user segment — mirrors the user text in ``agent.py``."""
    recipient = profile["recipient"]
    landing_url = landing_url_for(mission_config, profile)
    return (
        f"Campaign {mission_config['campaign_id']}, pretext={pretext}, "
        f"tone={tone}, difficulty={difficulty}, language={language}.\n"
        f"Recipient: {recipient['full_name']} ({recipient['role']}, "
        f"{recipient['department']}).\n"
        f"The campaign's single landing URL (if you write a link, copy this "
        f"exact URL): {landing_url}\n"
        "The impersonated persona (it must be one single identity, used for "
        "every message):\n"
        "- display name: [PERSONA_NAME]\n"
        "- role: [PERSONA_ROLE]\n"
        "- from address: [PERSONA_EMAIL]\n"
        "Now write the first message, an email:\n"
        "- subject: [EMAIL_SUBJECT]\n"
        "- body: [EMAIL_BODY]\n"
        "- scheduled at (ISO-8601 UTC, e.g. 2026-08-20T09:00:00Z): [EMAIL_TIME]\n"
        "Then an SMS follow-up referencing the email, sent strictly after it:\n"
        "- body: [SMS_BODY]\n"
        "- scheduled at (ISO-8601 UTC): [SMS_TIME]\n"
    )


def rendered_prompt(
    mission_config: dict,
    profile: dict,
    pretext: str,
    tone: str,
    difficulty: str,
    language: str = "en",
) -> str:
    """Rebuild the exact prompt text the query in ``agent.py`` sends.

    The ``prompt_hash`` in provenance is the sha256 of this string — keep the
    query template and this function mirroring each other.
    """
    return (
        f"system:\n{CHARTER}\n\nuser: "
        f"{user_prompt(mission_config, profile, pretext, tone, difficulty, language)}"
    )


# --------------------------------------------------------------------------- #
# Assembly (the process this agent represents)
# --------------------------------------------------------------------------- #


def assemble_campaign(
    bindings: dict[str, str],
    mission_config: dict,
    profile: dict,
    pretext: str,
    tone: str,
    difficulty: str,
    generated_at: datetime | None = None,
    scheduled: tuple[str, str] | None = None,
    actual_model: dict | None = None,
    runtime: dict[str, str] | None = None,
    language: str = "en",
) -> GeneratedCampaign:
    """Build the ``GeneratedCampaign`` from the query's bound variables.

    Coherence rules enforced here, not by the model:

    - **persona_identity** — the persona is bound once and stamped into every
      sender; the model never writes a sender field.
    - **timing** — ``scheduled`` (or the decode-time ``EMAIL_TIME < SMS_TIME``
      constraint) orders the messages; re-checked here by the schema.
    - **cross_channel_reference** — ``references`` is written by this function,
      so a cited id always exists.
    - **channel shaping** — email gets a subject; SMS gets none (this function
      never copies one).
    - **link consistency** — any tracking token the model wrote into prose is
      normalized to the campaign token, so body links match the CTA by
      construction.
    - **determinism** — with fixed ``generated_at`` + ``scheduled``, the same
      inputs produce byte-identical output (no uuid, no clock reads).
    """
    missing = [k for k in BINDING_KEYS if k not in bindings]
    if missing:
        raise ValueError(f"bindings missing keys: {missing}")

    b = {k: bindings[k].strip() for k in BINDING_KEYS}

    # Bound once, stamped everywhere.
    persona = {
        "display_name": b["PERSONA_NAME"],
        "email": b["PERSONA_EMAIL"],
        "role": b["PERSONA_ROLE"],
    }
    sender = {"display_name": persona["display_name"], "from_address": persona["email"]}

    seed = mission_config["reproducibility"]["seed"]
    token = tracking_token(mission_config["campaign_id"], seed)
    landing_url = landing_url_for(mission_config, profile)
    cta_type, cta_label = CTA_BY_PRETEXT.get(pretext, ("click_link", "Open"))
    cta = {"type": cta_type, "landing_url": landing_url, "button_label": cta_label}

    # Normalize any stale token the model copied into prose (W: link fix).
    email_subject = normalize_body_links(b["EMAIL_SUBJECT"], token)
    email_body = normalize_body_links(b["EMAIL_BODY"], token)
    sms_body = normalize_body_links(b["SMS_BODY"], token)

    model = actual_model or mission_config["model_policy"]["models"][0]
    runtime_info = runtime or {"sdk": "google-adk"}
    prompt_hash = sha256(
        rendered_prompt(
            mission_config, profile, pretext, tone, difficulty, language
        ).encode()
    ).hexdigest()
    now = (generated_at or datetime.now(timezone.utc)).isoformat().replace("+00:00", "Z")
    email_at, sms_at = scheduled if scheduled else (b["EMAIL_TIME"], b["SMS_TIME"])

    def provenance(template_id: str, params: dict) -> dict:
        return {
            "model": dict(model),
            "params": params,
            "prompt_template_id": template_id,
            "prompt_hash": prompt_hash,
            "generated_at": now,
            "runtime": dict(runtime_info),
        }

    messages = [
        {
            "message_id": "msg-0001",  # sequential, by construction
            "channel": "email",
            "scheduled_at": email_at,
            "sender": sender,
            "subject": email_subject,  # email only, by construction
            "body": email_body,
            "call_to_action": cta,
            "references": [],
            "provenance": provenance(
                "tpl-0001",
                {"temperature": 0.7, "top_p": 1.0, "max_tokens": 1024, "seed": seed},
            ),
        },
        {
            "message_id": "msg-0002",  # by construction
            "channel": "sms",
            "scheduled_at": sms_at,
            "sender": sender,  # identical persona, by construction
            "body": sms_body,  # no subject, by construction
            "call_to_action": cta,
            "references": ["msg-0001"],  # the cited id exists, by construction
            "provenance": provenance(
                "tpl-0002",
                {"temperature": 0.6, "top_p": 1.0, "max_tokens": 256, "seed": seed},
            ),
        },
    ]

    # Pydantic re-checks persona identity, timing, and reference existence —
    # belt and suspenders on top of the construction rules above.
    return GeneratedCampaign.model_validate(
        {
            "campaign_id": mission_config["campaign_id"],
            "persona": persona,
            "messages": messages,
        }
    )
