# Metrics catalog — what we measure, against what truth

One table per metric family: **what it measures**, the **ground truth** it is
scored against, and its **validation status**. The point of this doc is the
third column — it names, honestly, which numbers are anchored to something
external and which are only self-consistent.

The deep mechanics live in
[`../architecture/self-refinement-and-quality.md`](../architecture/self-refinement-and-quality.md);
this is the map, not the mechanism.

## How to read the "ground truth" column

Every metric is scored against one of four things, and the difference is what
determines how much a number is allowed to claim:

| Truth | Meaning | What a good number proves |
|-------|---------|---------------------------|
| **invariant** | stamped by the deterministic assembler | the pipeline's plumbing holds — *not* a model result |
| **rule** | a deterministic detector over the prose | the pattern is present/absent, as the rule defines it |
| **spec** | the label that was requested | the output is *self-consistent* with the request |
| **human** | a person's judgment on a sample | the output corresponds to *reality* (the only external anchor) |

A `spec`-scored or `rule`-scored number can be perfectly reproducible and still
be measuring the wrong thing, if the rule/labeler disagrees with a human. That
gap is closed only by the **human** column — see [§6](#6-labeler-validation-the-anchor).

---

## 1. Structural coherence — `truth: invariant`

`validator_agent/validate.py`. A campaign's `all_passed` requires all five.

| Metric | Measures | Validation status |
|--------|----------|-------------------|
| `persona_identity` · `timing` · `cross_channel_reference` · `link_consistency` · `sender_recipient` | the assembled artifact is internally consistent | **N/A** — stamped by construction; ~100% is a delivery guarantee of the deterministic layer, never an LLM result |

Do not report these as a model quality signal. A juez/fine-tune cannot improve
them because the LLM never gets to break them.

## 2. Quality scan — `truth: rule`

`quality_agent/scan.py`. Nine deterministic content detectors; reported as
`quality_flag_rate` + `flag_counts` + `per_pretext` rate.

| Metric | Measures |
|--------|----------|
| `dialogue_collapse` | prose signed by / addressed to the wrong identity (incl. a leaked few-shot name) |
| `stage_direction` | bracket directions, leftover `{{cta-link}}` / `[PLACEHOLDER]` |
| `turn_overflow` | messages far past / under their channel's expected size |
| `meta_bleed` | refusal/apology/prompt vocabulary leaking into content |
| `loop_detection` | duplicated lines, subject restated in body, SMS ≈ email (repetition *within* one campaign) |
| `pretext_contamination` | vocabulary from another pretext bleeding in |
| `name_contamination` | a roster name that is neither persona nor recipient |
| `brand_contamination` | a brand mention that does not belong to the pretext |
| `script_contamination` | non-Latin script where none is expected |

**Validation status:** unvalidated for precision/recall. These are cheap
pattern rules — an LLM judge would be slower and *worse* at most of them. The
open question is their false-positive rate, which would be measured by a human
spot-check of flagged vs unflagged prose, not by a judge.

## 3. Label audit — `truth: spec` ⚠️ (the subjective core)

`quality_agent/labels.py` — argmax over hand-written lexicons
(`quality_agent/lexicon.py`). This is the only family that depends on
subjective judgment, and therefore the only one where an LLM judge or a
fine-tuned classifier is worth the cost.

Label space:

| Axis | Classes | How the labeler decides |
|------|---------|-------------------------|
| **pretext** | 8 — `password_reset`, `account_suspension`, `package_delivery`, `it_support`, `hr_notice`, `executive_request`, `shared_document`, `invoice_payment` | argmax of per-pretext term hits |
| **tone** | 4 — `urgent`, `friendly`, `authoritative`, `neutral` | argmax of tone-marker hits |
| **difficulty** | 3 bands — `easy` (0–3), `medium` (4–6), `hard` (7+) | banded count of difficulty markers (`urgency`, `threat`, `ask`, `impersonation`) |

No signal / a tie → `unverifiable` (never forced into a mismatch).

| Metric | Measures (vs the requested spec) |
|--------|----------------------------------|
| `match_rate` (per label) | share of campaigns the labeler reads as matching the requested label |
| `label_correction_rate` | share of campaigns with ≥1 tone/difficulty mismatch (feeds self-refinement) |
| `most_common_corrections` | which requested→detected swaps happen most |
| achieved distribution | what the labeler actually detected (honest relabel) |

**Validation status: NOT ANCHORED.** Every number here assumes the lexicon
labeler is correct. That assumption is unmeasured until the labeler is scored
against human labels ([§6](#6-labeler-validation-the-anchor)). Until then these
are *self-consistency* metrics ("the prose matches the request as the lexicon
sees it"), not *accuracy* metrics.

## 4. Contamination & stripping — `truth: rule`

| Metric | Measures |
|--------|----------|
| `contamination_rate`, `per_pretext_contamination` | pretext/name/brand/script bleed (aggregated from §2) |
| `strip_affected_rate`, `total_stripped_chars` | how much stage-direction stripping *would* remove (measured on a copy, never applied) |

Diagnostic, deterministic. No external truth needed.

## 5. Inter-run diversity — `truth: rule` (mode-collapse evidence)

`quality_agent/diversity.py`. Complements `loop_detection`: repetition *across*
runs of the same pretext, not within one campaign. Needs `--runs > 1`.

| Metric | Measures |
|--------|----------|
| `distinct_1` / `distinct_2` | unique n-grams / total over the pretext's campaigns (Li et al. 2016) — higher = more varied |
| `mean_pairwise_similarity` | mean `difflib` ratio over every campaign pair — higher = collapse toward one template (Padmakumar & He 2024) |

**Validation status:** evidence, never pass/fail. A stdlib stand-in for
Self-BLEU. Could optionally be checked for correlation with a human "how
repetitive does this feel" rating, but is not claimed as a validated score.

## 6. Labeler validation — `truth: human` (THE ANCHOR)

`scripts/validate_labeler.py`. This is the meta-metric that converts §3 from
self-consistency into accuracy. Without it, every tone/difficulty/pretext
number — and the Wilson CIs built on them — measures the lexicon's bias, not
the model.

| Metric | Measures |
|--------|----------|
| exact-match rate (per axis) | share of sampled campaigns where labeler == human |
| **Cohen's kappa** (per axis) | labeler↔human agreement corrected for chance |

Flow:

```
validate_labeler.py --sample <exp>  ->  labeler_validation_sheet.csv
  (human_pretext / human_tone / human_difficulty columns, empty)
         |
   a human fills them
         v
validate_labeler.py --score-from-experiment <exp>  ->  exact-match + kappa
```

**Current status (2026-11-20): NOT RUN.** The most recent sheet
(`experiment/reliability-final-.../labeler_validation_sheet.csv`, 80 rows) has
**0 rows labeled**. This is the single open gap that leaves §3 ungrounded.

### Planned extension — three labelers against one gold

To decide whether to keep the lexicon labeler, replace it, or distill a better
one, the gold set scores **three** labelers against the same human column:

| Labeler | Cost | Needs |
|---------|------|-------|
| lexicon (current) | free | nothing |
| LLM judge (few-shot) | per-call | a strong model; try **first** — if kappa is high, fine-tuning is YAGNI |
| distilled classifier (embedding + logreg, or small encoder) | one-time train | the LLM judge as weak supervision + the human gold to validate |

The human gold (40–80 rows) is the bottleneck for **both** validation and any
fine-tune: enough to validate, too few to train a generative judge. The honest
architecture is to validate the LLM judge against the human gold, then use that
judge to weak-label a larger corpus to train the small classifier, and validate
*all three* against the same human gold with kappa.

---

## The one-line summary

Everything in §1, §2, §4, §5 is deterministic and needs no external truth.
**Only §3 (pretext/tone/difficulty) is subjective, and §6 is the human anchor
that validates it — and §6 has not been run.** That is where the gold labels,
the LLM judge, and any fine-tuned model belong; nowhere else.
