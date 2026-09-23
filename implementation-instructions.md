# Implementation Instructions — Generator Reliability & Scope Reduction (ADK)

> **Audience:** an LLM/engineer executing this work with full access to the
> repo. Follow the steps in order. Each step names the files to touch and the
> acceptance test that proves it is done. Where code is marked
> `copy verbatim`, do not "improve" it; where it is marked
> `adapt to your installed version`, only the marked API call may change.
>
> **This document supersedes the previous revision** (the 5-stage
> Orchestrator/Recon/Profiler/Generator/Validator ADK template). Its
> Recon/Profiler content is obsolete and must **not** be implemented.
>
> **Goal of this pass:** stop *building* the generator and start *measuring*
> it. Three deliverables, in order:
> 1. the pipeline rebuilt as a real **Google ADK** agent graph — no hardcoded
>   API key, no hardcoded inline flow (**Step W0**),
> 2. a **deterministic** generation path (so "same spec + same seed" is a
>   well-posed question) (**Step W1**), and
> 3. a **measurement harness** that reports reproducibility and the
>   constraint-violation failure rate over a fixed set of specs, plus the
>   validator change that lets it *catch* the known cross-channel link bug
>   instead of hiding it (**Steps W2–W3**).
>
> **Do not** "fix" the generator so the known link bug disappears. That bug is
> the first data point; the deliverable is the validator that detects it.
>
> Rationale and design notes: [`docs/generator-reliability-plan.md`](./docs/generator-reliability-plan.md).
> This file is the operative step list; the design doc is the reference.

---

## 0. Read these files first

| File | Why |
|---|---|
| `app/core/schemas.py` | Authoritative Pydantic contracts (you **will** modify it in W2/W4). |
| `generator_agent/assemble.py` | Model-free assembler — where determinism must be enforced. |
| `generator_agent/deepseek.py` | Current real generator; the model call moves into ADK. |
| `data/q3-awareness-2026/generated_campaign.json` | The known-bad evidence (F3) — preserve a copy, never overwrite it. |
| `prompts/generator_ag.md`, `prompts/validator_ag.md` | Charters for the two surviving stages. |
| `org/fantazylabz_org.json` | Current 50-person roster (trim in W5). |
| `tests/test_flow_contracts.py`, `tests/test_generator_agent.py` | Must stay green after your edits. |
| `docs/flow-schema.md`, `docs/architecture.md`, `README.md` | Must be updated to the new 3-stage flow. |

## Hard constraints (never violate)

1. **Synthetic-only, authorized, isolated.** The schema gates stay:
   `authorized: true`, `synthetic_data_only: true`, `isolated_environment:
   true`. No real people, domains, banks, or suppliers; external personas use
   the reserved `.example` TLD.
2. **Preserve evidence first.** Before touching anything:
   ```bash
   mkdir -p data/measurements/known-case
   cp data/q3-awareness-2026/generated_campaign.json \
      data/measurements/known-case/generated_campaign.json
   ```
3. **No hardcoded secrets.** Delete the untracked root `deepseek.py` (it
   hardcodes an API key), rotate that key in the DeepSeek console, then verify:
   ```bash
   grep -rniE "sk-[a-z0-9]{16,}|api_key\s*=\s*['\"]" --include=*.py . | grep -v venv
   # must print nothing
   ```
   Credentials come from the environment only (`GOOGLE_API_KEY`,
   `DEEPSEEK_API_KEY`). `.env` stays gitignored.
4. **Orchestration must be Google ADK.** The topology lives in
   `agent/pipeline.py` as an ADK agent graph; the flow and the model are loaded
   from config/env, never hardcoded at a call site. The measurement harness
   drives the ADK `Runner`.
5. English for all code, comments, and docs.
6. `app/core/schemas.py` **is** modifiable in this pass (W2/W4 change it), but
   every schema change must come with the matching test/doc update in the same
   commit.

---

## 1. Target end-state

```
CampaignSpec / MissionConfig (files)        PersonaCatalog (W5)
                 │                                  │
                 ▼                                  ▼
   ┌────────────────── ADK SequentialAgent (no autonomy) ──────────────────┐
   │  1. generator_content_agent  LlmAgent   ── model from env             │
   │         │  raw bindings (persona + subject/body)                      │
   │         ▼                                                             │
   │  2. assembler_agent  custom BaseAgent (deterministic, no LLM)         │
   │         │  deterministic token, clock, refs, provenance               │
   │         ▼  GeneratedCampaign                                          │
   │  3. validator_agent  custom BaseAgent (deterministic, no LLM)         │
   │         │  4 coherence checks                                         │
   │         ▼  CoherenceReport                                            │
   └───────────────────────────────────────────────────────────────────────┘
                                 │
                                 ▼
   Measurement harness (drives ADK Runner):
   reproducibility.json + reliability.json + summary.md
```

- Channels: **email + SMS only**.
- One-way **generate → verify**; no Monitor, no feedback, no voice.
- The only LLM is the content step. The Orchestrator is the `SequentialAgent`
  itself; the Validator is deterministic code.

---

## 2. Step W0 — Build the pipeline as a real ADK agent (no hardcoding)

### W0.1 Dependency + key hygiene

```bash
pip install google-adk
pip show google-adk | grep ^Version
# append to requirements.txt, pinned, before "email-validator":
#   google-adk==<version>
# if you route DeepSeek through ADK's LiteLLM wrapper, also:
#   pip install litellm  ->  litellm==<version>
python -c "from google.adk.agents import LlmAgent, SequentialAgent; print('ok')"
```

If the import fails, the installed `google-adk` is pre-1.0 — upgrade; do not
adapt the import paths. **Verified on `google-adk 2.9.2`** (`litellm 1.102.1`).

Then: `rm deepseek.py` (repo root, untracked, contains a hardcoded key) and
rotate that key. Run the secret grep from Constraint 3 — it must print nothing.

### W0.2 Create the `agent/` package

**`agent/__init__.py`** (copy verbatim):
```python
"""ADK agent package: exposes the campaign pipeline as ``root_agent``."""

from . import pipeline
from .pipeline import root_agent

__all__ = ["pipeline", "root_agent"]
```

**`agent/config.py`** (copy verbatim):
```python
"""Config for the ADK pipeline. No secrets here — env only."""

import os

DEFAULT_MODEL = os.getenv("ADK_MODEL", "gemini-2.5-flash")


def resolve_model():
    """Model object from config/env. Never hardcode a provider at a call site."""
    if DEFAULT_MODEL.startswith("deepseek/"):
        # OpenAI-compatible provider via ADK's LiteLLM wrapper; the key is read
        # by litellm from DEEPSEEK_API_KEY.
        from google.adk.models.lite_llm import LiteLlm

        return LiteLlm(model=DEFAULT_MODEL)
    return DEFAULT_MODEL  # Gemini model id, key from GOOGLE_API_KEY
```

**`agent/pipeline.py`** (copy verbatim; `BINDINGS_CONTRACT` mirrors the strict
8-line format the model must answer with):
```python
"""Google ADK pipeline: generate -> assemble -> verify (linear, no autonomy).

Root agent = SequentialAgent running, in order:
    generator_content_agent (LlmAgent)   -> raw_bindings
    assembler_agent         (BaseAgent)  -> generated_campaign
    validator_agent         (BaseAgent)  -> coherence_report

There is no Orchestrator-LLM: the SequentialAgent IS the orchestrator. The LLM
only writes content; ids, persona, URLs, references, schedule, and provenance
are decided by the deterministic assembler (generator_agent.assemble).
"""

from __future__ import annotations

from google.adk.agents import LlmAgent, SequentialAgent

from agent.assembler import AssemblerAgent
from agent.config import resolve_model
from agent.validator import ValidatorAgent
from generator_agent.assemble import CHARTER

BINDINGS_CONTRACT = """

---
ANSWER FORMAT — answer with EXACTLY these 8 lines, one per line, no markdown,
no extra text:
- display name: <value>
- role: <value>
- from address: <value>
- subject: <value>
- body: <value>
- scheduled at: <value>
- body: <value>
- scheduled at: <value>
"""

generator_content_agent = LlmAgent(
    model=resolve_model(),
    name="generator_content_agent",
    description=(
        "Emit the 8 content bindings (persona + email subject/body + SMS body) "
        "for one synthetic recipient."
    ),
    instruction=CHARTER + BINDINGS_CONTRACT,
    output_key="raw_bindings",
)

root_agent = SequentialAgent(
    name="campaign_generator_pipeline",
    sub_agents=[
        generator_content_agent,
        AssemblerAgent(name="assembler_agent"),
        ValidatorAgent(name="validator_agent"),
    ],
    description=(
        "Configurable, reproducible generator of synthetic phishing-simulation "
        "campaigns (email + SMS) for authorized security-awareness research."
    ),
)
```

### W0.3 The two deterministic stages (custom `BaseAgent`, no LLM)

**Verified on `google-adk 2.9.2`** (implemented in `agent/assembler.py` and
`agent/validator.py` — copy those files as the reference):

- Subclass `from google.adk.agents import BaseAgent` and implement
  `async def _run_async_impl(self, ctx) -> AsyncGenerator[Event, None]`.
- Read session state from `ctx.session.state` (a plain dict).
- **Persist state by attaching a delta to the yielded event**, not by mutating
  the dict: `yield Event(author=self.name,
  actions=EventActions(state_delta={"generated_campaign": ...}), content=...)`
  (`EventActions` from `google.adk.events`). State is committed by the Runner
  and visible to the next stage.
- Seed the session before the run with
  `await session_service.create_session(..., state={"campaign_spec": ..., ...})`;
  an `LlmAgent`'s `output_key="raw_bindings"` lands its final text in the same
  state dict.
- On 2.9.x `SequentialAgent` emits a deprecation warning (in favor of
  `Workflow`); the pipeline silences it with a targeted `warnings.filterwarnings`.
- `LlmAgent` instruction placeholders `{key}` resolve from session state at
  run time, but the implemented pipeline passes the spec in the user message
  instead — simpler and version-independent.

If a future ADK version changes these signatures, adapt only the marked lines;
the logic (read state → compute → write state via `state_delta` → yield) is
fixed.

**`agent/assembler.py`** (adapt the marked lines to your ADK version):
```python
"""Stage 2: deterministic assembler. No LLM, no randomness."""

from __future__ import annotations

import json
import re
from datetime import datetime, timedelta, timezone

from google.adk.agents import BaseAgent  # ADAPT: import path per version
from google.adk.events import Event      # ADAPT: import path per version

from generator_agent.assemble import assemble_campaign

_LABELS = (
    ("PERSONA_NAME", "display name"),
    ("PERSONA_ROLE", "role"),
    ("PERSONA_EMAIL", "from address"),
    ("EMAIL_SUBJECT", "subject"),
    ("EMAIL_BODY", "body"),
    ("EMAIL_TIME", "scheduled at"),
    ("SMS_BODY", "body"),
    ("SMS_TIME", "scheduled at"),
)


def parse_bindings(text: str) -> dict[str, str]:
    lines = [
        re.sub(r"^[\s\-*•>]+", "", line).strip()
        for line in text.splitlines()
        if line.strip()
    ]
    bindings, cursor = {}, 0
    for key, label in _LABELS:
        while cursor < len(lines) and f"{label}:" not in lines[cursor].lower():
            cursor += 1
        if cursor >= len(lines):
            raise ValueError(f"bindings missing '{label}'")
        bindings[key] = lines[cursor].split(":", 1)[-1].strip()
        cursor += 1
    return bindings


class AssemblerAgent(BaseAgent):  # ADAPT: base class per version
    """Deterministic assembly: bindings + spec -> GeneratedCampaign."""

    async def _run_async_impl(self, ctx):  # ADAPT: exact hook signature
        state = ctx.session.state  # ADAPT: state accessor
        spec = state["campaign_spec"]     # seeded before Runner.run (W0.4)
        mission = state["mission_config"]
        profile = state["profile"]
        bindings = parse_bindings(state["raw_bindings"])

        start = datetime.fromisoformat(spec["start_at"].replace("Z", "+00:00"))
        email_at = start.isoformat().replace("+00:00", "Z")
        sms_at = (start + timedelta(minutes=spec["followup_minutes"])) \
            .isoformat().replace("+00:00", "Z")

        campaign = assemble_campaign(
            bindings,
            mission,
            profile,
            spec["pretext"],
            spec["tone"],
            spec["difficulty"],
            generated_at=start,          # fixed clock (W1)
            scheduled=(email_at, sms_at),  # spec-derived schedule (W1)
        )
        state["generated_campaign"] = campaign.model_dump_json()
        yield Event(  # ADAPT: Event construction per version
            author=self.name,
            content=state["generated_campaign"],
        )
```

**`agent/validator.py`** (adapt the marked lines):
```python
"""Stage 3: deterministic validator. No LLM, no randomness."""

from __future__ import annotations

from google.adk.agents import BaseAgent  # ADAPT: import path per version
from google.adk.events import Event      # ADAPT: import path per version

from app.core.schemas import GeneratedCampaign
from validator_agent.validate import validate_campaign


class ValidatorAgent(BaseAgent):  # ADAPT: base class per version
    async def _run_async_impl(self, ctx):  # ADAPT: exact hook signature
        state = ctx.session.state  # ADAPT: state accessor
        campaign = GeneratedCampaign.model_validate_json(state["generated_campaign"])
        report = validate_campaign(campaign)  # W2 — always returns, never raises
        state["coherence_report"] = report.model_dump_json()
        yield Event(  # ADAPT: Event construction per version
            author=self.name,
            content=state["coherence_report"],
        )
```

### W0.4 Seed the session before the run

The harness (W3) and any CLI driver must put `campaign_spec`, `mission_config`,
and `profile` into session state **before** `Runner.run`, so the deterministic
stages can read them. The only user message sent to the `SequentialAgent` is a
one-line instruction ("Generate the campaign."); the content agent ignores the
mission as free text because the spec is already in state.

**Acceptance W0**
- `python -c "from agent.pipeline import root_agent"` builds the graph offline.
- The secret grep prints nothing; the root `deepseek.py` is gone.
- `grep -n "DEMO_MISSION" generator_agent/run.py generator_agent/deepseek.py`
  finds nothing (or the file no longer exists).

---

## 3. Step W1 — Make generation deterministic

### W1.1 Deterministic tracking token
**File:** `generator_agent/assemble.py`.

- Remove `from uuid import uuid4` and the `uuid4().hex[:12]` call.
- Add (copy verbatim):
```python
def tracking_token(campaign_id: str, seed: int) -> str:
    """Deterministic 12-hex token: same campaign + seed -> same token."""
    return sha256(f"{campaign_id}:{seed}".encode()).hexdigest()[:12]
```
- In `assemble_campaign`, replace the `landing_url` line with:
```python
    token = tracking_token(mission_config["campaign_id"], seed)
    landing_url = f"https://sim.{email_domain}/t/{token}"
```
Both messages keep sharing the same `cta` object, so cross-channel CTA equality
holds by construction.

### W1.2 Injectable clock + schedule
**File:** `generator_agent/assemble.py`.

- Extend the signature:
```python
def assemble_campaign(
    bindings, mission_config, profile, pretext, tone, difficulty,
    generated_at: datetime | None = None,
    scheduled: tuple[str, str] | None = None,   # (email_at, sms_at) ISO-8601
    actual_model: dict | None = None,
    runtime: dict[str, str] | None = None,
) -> GeneratedCampaign:
```
- `scheduled_at` for msg-0001/msg-0002: use `scheduled[0]`/`scheduled[1]` when
  `scheduled` is not `None`; otherwise fall back to `b["EMAIL_TIME"]` /
  `b["SMS_TIME"]` (interactive use).
- `generated_at` already defaults to `datetime.now(timezone.utc)`; the harness
  and assembler always pass a fixed value.

### W1.3 Model decoding determinism
**File:** `agent/config.py` / the model object it returns.

- Pass `temperature=0` (via `generate_content_config` or the model's config).
- If the provider exposes a `seed` parameter, pass the campaign seed; otherwise
  record `"seed_supported": false` in the message `runtime` and note in the
  report that content-level reproducibility is not provider-guaranteed.
- The hand-rolled HTTP client in `generator_agent/deepseek.py` is **superseded**
  by the ADK model: delete the file (its `parse_bindings` logic now lives in
  `agent/assembler.py`, its strict format in `BINDINGS_CONTRACT`).

**Acceptance W1**
- New unit test in `tests/test_generator_agent.py`: call `assemble_campaign`
  twice with identical inputs + fixed `generated_at` + `scheduled`, assert
  `model_dump()` is byte-identical between the two runs.
- Existing tests still green.

---

## 4. Step W2 — Deterministic Validator module + `link_consistency`

### W2.1 Schema: add the 4th check
**File:** `app/core/schemas.py`.

```python
class CoherenceCheck(str, Enum):
    PERSONA_IDENTITY = "persona_identity"
    TIMING = "timing"
    CROSS_CHANNEL_REFERENCE = "cross_channel_reference"
    LINK_CONSISTENCY = "link_consistency"   # NEW
```

In `CoherenceReport`, change `results: ... = Field(..., min_length=3)` to
`min_length=4` and add the check to the class docstring. The existing
`_report_is_consistent` already requires the results to cover
`set(CoherenceCheck)` exactly once — it now implies 4 results, no other change.

**The new rule (add to the module docstring and to `docs/flow-schema.md`):**
> Every link-like token appearing in a message's `body` must refer to that
> message's `call_to_action.landing_url` or to the `landing_url` of a message it
> `references`. When a message references another, both must carry the **same**
> `landing_url`. Comparison is on the tracking token (last path segment), after
> normalising away scheme/host and trailing punctuation.

### W2.2 The validator package (no LLM)

**`validator_agent/__init__.py`** (copy verbatim):
```python
"""Deterministic coherence validator (no LLM). See validate.validate_campaign."""

from .validate import validate_campaign

__all__ = ["validate_campaign"]
```

**`validator_agent/links.py`** (copy verbatim):
```python
"""URL/token extraction for the link_consistency coherence check."""

from __future__ import annotations

import re

FULL_URL = re.compile(r"https?://[^\s)\]\"'>]+")
BARE_REF = re.compile(r"\bsim\.[a-z0-9.-]+/t/[A-Za-z0-9._-]+")
_TRAILING = re.compile(r"[.,;:)\]]+$")


def _strip(url: str) -> str:
    return _TRAILING.sub("", url.rstrip())


def _token(url: str) -> str:
    return _strip(url).rstrip("/").rsplit("/", 1)[-1]


def tokens_in(text: str) -> set[str]:
    """Tracking tokens that appear in message prose (full URLs or bare refs)."""
    found = set()
    for m in FULL_URL.finditer(text):
        found.add(_token(m.group(0)))
    for m in BARE_REF.finditer(text):
        found.add(_token(m.group(0)))
    return found
```

**`validator_agent/validate.py`** (copy verbatim):
```python
"""Deterministic coherence validation of a GeneratedCampaign (no LLM).

The four checks mirror GeneratedCampaign._coherent plus the new link rule.
Every check returns a result object; this module never raises on bad content —
failures are data, not exceptions.
"""

from __future__ import annotations

from app.core.schemas import (
    CoherenceCheckResult,
    CoherenceReport,
    GeneratedCampaign,
)
from validator_agent.links import tokens_in


def _token_of(url) -> str:
    return str(url).rstrip("/").rsplit("/", 1)[-1]


def _check_persona(campaign: GeneratedCampaign) -> CoherenceCheckResult:
    bad = [
        m.message_id
        for m in campaign.messages
        if m.sender.display_name != campaign.persona.display_name
        or str(m.sender.from_address) != str(campaign.persona.email)
    ]
    return CoherenceCheckResult(
        check="persona_identity",
        passed=not bad,
        detail=f"all {len(campaign.messages)} messages match the persona"
        if not bad
        else f"sender mismatch in: {', '.join(bad)}",
    )


def _check_timing(campaign: GeneratedCampaign) -> CoherenceCheckResult:
    by_id = {m.message_id: m for m in campaign.messages}
    bad = [
        f"{m.message_id} before {ref}"
        for m in campaign.messages
        for ref in m.references
        if by_id[ref].scheduled_at > m.scheduled_at
    ]
    return CoherenceCheckResult(
        check="timing",
        passed=not bad,
        detail="no ordering violations" if not bad else "; ".join(bad),
    )


def _check_references(campaign: GeneratedCampaign) -> CoherenceCheckResult:
    by_id = {m.message_id: m for m in campaign.messages}
    bad = [
        f"{m.message_id} -> {ref}"
        for m in campaign.messages
        for ref in m.references
        if ref not in by_id or ref == m.message_id
    ]
    return CoherenceCheckResult(
        check="cross_channel_reference",
        passed=not bad,
        detail="all references resolve" if not bad else "; ".join(bad),
    )


def _check_links(campaign: GeneratedCampaign) -> CoherenceCheckResult:
    by_id = {m.message_id: m for m in campaign.messages}
    problems: list[str] = []
    for m in campaign.messages:
        allowed = {_token_of(m.call_to_action.landing_url)}
        for ref in m.references:
            if ref in by_id:
                allowed.add(_token_of(by_id[ref].call_to_action.landing_url))
        for tok in sorted(tokens_in(m.body) - allowed):
            problems.append(
                f"{m.message_id} body token '{tok}' not in CTA tokens "
                f"({', '.join(sorted(allowed)) or 'none'})"
            )
        # cross-channel: a follow-up must point at the same link it cites
        for ref in m.references:
            if (
                ref in by_id
                and _token_of(by_id[ref].call_to_action.landing_url)
                != _token_of(m.call_to_action.landing_url)
            ):
                problems.append(
                    f"{m.message_id} CTA token "
                    f"'{_token_of(m.call_to_action.landing_url)}' != {ref} CTA "
                    f"token '{_token_of(by_id[ref].call_to_action.landing_url)}'"
                )
    return CoherenceCheckResult(
        check="link_consistency",
        passed=not problems,
        detail="all body links match the CTA" if not problems else "; ".join(problems),
    )


def validate_campaign(campaign: GeneratedCampaign) -> CoherenceReport:
    """Run the four coherence checks. Never raises on incoherent content."""
    results = [
        _check_persona(campaign),
        _check_timing(campaign),
        _check_references(campaign),
        _check_links(campaign),
    ]
    return CoherenceReport(
        campaign_id=campaign.campaign_id,
        results=results,
        all_passed=all(r.passed for r in results),
    )
```

### W2.3 Charter parity
**File:** `prompts/validator_ag.md`.

- Add the 4th check to the charter and few-shot examples.
- Add a header note: *"The authoritative validator is
  `validator_agent/validate.py` (deterministic); this charter exists for
  documentation parity and is never called by the measurement harness."*

### W2.4 Regression test against the real known-bad fixture
**File:** `tests/test_validator_agent.py` (new, copy verbatim):
```python
"""The validator must catch the known cross-channel link failure (F3)."""

from pathlib import Path

from app.core.schemas import GeneratedCampaign
from validator_agent.validate import validate_campaign

KNOWN_BAD = Path("data/measurements/known-case/generated_campaign.json")


def test_known_bad_campaign_fails_link_consistency():
    campaign = GeneratedCampaign.model_validate_json(KNOWN_BAD.read_text())
    report = validate_campaign(campaign)
    by_check = {r.check.value: r for r in report.results}
    assert by_check["link_consistency"].passed is False
    assert "abc123" in by_check["link_consistency"].detail
    assert "d6db8064874a" in by_check["link_consistency"].detail
    assert report.all_passed is False


def test_coherent_campaign_passes_all_checks():
    from tests.test_generator_agent import CAMPAIGN  # assembled fixture
    report = validate_campaign(CAMPAIGN)
    assert report.all_passed is True
```

Update `tests/test_flow_contracts.py`'s
`test_coherence_report_all_passed_must_match_results` to carry 4 results (add a
`link_consistency` row) so it stays valid under `min_length=4`.

**Acceptance W2**
- `validate_campaign` on the known-bad fixture reports exactly one failing check
  (`link_consistency`) and `all_passed is False`.
- On a coherent campaign: `all_passed is True`.
- `pytest -q` green.

---

## 5. Step W5 — Persona catalog: 12 internal + external BEC personas

### W5.1 Trim the internal roster
**File:** `org/fantazylabz_org.json` (+ `org/fantazylabz_org.md`,
`org/fantazylabz_org_graph.md`).

Keep exactly these 12 `employees` (delete the other 38 objects), set
`"headcount": 12`, and update the two rendered docs to match:

| id | name | dept | role |
|----|------|------|------|
| 1 | Elena Marchetti | Executive | CEO |
| 2 | Rajesh Kapoor | Engineering | CTO |
| 3 | Sofia Reyes | Finance | CFO |
| 4 | Marcus Bergström | Operations | COO |
| 7 | Yuki Tanaka | Security | CISO |
| 11 | Gregory Whitfield | Finance | Director of Finance |
| 12 | Fatima El-Sayed | IT | Director of Operations & IT |
| 16 | Hannah Fischer | HR | Director of People Operations |
| 24 | Samuel Adeyemi | Finance | Accounting Manager |
| 25 | Natalia Popov | IT | IT Manager |
| 40 | Rebecca Stern | Finance | Staff Accountant |
| 41 | Bruno Costa | IT | IT Support Specialist |

Keep the original `id` values (non-contiguous is fine — `run.py` resolves by
`id`).

### W5.2 External personas
**New file:** `org/external_personas.json` (copy verbatim):
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

### W5.3 Catalog loader
**New file:** `generator_agent/catalog.py` (copy verbatim):
```python
"""Unified persona/recipient catalog: 12 internal + external BEC personas."""

from __future__ import annotations

import json
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
ORG_FILE = REPO_ROOT / "org" / "fantazylabz_org.json"
EXT_FILE = REPO_ROOT / "org" / "external_personas.json"


def load_catalog() -> list[dict]:
    org = json.loads(ORG_FILE.read_text(encoding="utf-8"))
    internal = [
        {
            "id": e["id"],
            "class": "internal",
            "org_type": "internal",
            "display_name": e["name"],
            "email": e["email"],
            "role": e["position"],
            "department": e["department"],
            "supports_pretexts": [],
        }
        for e in org["employees"]
    ]
    external = [
        {
            "id": p["persona_id"],
            "class": p["class"],
            "org_type": p["org_type"],
            "display_name": p["display_name"],
            "email": p["email"],
            "role": None,
            "department": None,
            "supports_pretexts": p["supports_pretexts"],
        }
        for p in json.loads(EXT_FILE.read_text(encoding="utf-8"))["personas"]
    ]
    return internal + external


def profile_for(persona_id) -> dict:
    """Build a generator profile dict (the shape run.py/_demo_profile used)."""
    p = next(p for p in load_catalog() if str(p["id"]) == str(persona_id))
    return {
        "profile_id": f"prf-{persona_id}",
        "target_id": "tgt-0001",
        "recipient": {
            "email": p["email"],
            "full_name": p["display_name"],
            "role": p["role"],
            "department": p["department"],
        },
        "attributes": {"seniority": "senior", "devices": ["windows"],
                       "language": "en", "language_patterns": ["formal"]},
        "labels": {"segment": str(p["org_type"]), "risk_tier": "medium"},
    }
```

- Switch `generator_agent/run.py::_demo_profile` and
  `generator_agent/send.py::_default_to` to `load_catalog()` (remove their
  direct `ORG_FILE` reads).

**Acceptance W5**
- `len(load_catalog()) == 14` (12 internal + 2 external).
- External supplier supports `invoice_payment`; bank supports
  `account_suspension`.
- `pytest -q` green.

---

## 6. Step W4 — Scope reduction (remove Recon, Profiler, Monitor)

### W4.1 Retire the stages
- Delete `prompts/recon_ag.md`, `prompts/profiler_ag.md`.
- Replace `prompts/orchestrator_ag.md`'s body with a short note that the
  Orchestrator is now the ADK `SequentialAgent` in `agent/pipeline.py`
  (non-executable design note), or delete it.

### W4.2 Schema pruning
**File:** `app/core/schemas.py`.
- `Agent` enum → keep only `ORCHESTRATOR`, `GENERATOR`, `VALIDATOR`.
- Remove `SyntheticTargetSet`, `ProfileDataset`, and their helper models
  (`SyntheticTarget`, `DomainPattern`, `AttackSurface`, `AttackSurfaceType`,
  `ProfileAttributes`, `SyntheticProfile`).
- Keep `TemplateSet`/`PayloadAssets` only if the sequencer loads them as static
  spec inputs; otherwise remove them in the same pass (nothing else consumes
  them today).
- Update `MessageEnvelope.phase` docstring to the 3-stage flow (Phase 0 config,
  Phase 1 generation, Phase 2 verification).

### W4.3 Purge Monitor / voice / feedback
- `docs/architecture.md`: remove any Monitor/feedback remnants; the "no success
  loop" statement becomes the operative design.
- `scripts/generate_diagrams.py`: it still draws the 7-agent design (Monitor-AG,
  Harvest-AG, Design-AG, Payload-AG, Responder-AG, voice, feedback arrows).
  Rewrite it to the 3-stage flow and regenerate `diagrams_output/*.png`
  (`python3 scripts/generate_diagrams.py`).
- Verify no `voice` channel survives in `docs/`, `prompts/`, or schemas.

### W4.4 Docs to match
- `docs/flow-schema.md`: drop contracts #2/#3, add `link_consistency` to the
  enum lists, update the contract index, the end-to-end diagram, and the
  persistence table.
- `docs/architecture.md`: stage table = Orchestrator (ADK `SequentialAgent`),
  Generator, Validator; note the deterministic/stochastic split.
- `README.md`: update "Generation pipeline" and the Quick Start (drop
  `recon`/`profile` CLI steps).

### W4.5 Tests
- `tests/test_flow_contracts.py`: remove tests for the deleted contracts
  (`test_synthetic_target_set_accepts_documented_example`,
  `test_target_count_must_match_number_of_targets`,
  `test_tracking_link_requires_url_and_token` if `PayloadAssets` goes, and the
  removed entries in the persistence parametrization).
- Keep every remaining test green: `pytest -q`.

---

## 7. Step W3 — Measurement harness (the actual contribution)

### W3.1 Specs
**New file:** `measurement/__init__.py` (empty) and `measurement/specs.py`
(copy the structure, adjust details):
```python
"""The fixed spec set for the reliability experiment (10 specs)."""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class CampaignSpec:
    spec_id: str
    campaign_id: str
    pretext: str
    tone: str
    difficulty: str
    language: str
    seed: int
    model: dict
    recipient_id: str          # catalog id: int (internal) or persona_id
    start_at: str              # ISO-8601 UTC, fixed
    followup_minutes: int


def baseline_specs() -> list[CampaignSpec]:
    model = {"family": "deepseek", "name": "deepseek-chat", "adapter_version": "1.0"}
    start = "2026-08-20T09:00:00Z"

    def s(spec_id, recipient_id, pretext, tone, difficulty, seed):
        return CampaignSpec(
            spec_id=spec_id, campaign_id="q3-awareness-2026",
            pretext=pretext, tone=tone, difficulty=difficulty, language="en",
            seed=seed, model=model, recipient_id=str(recipient_id),
            start_at=start, followup_minutes=75,
        )

    return [
        s("S1", 1, "executive_request", "urgent", "medium", 42),
        s("S2", 1, "executive_request", "urgent", "medium", 42),  # repeat of S1
        s("S3", 40, "invoice_payment", "friendly", "easy", 42),
        s("S4", 24, "invoice_payment", "authoritative", "medium", 7),
        s("S5", 25, "it_support", "urgent", "hard", 13),
        s("S6", 41, "password_reset", "neutral", "easy", 42),
        s("S7", 16, "hr_notice", "friendly", "medium", 99),
        s("S8", "ext-supplier-01", "invoice_payment", "authoritative", "medium", 42),
        s("S9", "ext-bank-01", "account_suspension", "urgent", "hard", 5),
        s("S10", 3, "shared_document", "authoritative", "medium", 42),
    ]
```

### W3.2 Adapters (drive the ADK pipeline)
**New file:** `measurement/adapters.py`.

- `AdkPipelineAdapter.run(spec)` — the real path: seed session state
  (`campaign_spec`, `mission_config`, `profile` via `catalog.profile_for`),
  run `agent.pipeline.root_agent` through the ADK `Runner` with
  `InMemorySessionService`, and return `GeneratedCampaign` +
  `CoherenceReport` from state. **Never** call `generator_agent.deepseek.*`.
- `StubAdapter.run(spec)` — offline: fixed bindings, same assembler/validator
  path, no API key. For testing the harness and CI only.
- Both return the same record shape; the report states which adapter ran.

### W3.3 Runner + record
**New file:** `measurement/runner.py` (structure; complete the details).
```python
"""Run one spec, validate, and record — never crash on a bad generation."""

from __future__ import annotations

import hashlib
import json
import time
from dataclasses import asdict, dataclass, field


@dataclass
class RunRecord:
    spec_id: str
    run_index: int
    adapter: str
    model: str
    seed: int
    status: str            # "ok" | "generation_error"
    campaign_hash: str | None = None
    failing_checks: list = field(default_factory=list)
    report: dict | None = None
    error: str | None = None
    duration_ms: int = 0


def canonical_hash(campaign) -> str:
    data = json.dumps(campaign.model_dump(mode="json"), sort_keys=True,
                      separators=(",", ":"))
    return hashlib.sha256(data.encode()).hexdigest()


def run_spec(spec, adapter, run_index: int) -> RunRecord:
    start = time.perf_counter()
    try:
        campaign, report = adapter.run(spec)
    except Exception as exc:            # ValidationError, timeouts, provider
        return RunRecord(spec_id=spec.spec_id, run_index=run_index,
                         adapter=adapter.name, model=spec.model["name"],
                         seed=spec.seed, status="generation_error",
                         error=f"{type(exc).__name__}: {exc}",
                         duration_ms=int((time.perf_counter() - start) * 1000))
    return RunRecord(
        spec_id=spec.spec_id, run_index=run_index, adapter=adapter.name,
        model=spec.model["name"], seed=spec.seed, status="ok",
        campaign_hash=canonical_hash(campaign),
        failing_checks=[r.check.value for r in report.results if not r.passed],
        report=asdict(report),
        duration_ms=int((time.perf_counter() - start) * 1000),
    )
```

### W3.4 Reproducibility module
**New file:** `measurement/reproduce.py` + CLI `python -m measurement.reproduce`.

- `--spec-id` (or all), `--runs N` (default 2), `--adapter {stub,adk}`,
  `--out`.
- Per spec: run N times, compare `campaign_hash`; when hashes differ, also
  compare the **deterministic layer** (campaign dict with `subject`, `body`,
  `generated_at`, `adapter_latency_ms` blanked) and list which fields changed.
- Write `reproducibility.json`:
  `{spec_id: {runs: [hash, ...], identical: bool, deterministic_layer_identical: bool, diff_fields: [...]}}`.
- The deterministic layer **must** be identical (100% by construction); the
  content layer is the measured result.

### W3.5 Reliability module
**New file:** `measurement/reliability.py` + CLI
`python -m measurement.reliability`.

- `--specs`, `--runs N` (default 1), `--adapter {stub,adk}`, `--out`.
- Aggregate over all runs: `n_specs`, `n_runs`, `n_generation_errors`,
  `n_campaigns_with_violation`, `violation_counts` per check
  (`persona_identity`, `timing`, `cross_channel_reference`,
  `link_consistency`), and per-spec rows.
- Write `reliability.json` **and** `summary.md` with two tables
  (reproducibility, failure rate). **This failure rate is the paper's first
  result — do not skip `summary.md`.**

**Acceptance W3**
- `python -m measurement.reliability --adapter stub` runs offline and writes
  both artifacts.
- `python -m measurement.reproduce --adapter stub --spec-id S1` reports
  deterministic-layer identical.
- With the real adapter: `summary.md` contains the F1/F2 numbers.

---

## 8. Execution order (respect the dependencies)

1. **W0** — ADK pipeline + de-hardcode (nothing else plugs in until this exists).
2. **W1** — determinism.
3. **W2** — validator + `link_consistency`.
4. **W5** — catalog (can be done while W2 lands).
5. **W4** — scope reduction + docs/tests/diagrams.
6. **W3** — harness, last.
7. Run the real experiments (F1 + F2) and commit the results.

---

## 9. Verification checklist (run in order)

```bash
# 1. de-hardcoded
grep -rniE "sk-[a-z0-9]{16,}|api_key\s*=\s*['\"]" --include=*.py . | grep -v venv  # empty
python -c "from agent.pipeline import root_agent; print(type(root_agent).__name__)"

# 2. all tests
pytest -q

# 3. the validator catches the known cross-channel link failure
pytest -q tests/test_validator_agent.py

# 4. harness offline (CI-safe)
python -m measurement.reliability --adapter stub --out data/measurements/_selftest
python -m measurement.reproduce   --adapter stub --spec-id S1

# 5. real experiments through the ADK Runner
#    (needs GOOGLE_API_KEY, or DEEPSEEK_API_KEY + ADK_MODEL=deepseek/deepseek-chat)
python -m measurement.reproduce   --adapter adk --spec-id S1 --runs 2
python -m measurement.reliability --adapter adk --runs 1
```

**Pass criteria**
- `pytest -q` green; the ADK graph builds offline; no hardcoded key or flow.
- `tests/test_validator_agent.py` proves the `abc123` vs `d6db8064874a`
  mismatch is detected (`link_consistency: failed`, `all_passed: false`).
- Deterministic-layer reproducibility is **100%**.
- `data/measurements/<run_id>/summary.md` contains: the seed-42 reproducibility
  row (S1 vs S2: identical yes/no + diff), the reliability table
  (# campaigns with ≥1 violation / total, broken down by check), and the
  adapter/model + spec set used.

---

## 10. Non-goals (do **not** do these in this pass)

- Do **not** fix generation so the SMS body URL matches the CTA — preserve the
  failure and let the validator flag it.
- Do **not** add victim-interaction tracking, KPIs, a Monitor agent, a voice
  channel, or a success-optimization feedback loop.
- Do **not** hand-roll the orchestration outside ADK, and do **not** hardcode
  the flow/model at a call site.
- Do **not** delete `data/q3-awareness-2026/generated_campaign.json` (evidence).
- Do **not** use real domains, banks, or suppliers; use `.example`.
- Do **not** implement the old 5-stage Recon/Profiler pipeline from earlier
  revisions of this file.

---

## 11. Gotchas & troubleshooting

- **Old ADK on the box?** Pre-1.0 ADK used different imports. Upgrade to
  `google-adk ≥ 1.22`; do not adapt the imports to an old version.
- **Custom `BaseAgent` signatures vary** across 1.x minors. `help(BaseAgent)`
  and the installed `Event` constructor are the ground truth for
  `agent/assembler.py` / `agent/validator.py`; adapt only those lines, keep the
  logic fixed.
- **`{output_key}` placeholders** in `instruction` strings must stay literal
  braces (ordinary strings, never f-strings). ADK substitutes them at run time.
- **State seeding** must happen before `Runner.run` (W0.4) or the deterministic
  stages will find no `campaign_spec`.
- **Missing provider key** → ADK raises at the content agent. The harness
  records it as `generation_error`; it must never crash the batch (W3.3).
- **JSON in fences:** the content agent's 8-line answer is parsed by
  `agent/assembler.parse_bindings`; if the model wraps it in fences, extend the
  parser, not the contract.
- **Schema failures are data.** If `GeneratedCampaign` validation raises during
  a run, that is a measured generation failure, not a bug to silently patch in
  the validator.

---

## 12. Reference

- Design rationale: [`docs/generator-reliability-plan.md`](./docs/generator-reliability-plan.md)
- ADK docs: <https://adk.dev/> · source: <https://github.com/google/adk-python>
- Known finding (F3) evidence: `data/q3-awareness-2026/generated_campaign.json`
  (preserved copy: `data/measurements/known-case/generated_campaign.json`)
