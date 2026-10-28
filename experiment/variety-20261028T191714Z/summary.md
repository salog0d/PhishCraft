# Variety experiment — quality lifecycle summary

- generated: `2026-10-28T20:29:42.565607Z` · dir: `experiment/variety-20261028T191714Z`
- runs: 64 (ok 64, ok=64)
- campaigns with >= 1 quality flag: 39/64 (rate 0.6094)
- contaminated campaigns: 7/64 (rate 0.1094)
- label-correction rate: 0.7812 (mismatch {'pretext': 12, 'tone': 29, 'difficulty': 37}, unverifiable {'pretext': 16, 'tone': 12, 'difficulty': 0})
- strip-affected campaigns: 0/64 (rate 0.0); 0 chars would be removed from 0 messages

## Findings by check

| check | findings | campaigns flagged |
|---|---|---|
| `dialogue_collapse` | 0 | 0 |
| `stage_direction` | 0 | 0 |
| `turn_overflow` | 20 | 20 |
| `meta_bleed` | 33 | 20 |
| `loop_detection` | 1 | 1 |
| `pretext_contamination` | 7 | 7 |
| `name_contamination` | 0 | 0 |
| `brand_contamination` | 0 | 0 |
| `script_contamination` | 0 | 0 |

## Contamination by category

| category | campaigns |
|---|---|
| `pretext_contamination` | 7 |
| `name_contamination` | 0 |
| `brand_contamination` | 0 |
| `script_contamination` | 0 |

## Coherence (validator) failures

| check | campaigns failing |
|---|---|
| `persona_identity` | 0 |
| `timing` | 0 |
| `cross_channel_reference` | 0 |
| `link_consistency` | 0 |
| `sender_recipient` | 0 |

## Per model

| model | runs | quality flag rate | contamination rate | label correction rate | coherence failure rate | median duration |
|---|---|---|---|---|---|---|
| `qwen3:8b` | 16 | 0.3125 | 0.0625 | 0.75 | 0.0 | 84.0s |
| `llama3.1:8b` | 16 | 0.875 | 0.125 | 0.5625 | 0.0 | 68.7s |
| `gemma4:latest` | 16 | 0.375 | 0.1875 | 0.9375 | 0.0 | 72.7s |
| `phi4-mini:latest` | 16 | 0.875 | 0.0625 | 0.875 | 0.0 | 196.2s |

## Per temperature (sweep)

| temperature | runs | unique-body ratio | near-dup rate | retry rate | refinement rate | quality flag rate | mean attempts |
|---|---|---|---|---|---|---|---|
| `0.0` | 16 | 1.0 | 0.0 | 0.5625 | 0.5625 | 0.5625 | 2.06 |
| `0.5` | 16 | 1.0 | 0.0 | 0.6875 | 0.6875 | 0.75 | 2.25 |
| `0.8` | 16 | 1.0 | 0.0 | 0.625 | 0.5625 | 0.6875 | 2.25 |
| `1.2` | 16 | 1.0 | 0.0 | 0.5 | 0.5 | 0.4375 | 2.06 |

## Flag rate by pretext

| pretext | runs | flagged | rate | contaminated | contamination rate |
|---|---|---|---|---|---|
| `executive_request` | 16 | 8 | 0.5 | 1 | 0.0625 |
| `invoice_payment` | 16 | 12 | 0.75 | 1 | 0.0625 |
| `it_support` | 16 | 11 | 0.6875 | 4 | 0.25 |
| `password_reset` | 16 | 8 | 0.5 | 1 | 0.0625 |

### Most common label corrections (spec label -> runs)

- `pretext`: it_support->9, executive_request->3
- `tone`: urgent->29
- `difficulty`: medium->37

## Refinement activity

- campaigns refined: 37 (37/64)
- total attempts: 138 (mean per campaign 2.16)
- raw link violations (final artifact): 0 (first-attempt: 0)

## Charts

![by_model](charts/by_model.png)

![coherence_by_check](charts/coherence_by_check.png)

![contamination_by_category](charts/contamination_by_category.png)

![cumulative_findings](charts/cumulative_findings.png)

![duration_by_model](charts/duration_by_model.png)

![heatmap_pretext_check](charts/heatmap_pretext_check.png)

![label_audit](charts/label_audit.png)

![quality_by_check](charts/quality_by_check.png)

![quality_by_pretext](charts/quality_by_pretext.png)

![strip_stats](charts/strip_stats.png)

![temperature_sweep](charts/temperature_sweep.png)

> Quality findings are evidence, never repairs: the delivered campaigns are untouched by the scan, and every number above measures the generator, not a cleanup of its output.
