# Generator Reliability & Scope-Reduction — Implementation Plan

> **Audience:** an LLM/engineer executing this work with full access to the repo.
> **Follow the steps in order.** Each step names the files to touch and the
> acceptance test that proves it is done.
>
> **Goal of this pass:** stop *building* the generator and start *measuring* it.
> Three things must come out of this pass and nothing else:
> 1. the pipeline rebuilt as a real **Google ADK** agent graph — no hardcoded
>    API key, no hardcoded inline flow (**W0**),
> 2. a **deterministic** generation path (so "same spec + same seed" is a
>    well-posed question), and
> 3. a **measurement harness** that reports (a) reproducibility and (b) the
>    constraint-violation failure rate over a fixed set of specs — plus the
>    validator change that lets it *catch* the known cross-channel link bug
>    instead of hiding it.
>
> **Do not** "fix" the generator so the known link bug disappears. That bug is
> the first data point; the deliverable is the validator that detects it.

---

## 0. Source of this plan (the mentor feedback, decoded)

| # | Feedback point | Workstream |
|---|----------------|------------|
| F1 | "Seed 42 registered: run the same spec twice, see if it reproduces the same campaign." | **W1** determinism, **W3** reproducibility experiment |
| F2 | "Run ten specs and count how many violate a constraint; that failure rate is your first reliability result." | **W3** reliability experiment |
| F3 | "Your email link ends `…d6db8064874a`, the SMS-body link ends `abc123`; they don't match. The question is not whether you fix it, but whether your validator catches it." | **W2** 4th coherence check `link_consistency` |
| F4 | "Scope down: email + SMS only; remove the success-optimization loop (Monitor → feedback); Generator and Validator stay as modules; Orchestrator becomes a linear sequencer without autonomy; Recon and Profiler are removed." | **W4** scope reduction |
| F5 | "50 people is more than you need; 10–12 is enough, and add external personas (a supplier, a bank) — half of BEC attacks." | **W5** persona catalog |
| F6 | Repo owner: "The agent must be done using the **ADK** library — the API key and the pipeline were hardcoded, not an ADK agent." | **W0** ADK pipeline |

---

## 1. Guardrails (never violate)

1. This is a **generator of synthetic phishing-simulation content for authorized
   security-awareness research**. Synthetic data only, no live infrastructure,
   no real people/domains. Keep the schema gates (`authorized: true`,
   `synthetic_data_only: true`, `isolated_environment: true`).
2. **Preserve evidence.** Before running anything, copy the committed known-bad
   campaign so a regeneration can never destroy it:
   ```bash
   mkdir -p data/measurements/known-case
   cp data/q3-awareness-2026/generated_campaign.json \
      data/measurements/known-case/generated_campaign.json
   ```
3. **No hardcoded secrets — clean up the leak.** The untracked root file
   `deepseek.py` hardcodes an API key. Delete it (it is untracked, so no history
   rewrite is needed) and rotate that key in the DeepSeek console. Then verify
   no key literal remains anywhere (tracked **or** untracked Python):
   ```bash
   grep -rniE "sk-[a-z0-9]{16,}|api_key\s*=\s*['\"]" --include=*.py . | grep -v venv
   ```
   Credentials come from the environment only. `.env` stays gitignored.
4. Keep the project's public contracts (`app/core/schemas.py`) the single source
   of truth. Update docs/tests in the same commit as the schema.
5. English for all code, comments, and docs (repo convention).
6. **Orchestration must be Google ADK.** The pipeline topology is a real ADK
   agent graph (`SequentialAgent` + agents), not inline Python orchestration.
   The flow and the model are loaded from config/env — never hardcoded at the
   call site — and the measurement harness must drive the ADK `Runner` so what
   is measured is the actual ADK artifact. See **W0**.

---

## 2. Current state (as-is) and the defects this pass must address

**As-is:** a 5-stage LLM pipeline — `Orchestrator-AG → Recon-AG → Profiler-AG →
Generator-AG → Validator-AG` (ADK/LMQL-flavoured), plus a real DeepSeek adapter
(`generator_agent/deepseek.py`), a model-free assembler
(`generator_agent/assemble.py`), an LLM Validator charter
(`prompts/validator_ag.md`), a FastAPI shell, and one committed sample campaign
(`data/q3-awareness-2026/generated_campaign.json`).

**Defects found by reading the code (fix or measure, per the table):**

| ID | Defect | Where | Action |
|----|--------|-------|--------|
| D1 | Landing-URL token is `uuid4()` → changes every run | `generator_agent/assemble.py:205` | W1: derive deterministically from seed |
| D2 | `generated_at = datetime.now()` → changes every run | `assemble.py:215` | W1: inject a fixed clock |
| D3 | Model bind `EMAIL_TIME`/`SMS_TIME` are LLM-chosen | `agent.py` / `deepseek.py` | W1: schedule from the spec, not the model |
| D4 | SMS **body** says `…/t/abc123` while the CTA is `…/t/d6db8064874a`; no check detects it | `generated_campaign.json` + `GeneratedCampaign._coherent` | W2: add `link_consistency` check |
| D5 | Validator is an LLM (`prompts/validator_ag.md`) → itself non-deterministic | `prompts/validator_ag.md` | W2: deterministic Python validator module |
| D6 | Recon-AG, Profiler-AG, and the whole Monitor/voice/feedback design are still present in docs/schemas/diagrams | schemas, docs, `scripts/generate_diagrams.py` | W4: remove |
| D7 | Catalog is 50 internal people only; no external personas | `org/fantazylabz_org.json` | W5: trim to 12 + add external |

**Why D1–D3 matter:** you cannot measure reproducibility of a pipeline that
injects randomness by construction. Split the artifact into a **deterministic
layer** (ids, persona, URLs, references, schedule, provenance) and a
**stochastic layer** (LLM-written `subject`/`body`). The deterministic layer
*must* be byte-identical across runs; the stochastic layer's match rate is the
measured result.

---

## 3. Target end-state

The pipeline is an **ADK agent graph** (W0), executed deterministically:
a `SequentialAgent` (no autonomy) whose first stage asks the LLM only for
content, and whose remaining stages are deterministic Python modules.

```
CampaignSpec / MissionConfig (files, W3)   PersonaCatalog (W5)
                 │                                  │
                 ▼                                  ▼
   ┌──────────────────── ADK SequentialAgent (no autonomy) ───────────────────┐
   │                                                                          │
   │  1. generator_content_agent (LlmAgent)  ── ADK LlmAgent, model from env   │
   │         │  raw bindings (persona + subject/body)                         │
   │         ▼                                                                │
   │  2. assembler_agent (custom BaseAgent, deterministic)                    │
   │         │  deterministic token, clock, refs, provenance                  │
   │         ▼  GeneratedCampaign                                             │
   │  3. validator_agent (custom BaseAgent, deterministic)                    │
   │         │  4 coherence checks                                            │
   │         ▼  CoherenceReport                                               │
   └──────────────────────────────────────────────────────────────────────────┘
                                 │
                                 ▼
   Measurement harness (drives ADK Runner):
   reproducibility.json + reliability.json + summary.md
```

- Channels: **email + SMS only**.
- Pipeline: **generate → verify**, one-way; no Monitor, no feedback, no voice.
- The only LLM is the content step; the **Orchestrator is the `SequentialAgent`
  itself** and the **Validator is deterministic code** (a custom ADK
  `BaseAgent`), not an LLM.
- Credentials and the model id come from the environment; the topology comes
  from `agent/pipeline.py` — nothing about the flow or the key is hardcoded.

---

## Workstream W0 — Build the pipeline as a real ADK agent (no hardcoding)

> **Hard requirement (repo owner).** The pipeline must be built with the
> **Google ADK** (`google-adk`) library, not hand-rolled inline orchestration.
> Today the flow and mission are hardcoded (`generator_agent/run.py`'s
> `DEMO_MISSION`, `generator_agent/deepseek.py`'s call site) and a key literal
> lives in the untracked root `deepseek.py`. Replace both.

### W0.1 Dependencies and credentials
- `requirements.txt`: add `google-adk` (pin a version). If the LLM is routed
  through ADK's LiteLLM wrapper for DeepSeek (OpenAI-compatible), also add
  `litellm`.
- Credentials from the **environment only**: `GOOGLE_API_KEY` (Gemini) or
  `DEEPSEEK_API_KEY` (DeepSeek). No key literal in any file (Guardrail 3).
- Delete the root `deepseek.py` and rotate the exposed key.

### W0.2 Pipeline topology (linear, no autonomy)
**New package:** `agent/` (`agent/__init__.py`, `agent/pipeline.py`,
`agent/config.py`).

Build the flow as ADK **workflow** agents — a `SequentialAgent` runs its
sub-agents in order without pausing or planning. Three stages:

| Order | ADK agent | Kind | Responsibility | Session state |
|-------|-----------|------|----------------|---------------|
| 1 | `generator_content_agent` | `LlmAgent` | Emit the 8 content bindings (persona + subject/body) in the requested tone/difficulty/language | `output_key="raw_bindings"` |
| 2 | `assembler_agent` | custom `BaseAgent` (deterministic, **no LLM**) | Call `assemble_campaign(...)` with the fixed clock/schedule (W1) to build `GeneratedCampaign` | writes `generated_campaign` |
| 3 | `validator_agent` | custom `BaseAgent` (deterministic, **no LLM**) | Call `validator_agent.validate_campaign(...)` (W2) to build `CoherenceReport` | writes `coherence_report` |

- The **Orchestrator is the `SequentialAgent` itself** — there is no
  Orchestrator-LLM and no feedback edge (satisfies F4 *and* F6).
- The model id is resolved from config/env, e.g. an ADK
  `LiteLlm(model="deepseek/deepseek-chat")` or a Gemini model string — never
  hardcoded at the call site.
- For the exact ADK imports and the custom-`BaseAgent` / `Event` /
  `_run_async_impl` signatures, use the verified snippets already in
  `implementation-instructions.md` (`LlmAgent`/`SequentialAgent`/`Runner`/
  `InMemorySessionService`); do not guess the API.

### W0.3 Config, not an inline mission
- `MissionConfig` and the `CampaignSpec` are loaded from files (see W3.1),
  never from an inline dict in a runner.
- A deterministic setup step seeds the ADK session (campaign_id, mission,
  profile, seed) before `Runner.run`.

### W0.4 Drive the measurement harness through ADK
- The harness adapter (W3.2) invokes the **ADK `Runner`** with
  `InMemorySessionService` and reads `generated_campaign` / `coherence_report`
  from session state. It must **not** call `generator_agent.deepseek.generate`
  directly, so the measured artifact is the real ADK output.

**Acceptance W0**
- The ADK graph builds with no network: `python -c "from agent.pipeline import pipeline"`.
- The secret grep in Guardrail 3 returns nothing.
- No inline `DEMO_MISSION` and no inline pipeline remain in
  `generator_agent/run.py`; `generator_agent/deepseek.py` is retired (or, if
  kept, contains no orchestration).

---

## Workstream W1 — Make generation deterministic

### W1.1 Deterministic landing-URL token
**File:** `generator_agent/assemble.py` (replace the `uuid4()` line, drop the
`uuid4` import).

```python
from hashlib import sha256

def tracking_token(campaign_id: str, seed: int) -> str:
    """Deterministic 12-hex token: same campaign + seed -> same token."""
    return sha256(f"{campaign_id}:{seed}".encode()).hexdigest()[:12]

# in assemble_campaign(...)
token = tracking_token(mission_config["campaign_id"], seed)
landing_url = f"https://sim.{email_domain}/t/{token}"
```
Both messages keep sharing the same `cta` object → cross-channel CTA equality
holds by construction.

### W1.2 Injectable clock
**File:** `generator_agent/assemble.py`.
- Keep `generated_at: datetime | None = None`, but tighten the fallback and let
  the caller (harness) pass a fixed value.
- Add `scheduled: tuple[str, str] | None = None` so the caller can supply the
  two ISO timestamps; otherwise fall back to the model bindings. When supplied
  (the measurement path), they are used verbatim.

### W1.3 Schedule from the spec, not the model
**File:** the deterministic assembler stage `agent/assembler.py` (W0, stage 2).
- The assembler computes `email_at = spec.start_at`, `sms_at =
  spec.start_at + timedelta(minutes=spec.followup_minutes)`.
- It passes those into `assemble_campaign`, so `EMAIL_TIME < SMS_TIME` is true
  by construction and reproducible.

### W1.4 Model decoding determinism
**File:** the ADK model config (`agent/config.py`) — the concrete model object is
chosen there (W0.2). The hand-rolled HTTP client in `generator_agent/deepseek.py`
is **superseded** once the ADK `LlmAgent` owns the model call; retire it unless
you deliberately wrap it as a custom ADK model.
- Set `temperature: 0.0` via the ADK model / `generate_content_config`.
- If the provider exposes a `seed` parameter, pass `GenerationParams.seed`;
  otherwise record `"seed_supported": false` in `runtime` and document that
  content-level reproducibility is **not guaranteed by the provider** (that fact
  is itself a result).

**Acceptance W1**
- `pytest -q tests/test_generator_agent.py` green.
- New test: `assemble_campaign(..., generated_at=FIXED, scheduled=(...) )` run
  twice with the same bindings → `model_dump()` **byte-identical**.
- Existing committed sample is left untouched.

---

## Workstream W2 — Deterministic Validator module + `link_consistency`

### W2.1 Add the schema check + bump the report contract
**File:** `app/core/schemas.py`.
```python
class CoherenceCheck(str, Enum):
    PERSONA_IDENTITY = "persona_identity"
    TIMING = "timing"
    CROSS_CHANNEL_REFERENCE = "cross_channel_reference"
    LINK_CONSISTENCY = "link_consistency"          # NEW (F3)
```
In `CoherenceReport`, change `results: ... = Field(..., min_length=3)` →
`min_length=4`. The `_report_is_consistent` validator already requires the
results to cover `set(CoherenceCheck)` exactly once — no change needed there,
but it now implies 4 results.

**The rule (put it in the module docstring and `docs/flow-schema.md`):**
> Every link-like token appearing in a message's `body` must refer to that
> message's `call_to_action.landing_url`, or to the `landing_url` of a message it
> `references`. When a message references another, both must carry the **same**
> `landing_url`. Comparison is on the tracking token (last path segment),
> after normalising away the scheme/host.

This is what catches the known case: `msg-0002.body` token `abc123` vs
`msg-0002.call_to_action` token `d6db8064874a`.

### W2.2 Deterministic validator module
**New package:** `validator_agent/` with:
- `validator_agent/__init__.py`
- `validator_agent/validate.py` — pure functions, **no LLM**:
  ```python
  def validate_campaign(campaign: GeneratedCampaign) -> CoherenceReport: ...
  ```
  Implement all four checks; **each check must always return a result object,
  never raise** (failures are data). Mirror the exact rules currently encoded in
  `GeneratedCampaign._coherent` plus the new link rule.
- `validator_agent/links.py` — URL/token extraction + comparison helpers:
  ```python
  FULL_URL = re.compile(r"https?://[^\s)\]\"'>]+")
  BARE_REF = re.compile(r"\bsim\.[a-z0-9.-]+/t/[A-Za-z0-9._-]+")
  def tokens_in(text: str) -> set[str]: ...        # last path segment, normalised
  ```
  Strip trailing punctuation (`.`, `,`, `)`, `]`, `"`, `'`).

### W2.3 Keep the charter in sync / demote it
**File:** `prompts/validator_ag.md`.
- Add the 4th check to the charter and the few-shot examples, and add a header
  note: *"The authoritative validator is `validator_agent/validate.py`; this
  charter exists for documentation parity. The measurement harness never calls
  the LLM for validation."*
- Do **not** wire the LMQL validator into the harness.

### W2.4 Regression test against the real known-bad fixture
**File:** `tests/test_validator_agent.py` (new).
- Load `data/measurements/known-case/generated_campaign.json`.
- Assert `validate_campaign(...)` returns `link_consistency.passed is False`
  and the detail names both `abc123` and `d6db8064874a`.
- Assert `all_passed is False`.
- Keep the existing `test_coherence_report_all_passed_must_match_results`
  (add a 4th result there so it stays valid with `min_length=4`).

**Acceptance W2**
- `validator_agent.validate_campaign` on the known-bad fixture reports exactly
  one failing check (`link_consistency`) and three passing.
- A hand-built coherent campaign reports `all_passed is True`.
- `pytest -q` green.

---

## Workstream W3 — Measurement harness (the actual contribution)

### W3.1 Spec type
**New file:** `measurement/specs.py`.
```python
@dataclass(frozen=True)
class CampaignSpec:
    spec_id: str            # "S1".."S10"
    campaign_id: str
    pretext: str            # from Pretext enum
    tone: str
    difficulty: str
    language: str
    seed: int
    model: dict             # ModelSpec dict
    recipient_id: int       # catalog id
    start_at: str           # ISO-8601 UTC
    followup_minutes: int
```

### W3.2 Adapters (drive the ADK pipeline)
**New file:** `measurement/adapters.py`.
- `AdkPipelineAdapter` — runs the ADK `Runner` over `agent/pipeline.py` (W0.4)
  and returns the `GeneratedCampaign` + `CoherenceReport` from session state.
  This is the real measurement path; the model is whatever the ADK config
  resolves from the environment.
- `StubAdapter` — deterministic, offline, no API key; returns fixed bindings so
  the harness and CI are runnable without network. This is for *testing the
  harness*, not for the results.
- The final results must be produced with `AdkPipelineAdapter`; the adapter name
  and resolved model are recorded in every report row.

### W3.3 Runner
**New file:** `measurement/runner.py`.
- `run_spec(spec, adapter, run_index, clock) -> RunRecord`:
  - build mission + profile from the catalog (W5),
  - call the adapter, assemble with the fixed clock/schedule (W1),
  - **catch every exception** (`ValidationError`, `SystemExit`, timeouts) and
    record `status = "generation_error"` with the message instead of crashing,
  - run `validate_campaign`, store the report,
  - store a canonical hash:
    ```python
    canonical = json.dumps(campaign.model_dump(mode="json"),
                           sort_keys=True, separators=(",", ":"))
    campaign_hash = sha256(canonical.encode()).hexdigest()
    ```
- `RunRecord` fields: `spec_id, run_index, adapter, model, seed, status,
  campaign_hash, report (dict), failing_checks (list), duration_ms, error`.

### W3.4 Reproducibility module
**New file:** `measurement/reproduce.py` + CLI `python -m measurement.reproduce`.
- For each spec (or `--spec-id`), run it `--runs` times (default 2).
- Compare `campaign_hash`. Report per-spec `identical: bool` and, when
  different, a field-level diff (`deepdiff`-style, hand-rolled is fine) so the
  report shows *what* changed (e.g. `messages[1].body`).
- Also report the **deterministic-layer** comparison (hash of the campaign with
  `subject`/`body`/`generated_at`/`adapter_latency_ms` blanked) — this is the
  number that must be 100% and that isolates provider stochasticity.

### W3.5 Reliability module
**New file:** `measurement/reliability.py` + CLI
`python -m measurement.reliability`.
- Run every spec in `measurement/specs.py` (`--runs N`, default 1).
- Aggregate:
  - `n_specs`, `n_runs`, `n_generation_errors`,
  - `n_campaigns_with_violation`,
  - `violation_counts` per check (`persona_identity`, `timing`,
    `cross_channel_reference`, `link_consistency`),
  - per-spec rows.
- Write `reliability.json` **and** a human-readable `summary.md` with two tables
  (reproducibility, failure rate). This is the paper's first result.

### W3.6 The 10 specs (baseline set)
**File:** `measurement/specs.py`. Vary the dimensions that matter; keep the
synthetic-only/authorized gates on. Suggested baseline:

| spec | recipient | pretext | tone | difficulty | seed | model |
|------|-----------|---------|------|-----------|------|-------|
| S1 | CEO (internal) | executive_request | urgent | medium | 42 | deepseek-chat |
| S2 | CEO (internal) | executive_request | urgent | medium | 42 | deepseek-chat (repeat of S1 → reproducibility) |
| S3 | Staff Accountant | invoice_payment | friendly | easy | 42 | deepseek-chat |
| S4 | Accounting Manager | invoice_payment | authoritative | medium | 7 | deepseek-chat |
| S5 | IT Manager | it_support | urgent | hard | 13 | deepseek-chat |
| S6 | IT Support | password_reset | neutral | easy | 42 | deepseek-chat |
| S7 | HR Manager | hr_notice | friendly | medium | 99 | deepseek-chat |
| S8 | Supplier contact (external) | invoice_payment | authoritative | medium | 42 | deepseek-chat |
| S9 | Bank contact (external) | account_suspension | urgent | hard | 5 | deepseek-chat |
| S10 | CFO | shared_document | authoritative | medium | 42 | deepseek-chat |

> S1/S2 are the *same spec twice* (F1). If the model layer cannot reproduce
> them, report it — do not quietly change the spec.

**Acceptance W3**
- `python -m measurement.reliability --adapter stub` runs offline and writes
  `data/measurements/<run_id>/{reliability.json,summary.md}`.
- `python -m measurement.reproduce --adapter stub --spec-id S1` writes
  `reproducibility.json`; deterministic-layer match is 100%.
- With the real adapter, `summary.md` contains the failure rate from F2.

---

## Workstream W4 — Scope reduction (remove Recon, Profiler, Monitor)

### W4.1 Orchestrator → ADK linear sequencer
- The linear sequencer **is the ADK `SequentialAgent`** defined in **W0**
  (`agent/pipeline.py`). Do **not** also write a parallel hand-rolled
  `generator_agent/sequencer.py`; one orchestration path only.
- For a batch of recipients (`run_campaign(spec)`), loop over the catalog and
  run the same ADK `Runner` per recipient — **no looping on outcomes, no
  branching on "success", no feedback edge.**
- Delete `prompts/orchestrator_ag.md` (it is an autonomous LLM orchestrator), or
  replace its body with a short description of the ADK pipeline and mark it
  non-executable.

### W4.2 Retire Recon-AG and Profiler-AG
- Delete `prompts/recon_ag.md` and `prompts/profiler_ag.md`.
- **File:** `app/core/schemas.py`:
  - `Agent` enum → keep only `ORCHESTRATOR`, `GENERATOR`, `VALIDATOR`.
  - Remove `SyntheticTargetSet` and `ProfileDataset` and their helper models
    (`SyntheticTarget`, `DomainPattern`, `AttackSurface`, `AttackSurfaceType`,
    `ProfileAttributes`, `SyntheticProfile`).
  - Keep `TemplateSet` and `PayloadAssets` **only** as static spec inputs (the
    sequencer may load them; otherwise remove them in the same pass). They are
    no longer produced by any agent.
  - Update `MessageEnvelope.phase` docs/bounds to the 3-stage flow (Phase 0
    config, Phase 1 generation, Phase 2 verification).

### W4.3 Monitor / voice / feedback purge
- `docs/architecture.md`: delete the remaining references to any Monitor or
  feedback loop; make the "no success loop" statement the operative design, not
  a disclaimer.
- `scripts/generate_diagrams.py`: it still draws the 7-agent design (Monitor-AG,
  Harvest-AG, Design-AG, Payload-AG, Responder-AG, voice, feedback arrows). Rewrite
  it to the 3-stage flow and regenerate `diagrams_output/*.png`
  (`python3 scripts/generate_diagrams.py`).
- Ensure no `voice` channel survives anywhere (`docs/`, `prompts/`, schemas).

### W4.4 Update docs to match
- `docs/flow-schema.md`: contract index (drop contracts #2/#3; keep envelope +
  mission + generation + campaign + report + provenance), enum lists (add
  `link_consistency`), the end-to-end diagram, and the persistence table.
- `docs/architecture.md`: stage table = Orchestrator (sequencer), Generator,
  Validator; note the model families and the deterministic/stochastic split.
- `README.md`: "Generation pipeline" bullet and the Quick Start (drop
  `recon`/`profile` CLI steps).
- `implementation-instructions.md`: mark the Recon/Profiler/ADK sections
  superseded by this plan (add a status header; do not silently delete history).

### W4.5 Update tests
- Remove/replace tests that assert the deleted stages/contracts
  (`test_flow_contracts.py`: `test_synthetic_target_set_accepts_documented_example`,
  `test_target_count_must_match_number_of_targets`, `test_tracking_link_requires_url_and_token`
  if `PayloadAssets` is removed, and the persistence parametrization entries for
  the removed contracts), and the ADK-oriented assertions in
  `implementation-instructions.md` (docs only).
- Keep every remaining test green: `pytest -q`.

---

## Workstream W5 — Persona catalog: 12 internal + external BEC personas

### W5.1 Trim the internal roster
**File:** `org/fantazylabz_org.json` (+ `org/fantazylabz_org.md`,
`org/fantazylabz_org_graph.md`).
Reduce `employees` from 50 to **12**, keeping BEC-relevant coverage:

| id | name | dept | role | level |
|----|------|------|------|-------|
| 1 | Elena Marchetti | Executive | CEO | 1 |
| 2 | Rajesh Kapoor | Engineering | CTO | 2 |
| 3 | Sofia Reyes | Finance | CFO | 2 |
| 4 | Marcus Bergström | Operations | COO | 2 |
| 7 | Yuki Tanaka | Security | CISO | 2 |
| 11 | Gregory Whitfield | Finance | Director of Finance | 3 |
| 12 | Fatima El-Sayed | IT | Director of Operations & IT | 3 |
| 16 | Hannah Fischer | HR | Director of People Operations | 3 |
| 24 | Samuel Adeyemi | Finance | Accounting Manager | 4 |
| 25 | Natalia Popov | IT | IT Manager | 4 |
| 40 | Rebecca Stern | Finance | Staff Accountant | 5 |
| 41 | Bruno Costa | IT | IT Support Specialist | 5 |

Set `headcount: 12`. Any old ids referenced by `_demo_profile`
(`generator_agent/run.py`) must still resolve — they do.

### W5.2 Add external personas (BEC)
**New file:** `org/external_personas.json`.
```json
{
  "personas": [
    {
      "persona_id": "ext-supplier-01",
      "class": "external",
      "org_type": "supplier",
      "display_name": "Northwind Supplies — Accounts Payable",
      "email": "ap@northwind-supplies.example",
      "brand": "Northwind Supplies",
      "supports_pretexts": ["invoice_payment", "shared_document"]
    },
    {
      "persona_id": "ext-bank-01",
      "class": "external",
      "org_type": "bank",
      "display_name": "Meridian Bank — Security Alerts",
      "email": "alerts@meridianbank.example",
      "brand": "Meridian Bank",
      "supports_pretexts": ["account_suspension", "password_reset"]
    }
  ]
}
```
- Use the reserved `.example` TLD for every synthetic external domain.
- Recommended (small, optional) schema add: `Pretext.BANK_NOTICE = "bank_notice"`
  so the bank persona has a native scenario; update `docs/flow-schema.md` and
  tests if you add it.

### W5.3 Catalog loader
**New file:** `generator_agent/catalog.py`.
- `load_persona_catalog()` merges internal employees (as `class: "internal"`)
  and external personas (as `class: "external"`), exposing a uniform record:
  `{id, class, org_type, display_name, email, role, department, supports_pretexts}`.
- The sequencer (W4.1) and the harness (W3.3) select recipients/personas through
  this loader — no direct `org/fantazylabz_org.json` reads elsewhere.
- `generator_agent/run.py::_demo_profile` and `generator_agent/send.py::_default_to`
  switch to the loader.

**Acceptance W5**
- Catalog has exactly 12 internal + 2 external records.
- `supports_pretexts` maps external supplier→`invoice_payment` and
  bank→`account_suspension` (or `bank_notice`).
- `pytest -q` green.

---

## 4. Execution order (respect the dependencies)

1. **W0** (ADK pipeline + de-hardcode) — the runtime everything else plugs into;
   do this first so no work is written against the old inline flow.
2. **W1** (determinism) — otherwise the experiments are meaningless.
3. **W2** (validator + `link_consistency`) — needed before any measurement, and
   its regression test pins the known F3 finding.
4. **W5** (catalog) — needed by the runner.
5. **W4** (scope reduction + docs/tests/diagrams) — can run in parallel with W5
   once W0/W1/W2 land.
6. **W3** (harness) — last; depends on W0, W1, W2, W5.
7. Produce the results (F1 + F2) and commit them.

---

## 5. Definition of done (run these)

```bash
# 1. nothing broken
pytest -q

# 2. the ADK graph builds without network, and no key is hardcoded
python -c "from agent.pipeline import pipeline"
grep -rniE "sk-[a-z0-9]{16,}|api_key\s*=\s*['\"]" --include=*.py . | grep -v venv   # -> empty

# 3. deterministic assembly is byte-reproducible
pytest -q tests/test_generator_agent.py

# 4. the validator catches the known cross-channel link failure
pytest -q tests/test_validator_agent.py

# 5. harness works offline (CI-safe)
python -m measurement.reliability --adapter stub --out data/measurements/_selftest
python -m measurement.reproduce   --adapter stub --spec-id S1

# 6. the real experiments through the ADK Runner (needs GOOGLE_API_KEY or DEEPSEEK_API_KEY)
python -m measurement.reproduce   --adapter adk --spec-id S1 --runs 2
python -m measurement.reliability --adapter adk --runs 1
```

**Pass criteria**
- `pytest -q` is green.
- The pipeline is an ADK agent graph that builds offline, drives the run via
  `Runner`, and contains **no hardcoded key and no hardcoded inline flow**.
- `tests/test_validator_agent.py` proves the known `abc123` vs `d6db8064874a`
  mismatch is detected (`link_consistency: failed`, `all_passed: false`).
- The deterministic-layer reproducibility rate is **100%** (by construction).
- `data/measurements/<run_id>/summary.md` contains, at minimum:
  - a **reproducibility** row for seed 42 (S1 vs S2): identical yes/no + diff,
  - a **reliability** table: # campaigns with ≥1 violation / total, broken down
    by check,
  - the adapter/model and the exact spec set used.

---

## 6. Non-goals (do **not** do these in this pass)

- Do **not** fix generation so the SMS body URL matches the CTA. Preserve the
  failure and let the validator flag it (F3). A fix, if any, is a *later*,
  separately-measured change.
- Do **not** add victim-interaction tracking, KPIs, a Monitor agent, a voice
  channel, or any success-optimization feedback loop (F4).
- Do **not** replace the LLM validator with an LLM validator "that checks
  better" — the validator must be deterministic code (W2).
- Do **not** hand-roll the orchestration outside ADK or hardcode the flow/model
  at a call site (F6). The topology lives in `agent/pipeline.py`; the model and
  keys come from config/env.
- Do **not** delete `data/q3-awareness-2026/generated_campaign.json`; it is the
  committed evidence for F3 (copy it first, per Guardrail 2).
- Do **not** invent real domains, banks, or suppliers; use `.example`.

---

## Appendix A — Files created / changed at a glance

| Workstream | Create | Change | Delete |
|-----------|--------|--------|--------|
| W0 | `agent/{__init__,pipeline,config,assembler,validator}.py` | `requirements.txt`, `generator_agent/run.py` | `deepseek.py` (root, secret), `generator_agent/deepseek.py` (superseded by the ADK model) |
| W1 | — | `generator_agent/assemble.py` | — |
| W2 | `validator_agent/{__init__,validate,links}.py`, `tests/test_validator_agent.py` | `app/core/schemas.py`, `prompts/validator_ag.md`, `tests/test_flow_contracts.py` | — |
| W3 | `measurement/{__init__,specs,adapters,runner,reproduce,reliability}.py` | — | — |
| W4 | — | `app/core/schemas.py`, `docs/{architecture,flow-schema}.md`, `README.md`, `scripts/generate_diagrams.py`, `diagrams_output/*` | `prompts/{orchestrator_ag,recon_ag,profiler_ag}.md` |
| W5 | `org/external_personas.json`, `generator_agent/catalog.py` | `org/fantazylabz_org.json`, `org/fantazylabz_org.md`, `org/fantazylabz_org_graph.md`, `generator_agent/run.py`, `generator_agent/send.py` | — |

## Appendix B — Reference: the known finding (F3)

From the committed sample (`data/q3-awareness-2026/generated_campaign.json`):

- `msg-0001` (email) CTA: `https://sim.fantazylabz.tech/t/d6db8064874a`
- `msg-0002` (sms)  CTA: `https://sim.fantazylabz.tech/t/d6db8064874a`
- `msg-0002` **body**: `... link: sim.fantazylabz.tech/t/abc123`

→ the SMS prose points at a *different* tracking token than the CTA and the
email. This is the cross-channel consistency failure the mentor already spotted;
the expected report is:

```json
{
  "campaign_id": "q3-awareness-2026",
  "results": [
    { "check": "persona_identity", "passed": true },
    { "check": "timing", "passed": true },
    { "check": "cross_channel_reference", "passed": true },
    { "check": "link_consistency", "passed": false,
      "detail": "msg-0002 body token 'abc123' != CTA token 'd6db8064874a'" }
  ],
  "all_passed": false
}
```

## Appendix C — ADK pipeline skeleton (W0)

Topology only; no keys, no mission literals. Place in `agent/pipeline.py`.

```python
# agent/pipeline.py
import os

from google.adk.agents import LlmAgent, SequentialAgent
# The custom deterministic stages subclass ADK's BaseAgent:
# from google.adk.agents import BaseAgent
# Verify exact names/signatures against implementation-instructions.md / ADK docs.

from agent.assembler import AssemblerAgent   # custom BaseAgent, deterministic (W1)
from agent.validator import ValidatorAgent   # custom BaseAgent, deterministic (W2)


def _model():
    """Model comes from config/env — never hardcoded at the call site."""
    name = os.environ.get("PIPELINE_MODEL", "gemini-2.5-flash")
    if name.startswith("deepseek/"):         # OpenAI-compatible via LiteLLM
        from google.adk.models.lite_llm import LiteLlm
        return LiteLlm(model=name)           # key read from DEEPSEEK_API_KEY
    return name                              # Gemini model id via GOOGLE_API_KEY


def build_pipeline() -> SequentialAgent:
    content = LlmAgent(
        name="generator_content_agent",
        model=_model(),
        description="Emit the 8 content bindings for one synthetic recipient.",
        instruction=...,                     # charter: generator_agent.assemble.CHARTER
        output_key="raw_bindings",           # -> shared session state
    )
    return SequentialAgent(
        name="pipeline",
        description="Linear generate -> assemble -> verify. No autonomy.",
        sub_agents=[content, AssemblerAgent(name="assembler_agent"),
                    ValidatorAgent(name="validator_agent")],
    )


pipeline = build_pipeline()
```

The custom `AssemblerAgent` / `ValidatorAgent` subclass ADK's `BaseAgent` and
implement the async run hook (per ADK docs; see the signatures already quoted in
`implementation-instructions.md`) to read/write session state. They contain **no
LLM calls**, which is what keeps the validator deterministic and the whole
pipeline reproducible.

> **Executed and verified on `google-adk 2.9.2`:** the working implementation
> lives in `agent/assembler.py` / `agent/validator.py`. State is persisted via
> `Event(author=..., actions=EventActions(state_delta={...}))` (imports from
> `google.adk.events`), session state is seeded via
> `session_service.create_session(..., state={...})`, and the content agent's
> final text lands in state under `output_key="raw_bindings"`. `SequentialAgent`
> is deprecated in favor of `Workflow` on 2.9.x; the pipeline suppresses the
> warning. Use those files as the ground truth for any ADK version.

