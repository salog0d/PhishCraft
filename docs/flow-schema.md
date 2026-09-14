# Flow Schema — JSON Contracts

JSON data contracts for the **campaign generator**. Each hand-off between stages
(Phases 0–4) is a versioned contract with a concrete synthetic example. The
generator covers **email and SMS**; it produces content and verifies coherence,
and does **not** track victim interaction or campaign KPIs.

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
  (`^[A-Za-z0-9._-]{1,64}$`); others are prefixed (`tgt-`, `prf-`, `tpl-`,
  `ast-`, `msg-`, `bat-`) or UUIDv4 (`generation_id`).
- **Versioning.** `schema_version` uses SemVer; this document describes `1.0`.
- **Enums** mirror `app/core/schemas.py`: `channel` ∈ {`email`, `sms`},
  `pretext`, `call_to_action.type`, `tone`, `difficulty`, `model.family`.

### Contract index

| # | Contract | Producer | Consumer | Phase |
|---|----------|----------|----------|-------|
| — | `MessageEnvelope` | any stage | any stage | all |
| 1 | `MissionConfig` | Orchestrator-AG | pipeline | 0 |
| 2 | `SyntheticTargetSet` | Recon-AG | Profiler-AG | 1 |
| 3 | `ProfileDataset` | Profiler-AG | Generator-AG | 2 |
| 4 | `TemplateSet` | Profiler-AG | Generator-AG | 2 |
| 5 | `PayloadAssets` | Profiler-AG | Generator-AG | 2 |
| 6 | `PhishingGenerationRequest` | Orchestrator-AG | Generator-AG | 3 |
| 6b | `PhishingGenerationResponse` | Generator-AG | Orchestrator-AG | 3 |
| 7 | `GeneratedMessage` | Generator-AG | Validator-AG | 3 |
| 8 | `DeploymentManifest` | Orchestrator-AG | Generator-AG | 3 |
| 9 | `GeneratedCampaign` | Validator-AG | store | 4 |
| 10 | `CoherenceReport` | Validator-AG | store | 4 |
| 11 | `ProvenanceLog` | Validator-AG | store | 4 |

---

## Message Envelope

Common wrapper for every message on the stage bus.

```json
{
  "message_id": "5b9c1f2a-6c1e-4b2a-9c3d-7e0a1b2c3d4e",
  "schema_version": "1.0",
  "campaign_id": "q3-awareness-2026",
  "phase": 1,
  "from_agent": "Recon-AG",
  "to_agent": "Profiler-AG",
  "emitted_at": "2026-08-19T14:30:00Z",
  "authorized": true,
  "payload": { "contract": "SyntheticTargetSet", "...": "..." }
}
```

| Field | Type | Notes |
|-------|------|-------|
| `phase` | integer 0–4 | Pipeline phase that emitted the message. |
| `from_agent` / `to_agent` | enum | `Orchestrator-AG`, `Recon-AG`, `Profiler-AG`, `Generator-AG`, `Validator-AG`; must differ. |
| `authorized` | boolean | Propagated attestation; must be `true`. |

---

## 1 · MissionConfig — Phase 0 (Orchestrator-AG)

Defines scope, constraints, the model policy (≥ 2 families), reproducibility,
and ethics guardrails.

```json
{
  "contract": "MissionConfig",
  "campaign_id": "q3-awareness-2026",
  "authorized": true,
  "objective": "security-awareness-training",
  "scope": { "region": "LATAM", "sector": "finance"},
  "constraints": {
    "synthetic_data_only": true,
    "channels": ["email", "sms"],
    "max_messages_per_persona": 3
  },
  "model_policy": {
    "models": [
      { "family": "anthropic", "name": "claude-opus-5", "adapter_version": "1.0" },
      { "family": "openai", "name": "gpt-4.1", "adapter_version": "1.0" }
    ]
  },
  "ethics": {  "isolated_environment": true }
}
```

| Field | Type | Notes |
|-------|------|-------|
| `constraints.channels` | enum[] | Subset of `email`, `sms` (unique). |
| `model_policy.models` | ModelSpec[] | ≥ 2 entries spanning **≥ 2 distinct families**. |

---

## 2 · SyntheticTargetSet — Phase 1 (Recon-AG → Profiler-AG)

Programmatically generated targets and simulated attack surfaces. No external
scanning.

```json
{
  "contract": "SyntheticTargetSet",
  "campaign_id": "q3-awareness-2026",
  "source": "synthetic",
  "target_count": 1,
  "targets": [
    {
      "target_id": "tgt-0001",
      "synthetic_domain": "fantazylabz.tech",
      "domain_pattern": "typosquat",
      "attack_surfaces": [
        { "type": "mail_server", "value": "mx.fantazylabz.tech" },
        { "type": "login_form", "value": "https://fantazylabz.tech/login" }
      ]
    }
  ]
}
```

| Field | Type | Notes |
|-------|------|-------|
| `source` | const `"synthetic"` | Guards against real collection. |
| `domain_pattern` | enum | `typosquat` \| `homoglyph` \| `subdomain` \| `combosquat`. |
| `attack_surfaces[].type` | enum | `mail_server` \| `login_form` \| `api` \| `portal`. |

---

## 3 · ProfileDataset — Phase 2 (Profiler-AG → Generator-AG)

Labeled synthetic recipient profiles. `recipient` matches the `Recipient` model.

```json
{
  "contract": "ProfileDataset",
  "campaign_id": "q3-awareness-2026",
  "source": "synthetic",
  "format": "json",
  "record_count": 1,
  "profiles": [
    {
      "profile_id": "prf-0001",
      "target_id": "tgt-0001",
      "recipient": {
        "email": "rebecca.stern@fantazylabz.tech",
        "full_name": "Rebecca Stern",
        "role": "Staff Accountant",
        "department": "Finance"
      },
      "attributes": {
        "seniority": "mid",
        "devices": ["windows", "ios"],
        "language": "en",
        "language_patterns": ["formal"]
      },
      "labels": { "segment": "finance", "risk_tier": "medium" }
    }
  ]
}
```

---

## 4 · TemplateSet — Phase 2 (Profiler-AG → Generator-AG)

Seed **prompt templates** the generator conditions on. `pretext`, `tone`,
`difficulty` use the shared enums; email templates require a `subject`.

```json
{
  "contract": "TemplateSet",
  "campaign_id": "q3-awareness-2026",
  "templates": [
    {
      "template_id": "tpl-0001",
      "channel": "email",
      "pretext": "executive_request",
      "tone": "authoritative",
      "difficulty": "medium",
      "language": "en",
      "subject": "Quick approval needed before EOD",
      "body": "Hi {{full_name}}, can you approve this today? {{link}}",
      "variables": ["full_name", "link"],
      "ab_variant": "A"
    }
  ]
}
```

---

## 5 · PayloadAssets — Phase 2 (Profiler-AG → Generator-AG)

Simulation assets (tracking links, sandboxed attachments, mirror pages). All
assets are marked `simulated`.

```json
{
  "contract": "PayloadAssets",
  "campaign_id": "q3-awareness-2026",
  "assets": [
    {
      "asset_id": "ast-0001",
      "type": "tracking_link",
      "landing_url": "https://sim.fantazylabz.tech/t/abc123",
      "tracking_token": "abc123",
      "linked_template_id": "tpl-0001",
      "simulated": true
    }
  ]
}
```

| Field | Type | Notes |
|-------|------|-------|
| `type` | enum | `tracking_link` \| `attachment` \| `mirror_page`. |
| `content_ref` | URI | `sandbox://` reference (attachments/mirror pages). |
| `simulated` | const `true` | Assets are inert simulation artifacts. |

---

## 6 · PhishingGenerationRequest — Phase 3 (Orchestrator-AG → Generator-AG)

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
    "landing_url": "https://sim.fantazylabz.tech/t/abc123",
    "button_label": "Review Document"
  },
  "model": { "family": "anthropic", "name": "claude-opus-5", "adapter_version": "1.0" },
  "params": { "temperature": 0.7, "top_p": 1.0, "max_tokens": 1024, "seed": 42 },
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
| `model.family` | enum | `anthropic`, `openai`, `mistral`, `llama`, `local`. |
| `params.seed` | integer ≥ 0 | **Required** — makes the generation reproducible. |
| `pretext` | enum | `password_reset`, `invoice_payment`, `package_delivery`, `it_support`, `hr_notice`, `executive_request`, `shared_document`, `account_suspension`. |
| `call_to_action.type` | enum | `click_link`, `enter_credentials`, `open_attachment`, `reply`. |
| `subject_hint` / `include_tracking_pixel` | — | **Email only**; must be unset/`false` for SMS. |

### 6b · PhishingGenerationResponse

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

## 7 · GeneratedMessage — Phase 3 (Generator-AG → Validator-AG)

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
  "call_to_action": { "type": "click_link", "landing_url": "https://sim.fantazylabz.tech/t/abc123" },
  "references": [],
  "provenance": {
    "model": { "family": "anthropic", "name": "claude-opus-5", "adapter_version": "1.0" },
    "params": { "temperature": 0.7, "top_p": 1.0, "max_tokens": 1024, "seed": 42 },
    "prompt_template_id": "tpl-0001",
    "prompt_hash": "aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa",
    "generated_at": "2026-08-20T09:00:00Z",
    "adapter_latency_ms": 812,
    "runtime": { "sdk": "0.40.0" }
  }
}
```

| Field | Type | Notes |
|-------|------|-------|
| `references` | MessageId[] | Ids of earlier messages this one cites (cross-channel). |
| `provenance.prompt_hash` | sha256 hex | sha256 of the fully rendered prompt actually sent. |

---

## 8 · DeploymentManifest — Phase 3 (Orchestrator-AG → Generator-AG)

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

## 9 · GeneratedCampaign — Phase 4 (Validator-AG)

A coherent multi-channel bundle for one impersonated persona. Enforces the three
coherence rules.

```json
{
  "contract": "GeneratedCampaign",
  "campaign_id": "q3-awareness-2026",
  "persona": {
    "display_name": "Elena Marchetti",
    "email": "ceo@fantazylabz.tech",
    "role": "CEO",
    "organization": "Fantazy Labz"
  },
  "messages": [
    { "message_id": "msg-0001", "channel": "email", "scheduled_at": "2026-08-20T09:00:00Z", "...": "..." },
    { "message_id": "msg-0002", "channel": "sms", "scheduled_at": "2026-08-20T10:00:00Z", "references": ["msg-0001"], "...": "..." }
  ]
}
```

**Coherence rules (all enforced in code):**

- **Persona identity** — every message's `sender.display_name` and
  `sender.from_address` must equal the campaign `persona` (the CEO is the same
  everywhere).
- **Cross-channel reference existence** — every id in `references` must exist in
  the bundle; a message may not reference itself.
- **Timing** — a message may not be scheduled before any message it references.

---

## 10 · CoherenceReport — Phase 4 (Validator-AG)

The recorded outcome of the coherence checks — the evidence that the generator
satisfied its constraints.

```json
{
  "contract": "CoherenceReport",
  "campaign_id": "q3-awareness-2026",
  "results": [
    { "check": "persona_identity", "passed": true },
    { "check": "timing", "passed": true },
    { "check": "cross_channel_reference", "passed": true }
  ],
  "all_passed": true
}
```

`results` must cover every check exactly once, and `all_passed` must equal the
conjunction of the individual results.

---

## 11 · ProvenanceLog — Phase 4 (Validator-AG)

Append-only reproducibility record: one `GenerationProvenance` entry per
generated message.

```json
{
  "contract": "ProvenanceLog",
  "campaign_id": "q3-awareness-2026",
  "entries": [
    {
      "model": { "family": "anthropic", "name": "claude-opus-5", "adapter_version": "1.0" },
      "params": { "temperature": 0.7, "top_p": 1.0, "max_tokens": 1024, "seed": 42 },
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
  `SyntheticTargetSet` and `ProfileDataset` require `source == "synthetic"`.
- **Isolated environment.** `MissionEthics.isolated_environment` must be `true`.
- **Two model families.** `ModelPolicy` requires ≥ 2 entries spanning ≥ 2
  distinct `family` values.
- **Reproducibility.** `GenerationParams.seed` is required.
- **Channel shaping.** `channels ⊆ {email, sms}`; email requires a `subject`,
  SMS forbids one; `subject_hint`/`include_tracking_pixel` are email-only.
- **Coherence.** `GeneratedCampaign` enforces persona identity, cross-channel
  reference existence, and timing; `CoherenceReport` must be internally
  consistent.
- **Referential integrity.** Prefix-typed ids (`tgt-`, `prf-`, `tpl-`, `ast-`,
  `msg-`, `bat-`) are unique within a collection; `target_count` / `record_count`
  equal their array lengths.
- **Assets are inert.** Every `PayloadAsset.simulated` must be `true`.

### Persistence rules

Every contract carries a `PersistencePolicy` (`store`, `retention_days`, `pii`).
All artifacts are **append-only (immutable)** and **encrypted at rest**.

| Contract | Store | Retention (days) | PII class |
|----------|-------|------------------|-----------|
| `MessageEnvelope` | `bus-audit-log` | 90 | none |
| `MissionConfig` | `campaign-configs` | 365 | none |
| `SyntheticTargetSet` | `synthetic-datasets` | 180 | synthetic |
| `ProfileDataset` | `synthetic-datasets` | 180 | synthetic |
| `TemplateSet` | `campaign-content` | 365 | none |
| `PayloadAssets` | `sandbox-assets` | 90 | none |
| `DeploymentManifest` | `campaign-schedules` | 365 | synthetic |
| `GeneratedCampaign` | `generated-campaigns` | 365 | synthetic |
| `CoherenceReport` | `coherence-reports` | 365 | none |
| `ProvenanceLog` | `provenance-log` | 730 | none |

---

## End-to-end flow

```
MissionConfig ─▶ SyntheticTargetSet ─▶ ProfileDataset ─┬▶ TemplateSet ──┐
                (Profiler-AG)                          └▶ PayloadAssets ┘
                                                                        ▼
                              PhishingGenerationRequest ─▶ GeneratedMessage (per channel)
                                        (Generator-AG, via ModelSpec adapter + provenance)
                                                                        ▼
                              GeneratedCampaign ─▶ CoherenceReport + ProvenanceLog
                                        (Validator-AG — one-way verify, no feedback loop)
```

See [architecture.md](./architecture.md) for the stage roles and phase
descriptions.
