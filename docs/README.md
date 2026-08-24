# [Project Name] — Documentation

Welcome to the documentation for **[Project Name]**, a configurable, reproducible **generator** of synthetic phishing-simulation campaigns over **email and SMS**, for **authorized** security-awareness research in controlled, isolated environments.

> **Scope & responsible use.** This project runs on **synthetic, internally generated data only** — no external tools or OSINT sources are used to collect real data. Every campaign must pass a built-in authorization gate. Its goal is showing the generator **reliably and reproducibly satisfies campaign constraints** — not measuring whether a message deceives a victim (there is no interaction tracking, KPI, or success-optimization loop). It is intended solely for security-awareness training and red-team exercises with explicit authorization.

---

## Contents

| Document | Description |
|----------|-------------|
| [Architecture](./architecture.md) | Stage roles, the pipeline (Phases 0–4), and the communication graph. |
| [Flow Schema](./flow-schema.md) | JSON data contracts for every stage hand-off across the pipeline. |
| [Diagrams](../diagrams_output/) | Rendered architecture diagrams (PNG, 300 DPI). **Stale — regenerate after this realignment.** |
| [Project README](../README.md) | Installation, quick start, and configuration. |

---

## Overview

The system decomposes campaign generation into single-responsibility stages coordinated by an orchestrator:

| Stage | Role | Responsibility |
|-------|------|----------------|
| **Orchestrator-AG** | Coordination | Reads the `MissionConfig`, enforces constraints, fixes the seed and model policy, drives the run. |
| **Recon-AG** | Intelligence | Synthetic targets/domains and simulated attack surfaces (no external collection). |
| **Profiler-AG** | Synthetic data | Labeled synthetic recipient profiles built from the targets (no external collection). |
| **Generator-AG** | LLM generation | Generates email and SMS content through model-family adapters (≥ 2 families), recording provenance. |
| **Validator-AG** | Coherence & provenance | Runs the coherence validators (persona / timing / cross-channel reference) and finalizes the provenance log. |

See [architecture.md](./architecture.md) for the full pipeline, per-phase outputs, and the stage communication diagram.

---

## Pipeline at a glance

```
Phase 0  Planning                  (Orchestrator-AG) → MissionConfig (channels, model policy, seed)
Phase 1  Synthetic Reconnaissance  (Recon-AG)        → synthetic targets + attack surfaces
Phase 2  Profiling & Content       (Profiler-AG)     → recipient profiles + prompt templates + assets
Phase 3  Generation                (Generator-AG)    → GeneratedMessage (email/SMS) + provenance
Phase 4  Coherence & Provenance    (Validator-AG)    → CoherenceReport + ProvenanceLog
```

---

## Working with the docs

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

- **Issues:** [https://github.com/[owner]/[repo]/issues](https://github.com/[owner]/[repo]/issues)
- **Discussions:** [https://github.com/[owner]/[repo]/discussions](https://github.com/[owner]/[repo]/discussions)
- **Security disclosures:** report privately per [`SECURITY.md`](../SECURITY.md).
