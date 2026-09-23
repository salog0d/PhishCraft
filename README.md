# [Project Name]

> A configurable, reproducible **generator** of synthetic phishing-simulation campaigns over **email and SMS**, for **authorized** security-awareness research in controlled, isolated environments.

<!-- Replace [owner]/[repo] with your repository path before publishing. -->
[![CI](https://img.shields.io/github/actions/workflow/status/[owner]/[repo]/ci.yml?branch=main&label=CI)](https://github.com/[owner]/[repo]/actions)
[![Coverage](https://img.shields.io/codecov/c/github/[owner]/[repo]?label=coverage)](https://codecov.io/gh/[owner]/[repo])
[![Version](https://img.shields.io/github/v/release/[owner]/[repo]?label=version)](https://github.com/[owner]/[repo]/releases)
[![License](https://img.shields.io/badge/license-[License]-blue.svg)](./LICENSE)
[![Status](https://img.shields.io/badge/status-research%20preview-orange.svg)](#)

---

## Introduction

**[Project Name]** orchestrates a set of cooperating stages that plan, generate, and verify simulated phishing campaigns — entirely from the command line.

**Problem.** Running realistic security-awareness simulations by hand is slow and inconsistent. Teams need a reproducible way to generate varied, well-labeled campaigns that provably satisfy their constraints — **without ever touching real victim data or live infrastructure.** The contribution here is a generator whose output is *reproducible* (fixed seed, logged provenance) and *coherent* (persona, timing, and cross-channel references hold), verified rather than measured against victims.

**Key features**

- **ADK pipeline** — a Google ADK `SequentialAgent` running three stages:
  an `LlmAgent` content step, a deterministic assembler, and a deterministic
  validator (generate → assemble → verify, one-way).
- **Two channels** — email and SMS (voice is out of scope).
- **Multi-model adapters** — generate through at least two model families so results are comparable and reproducible across families.
- **Coherence validators** — a consistent impersonated persona, a coherent send timeline, existing cross-channel references, and link consistency (body links must match the CTA), all enforced in the schema and reported by a deterministic validator.
- **Provenance log** — model, parameters, seed, and prompt hash recorded for every artifact.
- **Synthetic-only data** — the persona catalog (12 internal + 2 external personas) is generated internally; no external OSINT tools or live collection.
- **Reproducibility & reliability measurement** — a harness that reruns the same spec with a fixed seed and counts constraint violations across a 10-spec baseline.
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
git clone https://github.com/[owner]/[repo].git
cd [repo]

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
[cli-name] --version
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

# Measure reproducibility (same spec twice) and reliability (10 specs)
python -m measurement.reproduce   --adapter adk --spec-id S1 --runs 2
python -m measurement.reliability --adapter adk --runs 1
# → data/measurements/.../reproducibility.json + reliability.json + summary.md
```

Prefer the HTTP service? The same engine is exposed as an API:

```bash
uvicorn app.main:app --reload
# → http://127.0.0.1:8000/docs  (interactive OpenAPI docs)
# → GET /health returns {"status": "ok"}
```

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
| `generator_agent/assemble.py` | Model-free, **deterministic** assembler: seed-derived tracking token, persona stamping, references, provenance, and the charter constant. Unit-tested with no API key. |
| `generator_agent/catalog.py` | Loads the persona catalog (12 internal + external) and builds generator profiles from it. |
| `generator_agent/run.py` | CLI: loads a mission file, drives the ADK pipeline, writes campaign + report, optional `--send`. |
| `generator_agent/send.py` | Delivers a campaign to the MailHog SMTP sink (email as email, SMS tagged `[SMS]`). |
| `generator_agent/agent.py` | **Legacy reference**: the old LMQL query; superseded by the ADK content agent, kept for documentation only. |
| `generator_agent/__init__.py` | Package marker. |

### `validator_agent/` — the deterministic validator (no LLM)

| File | What it is / why it matters |
|------|------------------------------|
| `validator_agent/validate.py` | The four coherence checks (persona, timing, reference existence, **link consistency**); always emits a `CoherenceReport`, never raises. |
| `validator_agent/links.py` | URL/token extraction used by the `link_consistency` check. |
| `validator_agent/__init__.py` | Package marker exposing `validate_campaign`. |

### `measurement/` — the reproducibility & reliability harness

| File | What it is / why it matters |
|------|------------------------------|
| `measurement/specs.py` | The 10-spec baseline (`CampaignSpec`): recipients, pretexts, tones, seeds. |
| `measurement/adapters.py` | `AdkPipelineAdapter` (real, drives ADK) and `StubAdapter` (offline CI path). |
| `measurement/runner.py` | Runs one spec, catches every failure as a `generation_error` record, computes canonical hashes. |
| `measurement/reproduce.py` | CLI: same spec × N runs → `reproducibility.json` (content + deterministic-layer hashes). |
| `measurement/reliability.py` | CLI: all specs → `reliability.json` + `summary.md` with the violation/failure-rate tables. |
| `measurement/__init__.py` | Package marker. |

### `org/` — synthetic people (the simulation context)

| File | What it is / why it matters |
|------|------------------------------|
| `org/fantazylabz_org.json` | The 12-person internal roster (BEC-relevant roles). |
| `org/external_personas.json` | External BEC personas: a supplier and a bank (`.example` domains). |
| `org/fantazylabz_org.md` | Human-readable roster by department. |
| `org/fantazylabz_org_graph.md` | Org chart (Mermaid + text tree). |

### `prompts/` — stage charters

| File | What it is / why it matters |
|------|------------------------------|
| `prompts/generator_ag.md` | The content agent's charter (few-shot examples the LLM conditions on). |
| `prompts/validator_ag.md` | Documentation-parity charter for the 4 checks; the code module is authoritative. |
| `prompts/orchestrator_ag.md` | Non-executable design note: the orchestrator is the ADK `SequentialAgent`. |

### `docs/` — documentation

| File | What it is / why it matters |
|------|------------------------------|
| `docs/architecture.md` | Stage architecture, phases, and the measurement loop. |
| `docs/flow-schema.md` | Every JSON contract with examples and business rules. |
| `docs/generator-reliability-plan.md` | The design rationale behind this build (workstreams W0–W5). |
| `docs/models.md` | Candidate model catalog (fine-tuned + foundation baselines). |
| `docs/README.md` | Docs index. |

### `config/`, `scripts/`, `tests/`, `data/`, `diagrams_output/`

| File | What it is / why it matters |
|------|------------------------------|
| `config/q3-awareness-2026.mission.json` | Default `MissionConfig` file (authorized, synthetic-only, seed 42). |
| `scripts/generate_diagrams.py` | Regenerates the five architecture diagrams into `diagrams_output/`. |
| `tests/test_flow_contracts.py` | Business-rule and persistence-rule tests for the schemas. |
| `tests/test_generator_agent.py` | Offline tests for the deterministic assembler (incl. determinism + token tests). |
| `tests/test_validator_agent.py` | Regression: the validator must catch the known `abc123` vs `d6db8064874a` link failure. |
| `tests/test_send.py` | Campaign-message → email mapping (no SMTP, no network). |
| `tests/__init__.py` | Test package marker. |
| `diagrams_output/diagram_*.png` | Rendered architecture diagrams (regenerate, don't hand-edit). |
| `data/q3-awareness-2026/generated_campaign.json` | **Committed evidence**: the original sample containing the cross-channel link bug. |
| `data/measurements/known-case/generated_campaign.json` | Preserved copy of that evidence, consumed by the validator regression test. |
| `data/measurements/reproduce-adk/` | Reproducibility results (seed 42 run twice, byte-identical). |
| `data/measurements/reliability-adk-*/` | Reliability results (`reliability.json` + `summary.md`: the failure-rate tables). |

---

## Documentation

- **Documentation home:** [`docs/`](./docs/README.md) · **Hosted docs:** [https://[docs-url]](https://[docs-url])
- **Architecture & pipeline design:** [`docs/architecture.md`](./docs/architecture.md)
- **Data contracts (JSON):** [`docs/flow-schema.md`](./docs/flow-schema.md)
- **Architecture diagrams:** [`diagrams_output/`](./diagrams_output/) — regenerate with `python3 scripts/generate_diagrams.py`
- **API reference:** available at `/docs` when the service is running.

---

## Configuration

Configuration is resolved in this order: **CLI flags → environment variables → config file → defaults.**

### Environment variables

| Variable | Description | Default |
|----------|-------------|---------|
| `[PREFIX]_ENV` | Runtime environment (`dev`, `staging`, `prod`) | `dev` |
| `[PREFIX]_CONFIG` | Path to the config file | `./config.yaml` |
| `[PREFIX]_DATA_DIR` | Directory for synthetic datasets and outputs | `./data` |
| `[PREFIX]_LOG_LEVEL` | Logging verbosity (`DEBUG`–`ERROR`) | `INFO` |
| `[PREFIX]_REQUIRE_AUTH` | Enforce the campaign authorization gate | `true` |

Copy the example file and adjust:

```bash
cp .env.example .env
```

### Config file (`config.yaml`)

```yaml
environment: dev
data_dir: ./data
require_authorization: true
channels: [email, sms]
reproducibility:
  seed: 42
model_policy:
  models:
    - { family: deepseek, name: deepseek-chat }
    - { family: anthropic, name: claude-opus-5 }
measurement:
  baseline_specs: 10
```

---

## Contributing

Contributions are welcome. Please read [`CONTRIBUTING.md`](./CONTRIBUTING.md) and our [Code of Conduct](./CODE_OF_CONDUCT.md) first.

```bash
# Fork, then set up a dev environment
git clone https://github.com/[your-username]/[repo].git
cd [repo]
python3 -m venv venv && source venv/bin/activate
pip install -r requirements.txt

# Run the test suite before opening a PR
pytest

# Format and lint
ruff check . && ruff format .
```

**Guidelines**

1. Open an issue to discuss significant changes before starting.
2. Create a feature branch (`feature/short-description`).
3. Keep commits focused; write clear messages.
4. Ensure tests and linters pass, and add tests for new behavior.
5. Open a pull request against `main` and fill in the template.

> **Responsible use:** This project is for authorized, controlled research only. Do not submit features that enable real-world data collection, targeting of non-consenting individuals, or bypassing the authorization gate.

---

## License

Distributed under the **[License]** license. See [`LICENSE`](./LICENSE) for full text.

---

## Contact & Support

- **Issue tracker:** [https://github.com/[owner]/[repo]/issues](https://github.com/[owner]/[repo]/issues)
- **Discussions / community:** [https://github.com/[owner]/[repo]/discussions](https://github.com/[owner]/[repo]/discussions)
- **Email:** [maintainer@example.com]
- **Security disclosures:** please report privately per [`SECURITY.md`](./SECURITY.md) — do not open a public issue.
