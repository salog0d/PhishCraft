# Self-refinement & Quality Checks

This document explains the two feedback layers the generator uses to turn a
first-draft campaign into a validated one, and exactly what evidence they
produce. It is the reference for interpreting the reliability matrix's
`n_attempts`, `refined`, `critic_calls`, `raw_link_violations`, and the
quality flags recorded per run.

---

## 1. The pipeline in one line

The pipeline is a linear ADK `SequentialAgent` — no planner, no autonomy:

```
generator_content_agent (LLM)  ->  assembler_agent (deterministic)  ->  validator_agent (deterministic)
      raw_bindings                     generated_campaign                   coherence_report
```

Only the first stage calls an LLM. The assembler stamps persona, tracking
token, schedule, references and provenance by construction; the validator runs
five deterministic coherence checks. On top of that, the driver (`agent/driver.py`)
wraps the whole run in a **rejection + self-refinement** loop, and a
post-run **quality scan** (`quality_agent/scan.py`) records content-level
findings as data.

---

## 2. Self-refinement (Reflexion-style) with the DeepSeek model

When a run parses but is not yet clean, the driver regenerates it with a
critique. This is the `Reflexion`-style "self-critique" step: the model sees
precise, deterministic evidence of its mistake and re-aims, instead of being
asked to try again blindly.

### 2.1 The two feedback loops

| Phase | Trigger | What happens | Bounded by |
|-------|---------|--------------|------------|
| **Rejection sampling** | an attempt fails to parse into a valid campaign (echoed placeholder, missing binding) | retried with a stricter format instruction (`STRICT_FORMAT`) | `MAX_ATTEMPTS = 3` |
| **Self-refinement** | an attempt *parses* but still has: stale tracking tokens (`link_fixes` non-empty), a coherence failure, or a structural quality finding | the campaign is regenerated with an evidence-driven critique appended to the prompt | `REFINE_EXTRA_ATTEMPTS = 2` |

### 2.2 Who writes the critique

There are **two** critique builders, chosen by evidence type:

1. **Deterministic link critique** (`build_refinement` in `driver.py`) — no LLM.
   Used when the model wrote stale tracking tokens. It lists, field by field,
   what the model wrote vs. the correct seed-derived token, then re-states the
   `{{cta-link}}` placeholder convention. Reason: the token is deterministic
   and unguessable, so the only reliable fix is "never write a URL; write the
   placeholder".

2. **The critic LLM** (`agent/critic.py`) — a separate reasoning model. Used for
   **structural** quality findings (`stage_direction`, `meta_bleed`) and any
   coherence failure the deterministic path does not own. It receives only the
   evidence (`findings_summary`), and writes a short (≤ 5 sentence) critique:
   what to remove, what to keep, and the rule about never writing URLs or
   bracket placeholders. It never repairs content itself and never invents new
   problems.

### 2.3 The critiquing model

The critic is resolved by `resolve_critic_model()` in `agent/config.py`:

- Default: `ollama/deepseek-r1:7b` — a local reasoning model
  (configurable via `ADK_CRITIC_MODEL`, e.g. `ollama/deepseek-r1:14b` for the
  cloud VM).
- It runs at **temperature 0.0** (deterministic criticism).
- If the critic model is unavailable, the driver falls back to the generator
  model, and — for stale-link cases — to the deterministic `build_refinement`.
  The loop never breaks the pipeline: on any critic error it is skipped and the
  deterministic backstop holds.

> **Why DeepSeek-R1:** it is a reasoning model — it emits a `<think>`/reasoning
> preamble before the answer. `critique_campaign` keeps only the non-`thought`
> parts, so the critique the content agent receives contains no reasoning leak.

### 2.4 What the refinement is and is not

- **It is** content-only: only the subject/body are regenerated. The
  deterministic layer (persona, token, schedule, provenance) is never touched,
  so the reproducibility guarantee survives refinement.
- **It is** bounded: at most 2 extra rounds, then the loop stops. A refinement
  that fails to parse keeps the previous valid campaign (the assembler's
  normalization is the backstop).
- **It is** *not* a repair: the critique is appended to the next prompt so the
  model re-aims; nothing mutates the artifact directly.

### 2.5 Effort evidence recorded

Every refinement round is visible in the per-run `llm_trace.jsonl`, including
the critic's own call (agent=`critic`, with prompt/completion/total tokens and
duration). The harness folds these into `generator_calls`, `critic_calls`,
`total_tokens`, and `refined`, so the experiment measures the *effort* each
model needs to reach a valid campaign — not just whether it does.

---

## 3. Quality checks

There are **two independent sets** of checks, answering different questions.

### 3.1 Coherence checks (the validator, `validator_agent/validate.py`)

Deterministic, structural, run on the delivered artifact. A campaign passes the
experiment's "all_passed" only if all five pass.

| Check | What it guarantees |
|-------|--------------------|
| `persona_identity` | the impersonated sender is the same identity across every message |
| `timing` | messages are ordered (email before SMS follow-up) |
| `cross_channel_reference` | a follow-up only references message ids that already exist |
| `link_consistency` | any URL in prose matches the campaign's single CTA link; a follow-up points at the same link it cites |
| `sender_recipient` | the impersonated persona is never the campaign's own recipient |

> These fail **by construction** extremely rarely — the assembler normalizes
> persona/token/schedule/references. A 100% pass rate here is a *delivery
> guarantee* of the deterministic layer, not a claim about the LLM's prose
> quality.

### 3.2 Quality scan (`quality_agent/scan.py`)

Deterministic, content-level, run post-assembly on the delivered artifact. It
records findings as data (never mutates). Nine check categories:

| Category | Scope | What it detects |
|----------|-------|-----------------|
| `dialogue_collapse` | role confusion | prose signed by, or addressed to, an identity that is neither the persona nor the recipient — *including a greeting to a name leaked from the few-shot examples (e.g. "Alex")* |
| `stage_direction` | artifacts | bracket/parenthetical directions, leftover `{{cta-link}}` / `[EMAIL_SUBJECT]` placeholders |
| `turn_overflow` | length anomalies | messages far past their channel's expected size, or underdeveloped |
| `meta_bleed` | instruction echo | refusal/apology phrasing, "here is the message", prompt vocabulary leaking into content |
| `loop_detection` | repetition | duplicated lines, subject restated verbatim in body, SMS nearly duplicating the email |
| `pretext_contamination` | lexical bleed | vocabulary from another pretext leaking in (e.g. invoice terms inside an account-suspension lure) |
| `name_contamination` | roster drift | a roster name that is neither persona nor recipient appearing in prose |
| `brand_contamination` | wrong brand | a brand mention that does not belong to the pretext |
| `script_contamination` | non-Latin script | scripts outside the expected alphabet appearing in prose |

Plus two aggregations:

- **`label_audit`** — a deterministic labeler infers pretext/tone/difficulty
  from lexicons and marks each `ok | mismatch | unverifiable`. `mismatch` means
  the delivered content does not read like the requested label.
- **`strip_stats`** — measured on a copy, never applied: how many messages and
  characters stage-direction stripping *would* remove (the paper's
  turn-affected rate analogue).

### 3.3 Which checks feed back vs. which only record

- **Feedback (into self-refinement):** coherence failures and the structural
  quality checks `stage_direction` + `meta_bleed` — the only content the
  generator can meaningfully re-aim at.
- **Record-only:** `label_audit`, contamination (`pretext`/`name`/`brand`/
  `script`), and `strip_stats` — evidence the scanner captures but the content
  agent cannot fix from a critique.

---

## 4. Reading the reliability matrix with this in mind

For each execution the harness records:

| Field | Meaning |
|-------|---------|
| `n_parse_attempts` | Phase-1 parse-level rejection attempts (before a valid campaign parses) |
| `n_refine_rounds` | Phase-2 self-refinement rounds actually run |
| `n_attempts` | `n_parse_attempts` + `n_refine_rounds` (back-compat total) |
| `refined` | whether any self-refinement round ran |
| `refine_reason` | which signal triggered refinement (`link_violation`, `structural`, or both) |
| `refinement_improved` | whether quality flags dropped after the critique (real success measure) |
| `critic_calls` | how many times the critic LLM was invoked |
| `generator_calls` | how many times the content LLM was invoked |
| `total_tokens` | tokens across generator + critic (effort) |
| `raw_link_violations` | stale tracking tokens the model wrote *before* the assembler normalized them |
| `failing_checks` | which of the 5 coherence checks failed (almost never) |
| `quality.*` | flags / label mismatches / strip stats from the quality scan |

The interesting number is the **effort**: a model that reaches a valid campaign
in 1 parse + 0 critic calls is "cheaper" than one that needs 3 parses and 2
critic rounds, even though both produce a passing artifact. Crucially,
`refinement_improved` separates *real* correction from *wasted* rounds: a round
that fired but did not lower the flags was chasing a non-issue (e.g. a detector
false positive), not improving the artifact. The 100 % coherence pass rate,
combined with the per-model effort distribution, is itself the study's result:
it shows what the assembler guarantees by construction, and how much each model
had to work to get there.
