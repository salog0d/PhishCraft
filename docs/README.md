# PhishCraft — Documentation

Welcome to the documentation for **PhishCraft**, a configurable, reproducible **generator** of synthetic phishing-simulation campaigns over **email and SMS**, for **authorized** security-awareness research in controlled, isolated environments.

> **Scope & responsible use.** This project runs on **synthetic, internally generated data only** — no external tools or OSINT sources are used to collect real data. Every campaign must pass a built-in authorization gate. Its goal is showing the generator **reliably and reproducibly satisfies campaign constraints** — not measuring whether a message deceives a victim (there is no interaction tracking, KPI, or success-optimization loop). It is intended solely for security-awareness training and red-team exercises with explicit authorization.

---

## Contents

| Document | Description |
|----------|-------------|
| [PhishCraft User Guide](./pt-shell-guide.md) | **How to use the tool**: install, launch, commands, settings, models, offline mode, measurement, troubleshooting. |
| [Architecture](./architecture.md) | Stage roles (ADK pipeline), phases, and the measurement loop. |
| [Flow Schema](./flow-schema.md) | JSON data contracts for every hand-off across the pipeline. |
| [Model catalog](./models.md) | Cross-family study candidates (standard open instructs; what was ruled out and why). |
| [Generator reliability plan](./generator-reliability-plan.md) | The design rationale behind the current build (workstreams W0–W5) + the Oct-2026 review addendum. |
| [Measurement results](../data/measurements/README.md) | **How to read the numbers** (raw vs post-assembler, actual params, known gaps). |
| [Bitácora](./bitacora.md) | Lab notebook: dated findings, decisions, and open questions. |
| [Diagrams](../diagrams_output/) | Rendered architecture diagrams (PNG, 300 DPI). |
| [Project README](../README.md) | Installation, quick start, project structure, and configuration. |

---

## Overview

The pipeline is a **Google ADK** agent graph — a linear, non-autonomous
`SequentialAgent` with three stages. Only the first stage calls an LLM.

| Stage | Kind | Responsibility |
|-------|------|----------------|
| `generator_content_agent` | ADK `LlmAgent` | Writes content bindings (persona echo + email subject/body + SMS body) in the requested tone/difficulty/language. |
| `assembler_agent` | ADK `BaseAgent` (deterministic) | Builds the `GeneratedCampaign`: ids, persona (deterministically selected per pretext × recipient), seed-derived tracking link, schedule, references, provenance. |
| `validator_agent` | ADK `BaseAgent` (deterministic) | Runs the five coherence checks (persona, timing, reference existence, link consistency, sender-recipient separation) and emits the `CoherenceReport`. |

See [architecture.md](./architecture.md) for the full pipeline, per-phase outputs,
and the stage communication diagram.

---

## Pipeline at a glance

```
Phase 0  Config                     → MissionConfig + CampaignSpec + PersonaCatalog (seeded into ADK state)
Phase 1  Generation  (Generator-AG) → GeneratedCampaign (email + SMS) with provenance
Phase 2  Verification (Validator-AG) → CoherenceReport (5 checks) + ProvenanceLog
Phase 3  Measurement (harness)      → reproducibility.json + reliability.json + summary.md
```

---

## Working with the docs

- **Use the tool interactively:** `python -m ptshell` — see the
  [PhishCraft User Guide](./pt-shell-guide.md).
- **Architecture diagrams** are generated from code. Regenerate them after editing the pipeline:

  ```bash
  python3 scripts/generate_diagrams.py
  ```

  Output is written to [`diagrams_output/`](../diagrams_output/). Requires system Graphviz (`apt-get install graphviz` / `brew install graphviz`).

- **API reference** is served interactively at `/docs` when the service is running:

  ```bash
  uvicorn app.main:app --reload
  ```

---

## Getting help

- **Issues:** open an issue in the repository.
- **Security disclosures:** report privately to the maintainer — do not open a public issue.
