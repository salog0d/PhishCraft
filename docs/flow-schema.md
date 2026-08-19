# Flow Schema — JSON Contracts

JSON data contracts for the full agentic flow of **[Project Name]**. Each hand-off between agents (Phases 0–7) is defined below as a versioned contract with a concrete synthetic example.

> **Scope.** All data is **synthetic and generated internally**. Every payload carries the campaign authorization attestation; downstream agents must reject any message where `authorized` is `false` or `synthetic_data_only` is not honored.

---

## Conventions

- **Transport envelope.** Every inter-agent message is wrapped in the [Message Envelope](#message-envelope); the agent-specific contract lives under `payload`.
- **Timestamps.** ISO 8601, UTC, `Z` suffix (e.g. `2026-08-20T09:00:00Z`).
- **Identifiers.** `campaign_id` is a caller-supplied slug (`^[A-Za-z0-9._-]{1,64}$`); all others are prefixed IDs (`tgt-`, `prf-`, `tpl-`, `ast-`, `evt-`) or UUIDv4 (`generation_id`).
- **Versioning.** `schema_version` uses SemVer; this document describes `1.0`.
- **Enums** mirror `app/core/schemas.py`: `pretext`, `call_to_action.type`, `tone`, `difficulty`.

### Contract index

| # | Contract | Producer | Consumer | Phase |
|---|----------|----------|----------|-------|
| — | `MessageEnvelope` | any agent | any agent | all |
| 1 | `MissionConfig` | Orchestrator-AG | pipeline | 0 |
| 2 | `SyntheticTargetSet` | Recon-AG | Harvest-AG | 1 |
| 3 | `ProfileDataset` | Harvest-AG | Design-AG, Payload-AG | 2 |
| 4 | `TemplateSet` | Design-AG | Orchestrator-AG | 3 |
| 5 | `PayloadAssets` | Payload-AG | Orchestrator-AG | 3 |
| 6 | `DeploymentManifest` | Orchestrator-AG | Responder-AG | 4 |
| 6a | `PhishingGenerationRequest` | Orchestrator-AG | generation engine | 4 |
| 6b | `PhishingGenerationResponse` | generation engine | Orchestrator-AG | 4 |
| 7 | `InteractionEvent` | channel gateway | Responder-AG | 5 |
| 8 | `InteractionResult` | Responder-AG | Monitor-AG | 5 |
| 9 | `MetricsReport` | Monitor-AG | Orchestrator-AG | 6 |
| 10 | `FeedbackDirective` | Monitor-AG / Orchestrator-AG | Design-AG, Harvest-AG | 7 |

---

## Message Envelope

Common wrapper for every message on the agent bus.

```json
{
  "message_id": "5b9c1f2a-6c1e-4b2a-9c3d-7e0a1b2c3d4e",
  "schema_version": "1.0",
  "campaign_id": "q3-awareness-2026",
  "phase": 1,
  "from_agent": "Recon-AG",
  "to_agent": "Harvest-AG",
  "emitted_at": "2026-08-19T14:30:00Z",
  "authorized": true,
  "payload": { "contract": "SyntheticTargetSet", "...": "..." }
}
```

| Field | Type | Notes |
|-------|------|-------|
| `message_id` | UUIDv4 | Unique per message. |
| `phase` | integer 0–7 | Pipeline phase that emitted the message. |
| `from_agent` / `to_agent` | string | Agent name (`Recon-AG`, …). |
| `authorized` | boolean | Propagated attestation; must be `true`. |
| `payload` | object | One of the contracts below; `payload.contract` names it. |

---

## 1 · MissionConfig — Phase 0 (Orchestrator-AG)

Defines campaign scope, constraints, and ethics guardrails.

```json
{
  "contract": "MissionConfig",
  "campaign_id": "q3-awareness-2026",
  "authorized": true,
  "objective": "security-awareness-training",
  "scope": {
    "region": "LATAM",
    "sector": "finance",
    "volume": 50,
    "duration_days": 14
  },
  "constraints": {
    "synthetic_data_only": true,
    "channels": ["email", "sms", "voice"],
    "max_interactions_per_target": 3
  },
  "ethics": {
    "consent_reference": "IRB-2026-014",
    "isolated_environment": true
  }
}
```

---

## 2 · SyntheticTargetSet — Phase 1 (Recon-AG → Harvest-AG)

Programmatically generated targets and simulated attack surfaces. No external scanning.

```json
{
  "contract": "SyntheticTargetSet",
  "campaign_id": "q3-awareness-2026",
  "source": "synthetic",
  "target_count": 1,
  "targets": [
    {
      "target_id": "tgt-0001",
      "synthetic_domain": "examp1e-corp.com",
      "domain_pattern": "typosquat",
      "attack_surfaces": [
        { "type": "mail_server", "value": "mx.examp1e-corp.com" },
        { "type": "login_form", "value": "https://examp1e-corp.com/login" },
        { "type": "api", "value": "https://api.examp1e-corp.com/v1" }
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

## 3 · ProfileDataset — Phase 2 (Harvest-AG → Design-AG, Payload-AG)

Labeled synthetic victim profiles. `recipient` matches the `Recipient` model.

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
        "email": "employee@examp1e-corp.com",
        "full_name": "Jordan Lee",
        "role": "Accountant",
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

## 4 · TemplateSet — Phase 3 (Design-AG → Orchestrator-AG)

Communication templates with A/B variants. `pretext`, `tone`, `difficulty` use the shared enums.

```json
{
  "contract": "TemplateSet",
  "campaign_id": "q3-awareness-2026",
  "templates": [
    {
      "template_id": "tpl-0001",
      "channel": "email",
      "pretext": "password_reset",
      "tone": "urgent",
      "difficulty": "medium",
      "language": "en",
      "subject": "Action required: password expires today",
      "body": "Hi {{full_name}}, your password expires today. {{reset_link}}",
      "variables": ["full_name", "reset_link"],
      "ab_variant": "A"
    }
  ]
}
```

---

## 5 · PayloadAssets — Phase 3 (Payload-AG → Orchestrator-AG)

Simulation assets (tracking links, sandboxed attachments, mirror pages). All assets are marked `simulated`.

```json
{
  "contract": "PayloadAssets",
  "campaign_id": "q3-awareness-2026",
  "assets": [
    {
      "asset_id": "ast-0001",
      "type": "tracking_link",
      "landing_url": "https://sim.example-corp.com/t/abc123",
      "tracking_token": "abc123",
      "linked_template_id": "tpl-0001",
      "simulated": true
    },
    {
      "asset_id": "ast-0002",
      "type": "attachment",
      "filename": "invoice.pdf",
      "content_ref": "sandbox://payloads/ast-0002",
      "simulated": true
    }
  ]
}
```

| Field | Type | Notes |
|-------|------|-------|
| `type` | enum | `tracking_link` \| `attachment` \| `mirror_page`. |
| `content_ref` | URI | `sandbox://` reference; content never leaves the isolated store. |
| `simulated` | const `true` | Assets are inert simulation artifacts. |

---

## 6 · DeploymentManifest — Phase 4 (Orchestrator-AG → Responder-AG)

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

### 6a · PhishingGenerationRequest

> **Canonical contract** — validated by `app/core/schemas.py::PhishingGenerationRequest`. `authorized` must be `true` or the request is rejected with `403`.

```json
{
  "campaign_id": "q3-awareness-2026",
  "authorized": true,
  "recipient": {
    "email": "employee@example.com",
    "full_name": "Jordan Lee",
    "role": "Accountant",
    "department": "Finance"
  },
  "sender": {
    "display_name": "IT Service Desk",
    "from_address": "it-support@example-corp.com",
    "impersonated_brand": "Example Corp IT"
  },
  "pretext": "password_reset",
  "call_to_action": {
    "type": "click_link",
    "landing_url": "https://sim.example-corp.com/t/abc123",
    "button_label": "Reset Password"
  },
  "tone": "urgent",
  "difficulty": "medium",
  "language": "en",
  "subject_hint": "Action required: password expires today",
  "include_tracking_pixel": true
}
```

| Field | Type | Constraint |
|-------|------|------------|
| `campaign_id` | string | 1–64 chars. |
| `authorized` | boolean | Must be `true`. |
| `pretext` | enum | `password_reset`, `invoice_payment`, `package_delivery`, `it_support`, `hr_notice`, `executive_request`, `shared_document`, `account_suspension`. |
| `call_to_action.type` | enum | `click_link`, `enter_credentials`, `open_attachment`, `reply`. |
| `tone` | enum | `urgent`, `friendly`, `authoritative`, `neutral` (default `neutral`). |
| `difficulty` | enum | `easy`, `medium`, `hard` (default `medium`). |
| `language` | string | BCP-47-ish, `^[a-z]{2}(-[A-Z]{2})?$` (default `en`). |

### 6b · PhishingGenerationResponse

> **Canonical contract** — `app/core/schemas.py::PhishingGenerationResponse`.

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

## 7 · InteractionEvent — Phase 5 (channel gateway → Responder-AG)

A recipient action on any channel, including inbound/outbound voice calls.

```json
{
  "contract": "InteractionEvent",
  "campaign_id": "q3-awareness-2026",
  "event_id": "evt-0001",
  "generation_id": "9f8e7d6c-5b4a-3210-fedc-ba9876543210",
  "profile_id": "prf-0001",
  "channel": "voice",
  "action": "enter_credentials",
  "occurred_at": "2026-08-20T09:15:00Z",
  "context": {
    "call_direction": "inbound",
    "transcript_ref": "sandbox://calls/evt-0001"
  }
}
```

| Field | Type | Notes |
|-------|------|-------|
| `channel` | enum | `email` \| `sms` \| `voice`. |
| `action` | enum | Mirrors `call_to_action.type`. |
| `context.call_direction` | enum | `inbound` \| `outbound` (voice only). |

---

## 8 · InteractionResult — Phase 5 (Responder-AG → Monitor-AG)

The card selected by the responder decision tree plus the logged outcome.

```json
{
  "contract": "InteractionResult",
  "campaign_id": "q3-awareness-2026",
  "event_id": "evt-0001",
  "profile_id": "prf-0001",
  "selected_card": "A",
  "card_type": "credentials",
  "channel": "voice",
  "outcome": "submitted",
  "captured_fields": ["username", "password"],
  "response_ref": "sandbox://responses/evt-0001",
  "logged_at": "2026-08-20T09:15:30Z"
}
```

| Field | Type | Notes |
|-------|------|-------|
| `selected_card` | enum | `A` \| `B` \| `C`. |
| `card_type` | enum | `credentials` \| `fake_support` \| `verification_form`. |
| `outcome` | enum | `submitted` \| `ignored` \| `reported` \| `bounced`. |
| `captured_fields` | string[] | Field names only — never captured values. |

---

## 9 · MetricsReport — Phase 6 (Monitor-AG → Orchestrator-AG)

Aggregated KPIs and the success decision that drives the feedback loop.

```json
{
  "contract": "MetricsReport",
  "campaign_id": "q3-awareness-2026",
  "window": { "from": "2026-08-20T09:00:00Z", "to": "2026-08-20T21:00:00Z" },
  "kpis": {
    "delivered": 50,
    "opened": 34,
    "clicked": 18,
    "converted": 7,
    "delivery_rate": 1.0,
    "open_rate": 0.68,
    "click_rate": 0.36,
    "conversion_rate": 0.14,
    "reported_as_spam": 2,
    "bounce_rate": 0.0
  },
  "anomalies": [],
  "exploit_successful": true
}
```

---

## 10 · FeedbackDirective — Phase 7 (Monitor-AG / Orchestrator-AG → Design-AG, Harvest-AG)

Closes the loop. On success, directs template optimization and profile enrichment; otherwise, adjusts parameters.

```json
{
  "contract": "FeedbackDirective",
  "campaign_id": "q3-awareness-2026",
  "exploit_successful": true,
  "directives": [
    {
      "target_agent": "Design-AG",
      "action": "optimize_templates",
      "template_ids": ["tpl-0001"],
      "reason": "high_click_rate"
    },
    {
      "target_agent": "Harvest-AG",
      "action": "update_profiles",
      "profile_ids": ["prf-0001"],
      "observed": { "clicked": true, "converted": true }
    }
  ],
  "parameter_adjustments": { "difficulty": "hard" }
}
```

| Field | Type | Notes |
|-------|------|-------|
| `directives[].action` | enum | `optimize_templates` \| `update_profiles` \| `adjust_parameters`. |
| `parameter_adjustments` | object | Applied when `exploit_successful` is `false` (or for the next iteration). |

---

## Validation & Persistence Rules

These contracts are enforced in code by Pydantic v2 models in
[`app/core/schemas.py`](../app/core/schemas.py) and covered by
`tests/test_flow_contracts.py`.

### Business rules

- **Authorization is mandatory.** `MissionConfig`, `DeploymentManifest`, and the
  `MessageEnvelope` reject any payload where `authorized` is not `true`.
- **Synthetic-only.** `MissionConstraints.synthetic_data_only` must be `true`;
  `SyntheticTargetSet` and `ProfileDataset` require `source == "synthetic"`.
- **Isolated environment.** `MissionEthics.isolated_environment` must be `true`.
- **Referential integrity.** IDs are prefix-typed (`tgt-`, `prf-`, `tpl-`,
  `ast-`, `evt-`, `bat-`) and must be unique within a collection; `target_count`
  and `record_count` must equal the length of their arrays.
- **Assets are inert.** Every `PayloadAsset.simulated` must be `true`;
  attachments/mirror pages require a `sandbox://` `content_ref`; tracking links
  require both `landing_url` and `tracking_token`.
- **KPI funnel is monotonic.** `converted ≤ clicked ≤ opened ≤ delivered`, all
  rates in `[0, 1]`, and `reported_as_spam ≤ delivered`.
- **Card/type coherence.** `selected_card` A/B/C must match `card_type`
  credentials/fake_support/verification_form.
- **Channel coherence.** `call_direction` is valid only for the `voice` channel;
  email templates require a `subject`.
- **Feedback coherence.** A directive's `action` must target the correct agent;
  a failed exploit (`exploit_successful == false`) requires `parameter_adjustments`.

### Persistence rules

Every contract carries a `PersistencePolicy` (`store`, `retention_days`, `pii`).
All artifacts are **append-only (immutable)** and **encrypted at rest**.
Critically, `InteractionResult.captured_fields` stores **field names only** —
raw captured values are never persisted (a value like `victim@example.com` fails
the field-name pattern).

| Contract | Store | Retention (days) | PII class |
|----------|-------|------------------|-----------|
| `MessageEnvelope` | `bus-audit-log` | 90 | none |
| `MissionConfig` | `campaign-configs` | 365 | none |
| `SyntheticTargetSet` | `synthetic-datasets` | 180 | synthetic |
| `ProfileDataset` | `synthetic-datasets` | 180 | synthetic |
| `TemplateSet` | `campaign-content` | 365 | none |
| `PayloadAssets` | `sandbox-assets` | 90 | none |
| `DeploymentManifest` | `campaign-schedules` | 365 | synthetic |
| `InteractionEvent` | `interaction-log` | 365 | sensitive |
| `InteractionResult` | `interaction-log` | 365 | sensitive |
| `MetricsReport` | `metrics-warehouse` | 730 | none |
| `FeedbackDirective` | `feedback-log` | 365 | none |

---

## End-to-end flow

```
MissionConfig ─▶ SyntheticTargetSet ─▶ ProfileDataset ─┬▶ TemplateSet ──┐
                                                        └▶ PayloadAssets ┘
                                                                         ▼
                                          DeploymentManifest (PhishingGenerationRequest/Response)
                                                                         ▼
                          InteractionEvent ─▶ InteractionResult ─▶ MetricsReport ─▶ FeedbackDirective
                                                                                        │
                          (loops back to Design-AG & Harvest-AG) ◀──────────────────────┘
```

See [architecture.md](./architecture.md) for the agent roles and phase descriptions, and [`diagrams_output/`](../diagrams_output/) for the rendered diagrams.
