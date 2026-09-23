# Measurement results — before/after the link fix

The `link_consistency` failure (the SMS body copying the few-shot example token
`abc123` while the CTA carried the seed-derived token) was fixed in
`feat/interactive-harness`:

1. **Charter** — the few-shot examples no longer hardcode `abc123`; a hard rule
   says to copy the exact landing URL supplied in the user message.
2. **Assembler (structural)** — `generator_agent.assemble.normalize_body_links`
   rewrites any tracking token written into a subject/body to the campaign
   token, so body links match the CTA by construction.
3. **Robustness** — the ADK driver retries (max 3 attempts) with a stricter
   format when the content agent echoes a prompt placeholder instead of a
   value.

The validator and the known-case evidence were **not** changed: the check
still catches the old failing sample
(`data/measurements/known-case/generated_campaign.json`), and the original
evidence remains at `data/q3-awareness-2026/generated_campaign.json`.

## Before (broken generator) — `reliability-adk-20260923T185148Z/`

| check | violations / 10 |
|---|---|
| persona_identity | 0 |
| timing | 0 |
| cross_channel_reference | 0 |
| **link_consistency** | **10** |

→ **campaigns with ≥ 1 violation: 10/10 (failure rate 1.0)**

## After (fixed generator) — `reliability-adk-20260923T195458Z/`

| check | violations / 10 |
|---|---|
| persona_identity | 0 |
| timing | 0 |
| cross_channel_reference | 0 |
| **link_consistency** | **0** |

→ **campaigns with ≥ 1 violation: 0/10 (failure rate 0.0)** · 0 generation errors

## Reproducibility (seed 42, spec S1 × 2, after the fix)

- `reproduce-adk/` (before): both runs byte-identical.
- `reproduce-adk-fixed/` (after): **deterministic layer identical** (ids,
  persona, URLs, references, schedule, provenance) — content prose varies
  slightly between provider calls at temperature 0. Both runs pass all four
  checks.
