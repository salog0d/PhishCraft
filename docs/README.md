# [Project Name] — Documentation

Welcome to the documentation for **[Project Name]**, a multi-agent, CLI-driven pipeline for **authorized** phishing-simulation research in controlled, isolated environments.

> **Scope & responsible use.** This project runs on **synthetic, internally generated data only** — no external tools or OSINT sources are used to collect real data. Every campaign must pass a built-in authorization gate. It is intended solely for security-awareness training and red-team exercises with explicit authorization.

---

## Contents

| Document | Description |
|----------|-------------|
| [Architecture](./architecture.md) | Agent roles, the distributed pipeline (Phases 0–7), and the communication graph. |
| [Flow Schema](./flow-schema.md) | JSON data contracts for every agent hand-off across the pipeline. |
| [Diagrams](../diagrams_output/) | Rendered architecture diagrams (PNG, 300 DPI). |
| [Project README](../README.md) | Installation, quick start, and configuration. |

---

## Overview

The system decomposes a simulation campaign into single-responsibility agents coordinated by an orchestrator:

| Agent | Role | Responsibility |
|-------|------|----------------|
| **Recon-AG** | Intelligence | Generation of synthetic target/domain data (no external collection). |
| **Harvest-AG** | Collection | Structuring of synthetic victim profiles into labeled datasets. |
| **Design-AG** | Creative | Generation of communication templates (email, SMS, voice). |
| **Payload-AG** | Technical | Creation of simulation content (links, files). |
| **Responder-AG** | Interaction | Automated responses across email, SMS, and voice calls. |
| **Orchestrator-AG** | Coordination | Launches campaigns, manages state, synchronizes agents. |
| **Monitor-AG** | Analytics | Collects KPIs, generates reports, detects success patterns. |

See [architecture.md](./architecture.md) for the full pipeline, per-phase outputs, and the agent communication diagram.

---

## Pipeline at a glance

```
Phase 0  Planning              (Orchestrator-AG)
Phase 1  Synthetic Recon       (Recon-AG)        → synthetic targets + surfaces
Phase 2  Dataset Construction  (Harvest-AG)      → labeled synthetic dataset
Phase 3  Content Generation    (Design + Payload)→ campaign set
Phase 4  Controlled Launch     (Orchestrator-AG) → send schedule
Phase 5  Interaction Handling  (Responder-AG)    → interaction transcripts
Phase 6  Monitoring & KPIs     (Monitor-AG)      → KPIs & dashboards
Phase 7  Feedback              (Orchestrator + Monitor) → refined dataset & templates
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
