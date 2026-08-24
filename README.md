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

- **Generation pipeline** — Orchestrator, Recon, Profiler, Generator, and Validator stages, each with a single responsibility.
- **Two channels** — email and SMS (voice is out of scope).
- **Multi-model adapters** — generate through at least two model families so results are comparable and reproducible across families.
- **Coherence validators** — a consistent impersonated persona, a coherent send timeline, and existing cross-channel references, all enforced in the schema.
- **Provenance log** — model, parameters, seed, and prompt hash recorded for every artifact.
- **Synthetic-only data** — target catalogs and recipient profiles are generated internally; no external OSINT tools or live collection.
- **Built-in authorization gate** — every campaign must be attested as authorized before generation runs.

---

## Installation

### Prerequisites

- **Python** 3.14+
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

Run a full simulation pipeline against a synthetic dataset from the CLI:

```bash
# Initialize a workspace and a sample config
[cli-name] init ./my-campaign

# Generate synthetic targets/domains (no external data is collected)
[cli-name] recon --region latam --sector finance --count 50 --output targets.json

# Build synthetic recipient profiles from the targets
[cli-name] profile --input targets.json --output profiles.json

# Generate a campaign across email + SMS (authorization is required)
[cli-name] generate \
    --profiles profiles.json \
    --channels email,sms \
    --pretext executive_request \
    --difficulty medium \
    --model anthropic:claude-opus-5 --model openai:gpt-4.1 \
    --seed 42 \
    --authorized

# Verify coherence and write the provenance log
[cli-name] validate --campaign campaign.json
```

Prefer the HTTP service? The same engine is exposed as an API:

```bash
uvicorn app.main:app --reload
# → http://127.0.0.1:8000/docs  (interactive OpenAPI docs)
# → GET /health returns {"status": "ok"}
```

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
    - { family: anthropic, name: claude-opus-5 }
    - { family: openai, name: gpt-4.1 }
stages:
  recon:
    synthetic_count: 50
  profiler:
    profiles_per_target: 5
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
