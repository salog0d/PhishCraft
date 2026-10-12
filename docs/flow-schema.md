# Flow Schema — JSON Contracts

JSON data contracts for the **campaign generator**. Each hand-off of the
three-stage ADK pipeline is a versioned contract with a concrete synthetic
example. The generator covers **email and SMS**; it produces content and
verifies coherence, and does **not** track victim interaction or campaign KPIs.

> **Scope.** All data is **synthetic and generated internally**. Every payload
> carries the campaign authorization attestation; downstream stages must reject
> any message where `authorized` is `false` or `synthetic_data_only` is not
> honored.

---

## Conventions

- **Transport envelope.** Every inter-stage message is wrapped in the
  [Message Envelope](#message-envelope); the stage-specific contract lives under
  `payload`.
- **Timestamps.** ISO 8601, UTC, `Z` suffix (e.g. `2026-08-20T09:00:00Z`).
- **Identifiers.** `campaign_id` is a caller-supplied slug
  (`^[A-Za-z0-9._-]{1,64}$`); others are prefixed (`tpl-`, `msg-`, `bat-`) or
  UUIDv4 (`generation_id`).
- **Versioning.** `schema_version` uses SemVer; this document describes `1.0`.
- **Enums** mirror `app/core/schemas.py`: `channel` ∈ {`email`, `sms`},
  `pretext`, `call_to_action.type`, `tone`, `difficulty`, `model.family`.

### Contract index

| # | Contract | Producer | Consumer | Phase |
|---|----------|----------|----------|-------|
| — | `MessageEnvelope` | any stage | any stage | all |
| 1 | `MissionConfig` | config file | pipeline | 0 |
| 2 | `PhishingGenerationRequest` | Orchestrator | Generator | 1 |
| 2b | `PhishingGenerationResponse` | Generator | Orchestrator | 1 |
| 3 | `GeneratedMessage` | Generator | Validator | 1 |
| 4 | `DeploymentManifest` | Orchestrator | Generator | 1 |
| 5 | `GeneratedCampaign` | assembler | store / Validator | 1–2 |
| 6 | `CoherenceReport` | Validator | store / harness | 2 |
| 7 | `ProvenanceLog` | Validator | store | 2 |

---

## Message Envelope

Common wrapper for every message on the stage bus.

```json
{
  "message_id": "5b9c1f2a-6c1e-4b2a-9c3d-7e0a1b2c3d4e",
  "schema_version": "1.0",
  "campaign_id": "q3-awareness-2026",
  "phase": 1,
  "from_agent": "Generator-AG",
  "to_agent": "Validator-AG",
  "emitted_at": "2026-08-19T14:30:00Z",
  "authorized": true,
  "payload": { "contract": "GeneratedCampaign", "...": "..." }
}
```

| Field | Type | Notes |
|-------|------|-------|
| `phase` | integer 0–2 | Pipeline phase that emitted the message (0 config, 1 generation, 2 verification). |
| `from_agent` / `to_agent` | enum | `Orchestrator-AG`, `Generator-AG`, `Validator-AG`; must differ. |
| `authorized` | boolean | Propagated attestation; must be `true`. |

---

## 1 · MissionConfig — Phase 0 (config file)

Defines scope, constraints, the model policy (≥ 2 families), reproducibility,
and ethics guardrails. Loaded from `config/*.mission.json`, never decided by a
model.

```json
{
  "contract": "MissionConfig",
  "campaign_id": "q3-awareness-2026",
  "authorized": true,
  "objective": "security-awareness-training",
  "scope": { "region": "LATAM", "sector": "technology", "volume": 5, "duration_days": 14 },
  "constraints": {
    "synthetic_data_only": true,
    "channels": ["email", "sms"],
    "max_messages_per_persona": 3
  },
  "model_policy": {
    "models": [
      { "family": "deepseek", "name": "deepseek-chat", "adapter_version": "1.0" },
      { "family": "anthropic", "name": "claude-opus-5", "adapter_version": "1.0" }
    ]
  },
  "reproducibility": { "seed": 42, "deterministic": true },
  "ethics": { "consent_reference": "IRB-2026-014", "isolated_environment": true }
}
```

| Field | Type | Notes |
|-------|------|-------|
| `constraints.channels` | enum[] | Subset of `email`, `sms` (unique). |
| `model_policy.models` | ModelSpec[] | ≥ 2 entries spanning **≥ 2 distinct families**. |
| `reproducibility.seed` | integer ≥ 0 | Fixed seed; drives the deterministic tracking token. |

---

## 2 · PhishingGenerationRequest — Phase 1 (Orchestrator → Generator)

> **Canonical contract** — validated by
> `app/core/schemas.py::PhishingGenerationRequest`. `authorized` must be `true`
> or the request is rejected with `403`.

```json
{
  "campaign_id": "q3-awareness-2026",
  "authorized": true,
  "channel": "email",
  "recipient": {
    "email": "rebecca.stern@fantazylabz.tech",
    "full_name": "Rebecca Stern",
    "role": "Staff Accountant",
    "department": "Finance"
  },
  "sender": {
    "display_name": "Elena Marchetti",
    "from_address": "ceo@fantazylabz.tech",
    "impersonated_brand": "Fantazy Labz"
  },
  "pretext": "executive_request",
  "call_to_action": {
    "type": "click_link",
    "landing_url": "https://sim.fantazylabz.tech/t/8b9dc310f705",
    "button_label": "Review Document"
  },
  "model": { "family": "deepseek", "name": "deepseek-chat", "adapter_version": "1.0" },
  "params": { "temperature": 0.0, "top_p": 1.0, "max_tokens": 1024, "seed": 42 },
  "tone": "authoritative",
  "difficulty": "medium",
  "language": "en",
  "subject_hint": "Quick approval needed before EOD",
  "include_tracking_pixel": true
}
```

| Field | Type | Constraint |
|-------|------|------------|
| `channel` | enum | `email` \| `sms` (default `email`). |
| `model.family` | enum | `anthropic`, `openai`, `mistral`, `llama`, `local`, `deepseek`. |
| `params.seed` | integer ≥ 0 | **Required** — makes the generation reproducible. |
| `pretext` | enum | Consumer: `password_reset`, `account_suspension`, `package_delivery` · BEC: `executive_request`, `invoice_payment`, `shared_document`, `hr_notice`, `it_support` (see `Pretext.category`). |
| `call_to_action.type` | enum | `click_link`, `enter_credentials`, `open_attachment`, `reply`. |
| `subject_hint` / `include_tracking_pixel` | — | **Email only**; must be unset/`false` for SMS. |

### 2b · PhishingGenerationResponse

```json
{
  "generation_id": "9f8e7d6c-5b4a-3210-fedc-ba9876543210",
  "campaign_id": "q3-awareness-2026",
  "status": "queued",
  "accepted_at": "2026-08-20T09:00:01Z",
  "message": "Generation request accepted."
}
```

---

## 3 · GeneratedMessage — Phase 1 (Generator → Validator)

One generated message with its provenance. Email requires a `subject`; SMS must
not carry one (and is capped at 1600 characters).

```json
{
  "contract": "GeneratedMessage",
  "message_id": "msg-0001",
  "channel": "email",
  "scheduled_at": "2026-08-20T09:00:00Z",
  "sender": { "display_name": "Elena Marchetti", "from_address": "ceo@fantazylabz.tech" },
  "subject": "Quick approval needed before EOD",
  "body": "Rebecca, please review and approve the attached before end of day.",
  "call_to_action": { "type": "click_link", "landing_url": "https://sim.fantazylabz.tech/t/8b9dc310f705" },
  "references": [],
  "provenance": {
    "model": { "family": "deepseek", "name": "deepseek-chat", "adapter_version": "1.0" },
    "params": { "temperature": 0.0, "seed": 42 },
    "prompt_template_id": "tpl-0001",
    "prompt_hash": "aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa",
    "generated_at": "2026-08-20T09:00:00Z",
    "adapter_latency_ms": 812,
    "runtime": { "sdk": "google-adk", "seed_supported": "false" }
  }
}
```

| Field | Type | Notes |
|-------|------|-------|
| `references` | MessageId[] | Ids of earlier messages this one cites (cross-channel). |
| `link_fixes` | LinkFix[] | Stale tracking tokens the assembler rewrote in the raw model prose; empty = no raw link violation. Feeds the raw reliability metric. The prompt teaches the `{{cta-link}}` placeholder (expanded by the assembler, never recorded here); with the driver's self-refinement loop, `link_fixes` on the delivered artifact is the *post-refinement* number — the first-attempt number comes from the driver's run_info. |
| `provenance.prompt_hash` | sha256 hex | sha256 of the fully rendered prompt actually sent. |
| `provenance.params` | GenerationParams | The params **actually used** by the model call: `temperature: 0.0` (passed via ADK/LiteLlm) and the reproducibility `seed`. `top_p`/`max_tokens` are left at provider defaults and therefore not logged; the seed drives the deterministic layer only and is not passed to the provider (`runtime.seed_supported: false`). |

---

## 4 · DeploymentManifest — Phase 1 (Orchestrator → Generator)

Batches of per-recipient generation requests with a send schedule.

```json
{
  "contract": "DeploymentManifest",
  "campaign_id": "q3-awareness-2026",
  "authorized": true,
  "batches": [
    {
      "batch_id": "bat-01",
      "channel": "email",
      "scheduled_at": "2026-08-20T09:00:00Z",
      "requests": [ "<PhishingGenerationRequest>" ]
    }
  ]
}
```

---

## 5 · GeneratedCampaign — Phase 1–2 (assembler → Validator)

A coherent multi-channel bundle for one impersonated persona. The assembler
decides every structural field (ids, persona, seed-derived URL, schedule,
references, provenance); the LLM only wrote the `subject`/`body` text. The
persona itself is derived deterministically from the `(pretext, recipient)`
pair by `generator_agent.catalog.persona_for` (e.g. `executive_request` →
the recipient's manager, `invoice_payment` → the external supplier).

```json
{
  "contract": "GeneratedCampaign",
  "campaign_id": "q3-awareness-2026",
  "persona": {
    "display_name": "Elena Marchetti",
    "email": "ceo@fantazylabz.tech",
    "role": "Chief Executive Officer"
  },
  "recipient": {
    "email": "rebecca.stern@fantazylabz.tech",
    "full_name": "Rebecca Stern",
    "role": "Staff Accountant",
    "department": "Finance"
  },
  "messages": [
    { "message_id": "msg-0001", "channel": "email", "scheduled_at": "2026-08-20T09:00:00Z", "...": "..." },
    { "message_id": "msg-0002", "channel": "sms", "scheduled_at": "2026-08-20T10:15:00Z", "references": ["msg-0001"], "...": "..." }
  ]
}
```

**Coherence rules (all enforced in code, reported by the validator):**

- **Persona identity** — every message's `sender.display_name` and
  `sender.from_address` must equal the campaign `persona` (the CEO is the same
  everywhere).
- **Cross-channel reference existence** — every id in `references` must exist in
  the bundle; a message may not reference itself.
- **Timing** — a message may not be scheduled before any message it references.
- **Link consistency** — every link-like token in a message `body` must match
  that message's `call_to_action.landing_url` (or the landing URL of a message
  it references), and a follow-up must carry the same tracking token as the
  message it cites. This is the check that catches the known cross-channel
  failure in the committed sample (`msg-0002` body token `abc123` ≠ CTA token
  `d6db8064874a`). Because the assembler normalizes stale tokens, this check
  cannot fail by construction anymore — it is the *delivery guarantee*; the
  **first-attempt raw violation rate** (the stale tokens the LLM wrote before
  any refinement round, from the driver's run_info) is the *reliability*
  metric, and the `link_fixes` on the delivered artifact give the
  post-refinement number.
- **Sender vs recipient** — the impersonated persona must never be the
  campaign's own recipient (no CEO writing to herself); campaigns without a
  recorded `recipient` fail this check because the separation cannot be
  verified.

---

## 6 · CoherenceReport — Phase 2 (Validator → store / harness)

The recorded outcome of the coherence checks — the evidence that the generator
satisfied its constraints.

```json
{
  "contract": "CoherenceReport",
  "campaign_id": "q3-awareness-2026",
  "results": [
    { "check": "persona_identity", "passed": true },
    { "check": "timing", "passed": true },
    { "check": "cross_channel_reference", "passed": true },
    { "check": "link_consistency", "passed": false,
      "detail": "msg-0002 body token 'abc123' not in CTA tokens (d6db8064874a)" },
    { "check": "sender_recipient", "passed": true }
  ],
  "all_passed": false
}
```

`results` must cover every check exactly once, and `all_passed` must equal the
conjunction of the individual results. The validator
(`validator_agent/validate.py`) is deterministic Python — it always emits a
report, never raises on incoherent content.

---

## 7 · ProvenanceLog — Phase 2 (Validator → store)

Append-only reproducibility record: one `GenerationProvenance` entry per
generated message.

```json
{
  "contract": "ProvenanceLog",
  "campaign_id": "q3-awareness-2026",
  "entries": [
    {
      "model": { "family": "deepseek", "name": "deepseek-chat", "adapter_version": "1.0" },
      "params": { "temperature": 0.0, "seed": 42 },
      "prompt_template_id": "tpl-0001",
      "prompt_hash": "aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa",
      "generated_at": "2026-08-20T09:00:00Z"
    }
  ]
}
```

---

## Validation & Persistence Rules

Enforced by Pydantic v2 models in
[`app/core/schemas.py`](../app/core/schemas.py) and covered by
`tests/test_flow_contracts.py`.

### Business rules

- **Authorization is mandatory.** `MissionConfig`, `DeploymentManifest`, and the
  `MessageEnvelope` reject any payload where `authorized` is not `true`.
- **Synthetic-only.** `MissionConstraints.synthetic_data_only` must be `true`;
  all personas/recipients are synthetic (external personas use `.example`).
- **Isolated environment.** `MissionEthics.isolated_environment` must be `true`.
- **Two model families.** `ModelPolicy` requires ≥ 2 entries spanning ≥ 2
  distinct `family` values.
- **Reproducibility.** `GenerationParams.seed` is required; the tracking URL
  token is `sha256(campaign_id:seed)[:12]`.
- **Channel shaping.** `channels ⊆ {email, sms}`; email requires a `subject`,
  SMS forbids one; `subject_hint`/`include_tracking_pixel` are email-only.
- **Coherence.** The validator enforces persona identity, cross-channel
  reference existence, timing, link consistency, and sender-recipient
  separation; `CoherenceReport` must be internally consistent.
- **Referential integrity.** Prefixed ids (`msg-`, `bat-`) are unique within a
  collection.

### Persistence rules

Every contract carries a `PersistencePolicy` (`store`, `retention_days`, `pii`).
All artifacts are **append-only (immutable)** and **encrypted at rest**.

| Contract | Store | Retention (days) | PII class |
|----------|-------|------------------|-----------|
| `MessageEnvelope` | `bus-audit-log` | 90 | none |
| `MissionConfig` | `campaign-configs` | 365 | none |
| `DeploymentManifest` | `campaign-schedules` | 365 | synthetic |
| `GeneratedCampaign` | `generated-campaigns` | 365 | synthetic |
| `CoherenceReport` | `coherence-reports` | 365 | none |
| `ProvenanceLog` | `provenance-log` | 730 | none |

---

## End-to-end flow

```
MissionConfig (config file) ─┬▶ generator_content_agent (LlmAgent)
CampaignSpec + PersonaCatalog┘        │ raw_bindings
                                      ▼
                              assembler_agent (deterministic)
                                      │ GeneratedCampaign
                                      ▼
                              validator_agent (deterministic)
                                      │ CoherenceReport + ProvenanceLog
                                      ▼
                              measurement harness (reproducibility + reliability)
```

See [architecture.md](./architecture.md) for the stage roles and phase
descriptions.
