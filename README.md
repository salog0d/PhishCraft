# PhishCraft — Phishing-Simulation Campaign Generator

> A configurable, reproducible **generator** of synthetic phishing-simulation campaigns over **email and SMS**, for **authorized** security-awareness research in controlled, isolated environments.

[![Status](https://img.shields.io/badge/status-research%20preview-orange.svg)](#)
[![License](https://img.shields.io/badge/license-TBD-lightgrey.svg)](#)

---

## Introduction

**PhishCraft** orchestrates a set of cooperating stages that plan, generate, and verify simulated phishing campaigns — entirely from the command line, through the interactive shell `ptshell` or the plain CLIs.

**Problem.** Running realistic security-awareness simulations by hand is slow and inconsistent. Teams need a reproducible way to generate varied, well-labeled campaigns that provably satisfy their constraints — **without ever touching real victim data or live infrastructure.** The contribution here is a generator whose output is *reproducible* (fixed seed, logged provenance) and *coherent* (persona, timing, and cross-channel references hold), verified rather than measured against victims.

**Key features**

- **ADK pipeline** — a Google ADK `SequentialAgent` running three stages:
  an `LlmAgent` content step, a deterministic assembler, and a deterministic
  validator (generate → assemble → verify, one-way).
- **Two channels** — email and SMS (voice is out of scope).
- **Multi-model adapters** — generate through at least two model families so results are comparable and reproducible across families.
- **Coherence validators** — a consistent impersonated persona, a coherent send timeline, existing cross-channel references, link consistency (body links must match the CTA), and sender-recipient separation (the persona never impersonates its own recipient), enforced in the schema and reported by a deterministic validator.
- **Deterministic persona selection** — the impersonated identity is derived from the `(pretext, recipient)` pair (org chart for executive requests, service desk for IT pretexts, supplier/carrier/bank for BEC pretexts), so the LLM never invents the sender.
- **Provenance log** — model, parameters, seed, and prompt hash recorded for every artifact.
- **Synthetic-only data** — the target catalog (12 internal employees + 3 external personas) is generated internally; no external OSINT tools or live collection.
- **Reproducibility & reliability measurement** — a harness that reruns the same spec with a fixed seed and reports three link-consistency numbers over a 10-spec baseline: the **first-attempt raw violation rate** (generator reliability, from the stale tokens the LLM wrote before any refinement round), the **post-refinement raw violation rate** (what remains on the delivered artifact), and the **post-assembler failure rate** (delivery guarantee, by construction 0 for links). A driver-level self-refinement loop (critique from the validator's own `link_fixes`, `{{cta-link}}` placeholder convention) repairs violations before delivery.
- **Built-in authorization gate** — every campaign must be attested as authorized before generation runs.

---

## Installation

### Prerequisites

- **Python** 3.12+
- **pip** 24+ (and optionally a virtual environment)
- **Graphviz** (only for regenerating architecture diagrams): `apt-get install graphviz` (Linux) / `brew install graphviz` (macOS)

### Install

```bash
# 1. Clone
git clone <repository-url>
cd <repository>

# 2. Create and activate a virtual environment
python3 -m venv venv
source venv/bin/activate        # Windows: venv\Scripts\activate

# 3. Install dependencies
pip install -r requirements.txt

# 4. (Optional) Install the CLI in editable mode
pip install -e .
```

Verify the installation:

```bash
python -m generator_agent.run --help
python -m ptshell                 # or just start the interactive shell
```

---

## Quick Start

Run the ADK pipeline against a synthetic persona from the CLI:

```bash
# Generate a campaign across email + SMS through the ADK pipeline
# (model from env: ADK_MODEL=deepseek/deepseek-chat uses DEEPSEEK_API_KEY,
#  default gemini-2.5-flash uses GOOGLE_API_KEY)
python -m generator_agent.run \
    --pretext executive_request \
    --difficulty medium \
    --seed 42
# → data/q3-awareness-2026/generated_campaign.json
# → data/q3-awareness-2026/coherence_report.json

# Measure reproducibility (same spec twice), reliability (10 specs), and
# run the post-run quality lifecycle (every run is scanned)
python -m measurement.reproduce   --adapter adk --spec-id S1 --runs 2
python -m measurement.reliability --adapter adk --runs 1
python -m measurement.quality     --adapter adk --runs 1
# → data/measurements/.../reproducibility.json + reliability.json + summary.md
# → data/measurements/.../quality.json + quality-summary.md
#   (artifact scan, contamination scan, stage-direction stripping stats,
#    automated label audit — the COVA-X-style quality lifecycle, recorded
#    on every run; findings are evidence, never repairs)
```

### The variety experiment — 1000 campaigns

A large, balanced generation experiment: 8 pretexts × 4 tones ×
3 difficulties = **96 spec cells** × 12 internal recipients × 6 local models
= **1000 campaigns** through the real ADK pipeline, each with a unique seed,
the coherence validation, and the post-run quality scan. Resumable and
piloted:

```bash
python scripts/variety_experiment.py --pilot     # 2 runs per model (12 total)
python scripts/variety_experiment.py             # the full 1000-run experiment
python scripts/variety_experiment.py --workers 2 # ... two models in parallel

python scripts/variety_report.py --out experiment/variety-<timestamp>
# → quality.json (aggregate payload), summary.md, charts/*.png
#   (flag rates per check / pretext / model, contamination, label audit,
#    coherence failures, durations, cumulative findings, heatmap)
```

Per-run artifacts (campaign, coherence report, quality report) land under
`experiment/variety-*/models/<model>/<run_id>/`; every outcome is appended to
the append-only `runs.jsonl`, so an interrupted run resumes where it stopped
(completed runs are skipped, failed ones retried). The report can be re-run
mid-experiment to watch the metrics accumulate.

Prefer the HTTP service? The same engine is exposed as an API:

```bash
uvicorn app.main:app --reload
# → http://127.0.0.1:8000/docs  (interactive OpenAPI docs)
# → GET /health returns {"status": "ok"}
```

---

## Local models with Ollama (NVIDIA GeForce RTX 3070)

PhishCraft can generate entirely offline through [Ollama](https://ollama.com/).
The pipeline was validated on an **RTX 3070 (8 GB VRAM)**: the sweet spot is
**7–8B models at 4-bit quantization**, plus fast 3–4B models. These local models
satisfy the multi-model / cross-family requirement of `model_policy` without
any API key, and keep every artifact on this machine.

### Recommended models

| Model | Pull command | Size (Q4) | Fits in 8 GB? | Why for PhishCraft |
|---|---|---|---|---|
| **Qwen3 8B** | `ollama pull qwen3:8b` | ~5.4 GB | ✅ comfortable | Best all-rounder: strong Spanish/Portuguese (LATAM config), reliable JSON for the assembler/validator schema |
| **Llama 3.1 8B** | `ollama pull llama3.1:8b` | ~4.9 GB | ✅ comfortable | Reliable general writer for email/SMS copy; second model family for cross-family runs |
| **Gemma 3 4B** | `ollama pull gemma3:4b` | ~3.4 GB | ✅ lots of headroom | 140+ languages, good instruction following, fast |
| **Qwen3 4B** | `ollama pull qwen3:4b` | ~2.6 GB | ✅ lots of headroom | Fast, multilingual, very good JSON reliability |
| **Phi-4 Mini** | `ollama pull phi4-mini` | ~2.5 GB | ✅ lots of headroom | Strong structured output / reasoning for the validation-side work |
| **Llama 3.2 3B** | `ollama pull llama3.2:3b` | ~2.0 GB | ✅ fastest | High-throughput drafting when generating volume |
| **DeepSeek-R1 7B** | `ollama pull deepseek-r1:7b` | ~4.7 GB | ✅ comfortable | Reasoning model for the self-refinement / critique loop |

**Avoid** models ≥ 12–14B (`phi4:14b`, `gemma3:12b`, `mistral-small3.1:24b`):
their weights alone need 9–17 GB and spill into CPU RAM, making generation
painfully slow on this card.

**Picks for the pipeline:** `qwen3:8b` as the primary generator and
`llama3.1:8b` as the second family (cross-family comparison); `gemma3:4b` as a
lightweight fallback.

### Install Ollama

```bash
# Linux / WSL2 (auto-detects the NVIDIA GPU via CUDA)
curl -fsSL https://ollama.com/install.sh | sh
```

- **macOS / Windows:** download the installer from
  <https://ollama.com/download>.
- **NVIDIA driver:** Ollama 0.22+ ships CUDA support out of the box; make sure
  the proprietary NVIDIA driver is installed (`nvidia-smi` must list the GPU).

### Pull the models and verify the GPU

```bash
# Pull the validated local set (~25 GB total)
ollama pull qwen3:8b
ollama pull llama3.1:8b
ollama pull gemma3:4b
ollama pull qwen3:4b
ollama pull phi4-mini
ollama pull llama3.2:3b
ollama pull deepseek-r1:7b

# Sanity check
ollama run qwen3:8b "Write one short test sentence."
ollama list      # shows every model + disk size
ollama ps        # while running: confirms the model sits on the GPU, not CPU
```

### Use them with PhishCraft

The generator resolves the model from `ADK_MODEL` (see
[Configuration](#configuration)). Ollama exposes an OpenAI-compatible endpoint
at `http://localhost:11434/v1`, so any `litellm`-style adapter can point at it:

```bash
# Example: generate through the local Qwen3 8B
ADK_MODEL=ollama/qwen3:8b python -m generator_agent.run \
    --pretext executive_request \
    --difficulty medium \
    --seed 42
```

> **Note:** `agent/config.py` routes both the `deepseek/` and `ollama/`
> prefixes through the LiteLlm wrapper (`OLLAMA_API_BASE` defaults to
> `http://localhost:11434`). Set `ADK_MODEL_TRACE_FILE` to capture every LLM
> call — prompt, thinking, answer, usage — as JSONL (see
> `scripts/ollama_experiment.py` and `scripts/read_trace.py`).

> **VRAM note:** keep the context window modest — `num_ctx` 4096–8192 — because
> the KV cache shares the same 8 GB. Structured output is available via
> `format=json` on all models listed above.

`python -m ptshell` opens **PhishCraft**, a Claude-Code-style interactive
REPL over the generator: a purple-and-white styled terminal UI with an ASCII
logo banner on startup, rich panels/tables, spinners, ✓/✗ badges,
a colored prompt with the model inline, tab-completion with descriptions, and
persistent command history. Configure everything in-session; settings persist
to `~/.pt-shell/config.json` (override the location with the `PTSHELL_CONFIG`
env var). All commands work with or without the leading slash.

```bash
python -m ptshell
```

**Full usage guide:** [`docs/pt-shell-guide.md`](./docs/pt-shell-guide.md).

| Command | What it does |
|---------|--------------|
| `/help` | List commands. |
| `/config [key [value]]` | View or set settings (e.g. `/config seed 7`, `/config pretext invoice_payment`); `/config reset` restores defaults. |
| `/model <id>` · `/models` | Set or list the generation model (e.g. `deepseek/deepseek-chat`, or `ollama/qwen3:8b` for a local model — `/models` and Tab-completion discover them live from `ollama list`). Model switches apply to the next `/generate`. |
| `/recipient <id>` · `/recipients` | Set the default recipient or list the target catalog (12 internal + supplier/bank/carrier). |
| `/generate` | Run the ADK pipeline once with the current settings; prints the campaign + the 5-check validator report + the quality scan, and saves campaign/report/provenance/quality_report under `data/shell/<campaign_id>/`. |
| `/validate [campaign.json]` | Run the 5 coherence checks on a campaign file (defaults to the last generated one). |
| `/quality [campaign.json]` | Run the post-run quality scan (9 checks + label audit + strip stats) on a campaign file or the last run. |
| `/measure [--runs=N]` | Run the 10-spec reliability suite and print the failure-rate table (writes `summary.md`). |
| `/reproduce [all]` | Run the same spec twice and compare (default: spec S1, seed 42). |
| `/send` | Deliver the last generated campaign to the MailHog sink (`docker compose up -d`). |
| `/status` | Show current settings and the last run summary. |
| `/quit` | Exit (also `/exit` or Ctrl-D). |

Offline mode: `/config adapter stub` makes `/generate`, `/measure`, and
`/reproduce` run without any LLM call — useful for demos and CI.

---

## Project structure

Every file's job, grouped by directory.

### Root

| File | What it is / why it matters |
|------|------------------------------|
| `README.md` | This file: project framing, install, quick start, and structure. |
| `requirements.txt` | Pinned dependencies (`google-adk`, `litellm`, `fastapi`, `pydantic`, …). |
| `compose.yaml` | Local MailHog SMTP sink used by `--send` (delivery sandbox). |
| `implementation-instructions.md` | Step-by-step execution plan (ADK pipeline + measurement) for an implementing agent. |
| `.gitignore` | Excludes `venv/`, caches, `.env`, and other non-versioned files. |

### `agent/` — the Google ADK pipeline

| File | What it is / why it matters |
|------|------------------------------|
| `agent/pipeline.py` | The ADK `SequentialAgent` (the orchestrator): content `LlmAgent` → deterministic assembler → deterministic validator. |
| `agent/config.py` | Model resolution from env (`ADK_MODEL`, `DEEPSEEK_API_KEY`); loads the gitignored `.env`; no secrets in code. |
| `agent/assembler.py` | Stage 2: parses the 8 content bindings and calls `assemble_campaign` with the fixed clock/schedule. |
| `agent/validator.py` | Stage 3: runs `validator_agent.validate_campaign` and emits the `CoherenceReport`. |
| `agent/driver.py` | Programmatic runner: seeds session state, drives the ADK `Runner`, returns campaign + report. |
| `agent/__init__.py` | Package marker exposing `root_agent`. |

### `app/` — the FastAPI service and data contracts

| File | What it is / why it matters |
|------|------------------------------|
| `app/main.py` | FastAPI entry point (`uvicorn app.main:app`); registers routes and `/health`. |
| `app/presentation/routes.py` | `POST /generation/messages`: validates a `PhishingGenerationRequest` and returns the 202 acknowledgement. |
| `app/core/schemas.py` | **Single source of truth**: all Pydantic contracts (mission, generation, campaign, coherence, provenance, envelope) and their business rules. |
| `app/application/`, `app/domain/`, `app/infra/`, `app/services/`, `app/__init__.py`, `app/presentation/__init__.py`, `app/core/__init.py__.py` | Package markers; empty placeholders for the hex/clean architecture layers. |

### `generator_agent/` — the generator half

| File | What it is / why it matters |
|------|------------------------------|
| `generator_agent/assemble.py` | Model-free, **deterministic** assembler: seed-derived tracking token, persona stamping (from the deterministic selection), references, provenance, and the charter constant. Unit-tested with no API key. |
| `generator_agent/catalog.py` | Loads the target catalog (12 internal + 3 external personas), builds generator profiles, and derives the impersonated persona per `(pretext, recipient)` via `persona_for`. |
| `generator_agent/run.py` | CLI: loads a mission file, drives the ADK pipeline, writes campaign + report, optional `--send`. |
| `generator_agent/send.py` | Delivers a campaign to the MailHog SMTP sink (email as email, SMS tagged `[SMS]`). |
| `generator_agent/agent.py` | **Legacy reference**: the old LMQL query; superseded by the ADK content agent, kept for documentation only. |
| `generator_agent/__init__.py` | Package marker. |

### `validator_agent/` — the deterministic validator (no LLM)

| File | What it is / why it matters |
|------|------------------------------|
| `validator_agent/validate.py` | The five coherence checks (persona, timing, reference existence, **link consistency**, **sender-recipient separation**); always emits a `CoherenceReport`, never raises. |
| `validator_agent/links.py` | URL/token extraction used by the `link_consistency` check. |
| `validator_agent/__init__.py` | Package marker exposing `validate_campaign`. |

### `quality_agent/` — the post-run quality lifecycle (COVA-X methodology)

Deterministic, no LLM, runs on **every** generated campaign; findings are
evidence, never repairs.

| File | What it is / why it matters |
|------|------------------------------|
| `quality_agent/scan.py` | `scan_campaign`: the full lifecycle — 9 checks, strip stats, label audit → `QualityReport`. |
| `quality_agent/artifacts.py` | Five generation-artifact scanners: dialogue collapse, stage direction, turn overflow, meta bleed, loop detection. |
| `quality_agent/contamination.py` | Four contamination scanners: pretext lexicon bleed, roster-name drift, wrong-brand mentions, non-Latin script. |
| `quality_agent/strip.py` | `strip_stage_directions` — measured on a copy, never applied to the artifact. |
| `quality_agent/labels.py` | Automated label audit: heuristic-implied pretext/tone/difficulty vs. the spec labels (`ok` / `mismatch` / `unverifiable`). |
| `quality_agent/lexicon.py` | The shared deterministic lexicons and pattern sets behind the scanners. |

### `measurement/` — the reproducibility & reliability harness

| File | What it is / why it matters |
|------|------------------------------|
| `measurement/specs.py` | The 10-spec baseline (`CampaignSpec`): recipients, pretexts, tones, seeds. |
| `measurement/adapters.py` | `AdkPipelineAdapter` (real, drives ADK) and `StubAdapter` (offline CI path). |
| `measurement/runner.py` | Runs one spec, catches every failure as a `generation_error` record, computes canonical hashes, and records the post-run quality scan variables. |
| `measurement/reproduce.py` | CLI: same spec × N runs → `reproducibility.json` (content + deterministic-layer hashes). |
| `measurement/reliability.py` | CLI: all specs → `reliability.json` + `summary.md` with the violation/failure-rate tables and the quality-flag aggregates. |
| `measurement/quality.py` | CLI: all specs → `quality.json` + `quality-summary.md` (flag rates per check and per pretext, contamination, label audit, stripping stats). |
| `measurement/__init__.py` | Package marker. |

### `org/` — synthetic people (the simulation context)

| File | What it is / why it matters |
|------|------------------------------|
| `org/fantazylabz_org.json` | The 12-person internal roster (BEC-relevant roles). |
| `org/external_personas.json` | External BEC impersonation sources: a supplier, a bank, and a carrier (`.example` domains). |
| `org/fantazylabz_org.md` | Human-readable roster by department. |
| `org/fantazylabz_org_graph.md` | Org chart (Mermaid + text tree). |

### `prompts/` — stage charters

| File | What it is / why it matters |
|------|------------------------------|
| `prompts/generator_ag.md` | The content agent's charter (few-shot examples the LLM conditions on). |
| `prompts/validator_ag.md` | Documentation-parity charter for the 5 checks; the code module is authoritative. |
| `prompts/orchestrator_ag.md` | Non-executable design note: the orchestrator is the ADK `SequentialAgent`. |

### `docs/` — documentation

| File | What it is / why it matters |
|------|------------------------------|
| `docs/architecture.md` | Stage architecture, phases, and the measurement loop. |
| `docs/pt-shell-guide.md` | **User guide**: install, commands, settings, models, offline mode, measurement, troubleshooting. |
| `docs/flow-schema.md` | Every JSON contract with examples and business rules. |
| `docs/generator-reliability-plan.md` | The design rationale behind this build (workstreams W0–W5). |
| `docs/models.md` | Model catalog for the cross-family study (standard open instructs; abliterated/uncensored ruled out). |
| `docs/README.md` | Docs index. |

### `ptshell/` — PhishCraft, the interactive harness (Claude-Code-style REPL)

| File | What it is / why it matters |
|------|------------------------------|
| `ptshell/shell.py` | The REPL (`cmd.Cmd`): slash commands `/generate`, `/validate`, `/measure`, `/reproduce`, `/send`, `/config`, … each capability is a `do_*` method. |
| `ptshell/config.py` | Persistent settings (`~/.pt-shell/config.json`, override `PTSHELL_CONFIG`): defaults, validation, and save/reset. |
| `ptshell/__main__.py` | Entry point: `python -m ptshell`. |
| `ptshell/__init__.py` | Package marker. |

### `config/`, `scripts/`, `tests/`, `data/`, `diagrams_output/`

| File | What it is / why it matters |
|------|------------------------------|
| `config/q3-awareness-2026.mission.json` | Default `MissionConfig` file (authorized, synthetic-only, seed 42). |
| `scripts/generate_diagrams.py` | Regenerates the five architecture diagrams into `diagrams_output/`. |
| `tests/test_flow_contracts.py` | Business-rule and persistence-rule tests for the schemas. |
| `tests/test_generator_agent.py` | Offline tests for the deterministic assembler (incl. determinism + token tests). |
| `tests/test_validator_agent.py` | Regression: the validator must catch the known `abc123` vs `d6db8064874a` link failure. |
| `tests/test_send.py` | Campaign-message → email mapping (no SMTP, no network). |
| `tests/test_ptshell.py` | Offline tests for the interactive shell (config persistence + every command). |
| `tests/__init__.py` | Test package marker. |
| `diagrams_output/diagram_*.png` | Rendered architecture diagrams (regenerate, don't hand-edit). |
| `data/q3-awareness-2026/generated_campaign.json` | **Committed evidence**: the original sample containing the cross-channel link bug. |
| `data/measurements/known-case/generated_campaign.json` | Preserved copy of that evidence, consumed by the validator regression test. |
| `data/measurements/known-case/ceo_self_impersonation.json` | Preserved evidence of the sender-recipient gap (CEO addressing herself, passed the 4-check suite); pins the `sender_recipient` regression test. |
| `data/measurements/reproduce-adk/` | Reproducibility results (seed 42 run twice, byte-identical). |
| `data/measurements/reproduce-adk-fixed/` | Post-fix reproducibility: deterministic layer identical; prose varies between provider calls at temperature 0. |
| `data/measurements/reliability-adk-*/` | Reliability results (`reliability.json` + `summary.md`: raw + post-assembler failure tables). |
| `data/measurements/README.md` | **How to read the numbers**: raw vs post-assembler metrics, actual sampling params, known gaps. |

---

## Documentation

- **Documentation home:** [`docs/`](./docs/README.md)
- **Interactive shell guide:** [`docs/pt-shell-guide.md`](./docs/pt-shell-guide.md)
- **Architecture & pipeline design:** [`docs/architecture.md`](./docs/architecture.md)
- **Data contracts (JSON):** [`docs/flow-schema.md`](./docs/flow-schema.md)
- **Model catalog (cross-family study):** [`docs/models.md`](./docs/models.md)
- **Local models on Ollama (RTX 3070):** [README section](#local-models-with-ollama-nvidia-geforce-rtx-3070)
- **Lab notebook:** [`docs/bitacora.md`](./docs/bitacora.md)
- **Architecture diagrams:** [`diagrams_output/`](./diagrams_output/) — regenerate with `python3 scripts/generate_diagrams.py`
- **API reference:** available at `/docs` when the service is running.

---

## Configuration

Configuration is resolved in this order: **CLI flags → environment variables → mission file → defaults.**

### Environment variables

| Variable | Description | Default |
|----------|-------------|---------|
| `ADK_MODEL` | Model id resolved by ADK (e.g. `deepseek/deepseek-chat`, `gemini-2.5-flash`). | `gemini-2.5-flash` |
| `DEEPSEEK_API_KEY` | API key for DeepSeek models (via LiteLlm). | — |
| `GOOGLE_API_KEY` | API key for Gemini models. | — |
| `ANTHROPIC_API_KEY` / `OPENAI_API_KEY` | Keys for the LiteLlm options. | — |
| `PTSHELL_CONFIG` | Settings file for the interactive shell. | `~/.pt-shell/config.json` |

Keys can also live in a gitignored `.env` file at the repo root (loaded
automatically). **No key is ever committed.**

### Mission file (`config/q3-awareness-2026.mission.json`)

The mission file is the campaign-level config: authorization attestation,
synthetic-only constraints, channels, the model policy (≥ 2 families), the
reproducibility seed, and the ethics guardrails.

```json
{
  "campaign_id": "q3-awareness-2026",
  "authorized": true,
  "objective": "security-awareness-training",
  "constraints": { "synthetic_data_only": true, "channels": ["email", "sms"] },
  "model_policy": {
    "models": [
      { "family": "deepseek", "name": "deepseek-chat" },
      { "family": "anthropic", "name": "claude-opus-5" }
    ]
  },
  "reproducibility": { "seed": 42, "deterministic": true },
  "ethics": { "consent_reference": "IRB-2026-014", "isolated_environment": true }
}
```

---

## Contributing

Contributions are welcome. Open an issue to discuss significant changes before
starting; keep commits focused with clear messages; add tests for new
behavior; ensure `pytest -q` and `ruff check . && ruff format .` pass before
opening a PR.

> **Responsible use:** This project is for authorized, controlled research only. Do not submit features that enable real-world data collection, targeting of non-consenting individuals, or bypassing the authorization gate.

---

## License

License: **TBD** — pending the repository owner's decision.

---

## Contact & Support

- **Issue tracker:** open an issue in the repository.
- **Security disclosures:** please report privately to the maintainer — do not open a public issue.
