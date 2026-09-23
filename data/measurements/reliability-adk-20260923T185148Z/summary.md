# Reliability experiment — summary

- adapter: `adk` · model: `deepseek-chat`
- specs: 10 · runs: 10 · generation errors: 0
- **campaigns with ≥ 1 violation: 10/10 (failure rate 1.0)**

## Violations by coherence check

| check | violations |
|---|---|
| `persona_identity` | 0 |
| `timing` | 0 |
| `cross_channel_reference` | 0 |
| `link_consistency` | 10 |

## Per-spec results

| spec | run | seed | status | failing checks |
|---|---|---|---|---|
| S1 | 1 | 42 | ok | link_consistency |
| S2 | 1 | 42 | ok | link_consistency |
| S3 | 1 | 42 | ok | link_consistency |
| S4 | 1 | 7 | ok | link_consistency |
| S5 | 1 | 13 | ok | link_consistency |
| S6 | 1 | 42 | ok | link_consistency |
| S7 | 1 | 99 | ok | link_consistency |
| S8 | 1 | 42 | ok | link_consistency |
| S9 | 1 | 5 | ok | link_consistency |
| S10 | 1 | 42 | ok | link_consistency |
