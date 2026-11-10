```markdown
# Generator-AG — Constrained Query (LMQL), v2

> Refactored per *Prompting is Programming: A Query Language for LLMs*
> (Beurer-Kellner, Fischer & Vechev, PLDI 2023). The three core mechanisms are
> preserved:
>
> 1. **Guided generation** — the persona is bound *once* and stamped into every
>    message by the program, so persona-identity coherence holds **by construction**.
> 2. **Decode-time constraints** — send timing (`EMAIL_TIME < SMS_TIME`), the SMS
>    1600-character cap, and the new style/diversity axes are `where` clauses
>    rejected during decoding, not post-hoc checks.
> 3. **Programmatic assembly** — `references`, `message_id`s, and the email-only
>    `subject` shape are decided by control flow; a missing or self-referential
>    cross-channel cite is structurally impossible.
>
> **v2 changes (repetition fixes).** The v1 prompt mode-collapsed because
> `argmax` + `temperature 0.0` + two homogeneous few-shot examples + a `seed`
> that was recorded but never *used* produced the same "Hi … before end of day"
> campaign for every seed. v2 keeps the paper's mechanisms but:
>
> - **A.** Derives discrete variation axes from `seed` and injects them as
>   instruction + `where` constraints — two seeds now provably differ.
> - **B.** Replaces the two homogeneous examples with three **contrastive** ones
>   (formal/easy, urgent/hard SMS, executive/hard email) that share nothing
>   lexically, so the model learns the *space* rather than a point.
> - **C.** Gives the SMS its own job — it must *advance* the thread, not mirror
>   the email; enforced in the charter and the `where` clause.
> - **D.** Turns `tone` and `difficulty` into demonstrated, `where`-enforced
>   style contracts.
> - **F.** Names the negative space (banned openers/phrases) in the charter and
>   rejects them at decode time.
> - **Caution.** Softens "follow the examples **exactly**" — that sentence was
>   the strongest repetition signal in v1.
>
> Deferred (flagged, not applied): **E** (parameterize `message_id`/campaign
> shape — a schema-contract decision) and **G** (`sample(n=k)` with a pairwise
> `JACCARD_WORDS` diversity clause — needs an LMQL custom constraint).

```python
import json
import os
import random
from datetime import datetime, timezone
from hashlib import sha256

import lmql

from app.core.schemas import GeneratedCampaign

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

# [FIX C] Cross-channel rule
- The SMS must **advance** the thread, not restate the email. It may add a new
  detail (a time, a name, a consequence), shift the ask, or acknowledge the
  channel switch. It must **not** repeat the email's opening clause, CTA verb,
  or deadline phrasing. Where it references the email, do so in ≤ 6 words.

# [FIX D] Tone and difficulty are style contracts, not vibes
Apply the requested `tone` and `difficulty` as follows:
- tone=formal     -> no contractions, no exclamation, third-person reference
- tone=urgent     -> ≤ 2 sentences in the email body, one hard deadline, imperative verb first
- tone=executive  -> first-person persona, authority framing, no pleasantries, no salutation
- tone=casual     -> contractions allowed, one sentence, no salutation
- difficulty=easy -> no link, no deadline, single ask
- difficulty=hard -> CTA appears in body once and again in the button; deadline + named consequence

# [FIX F] Anti-repetition block — the negative space is named on purpose
Do not begin any message with "Hi", "Dear", or a bare first name.
Do not use the phrases "before end of day", "please review", "let me know",
"action required", or "confirm" in any subject.
Do not reuse the opening verb of any example below.
Vary sentence count between the email and the SMS in the same campaign.

---
### Few‑Shot Examples  [FIX B: contrastive — they share nothing lexically]

The examples show the *range*. The persona, recipient and URL are placeholders —
replace them with the values from the user message. **Do not copy their
phrasing**; copy their *shape*.

**Example 1 — channel: email, pretext: invoice_payment, tone: formal, difficulty: easy, model: anthropic**
```json
{
  "message_id": "msg-0001",
  "channel": "email",
  "scheduled_at": "2026-08-20T09:00:00Z",
  "sender": { "display_name": "<persona display name>", "from_address": "<persona address>", "impersonated_brand": "<brand if any>" },
  "subject": "Q3 vendor statement available",
  "body": "Good morning <recipient first name>,\n\nThe vendor statement for the third quarter has been posted to the portal. A summary of the outstanding line items is attached to your account record for reconciliation.\n\n— <persona first name>",
  "call_to_action": { "type": "click_link", "landing_url": "https://sim.example.com/t/<campaign-token>", "button_label": "View Invoice" },
  "references": [],
  "provenance": {
    "model": { "family": "anthropic", "name": "claude-opus-5", "adapter_version": "1.0" },
    "params": { "temperature": 0.0, "seed": 42 },
    "prompt_template_id": "tpl-0001",
    "prompt_hash": "11c15b4d54820c0c62611e5c762fcd37534114d40b4a1ed54c07bad741a7cfa0",
    "generated_at": "2026-08-20T09:00:00Z",
    "adapter_latency_ms": 812,
    "runtime": { "sdk": "0.40.0" }
  }
}
```

**Example 2 — channel: sms, pretext: it_support, tone: urgent, difficulty: hard, cross-channel follow-up of msg-0007, model: openai**
```json
{
  "message_id": "msg-0008",
  "channel": "sms",
  "scheduled_at": "2026-08-20T14:40:00Z",
  "sender": { "display_name": "<persona display name>", "from_address": "<persona address>" },
  "body": "Helpdesk ticket escalated at 14:30 — SSO access drops in 25 min unless revalidated: {{cta-link}}",
  "call_to_action": { "type": "click_link", "landing_url": "https://sim.example.com/t/<campaign-token>" },
  "references": ["msg-0007"],
  "provenance": {
    "model": { "family": "openai", "name": "gpt-4.1", "adapter_version": "1.0" },
    "params": { "temperature": 0.0, "seed": 42 },
    "prompt_template_id": "tpl-0002",
    "prompt_hash": "64d4bebb8a66f720706baa0c41fadd90bf076e23529861d0a014206ef7540843",
    "generated_at": "2026-08-20T14:40:00Z",
    "adapter_latency_ms": 430,
    "runtime": { "sdk": "1.30.0" }
  }
}
```

**Example 3 — channel: email, pretext: executive_request, tone: executive, difficulty: hard, model: anthropic**
```json
{
  "message_id": "msg-0012",
  "channel": "email",
  "scheduled_at": "2026-08-21T07:15:00Z",
  "sender": { "display_name": "<persona display name>", "from_address": "<persona address>", "impersonated_brand": "<brand if any>" },
  "subject": "Board pack — one item needs your sign-off",
  "body": "One item in tomorrow's board pack still needs your sign-off. The summary is behind the button below; the window closes at 09:00 tomorrow.\n\nI need this back before the audit committee convenes — no delegation on this one.\n\n{{cta-link}}\n\n— <persona first name>",
  "call_to_action": { "type": "click_link", "landing_url": "https://sim.example.com/t/<campaign-token>", "button_label": "Review Summary" },
  "references": [],
  "provenance": {
    "model": { "family": "anthropic", "name": "claude-opus-5", "adapter_version": "1.0" },
    "params": { "temperature": 0.0, "seed": 42 },
    "prompt_template_id": "tpl-0001",
    "prompt_hash": "11c15b4d54820c0c62611e5c762fcd37534114d40b4a1ed54c07bad741a7cfa0",
    "generated_at": "2026-08-21T07:15:00Z",
    "adapter_latency_ms": 795,
    "runtime": { "sdk": "0.40.0" }
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
    "bank_detail_change": ("click_link", "Update Bank Details"),
    "account_compromise": ("click_link", "View Request"),
    "attorney_impersonation": ("click_link", "Open File"),
    "data_theft": ("open_attachment", "Open Attachment"),
    "payroll_diversion": ("click_link", "Update Deposit Details"),
    "gift_card": ("click_link", "View Instruction"),
}

# [FIX A] Seed-derived variation axes. These *reshape the instruction* so that
# two different seeds provably produce different generation constraints — not
# just different provenance metadata.
OPENERS = ["direct address", "context-first", "question-led", "reference to prior thread"]
STRUCTURES = ["single paragraph", "two short paragraphs", "bulleted action list"]
URGENCY_STYLES = ["deadline named explicitly", "deadline implied", "no deadline, social proof instead"]
SMS_ANGLES = ["nudge", "new detail", "deadline reminder", "channel-switch apology"]

def variation_axes(seed: int) -> dict:
    rng = random.Random(seed)
    return {
        "opener": rng.choice(OPENERS),
        "structure": rng.choice(STRUCTURES),
        "urgency_style": rng.choice(URGENCY_STYLES),
        "sms_angle": rng.choice(SMS_ANGLES),
        "max_body_words": rng.choice([40, 55, 70]),
    }

@lmql.query
def generator_ag(
    mission_config: dict, profile: dict, pretext: str, tone: str, difficulty: str
) -> GeneratedCampaign:
    recipient = profile["recipient"]
    email_domain = recipient["email"].rsplit("@", 1)[-1]
    seed = mission_config["reproducibility"]["seed"]
    landing_url = f"https://sim.{email_domain}/t/{tracking_token(mission_config['campaign_id'], seed)}"
    cta_type, cta_label = CTA_BY_PRETEXT.get(pretext, ("click_link", "Open"))
    selected = profile.get("persona")  # deterministic selection (catalog.persona_for)

    # [FIX A] derive and inject variation axes
    axes = variation_axes(seed)

    user = (
        f"Campaign {mission_config['campaign_id']}, pretext={pretext}, "
        f"tone={tone}, difficulty={difficulty}, language=en.\n"
        f"Recipient: {recipient['full_name']} ({recipient['role']}, "
        f"{recipient['department']}).\n"
        f"The campaign's single landing URL is {landing_url}. Never write a "
        f"URL or tracking token into your output — where the link should "
        f"appear, write exactly the placeholder {{{{cta-link}}}}.\n"
        "The impersonated persona is fixed — use this identity for every "
        "message, byte-for-byte:\n"
        f"- display name: {selected['display_name']}\n"
        f"- role: {selected.get('role') or '(not specified)'}\n"
        f"- from address: {selected['email']}\n"
        # [FIX A] variation axes as hard constraints in the instruction itself
        f"\nVariation axes for THIS campaign (derived from seed {seed}):\n"
        f"- email opener style: {axes['opener']}\n"
        f"- email structure: {axes['structure']}\n"
        f"- urgency style: {axes['urgency_style']}\n"
        f"- email body ≤ {axes['max_body_words']} words\n"
        f"- SMS angle: {axes['sms_angle']}\n"
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
    '''lmql
    argmax
        """system:
        {CHARTER}

        user: {user}
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
        # [FIX A] enforce the seed-derived axes at decode time
        and WORD_COUNT(EMAIL_BODY) <= {axes['max_body_words']}
        # [FIX D] tone/difficulty as enforced style contracts
        and (tone != "urgent" or SENTENCE_COUNT(EMAIL_BODY) <= 2)
        and (tone != "executive" or not REGEX(EMAIL_BODY, r"(?i)\bhi\b"))
        and (difficulty != "hard" or EMAIL_BODY.count("{{cta-link}}") == 1)
        # [FIX C] SMS must advance, not mirror, the email
        and not REGEX(SMS_BODY, r"(?i)did you get my email")
        and not REGEX(SMS_BODY, r"(?i)^hi\b")
        # [FIX F] anti-repetition: reject the mode-collapse phrases
        and not REGEX(EMAIL_BODY, r"(?i)^hi\b")
        and not REGEX(EMAIL_BODY, r"(?i)before end of day")
        and not REGEX(EMAIL_BODY, r"(?i)please review")
        and not REGEX(EMAIL_SUBJECT, r"(?i)action required")
        and not REGEX(EMAIL_SUBJECT, r"(?i)confirm")
    '''
    # The persona is decided deterministically above and stamped into every
    # sender below: persona-identity coherence holds by construction.
    persona = {
        "display_name": selected["display_name"],
        "email": selected["email"],
        "role": selected.get("role"),
    }
    sender = {
        "display_name": persona["display_name"],
        "from_address": persona["email"],
    }
    # Rebuild the exact rendered prompt for the provenance hash. Keep this
    # mirroring the query text above — it is what `prompt_hash` hashes.
    rendered_prompt = f"system:\n{CHARTER}\n\nuser: {user}"
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
            "subject": expand_link_placeholders(EMAIL_SUBJECT.strip(), landing_url),
            "body": expand_link_placeholders(EMAIL_BODY.strip(), landing_url),
            "call_to_action": {
                "type": cta_type,
                "landing_url": landing_url,
                "button_label": cta_label,
            },
            "references": [],
            "provenance": provenance(
                "tpl-0001",
                {"temperature": 0.0, "seed": seed},
            ),
        },
        {
            "message_id": "msg-0002",  # by construction
            "channel": "sms",
            "scheduled_at": SMS_TIME.strip(),
            "sender": sender,  # by construction — identical persona
            "body": expand_link_placeholders(SMS_BODY.strip(), landing_url),
            "call_to_action": {
                "type": cta_type,
                "landing_url": landing_url,
                "button_label": cta_label,
            },
            "references": ["msg-0001"],  # by construction — the cited id exists
            "provenance": provenance(
                "tpl-0002",
                {"temperature": 0.0, "seed": seed},
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