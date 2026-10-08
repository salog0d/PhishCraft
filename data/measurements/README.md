# Measurement results — reading them correctly

This directory holds the experiment artifacts. Three clarifications matter
before these numbers go into the paper.

## 1. Two link-consistency numbers, not one

The original failure (`link_consistency` 10/10) and the "after" result (0/10)
measure **different layers of the pipeline**, and the 0/10 by itself measures
the assembler, not the model:

| metric | what it measures | where it comes from |
|---|---|---|
| **Raw (pre-assembler) violation rate** | how often the **LLM** writes a stale tracking token into its prose — the generator's *reliability* | each message's `link_fixes` (the rewrites `assemble_campaign` applied before normalization; normalization never triggers a retry, so this is first-attempt output) |
| **Post-assembler failure rate** | whether the **delivered artifact** satisfies all coherence checks — the *delivery guarantee* | the validator's `CoherenceReport` |

Since the assembler normalizes body links (`normalize_body_links`), the
post-assembler `link_consistency` check cannot fail by construction: the 0/10
"after" number is the guarantee, **not** the reliability result. The harness
(`measurement/reliability.py`) now reports both, in `reliability.json`
(`raw_link_violation_rate` + `failure_rate`) and in `summary.md`.

> The historical runs below predate the `link_fixes` recording, so their raw
> number is unknown — do not backfill it. Re-run the suite to obtain both.

## 2. The sampling parameters actually used

- The ADK model call runs at **temperature 0.0** (`agent/config.py`,
  `LiteLlm(..., temperature=0.0)`).
- Provenance now logs what the call used: `{"temperature": 0.0, "seed": 42}`
  (`top_p`/`max_tokens` are left at provider defaults and are not logged).
- The **seed drives the deterministic layer only** (tracking token, persona
  selection); it is **not passed to the provider** (`runtime.seed_supported:
  false`), so content sampling is unseeded.
- Earlier runs recorded `0.7` (email) / `0.6` (SMS) in provenance while the
  call already ran at 0.0 — that log was wrong and has been corrected. The
  committed artifacts from those runs keep their historical provenance values.

Measured consequence (see the reproducibility rows below): the deterministic
layer is byte-identical across runs; the LLM prose varies slightly between
calls **even at temperature 0**. The nondeterminism comes from the provider,
not from this codebase.

## 3. A gap the 4-check suite could not see

Run S1 in `reproduce-adk/` has the CEO addressing herself ("Elena, I'm
finalizing… — Elena") and every one of the four original checks passed it.
No check compared the sender against the recipient. That hole is itself a
finding: the suite does not detect everything, and knowing what it misses is
part of the result. The broken run is preserved as
`known-case/ceo_self_impersonation.json` (annotated with its recipient), and a
fifth check — `sender_recipient` — now catches it; a regression test pins it.

---

## Before (broken generator) — `reliability-adk-20260923T185148Z/`

| check | violations / 10 |
|---|---|
| persona_identity | 0 |
| timing | 0 |
| cross_channel_reference | 0 |
| **link_consistency** | **10** |

→ **campaigns with ≥ 1 violation: 10/10 (failure rate 1.0)**
(this is the post-assembler artifact of the *unfixed* generator; raw == post
here because no normalization existed yet)

## After (fixed generator) — `reliability-adk-20260923T195458Z/`

| check | violations / 10 |
|---|---|
| persona_identity | 0 |
| timing | 0 |
| cross_channel_reference | 0 |
| **link_consistency** | **0** |

→ **campaigns with ≥ 1 violation: 0/10 (failure rate 0.0)** · 0 generation errors

> **Post-assembler guarantee only.** The raw LLM violation rate for this run
> was not recorded (the `link_fixes` evidence postdates it). Re-run the suite
> to measure both numbers.

## Reproducibility (seed 42, spec S1 × 2)

- `reproduce-adk/` (before the link fix): both runs byte-identical.
- `reproduce-adk-fixed/` (after the fix): **deterministic layer identical**
  (ids, persona, recipient, URLs, references, schedule, provenance) — content
  prose varies slightly between provider calls at temperature 0.0. The
  deterministic layer is this codebase's guarantee; the prose variance is the
  provider's, and unseeded sampling makes it expected.
