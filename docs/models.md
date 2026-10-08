# Model Catalog — cross-family study

The generator's `ModelPolicy` requires **≥ 2 model families**, so the
reliability/reproducibility experiments must run on at least two. This
catalog lists the candidates and, explicitly, the models that are **ruled
out**.

- **Current baseline:** `deepseek/deepseek-chat` (API) — used by the committed
  measurements.
- **Cross-family goal:** add at least one **standard open instruct model that
  runs locally** (no API, reproducible offline, weights auditable).

---

## Candidates — standard instruct models, open weights, local

All are unmodified, openly-licensed instruction-tuned models. They run on a
single consumer GPU (quantized) or in CPU/RAM for the smallest ones. The final
pick depends on the machine available — see "Selection" below.

| Model | Params | Approx. size (bf16 / Q4) | Notes |
|-------|--------|--------------------------|-------|
| **Llama 3.1 8B Instruct** (`meta-llama/Llama-3.1-8B-Instruct`) | 8B | ~16 GB / ~5 GB | Strong general instruction-following; the same base as the discarded Dolphin abliteration, without the alignment damage. |
| **Qwen 2.5 7B Instruct** (`Qwen/Qwen2.5-7B-Instruct`) | 7B | ~15 GB / ~5 GB | Best-in-class at its size for structured output; 14B variant (~30 GB / ~9 GB) if the GPU allows. |
| **Mistral 7B Instruct v0.3** (`mistralai/Mistral-7B-Instruct-v0.3`) | 7B | ~14 GB / ~4 GB | Third family; runs comfortably in 8 GB VRAM quantized. |
| *(optional)* **Gemma 2 9B Instruct** (`google/gemma-2-9b-it`) | 9B | ~18 GB / ~6 GB | Google lineage; useful as a fourth family for the comparison matrix. |

### Selection

1. Check the local hardware first (VRAM if GPU, RAM if CPU-only).
2. Pick the **largest of these that runs comfortably quantized (Q4_K_M)**
   on that machine — "the best model your computer can run".
3. Wire it as the second adapter family next to `deepseek-chat`; record model,
   quantization, and adapter version in provenance for every run.

---

## Ruled out — fine-tuned cyber / abliterated-uncensored models

Earlier drafts listed red-team fine-tunes (RavenX-CyberAgent, Pentest-7B,
BugTraceAI-CORE, Dolphin3-Cyber, Security-SLM) and abliterated/uncensored
bases. They are **out of scope**, for two independent reasons:

1. **Dual-use review.** A study whose second adapter family is "models
   fine-tuned on offensive-security corpora" or "models with the safety
   filter removed" would be rejected in a dual-use review, and rightly so.
   The pipeline's framing is *authorized simulation content with a
   deterministic assembler and validator* — nothing about it requires
   uncensored checkpoints. Curiosity about what they generate is legitimate
   to note here, but not a reason to adopt them.
2. **The realism argument does not hold.** An abliterated model is *the same
   model with its instruction-following alignment degraded* — abliteration
   measurably costs a little quality rather than adding it. A standard
   Llama 3.1 / Qwen 2.5 / Mistral instruct, prompted in a research context
   (as this pipeline already does), generates equally realistic synthetic
   messages — arguably better, because the base model is intact. "Realism"
   is not a reason to drop the filter; it is a reason to keep the intact
   model.

If a comparison against fine-tuned checkpoints is ever wanted, it must be
justified as a *comparison baseline* and reviewed case by case — it is not a
default design choice.
