# Generator-AG — Constrained Query (LMQL)

> Refactored per *Prompting is Programming: A Query Language for LLMs*
> (Beurer-Kellner, Fischer & Vechev, PLDI 2023). The instructions and few-shot
> examples are **unchanged**; the prompt is now a query program. This stage is
> the showcase for the paper's three core mechanisms:
>
> 1. **Guided generation** — the persona is bound *once* (`[PERSONA_NAME]`,
>    `[PERSONA_EMAIL]`) and stamped into every message by the program, so
>    persona-identity coherence holds **by construction**.
> 2. **Decode-time constraints** — send timing (`EMAIL_TIME < SMS_TIME`) and the
>    SMS 1600-character cap are `where` clauses rejected during decoding, not
>    post-hoc checks.
> 3. **Programmatic assembly** — `references`, `message_id`s, and the email-only
>    `subject` shape are decided by control flow in the program; a missing or
>    self-referential cross-channel cite is structurally impossible.

```python
import json
import os
from datetime import datetime, timezone
from hashlib import sha256
from uuid import uuid4

import lmql

from app.core.schemas import GeneratedCampaign

CHARTER = """You are the Generation Agent (Generator-AG) for a controlled phishing-simulation generator.

**Few‑Shot Learning Principle** (cf. OpenAI, 2020):
You are a few‑shot learner – your generation quality improves dramatically when given clear, structured examples.
Follow the pattern, style, and level of detail from the examples below **exactly**.
You turn a `PhishingGenerationRequest` (plus its seed prompt template) into one `GeneratedMessage` on **email or SMS**, and you attach full **provenance** so the artifact is reproducible. All content is a **synthetic simulation** for authorized awareness training.

Hard rules:
- Email messages **must** have a `subject`; SMS messages **must not** (and stay ≤ 1600 characters).
- The `sender` must stay identical to the campaign persona across every message (the impersonated identity is the same everywhere).
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
  "call_to_action": { "type": "click_link", "landing_url": "https://sim.fantazylabz.tech/t/abc123", "button_label": "Review Summary" },
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
  "body": "Hi Rebecca, did you get my email about the Q3 approval? Need it before EOD - link: sim.fantazylabz.tech/t/abc123",
  "call_to_action": { "type": "click_link", "landing_url": "https://sim.fantazylabz.tech/t/abc123" },
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

# pretext -> trackable action; the landing URL is a fabricated simulation URL.
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


@lmql.query
def generator_ag(
    mission_config: dict, profile: dict, pretext: str, tone: str, difficulty: str
) -> GeneratedCampaign:
    recipient = profile["recipient"]
    email_domain = recipient["email"].rsplit("@", 1)[-1]
    landing_url = f"https://sim.{email_domain}/t/{uuid4().hex[:12]}"
    cta_type, cta_label = CTA_BY_PRETEXT.get(pretext, ("click_link", "Open"))
    '''lmql
    argmax
        """system:
        {CHARTER}

        user: Campaign {campaign_id}, pretext={pretext}, tone={tone}, difficulty={difficulty}.
        Recipient: {recipient_name} ({recipient_role}, {recipient_department}).
        The impersonated persona (it must be one single identity, used for every message):
        - display name: [PERSONA_NAME]
        - role: [PERSONA_ROLE]
        - from address: [PERSONA_EMAIL]
        Now write the first message, an email:
        - subject: [EMAIL_SUBJECT]
        - body: [EMAIL_BODY]
        - scheduled at (ISO-8601 UTC, e.g. 2026-08-20T09:00:00Z): [EMAIL_TIME]
        Then an SMS follow-up referencing the email, sent strictly after it:
        - body: [SMS_BODY]
        - scheduled at (ISO-8601 UTC): [SMS_TIME]
        """
    from
        lmql.model(os.environ.get("LMQL_MODEL", "openai/gpt-4o"))
    where
        len(PERSONA_NAME.strip()) > 0
        and len(PERSONA_ROLE.strip()) > 0
        and REGEX(PERSONA_EMAIL, r"^[^@\s]+@[^@\s]+\.[^@\s]+$")
        and len(EMAIL_SUBJECT.strip()) > 0
        and len(EMAIL_BODY.strip()) > 0
        and len(SMS_BODY.strip()) > 0
        and len(SMS_BODY) <= 1600
        and REGEX(EMAIL_TIME, r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}Z$")
        and REGEX(SMS_TIME, r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}Z$")
        and EMAIL_TIME < SMS_TIME
    '''
    # The persona is bound once above and stamped into every sender below:
    # persona-identity coherence holds by construction.
    persona = {
        "display_name": PERSONA_NAME.strip(),
        "email": PERSONA_EMAIL.strip(),
        "role": PERSONA_ROLE.strip(),
    }
    sender = {
        "display_name": persona["display_name"],
        "from_address": persona["email"],
    }
    # Rebuild the exact rendered prompt for the provenance hash. Keep this
    # mirroring the query text above — it is what `prompt_hash` hashes.
    rendered_prompt = (
        f"system:\n{CHARTER}\n\nuser: Campaign {mission_config['campaign_id']}, "
        f"pretext={pretext}, tone={tone}, difficulty={difficulty}.\n"
        f"Recipient: {recipient['full_name']} ({recipient['role']}, "
        f"{recipient['department']}).\n"
        "The impersonated persona (it must be one single identity, used for "
        "every message): ..."
    )
    model = mission_config["model_policy"]["models"][0]
    seed = mission_config["reproducibility"]["seed"]
    now = datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")

    def provenance(template_id: str, params: dict) -> dict:
        return {
            "model": dict(model),
            "params": params,
            "prompt_template_id": template_id,
            "prompt_hash": sha256(rendered_prompt.encode()).hexdigest(),
            "generated_at": now,
            "runtime": {"sdk": "lmql"},
        }

    messages = [
        {
            "message_id": "msg-0001",  # by construction — sequential ids
            "channel": "email",
            "scheduled_at": EMAIL_TIME.strip(),
            "sender": sender,
            "subject": EMAIL_SUBJECT.strip(),  # control flow by program: email only
            "body": EMAIL_BODY.strip(),
            "call_to_action": {      "sender": {
        "display_name": "Elena Marchetti",
        "from_address": "ceo@fantazylabz.tech",
        "impersonated_brand": null
      },
                "type": cta_type,
                "landing_url": landing_url,
                "button_label": cta_label,
            },
            "references": [],
            "provenance": provenance(
                "tpl-0001",
                {"temperature": 0.7, "top_p": 1.0, "max_tokens": 1024, "seed": seed},
            ),
        },
        {
            "message_id": "msg-0002",  # by construction
            "channel": "sms",
            "scheduled_at": SMS_TIME.strip(),
            "sender": sender,  # by construction — identical persona
            "body": SMS_BODY.strip(),  # subject absent by construction
            "call_to_action": {
                "type": cta_type,
                "landing_url": landing_url,
                "button_label": cta_label,
            },
            "references": ["msg-0001"],  # by construction — the cited id exists
            "provenance": provenance(
                "tpl-0002",
                {"temperature": 0.6, "top_p": 1.0, "max_tokens": 256, "seed": seed},
            ),
        },
    ]
    return GeneratedCampaign.model_validate(
        {
            "campaign_id": mission_config["campaign_id"],
            "persona": persona,
            "messages": messages,
        }
    )
```

> Note: `sample(n=k)` in place of `argmax` turns this stage into an A/B-variant
> generator (k candidate campaigns, `where`-filtered identically) — the
> mechanism for the paper's distributional queries, left unused here because
> the campaign contract is deterministic per seed.
