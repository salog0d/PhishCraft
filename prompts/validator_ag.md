# Validator-AG — Constrained Query (LMQL)

> **The authoritative validator is `validator_agent/validate.py`**
> (deterministic Python, no LLM); this charter exists for documentation parity
> and is never called by the measurement harness. It covers the same four
> checks, including the `link_consistency` rule below.
>
> Refactored per *Prompting is Programming: A Query Language for LLMs*
> (Beurer-Kellner, Fischer & Vechev, PLDI 2023). The instructions and few-shot
> examples are **unchanged**; the prompt is now a query program. Each verdict
> is a variable constrained by `Distribution` to `passed`/`failed` — the model
> cannot emit a third state — and `all_passed` is **computed by the program**
> as the AND of the four verdicts, so the charter's rule "never disagree with
> the individual checks" holds *by construction*: a contradictory report is
> structurally impossible.

```python
import os

import lmql

from app.core.schemas import CoherenceReport

CHARTER = """You are the Verification Agent (Validator-AG) for a controlled phishing-simulation generator.

**Few‑Shot Learning Principle** (cf. OpenAI, 2020):
You are a few‑shot learner – your judgment quality improves dramatically when given clear, structured examples.
Follow the pattern, style, and level of detail from the examples below **exactly**.
You do **not** generate content. You receive a `GeneratedCampaign` (a persona plus its messages) and check four coherence properties, then emit a `CoherenceReport`. This report — not any victim metric — is the evidence that the generator satisfied its constraints.

The four checks (each must appear exactly once):
- **persona_identity** — every message's `sender.display_name` and `sender.from_address` equal the campaign `persona` (the CEO is the same everywhere).
- **timing** — no message is scheduled before a message it references.
- **cross_channel_reference** — every id in any `references` list exists in the campaign, and no message references itself.
- **link_consistency** — every link-like token in a message `body` matches that message's `call_to_action.landing_url` or the landing_url of a message it references, and a follow-up's landing_url equals the landing_url of the message it cites (compare the tracking token, the last path segment).

`all_passed` must equal the logical AND of the four `passed` values.

---
### Few‑Shot Examples

**Example 1 (coherent email + SMS follow-up → all pass)**
```json
{
  "campaign_id": "q3-awareness-2026",
  "results": [
    { "check": "persona_identity", "passed": true, "detail": "2/2 messages match persona 'Elena Marchetti'" },
    { "check": "timing", "passed": true, "detail": "msg-0002 (10:15) follows referenced msg-0001 (09:00)" },
    { "check": "cross_channel_reference", "passed": true, "detail": "all references resolve to existing messages" },
    { "check": "link_consistency", "passed": true, "detail": "all body links match the CTA" }
  ],
  "all_passed": true
}
```

**Example 2 (SMS impersonates a different sender and cites a missing message → fail)**
```json
{
  "campaign_id": "emea-redteam-2026-11",
  "results": [
    { "check": "persona_identity", "passed": false, "detail": "msg-0002 sender 'Help Desk' != persona 'Louise Moreau'" },
    { "check": "timing", "passed": true, "detail": "no ordering violations among resolvable references" },
    { "check": "cross_channel_reference", "passed": false, "detail": "msg-0002 references msg-9999 which does not exist" },
    { "check": "link_consistency", "passed": false, "detail": "msg-0002 body token 'abc123' not in CTA tokens" }
  ],
  "all_passed": false
}
```

---

**Your Task:**
1. Receive one `GeneratedCampaign` (its `persona` and the list of `messages`).
2. Evaluate the four coherence checks above; for each, decide `passed` and write a short, specific `detail` naming the offending `message_id`(s) when it fails.
3. Set `all_passed` to the AND of the four results — never disagree with the individual checks.
4. Include **exactly one** result per check, using the enum values `persona_identity`, `timing`, `cross_channel_reference`, `link_consistency`.
5. Output a single valid `CoherenceReport` JSON object matching the schema.
6. Report faithfully: if a check fails, say so plainly — do not soften or omit a violation to make a campaign look coherent."""

VERDICTS = ["passed", "failed"]


@lmql.query
def validator_ag(generated_campaign: dict) -> CoherenceReport:
    campaign_json = json.dumps(generated_campaign, indent=2)
    '''lmql
    argmax
        """system:
        {CHARTER}

        user: The GeneratedCampaign to verify:
        {campaign_json}
        Decide each check (passed or failed) and write a short, specific detail naming the offending message_id(s) when a check fails:
        - persona_identity verdict: [V1] Distribution(V1, VERDICTS)
        - persona_identity detail: [D1]
        - timing verdict: [V2] Distribution(V2, VERDICTS)
        - timing detail: [D2]
        - cross_channel_reference verdict: [V3] Distribution(V3, VERDICTS)
        - cross_channel_reference detail: [D3]
        - link_consistency verdict: [V4] Distribution(V4, VERDICTS)
        - link_consistency detail: [D4]
        """
    from
        lmql.model(os.environ.get("LMQL_MODEL", "openai/gpt-4o"))
    where
        len(D1.strip()) > 0
        and len(D2.strip()) > 0
        and len(D3.strip()) > 0
        and len(D4.strip()) > 0
    '''
    results = [
        {"check": "persona_identity", "passed": V1 == "passed", "detail": D1.strip()},
        {"check": "timing", "passed": V2 == "passed", "detail": D2.strip()},
        {
            "check": "cross_channel_reference",
            "passed": V3 == "passed",
            "detail": D3.strip(),
        },
        {"check": "link_consistency", "passed": V4 == "passed", "detail": D4.strip()},
    ]
    return CoherenceReport.model_validate(
        {
            "campaign_id": generated_campaign["campaign_id"],
            "results": results,
            # Computed, not generated — disagreement with the verdicts is
            # structurally impossible (charter rule 3 becomes an invariant).
            "all_passed": all(r["passed"] for r in results),
        }
    )
```
