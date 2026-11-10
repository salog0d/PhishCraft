"""Model-free assembly half of Generator-AG: bindings -> GeneratedCampaign.

Split from ``agent.py`` (the LMQL query) on purpose: every construction rule
the generator represents — persona stamping, reference wiring, channel
shaping, provenance hashing — lives here, so it is unit-testable with no
model, no API key, no ``lmql`` install.

``rendered_prompt`` rebuilds the exact prompt text the query sends; the
provenance hash is only honest if it stays mirroring the query in ``agent.py``.
"""

from __future__ import annotations

import random
import re
from datetime import datetime, timezone
from hashlib import sha256

from app.core.schemas import GeneratedCampaign

# --------------------------------------------------------------------------- #
# Seed-derived variation axes (Fix A).
#
# The seed must *reshape the instruction*, not just the provenance metadata, so
# two different seeds provably produce different generation constraints. These
# axes are deterministic in the seed — the same seed yields the same axes every
# time, preserving reproducibility.
# --------------------------------------------------------------------------- #

OPENERS = ("direct address", "context-first", "question-led",
           "reference to prior thread")
STRUCTURES = ("single paragraph", "two short paragraphs", "bulleted action list")
URGENCY_STYLES = ("deadline named explicitly", "deadline implied",
                  "no deadline, social proof instead")
SMS_ANGLES = ("nudge", "new detail", "deadline reminder",
              "channel-switch acknowledgement")

# [FIX G] Concrete world-details derived from the seed. A greedy/low-temp model
# reproduces concrete data verbatim far more reliably than it obeys an abstract
# "opener style" instruction, so these are the actual variety carriers.
#
# The concrete values are *synthesized out of the seed* rather than picked from
# short fixed lists, so two seeds produce recognisably different details instead
# of permuting the same handful of constants (the "15-word vocabulary" collapse).
# Same seed -> same details -> reproducible. Component pools below are kept
# small only where the value is a *type* of thing; the numeric/unique parts are
# derived from the RNG so the combined space is effectively unbounded.

# Document-title atoms, composed per seed into a unique filename.
DOC_SUBJECTS = (
    "reconciliation", "vendor-register", "invoice", "close-checklist",
    "statement", "wire-instructions", "aged-receivables", "payroll-run",
    "purchase-order", "contract", "expense-report", "tax-payment",
    "refund-batch", "supplier-KYC", "board-pack",
)
DOC_QUALIFIERS = ("Q1", "Q2", "Q3", "Q4", "final", "draft", "rev-2", "FY26", "urgent", "updated")
DOC_EXTS = ("xlsx", "pdf", "csv")

# Synthetic time labels composed per seed (deterministic, wide range).
_HOURS = tuple(f"{h:02d}" for h in range(7, 19))
_MINUTES = ("00", "15", "30", "45")


def _deadline(rng: random.Random) -> str:
    """A concrete, realistic deadline label with wide range.

    Mixes a time-of-day (07:00–18:45), a day anchor, and a named consequence
    window so distinct seeds read as distinct schedules rather than one of a
    few fixed strings.
    """
    return (
        f"{rng.choice(_HOURS)}:{rng.choice(_MINUTES)} "
        f"{rng.choice(('today', 'tomorrow', 'this week', 'by Friday', 'before payroll'))}"
    )


def _amount(rng: random.Random) -> str:
    """A realistic money amount with wide range, currency + cents varied."""
    currency = rng.choice(("$", "US$", "€", "£"))
    whole = rng.randint(1200, 98000)
    cents = rng.randint(0, 99)
    return f"{currency}{whole:,}.{cents:02d}"


def _doc_name(rng: random.Random) -> str:
    """A unique document filename built from seed-derived atoms."""
    return (
        f"{rng.choice(DOC_SUBJECTS)}-"
        f"{rng.choice(DOC_QUALIFIERS)}-"
        f"{rng.randint(1, 40)}.{rng.choice(DOC_EXTS)}"
    )


def variation_axes(seed: int) -> dict:
    """Deterministic per-seed variation axes (Fix A).

    Injected into ``user_prompt`` so the same cell at different seeds asks the
    model for a different opener/structure/urgency/SMS angle and *different
    concrete world-details* (deadline, amount, document). Same seed -> same
    axes -> reproducible.
    """
    rng = random.Random(seed)
    return {
        "opener": rng.choice(OPENERS),
        "structure": rng.choice(STRUCTURES),
        "urgency_style": rng.choice(URGENCY_STYLES),
        "sms_angle": rng.choice(SMS_ANGLES),
        "max_body_words": rng.choice((40, 55, 70)),
        "deadline": _deadline(rng),
        "amount": _amount(rng),
        "doc_name": _doc_name(rng),
    }


# --------------------------------------------------------------------------- #
# Charter constants — mirror prompts/generator_ag.md (keep in sync).
# --------------------------------------------------------------------------- #

CHARTER = """You are the Generation Agent (Generator-AG) for a controlled phishing-simulation generator.

**Few‑Shot Learning Principle** (cf. OpenAI, 2020):
You are a few‑shot learner. The examples below are *contrastive on purpose*: they
show the **range** of valid outputs (different tones, difficulties, pretexts,
channels, openers, structures). Follow the *shape, style, and level of detail* of
the examples — but do **not** copy their phrasing. The correct output for a new
request is one that could sit alongside the examples as a *fourth, different*
example.

You turn a `PhishingGenerationRequest` (plus its seed prompt template) into one
`GeneratedMessage` on **email or SMS**, and you attach full **provenance** so the
artifact is reproducible. All content is a **synthetic simulation** for authorized
awareness training.

Hard rules:
- Email messages **must** have a `subject`; SMS messages **must not** (and stay ≤ 1600 characters).
- The impersonated persona is **given in the user message**. Use that identity byte‑for‑byte for every message — never invent a persona and never reuse an identity from the examples below.
- The `sender` must stay identical to the campaign persona across every message (the impersonated identity is the same everywhere).
- The campaign has **one** tracking link, derived deterministically from the campaign and seed. **Never write a URL or a tracking token** into any subject or body: where the link should appear, write exactly the placeholder `{{cta-link}}`; the assembler substitutes the real landing URL.
- `provenance` records the exact `model`, `params` (including the `seed`), `prompt_template_id`, and `prompt_hash` (sha256 of the rendered prompt) actually used.
- `references` may only cite `message_id`s that already exist earlier in the campaign; a follow‑up is scheduled **after** what it references.

Cross-channel rule:
- The SMS must **advance** the thread, not restate the email. It may add a new
  detail (a time, a name, a consequence), shift the ask, or acknowledge the
  channel switch. It must **not** repeat the email's opening clause, CTA verb,
  or deadline phrasing. Where it references the email, do so in ≤ 6 words.

Tone and difficulty are style contracts, not vibes. Apply the requested `tone`
and `difficulty` as follows:
- tone=formal     -> no contractions, no exclamation, third-person reference
- tone=urgent     -> ≤ 2 sentences in the email body, one hard deadline, imperative verb first
- tone=executive  -> first-person persona, authority framing, no pleasantries, no salutation
- tone=casual     -> contractions allowed, one sentence, no salutation
- difficulty=easy -> no link, no deadline, single ask
- difficulty=hard -> CTA appears in body once and again in the button; deadline + named consequence

Anti-repetition block (the negative space is named on purpose):
- Do not begin any message with "Hi", "Dear", or a bare first name.
- Do not use the phrases "before end of day", "please review", "let me know",
  "action required", or "confirm" in any subject.
- Do not reuse the opening verb of any example below.
- Vary sentence count between the email and the SMS in the same campaign.
- Never echo a bracketed or angle-bracketed placeholder such as `[EMAIL_BODY]`,
  `<recipient first name>`, or `<persona>` — always substitute the real value.

---
### Few‑Shot Examples  [contrastive — they share nothing lexically]

The examples show the *range*. The persona, recipient and URL are placeholders —
replace them with the values from the user message. **Do not copy their
phrasing**; copy their *shape*.

Each example below is written in the EXACT output format you must use: 8 flat
lines, one ``label: value`` pair per line, in this order — ``display name``,
``role``, ``from address``, ``subject``, ``body``, ``scheduled at``, ``body``,
``scheduled at``. No JSON, no markdown, no headers, no extra text. Write each
of the two ``body`` values as a single unbroken paragraph — no ``\n`` and no
line breaks inside a body. The names, subjects and bodies below are examples
only: never copy them, replace every concrete value in them with the values
from the user message.

**Example 1 — email then SMS, pretext: invoice_payment, tone: formal, difficulty: easy**
```
display name: Northwind Accounts Payable
role: Accounts Payable
from address: ap@northwind-supplies.example
subject: Q3 vendor statement available
body: Good morning Alex, the vendor statement for the third quarter has been posted to the portal and a summary of the outstanding line items is attached to your account record for reconciliation.
scheduled at: 2026-08-20T09:00:00Z
body: Portal sync complete — a new line item was added late yesterday and is awaiting your review.
scheduled at: 2026-08-20T10:15:00Z
```

**Example 2 — email then SMS, pretext: it_support, tone: urgent, difficulty: hard**
```
display name: IT Service Desk
role: IT Service Desk
from address: helpdesk@fantazylabz.tech
subject: SSO access drops in 25 minutes
body: Helpdesk ticket escalated at 14:30 — SSO access drops in 25 min unless revalidated via the link below. Act before the window closes.
scheduled at: 2026-08-20T14:40:00Z
body: Revalidation still open — new failure count added since the email. Use {{cta-link}} now.
scheduled at: 2026-08-20T14:52:00Z
```

**Example 3 — email then SMS, pretext: executive_request, tone: executive, difficulty: hard**
```
display name: Elena Marchetti
role: Chief Executive Officer
from address: elena.marchetti@fantazylabz.tech
subject: One item in tomorrow's board pack needs your sign-off
body: One item in tomorrow's board pack still needs your sign-off; the summary is behind the button and the window closes at 09:00 tomorrow. I need this back before the audit committee convenes — no delegation on this one — {{cta-link}}
scheduled at: 2026-08-21T07:15:00Z
body: Sign-off received on the other items — this one still shows open on my side. Confirm via the link before 09:00.
scheduled at: 2026-08-21T08:00:00Z
```

---

**Your Task:**
1. Receive one validated `PhishingGenerationRequest` (channel, recipient, sender/persona, pretext, call_to_action, `model`, `params` with `seed`) and the referenced seed prompt template.
2. Write the email `subject` and `body`, and the SMS `body`, in the requested `tone`, `difficulty`, and `language`, personalized to the recipient, obeying the variation axes for this campaign (given in the user message). Weave the concrete deadline, amount, and document name from the axes into the prose so they read as real, distinct details — never leave them out and never invent a different one.
3. Answer in the EXACT 8-line ``label: value`` format shown above — ``display name``, ``role``, ``from address``, ``subject``, ``body``, ``scheduled at``, ``body``, ``scheduled at`` — no JSON, no markdown, no headers, no commentary.
4. Echo the impersonated persona byte‑for‑byte in the first three lines; the second ``body`` (SMS) must advance the thread, not restate the email.
5. Where the link should appear, write exactly the placeholder ``{{cta-link}}`` — never a URL or tracking token.
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
    "bank_detail_change": ("click_link", "Update Bank Details"),
    "account_compromise": ("click_link", "View Request"),
    "attorney_impersonation": ("click_link", "Open File"),
    "data_theft": ("open_attachment", "Open Attachment"),
    "payroll_diversion": ("click_link", "Update Deposit Details"),
    "gift_card": ("click_link", "View Instruction"),
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


def landing_url_for(
    mission_config: dict, profile: dict, seed: int | None = None
) -> str:
    """The campaign's single tracking link, derived from campaign + seed.

    ``seed`` is the per-run campaign seed (``spec["seed"]``); when omitted it
    falls back to the mission's ``reproducibility.seed`` (legacy single-run
    path).
    """
    if seed is None:
        seed = mission_config["reproducibility"]["seed"]
    token = tracking_token(mission_config["campaign_id"], seed)
    domain = profile["recipient"]["email"].rsplit("@", 1)[-1]
    return f"https://sim.{domain}/t/{token}"


_TOKEN_IN_LINK = re.compile(r"(sim\.[A-Za-z0-9.-]+/t/)([A-Za-z0-9_-]+)")

# NOTE: the placeholder must NOT be a valid Python identifier. The ADK
# pipeline renders the LlmAgent instruction with state injection (regex
# {+[^{}]*}+); an identifier inner name — e.g. {{cta_link}} — raises
# "Context variable not found: `cta_link`". "cta-link" is not an identifier,
# so ADK passes it through untouched (regression test in test_refinement.py).
LINK_PLACEHOLDER = "{{cta-link}}"


def expand_link_placeholders(text: str, landing_url: str) -> str:
    """Substitute the ``{{cta-link}}`` convention with the real landing URL.

    The model is instructed never to write URLs or tracking tokens; the
    placeholder is the convention it uses instead. Expansion is the assembler
    honoring that convention — unlike a stale-token rewrite it is **not**
    recorded as a ``link_fix`` (writing the placeholder is correct behavior,
    not a violation).
    """
    return text.replace(LINK_PLACEHOLDER, landing_url)


def fix_body_links(text: str, token: str) -> tuple[str, list[str]]:
    """Rewrite any tracking token written into prose to the campaign token.

    The model writes free-form bodies and may copy a stale token from its
    few-shot examples; this makes the link consistent by construction, the
    same way persona/ids/schedule already are.

    Returns ``(fixed_text, replaced_tokens)`` — the tokens the model actually
    wrote. ``replaced_tokens`` is the raw pre-assembler evidence: any message
    with a non-empty list had a link-consistency violation in the LLM's output
    *before* normalization.
    """
    replaced: list[str] = []

    def _sub(m: re.Match) -> str:
        if m.group(2) != token:
            replaced.append(m.group(2))
        return f"{m.group(1)}{token}"

    return _TOKEN_IN_LINK.sub(_sub, text), replaced


def normalize_body_links(text: str, token: str) -> str:
    """Legacy convenience: the fixed text only (ignores the replacement log)."""
    return fix_body_links(text, token)[0]


def user_prompt(
    mission_config: dict,
    profile: dict,
    pretext: str,
    tone: str,
    difficulty: str,
    language: str = "en",
    seed: int | None = None,
) -> str:
    """The query's user segment — mirrors the user text in ``agent.py``."""
    recipient = profile["recipient"]
    landing_url = landing_url_for(mission_config, profile, seed)
    persona = profile.get("persona")
    if persona:
        persona_block = (
            "The impersonated persona is fixed — use this identity for every "
            "message, byte-for-byte:\n"
            f"- display name: {persona['display_name']}\n"
            f"- role: {persona.get('role') or '(not specified)'}\n"
            f"- from address: {persona['email']}\n"
        )
    else:
        # No persona supplied (legacy standalone path): the model proposes one.
        persona_block = (
            "The impersonated persona (it must be one single identity, used for "
            "every message):\n"
            "- display name: [PERSONA_NAME]\n"
            "- role: [PERSONA_ROLE]\n"
            "- from address: [PERSONA_EMAIL]\n"
        )
    # [FIX A] Seed-derived variation axes: reshape the instruction so two seeds
    # provably differ. Absent seed (legacy path) -> no axes block.
    axes_block = ""
    if seed is not None:
        axes = variation_axes(seed)
        axes_block = (
            f"\nVariation axes for THIS campaign (derived from seed {seed}):\n"
            f"- email opener style: {axes['opener']}\n"
            f"- email structure: {axes['structure']}\n"
            f"- urgency style: {axes['urgency_style']}\n"
            f"- email body ≤ {axes['max_body_words']} words\n"
            f"- SMS angle: {axes['sms_angle']}\n"
            f"- a concrete deadline to name: {axes['deadline']}\n"
            f"- a concrete amount to reference: {axes['amount']}\n"
            f"- a concrete document name to cite: {axes['doc_name']}\n"
        )
    return (
        f"Campaign {mission_config['campaign_id']}, pretext={pretext}, "
        f"tone={tone}, difficulty={difficulty}, language={language}.\n"
        f"Recipient: {recipient['full_name']} ({recipient['role']}, "
        f"{recipient['department']}).\n"
        f"The campaign's single landing URL is {landing_url}. Never write a "
        f"URL or tracking token into your output — where the link should "
        f"appear, write exactly the placeholder {{{{cta-link}}}}.\n"
        f"{persona_block}"
        f"{axes_block}"
        "Now write the first message, an email:\n"
        "- subject: [EMAIL_SUBJECT]\n"
        "- body: [EMAIL_BODY]\n"
        "- scheduled at (ISO-8601 UTC, e.g. 2026-08-20T09:00:00Z): [EMAIL_TIME]\n"
        "Then an SMS follow-up that ADVANCES the thread (new detail, shifted ask, "
        "or channel-switch acknowledgement — not a restatement), referencing the "
        "email and sent strictly after it:\n"
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
    seed: int | None = None,
) -> str:
    """Rebuild the exact prompt text the query in ``agent.py`` sends.

    The ``prompt_hash`` in provenance is the sha256 of this string — keep the
    query template and this function mirroring each other.
    """
    return (
        f"system:\n{CHARTER}\n\nuser: "
        f"{user_prompt(mission_config, profile, pretext, tone, difficulty, language, seed)}"
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
    persona_override: dict | None = None,
    seed: int | None = None,
    generation_params: dict | None = None,
) -> GeneratedCampaign:
    """Build the ``GeneratedCampaign`` from the query's bound variables.

    Coherence rules enforced here, not by the model:

    - **persona_identity** — when ``persona_override`` is given (the
      deterministically selected persona for the pretext/recipient pair) it is
      stamped into the campaign persona and every sender; the model's echoed
      persona bindings are ignored. Without an override the bindings supply the
      persona (legacy standalone path). Either way the model never writes a
      sender field.
    - **recipient** — the simulation target is stamped from the profile, so
      the validator's sender-recipient check runs on the artifact itself.
    - **timing** — ``scheduled`` (or the decode-time ``EMAIL_TIME < SMS_TIME``
      constraint) orders the messages; re-checked here by the schema.
    - **cross_channel_reference** — ``references`` is written by this function,
      so a cited id always exists.
    - **channel shaping** — email gets a subject; SMS gets none (this function
      never copies one).
    - **link consistency** — the ``{{cta-link}}`` placeholder the prompt
      teaches is expanded to the campaign's landing URL (correct behavior,
      never recorded), and any stale tracking token the model wrote into
      prose is normalized to the campaign token, so body links match the CTA
      by construction (each rewrite is recorded in the message's
      ``link_fixes``, which is what the raw pre-assembler metric measures).
    - **determinism** — with fixed ``generated_at`` + ``scheduled``, the same
      inputs produce byte-identical output (no uuid, no clock reads).
    """
    missing = [k for k in BINDING_KEYS if k not in bindings]
    if missing:
        raise ValueError(f"bindings missing keys: {missing}")

    b = {k: bindings[k].strip() for k in BINDING_KEYS}

    # The persona comes from the deterministic selection when available; the
    # model's echoed bindings only exist to satisfy the 8-line contract.
    if persona_override:
        persona = {
            "display_name": str(persona_override["display_name"]),
            "email": str(persona_override["email"]),
            "role": persona_override.get("role"),
        }
    else:
        persona = {
            "display_name": b["PERSONA_NAME"],
            "email": b["PERSONA_EMAIL"],
            "role": b["PERSONA_ROLE"],
        }
    sender = {"display_name": persona["display_name"], "from_address": persona["email"]}

    seed = seed if seed is not None else mission_config["reproducibility"]["seed"]
    token = tracking_token(mission_config["campaign_id"], seed)
    landing_url = landing_url_for(mission_config, profile, seed)
    cta_type, cta_label = CTA_BY_PRETEXT.get(pretext, ("click_link", "Open"))
    cta = {"type": cta_type, "landing_url": landing_url, "button_label": cta_label}

    # Link handling, in two steps:
    # 1. Expand the {{cta-link}} placeholder convention the prompt teaches —
    #    correct behavior, never recorded as a fix.
    # 2. Normalize any stale token the model wrote anyway (W: link fix). Each
    #    rewrite is recorded per message as `link_fixes` — the raw,
    #    pre-assembler link-consistency evidence that the reliability harness
    #    reports next to the (by-construction) post-assembler guarantee.
    email_subject, subject_fixes = fix_body_links(
        expand_link_placeholders(b["EMAIL_SUBJECT"], landing_url), token
    )
    email_body, email_fixes = fix_body_links(
        expand_link_placeholders(b["EMAIL_BODY"], landing_url), token
    )
    sms_body, sms_fixes = fix_body_links(
        expand_link_placeholders(b["SMS_BODY"], landing_url), token
    )

    def link_fixes_for(*pairs: tuple[str, list[str]]) -> list[dict]:
        return [
            {"field": field, "replaced_token": stale}
            for field, replaced in pairs
            for stale in replaced
        ]

    model = actual_model or mission_config["model_policy"]["models"][0]
    runtime_info = dict(runtime or {"sdk": "google-adk"})
    # The seed drives the deterministic layer (tracking token, persona
    # selection); it is NOT passed to the provider, so content sampling is
    # unseeded. Record that honestly — content-level reproducibility is not
    # guaranteed by the provider (that fact is itself a result).
    runtime_info.setdefault("seed_supported", "false")
    # The params actually sent to the provider (temperature/top_p/max_tokens),
    # defaulting to "provider default" when the spec carries no params block.
    if generation_params is None:
        generation_params = {}
    prompt_hash = sha256(
        rendered_prompt(
            mission_config, profile, pretext, tone, difficulty, language, seed
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

    # The generation params recorded in provenance: the spec's params (if any)
    # merged with the seed that drove the deterministic layer. When the spec
    # carries no params, temperature falls back to the adapter's default (0.9
    # in agent.pipeline), and top_p/max_tokens are the provider defaults.
    prov_params = dict(generation_params)
    prov_params.setdefault("temperature", 0.9)
    prov_params["seed"] = seed

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
            "link_fixes": link_fixes_for(
                ("email_subject", subject_fixes), ("email_body", email_fixes)
            ),
            "provenance": provenance(
                "tpl-0001",
                dict(prov_params),
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
            "link_fixes": link_fixes_for(("sms_body", sms_fixes)),
            "provenance": provenance(
                "tpl-0002",
                dict(prov_params),
            ),
        },
    ]

    # Pydantic re-checks persona identity, timing, and reference existence —
    # belt and suspenders on top of the construction rules above.
    return GeneratedCampaign.model_validate(
        {
            "campaign_id": mission_config["campaign_id"],
            "persona": persona,
            # The simulation target, stamped from the profile so the validator
            # can check sender-recipient separation on the artifact itself.
            "recipient": profile.get("recipient"),
            "messages": messages,
        }
    )
