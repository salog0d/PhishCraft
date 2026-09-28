# Configurable Phishing-Campaign Generator — Architecture

> **Note.** This system is a **generator of synthetic phishing-simulation
> content** for **authorized security-awareness research** in isolated
> environments. It must not be used for malicious activity. All data is
> **synthetic and generated internally** — no external tools or OSINT sources
> collect real data.

---

## What this project is (and is not)

This is a **configurable, reproducible campaign generator**, not an
attack-simulation platform. Its scientific contribution is showing that the
generator **reliably and reproducibly satisfies campaign constraints** across
model families — not measuring whether a message deceives a victim.

Two scope decisions follow from that framing:

- **Channels: email + SMS only.** Voice is out of scope.
- **No success-optimization loop.** There is no victim-interaction tracking,
  no KPI dashboard, and no "if the exploit succeeded, optimize the templates"
  feedback. The generator's success criterion is *constraint satisfaction*,
  verified by the coherence validators and recorded in the provenance log.

The pipeline is built as a **Google ADK** agent graph. The orchestrator is the
ADK `SequentialAgent` itself — a linear, non-autonomous
generate → assemble → verify sequence.

---

## Stage Architecture

The pipeline has three stages. Only the first calls an LLM; the other two are
deterministic Python (custom ADK `BaseAgent`s), which is what makes the
pipeline measurable for reproducibility.

| Stage | Kind | Responsibility |
|-------|------|----------------|
| `generator_content_agent` | ADK `LlmAgent` | Emits the 8 content bindings (persona echo + email subject/body + SMS body) in the requested tone/difficulty/language. Writes nothing structural; the persona it echoes is ignored — the deterministic layer picks it. |
| `assembler_agent` | ADK `BaseAgent` (deterministic) | Builds the `GeneratedCampaign`: ids, persona stamping (the identity derived from `pretext × recipient` via `catalog.persona_for`), seed-derived tracking URL, spec-derived schedule, references, and provenance are all decided in code. |
| `validator_agent` | ADK `BaseAgent` (deterministic) | Runs the four coherence checks and emits the `CoherenceReport`. |

### Core building blocks

1. **Deterministic assembly.** `assemble_campaign` (`generator_agent/assemble.py`)
   contains no randomness: the tracking token is `sha256(campaign_id:seed)[:12]`,
   the clock and send schedule are injected by the caller, and persona/reference
   wiring is structural. The impersonated persona is chosen by
   `catalog.persona_for(pretext, recipient_id)` — org-chart lookups for
   executive requests, the internal service desk for IT pretexts, and the
   external supplier/carrier/bank personas for BEC pretexts — so the LLM never
   invents the sender. Fixed inputs ⇒ byte-identical output.
2. **Coherence validators** (`validator_agent/validate.py`, no LLM):
   - **Persona identity** — the impersonated identity (e.g. the CEO) is the
     same across every message in the campaign.
   - **Timing** — a follow-up may not be scheduled before the message it cites.
   - **Cross-channel reference existence** — every referenced message id
     actually exists in the bundle (the SMS "as per my email" requires the
     email to exist).
   - **Link consistency** — every link-like token written into a message body
     must match that message's `call_to_action.landing_url` (or the landing URL
     of a message it references), and a follow-up must carry the same tracking
     token as the message it cites. This is the check that catches the known
     cross-channel failure (`abc123` vs `d6db8064874a`) in the committed sample.
3. **Provenance log.** `GenerationProvenance` / `ProvenanceLog` capture the
   model, decoding parameters, seed, prompt template id, and prompt hash for
   each artifact, so every generation is reproducible.

---

## Pipeline (phases)

### Phase 0 — Config (no agent)
- `MissionConfig` is loaded from a file (`config/q3-awareness-2026.mission.json`):
   authorized, synthetic-only, isolated, channels ⊆ {email, sms}, seed.
- The `CampaignSpec` (pretext, tone, difficulty, recipient, start time) and the
  `PersonaCatalog` (12 internal employees + 3 external personas) are seeded
  into ADK session state before the run.

### Phase 1 — Generation (`generator_content_agent` → `assembler_agent`)
- The `LlmAgent` writes only content (persona echo + subject/body), answering
  in a strict 8-line format; the persona in its echo is discarded in favour of
  the deterministic selection derived from the recipient's profile.
- The deterministic assembler parses the bindings and constructs the
  `GeneratedCampaign` (email + SMS follow-up) with provenance, stamping the
  selected persona into the campaign and every sender.

### Phase 2 — Verification (`validator_agent`)
- The deterministic validator runs the four coherence checks and emits a
  `CoherenceReport`; failures are recorded, never raised.

### Phase 3 — Measurement (harness, drives the ADK `Runner`)
- `measurement/reproduce.py` runs the same spec twice and compares (content
  hash and deterministic-layer hash).
- `measurement/reliability.py` runs the 10-spec baseline and counts constraint
  violations per check; the failure rate is the paper's first result.

---

## Stage Communication Diagram

```mermaid
flowchart TD
    A[MissionConfig + CampaignSpec + PersonaCatalog] -->|session state| R[generator_content_agent<br/>LlmAgent]
    R -->|raw_bindings| B[assembler_agent<br/>deterministic]
    B -->|GeneratedCampaign| C[validator_agent<br/>deterministic]
    B --> G[(generated-campaigns)]
    C -->|CoherenceReport| H[(coherence-reports)]
    C -->|ProvenanceLog| F[(provenance-log)]
    C --> M[measurement harness<br/>reproducibility + reliability]
```

There is intentionally **no edge back into generation** — the pipeline is a
one-way generate-then-verify flow, not an optimization loop.

---

## Design notes

- **Authorization & isolation** are mandatory and validated in code
  (`MissionConfig`, `DeploymentManifest`, `MessageEnvelope`).
- **Synthetic-only** is enforced (`MissionConstraints.synthetic_data_only`
  must be true; all personas/recipients are synthetic; external personas use
  the reserved `.example` TLD).
- **Determinism** lives in `assemble_campaign` and the deterministic ADK
  stages; the LLM only contributes `subject`/`body` text. Reproducibility is
  therefore measurable: the deterministic layer must match 100%, the content
  layer is the measured result.
- All contracts are defined and validated by Pydantic v2 models in
  [`app/core/schemas.py`](../app/core/schemas.py); the hand-off shapes are
  documented in [`flow-schema.md`](./flow-schema.md).
