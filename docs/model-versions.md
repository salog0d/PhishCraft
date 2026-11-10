# Model versions (frozen)

The experiment must be reproducible, so every model is pinned to an explicit,
immutable Ollama tag — **never `latest`**. The tables below record the exact
tag, the full SHA256 weight digest, and the quantization, so a run can be
reproduced on any machine with the same snapshot.

Frozen on: **2026-11-10** (via `ollama cp`).

## Generator models (reliability matrix)

| Tag (fixed) | Model | Params | Quant | Architecture | SHA256 digest |
|-------------|-------|--------|-------|--------------|---------------|
| `qwen3:8b-q4km-20261110` | Qwen3 | 8.2B | Q4_K_M | qwen3 | `a3de86cd1c132c822487ededd47a324c50491393e6565cd14bafa40d0b8e686f` |
| `llama3.1:8b-q4km-20261110` | Llama 3.1 | 8.0B | Q4_K_M | llama | `667b0c1932bc6ffc593ed1d03f895bf2dc8dc6df21db3042284a6f4416b06a29` |
| `phi4-mini:3.8b-q4km-20261110` | Phi-4 mini | 3.8B | Q4_K_M | phi3 | `3c168af1dea0a414299c7d9077e100ac763370e5a98b3c53801a958a47f0a5db` |

## Critic model (self-refinement)

| Tag (fixed) | Model | Params | Quant | Architecture | SHA256 digest |
|-------------|-------|--------|-------|--------------|---------------|
| `deepseek-r1:7b-q4km-20261110` | DeepSeek-R1 (distill) | 7.6B | Q4_K_M | qwen2 | `96c415656d377afbff962f6cdb2394ab092ccbcbaab4b82525bc4ca800fe8a49` |

## Reproducing a frozen tag

```bash
# regenerate the same snapshot from the running tag it was copied from:
ollama cp qwen3:8b qwen3:8b-q4km-20261110
ollama cp llama3.1:8b llama3.1:8b-q4km-20261110
ollama cp phi4-mini:latest phi4-mini:3.8b-q4km-20261110
ollama cp deepseek-r1:7b deepseek-r1:7b-q4km-20261110
```

## Why not `latest`

`latest` (and un-tagged names) are moving pointers: `ollama pull` can silently
update them to different weights, which would change every downstream number.
The experiment references only the frozen tags above, so "same tag -> same
weights -> same results" is guaranteed.
