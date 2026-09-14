# Implementation Instructions — Google ADK Pipeline Template

> **Audience:** an LLM executing this work with no prior knowledge of this
> repo or of Google ADK. Follow the steps in order, copy the provided file
> contents verbatim, and do not improvise on any API detail not shown here.
>
> **Goal of this pass:** wire the five existing pipeline charters into a
> runnable **Google ADK** agent pipeline (the "agentic ground"). The Pydantic
> contracts in `app/core/schemas.py` stay the single source of truth — this
> pass adds no new schemas, no persistence layer, no FastAPI changes.
>
> **Status update (supersedes parts of this plan):** `prompts/*.md` are no
> longer plain-text instructions — they were refactored into **LMQL query
> programs** (per "Prompting is Programming: A Query Language for LLMs").
> Consequently: Step 4's rewrite of `recon_ag.md` is **obsolete** (the LMQL
> recon charter already exists); `agent/agent.py`'s `_charter()` loader must
> not paste LMQL source into an ADK instruction — either keep ADK for
> orchestration only and call the LMQL queries as tools, or drop ADK in favor
> of the LMQL runtime (`pip install lmql`). The stage map, output keys, and
> validation gate in this plan are otherwise unchanged.

---

## 0. Read these files first (do NOT modify them)

| File | Why you need it |
|---|---|
| `app/core/schemas.py` | Authoritative Pydantic contracts. Every stage output must validate against one of these. |
| `prompts/orchestrator_ag.md` | Charter for stage 1. |
| `prompts/recon_ag.md` | Charter for stage 2. **Its examples are outdated** — you will rewrite this file in Step 4. |
| `prompts/profiler_ag.md` | Charter for stage 3. |
| `prompts/generator_ag.md` | Charter for stage 4. |
| `prompts/validator_ag.md` | Charter for stage 5. |
| `tests/test_flow_contracts.py` | Existing contract tests — must stay green. |
| `README.md` | Project framing (synthetic-only, authorized, isolated). |

**Hard constraints you must never violate:**

1. This is a **generator of synthetic phishing-simulation content for
   authorized security-awareness research**. Synthetic data only, no live
   infrastructure, no real people. The schemas enforce this (`authorized:
   true`, `synthetic_data_only: true`, `isolated_environment: true` are all
   required).
2. `app/core/schemas.py`, `app/` (FastAPI), `tests/test_flow_contracts.py`,
   and all charter files **except `prompts/recon_ag.md`** are off-limits.
3. Do not add new pip dependencies beyond `google-adk`.

---

## 1. The design (what you are building)

Google ADK exposes agents as Python objects and lets a `SequentialAgent` run
a fixed, ordered list of sub-agents — one `LlmAgent` per pipeline stage — with
no user interaction between stages. That matches the project's one-way
generate-then-verify flow exactly.

### Stage map

| # | Stage (ADK agent name) | Charter | `output_key` (shared state) | Output validated against |
|---|---|---|---|---|
| 1 | `orchestrator_ag` | `prompts/orchestrator_ag.md` | `mission_config` | `MissionConfig` |
| 2 | `recon_ag` | `prompts/recon_ag.md` (rewritten, Step 4) | `target_set` | `SyntheticTargetSet` |
| 3 | `profiler_ag` | `prompts/profiler_ag.md` | `profile_dataset` | `ProfileDataset` |
| 4 | `generator_ag` | `prompts/generator_ag.md` | `generated_campaign` | `GeneratedCampaign` |
| 5 | `validator_ag` | `prompts/validator_ag.md` | `coherence_report` | `CoherenceReport` |

### Key ADK facts (verified against ADK docs — copy these, don't "correct" them)

```python
from google.adk.agents import LlmAgent, SequentialAgent  # LlmAgent == Agent alias
from google.adk.runners import Runner
from google.adk.sessions import InMemorySessionService
from google.genai import types
```

- `LlmAgent(model=..., name=..., description=..., instruction=..., output_key=...)`
- `model` may be a string like `"gemini-2.5-flash"` (requires a
  `GOOGLE_API_KEY` env var) — that is all this pass needs.
- `SequentialAgent(name=..., sub_agents=[...], description=...)` runs its
  sub-agents in the given order, **without pausing**, sharing one session.
- Sub-agents exchange data via `output_key`: stage N's final response is
  stored in shared state under its `output_key`, and later stages read it by
  putting `{output_key}` **literally** in their `instruction` string. ADK
  substitutes these placeholders at run time. (They must stay literal — never
  use an f-string for an instruction containing `{...}`.)
- ADK convention: a folder `agent/` with `agent.py` defining a module-level
  `root_agent`, and `__init__.py` containing `from . import agent`. The CLI
  (`adk run agent`, `adk web`) discovers the package that way.
- ADK is installed from PyPI as `google-adk` (Python ≥ 3.10). The API changed
  between pre-1.0 and 1.x releases; these instructions target **google-adk
  ≥ 1.22**. If the imports in this document fail, the installed version is too
  old — upgrade, don't adapt the code.

### Files you will create or change

| File | Action |
|---|---|
| `requirements.txt` | Add `google-adk` (Step 2) |
| `agent/__init__.py` | Create (Step 3) |
| `agent/agent.py` | Create (Step 3) |
| `prompts/recon_ag.md` | **Rewrite** to match `SyntheticTargetSet` (Step 4) |
| `scripts/run_adk_pipeline.py` | Create — programmatic runner + validation gate (Step 5) |
| `tests/test_adk_agents.py` | Create — offline assembly tests (Step 6) |
| `.gitignore` | Append two lines (Step 7) |

---

## 2. Step 1 — Add the dependency

Run:

```bash
pip install google-adk
pip show google-adk | grep ^Version
```

Then append to `requirements.txt` (keeping the existing alphabetical,
`==`-pinned style — place it before `email-validator`):

```
google-adk==<the version pip show reported>
```

Verify: `python -c "from google.adk.agents import LlmAgent, SequentialAgent; print('ok')"`

If that import fails, the installed google-adk is pre-1.0; upgrade it. Do not
adapt the import paths.

---

## 3. Step 2 & 3 — Create the `agent/` package

### 3.1 Create `agent/__init__.py`

```python
"""ADK agent package: exposes the campaign pipeline as ``root_agent``."""

from . import agent
from .agent import root_agent

__all__ = ["agent", "root_agent"]
```

### 3.2 Create `agent/agent.py`

Copy this file **verbatim** (including the docstring and comments):

```python
"""Google ADK pipeline: the five generator stages wired as one sequential agent.

Root agent = SequentialAgent running, in order:
    Orchestrator-AG -> Recon-AG -> Profiler-AG -> Generator-AG -> Validator-AG

Each stage is an LlmAgent whose instruction is the matching charter in
``prompts/`` plus a pipeline tail. The tail (a) pins the output JSON contract
and (b) injects upstream outputs via ``{output_key}`` placeholders, which ADK
substitutes from shared session state at run time.

The authoritative schemas live in ``app/core/schemas.py`` (validated by
``scripts/run_adk_pipeline.py``) — this module defines no new data shapes.

Run interactively with ``adk run agent`` (needs a GOOGLE_API_KEY env var).
"""

from __future__ import annotations

import os
from pathlib import Path

from google.adk.agents import LlmAgent, SequentialAgent

PROMPTS_DIR = Path(__file__).resolve().parent.parent / "prompts"
DEFAULT_MODEL = os.getenv("ADK_MODEL", "gemini-2.5-flash")


def _charter(name: str) -> str:
    """Load a stage charter (``prompts/<name>_ag.md``)."""
    return (PROMPTS_DIR / f"{name}_ag.md").read_text(encoding="utf-8")


def _tail(contract: str, *inputs: str) -> str:
    """Pipeline tail appended to every charter.

    ``contract`` states the exact JSON the stage must emit. ``inputs`` are the
    output_keys of earlier stages, injected below as ``{key}`` placeholders
    (ADK substitutes them from shared state at run time — do NOT turn this
    into an f-string).
    """
    if inputs:
        joined = "\n".join(
            f"- `{key}`:\n```json\n{{{key}}}\n```" for key in inputs
        )
        inputs_block = f"INPUTS — the outputs of the previous stage(s):\n{joined}\n"
    else:
        inputs_block = "INPUTS — none; this is the first stage.\n"
    return (
        "\n\n---\n\nPIPELINE OVERRIDES (this section wins over anything above "
        "that contradicts it)\n\n"
        + inputs_block
        + "\nOUTPUT CONTRACT — emit exactly one JSON object with these fields "
        "and nothing else (no markdown fences, no commentary):\n"
        + contract
    )


# --------------------------------------------------------------------------- #
# Per-stage output contracts (field lists mirror app/core/schemas.py exactly)
# --------------------------------------------------------------------------- #

MISSION_CONFIG_CONTRACT = """{
  "campaign_id": "<string, use the campaign_id from the operator request>",
  "authorized": true,
  "objective": "<string, from the operator request>",
  "scope": {
    "region": "<string>", "sector": "<string>",
    "volume": <int, from the request>, "duration_days": <int, from the request>
  },
  "constraints": {
    "synthetic_data_only": true,
    "channels": ["<one or both of: email, sms>"],
    "max_messages_per_persona": <int, 1..20>
  },
  "model_policy": {
    "models": [
      { "family": "<one of: anthropic, openai, mistral, llama, local>",
        "name": "<provider model id>", "adapter_version": "1.0" },
      { "family": "<a DIFFERENT family>", "name": "<provider model id>",
        "adapter_version": "1.0" }
    ]
  },
  "reproducibility": { "seed": <the fixed int from the operator request>, "deterministic": true },
  "ethics": { "consent_reference": "<string>", "isolated_environment": true }
}
RULES: authorized, synthetic_data_only, and isolated_environment must all be
true; model_policy must list at least two distinct family values; channels
must be a subset of email and sms (never voice)."""

TARGET_SET_CONTRACT = """{
  "campaign_id": "<string, same as in the MissionConfig input>",
  "source": "synthetic",
  "target_count": <int, equal to len(targets)>,
  "targets": [
    {
      "target_id": "tgt-0001",   // sequential: tgt-0001, tgt-0002, ...
      "synthetic_domain": "<fabricated domain, never a real organization's>",
      "domain_pattern": "<one of: typosquat, homoglyph, subdomain, combosquat>",
      "attack_surfaces": [
        { "type": "<one of: mail_server, login_form, api, portal>",
          "value": "<fabricated URL on the synthetic domain>" }
      ]
    }
  ]
}
RULES: source must be exactly "synthetic"; target_count must equal the number
of targets; every target needs at least one attack_surface.
TEMPLATE LIMITATION: if MissionConfig scope.volume exceeds 10, generate 10
targets and set target_count to 10 (the profiler consumes what you emit)."""

PROFILE_DATASET_CONTRACT = """{
  "campaign_id": "<string, same as in the MissionConfig input>",
  "source": "synthetic",
  "format": "json",
  "record_count": <int, equal to len(profiles)>,
  "profiles": [
    {
      "profile_id": "prf-0001",   // sequential: prf-0001, prf-0002, ...
      "target_id": "<an existing target_id from the SyntheticTargetSet input>",
      "recipient": {
        "email": "<fabricated address on that target's synthetic_domain>",
        "full_name": "<fabricated name>",
        "role": "<string>",
        "department": "<string>"
      },
      "attributes": {
        "seniority": "<string>",
        "devices": ["<string>"],
        "language": "en",
        "language_patterns": ["<string>"]
      },
      "labels": { "segment": "<string>", "risk_tier": "<string>" }
    }
  ]
}
RULES: source must be exactly "synthetic"; record_count must equal the number
of profiles; every target_id must exist in the input SyntheticTargetSet;
generate at least 1 and at most 3 profiles per target; all identities are
fabricated — never real people."""

GENERATED_CAMPAIGN_CONTRACT = """{
  "campaign_id": "<string, same as in the MissionConfig input>",
  "persona": {
    "display_name": "<the single impersonated identity, e.g. the CEO>",
    "email": "<fabricated address>",
    "role": "<string>",
    "department": "<string>",
    "organization": "<string>"
  },
  "messages": [
    {
      "message_id": "msg-0001",   // sequential, and NO message references itself
      "channel": "email",         // or "sms"
      "scheduled_at": "2026-08-20T09:00:00Z",   // timezone-aware UTC
      "sender": { "display_name": "<MUST equal persona.display_name>",
                  "from_address": "<MUST equal persona.email>" },
      "subject": "<email ONLY — SMS messages must NOT carry a subject>",
      "body": "<the simulated message text>",
      "call_to_action": { "type": "<one of: click_link, enter_credentials, open_attachment, reply>",
                          "landing_url": "<synthetic simulation URL>",
                          "button_label": "<string>" },
      "references": ["<message_id> of an EARLIER message, or omit>"],
      "provenance": {
        "model": { "family": "<one of the families from model_policy>",
                   "name": "<one of the model names from model_policy>",
                   "adapter_version": "1.0" },
        "params": { "temperature": 0.7, "top_p": 1.0, "max_tokens": 1024,
                    "seed": <the campaign seed> },
        "prompt_template_id": "tpl-0001",
        "prompt_hash": "<64 hex chars: sha256 of the exact prompt text you rendered>",
        "generated_at": "<ISO-8601 UTC timestamp>",
        "adapter_latency_ms": <int>,
        "runtime": { "sdk": "google-adk" }
      }
    }
  ]
}
RULES: produce a campaign bundle of 2-3 messages — one email plus an SMS
follow-up that references it. The sender must be byte-for-byte identical to
the persona in EVERY message. Email messages must have a subject; SMS must
not and must stay under 1600 characters. A follow-up is scheduled AFTER the
message it references. Every message must be a simulation using only the
synthetic identities and URLs supplied."""

COHERENCE_REPORT_CONTRACT = """{
  "campaign_id": "<string, same as in the GeneratedCampaign input>",
  "results": [
    { "check": "persona_identity", "passed": <true|false>,
      "detail": "<one sentence; name the offending message_id(s) when false>" },
    { "check": "timing", "passed": <true|false>, "detail": "<...>" },
    { "check": "cross_channel_reference", "passed": <true|false>, "detail": "<...>" }
  ],
  "all_passed": <true only if ALL three results are true>
}
RULES: exactly one result per check, using exactly those three enum values in
that order; all_passed must equal the AND of the three passed values. Report
faithfully — never soften a violation."""


# --------------------------------------------------------------------------- #
# The five stage agents
# --------------------------------------------------------------------------- #

orchestrator_ag = LlmAgent(
    model=DEFAULT_MODEL,
    name="orchestrator_ag",
    description=(
        "Opens the campaign: emits the authorized, synthetic-only MissionConfig."
    ),
    instruction=_charter("orchestrator") + _tail(MISSION_CONFIG_CONTRACT),
    output_key="mission_config",
)

recon_ag = LlmAgent(
    model=DEFAULT_MODEL,
    name="recon_ag",
    description="Emits a synthetic-only SyntheticTargetSet (no live collection).",
    instruction=_charter("recon") + _tail(TARGET_SET_CONTRACT, "mission_config"),
    output_key="target_set",
)

profiler_ag = LlmAgent(
    model=DEFAULT_MODEL,
    name="profiler_ag",
    description="Emits synthetic recipient profiles (ProfileDataset) from the targets.",
    instruction=_charter("profiler")
    + _tail(PROFILE_DATASET_CONTRACT, "mission_config", "target_set"),
    output_key="profile_dataset",
)

generator_ag = LlmAgent(
    model=DEFAULT_MODEL,
    name="generator_ag",
    description=(
        "Emits a coherent GeneratedCampaign (email + SMS follow-up) with "
        "per-message provenance."
    ),
    instruction=_charter("generator")
    + _tail(GENERATED_CAMPAIGN_CONTRACT, "mission_config", "profile_dataset"),
    output_key="generated_campaign",
)

validator_ag = LlmAgent(
    model=DEFAULT_MODEL,
    name="validator_ag",
    description="Emits the CoherenceReport for the generated campaign.",
    instruction=_charter("validator")
    + _tail(COHERENCE_REPORT_CONTRACT, "generated_campaign"),
    output_key="coherence_report",
)


root_agent = SequentialAgent(
    name="campaign_generator_pipeline",
    sub_agents=[
        orchestrator_ag,
        recon_ag,
        profiler_ag,
        generator_ag,
        validator_ag,
    ],
    description=(
        "Configurable, reproducible generator of synthetic phishing-simulation "
        "campaigns (email + SMS) for authorized security-awareness research."
    ),
)
```

---

## 4. Step 4 — Rewrite `prompts/recon_ag.md`

The existing recon charter's examples use an old shape (`domain`,
`typo_variant`, `total_targets`) that predates the schemas realignment and
would fail `SyntheticTargetSet` validation. **Replace the entire file** with:

```markdown
You are the Intelligence Agent (Recon-AG) for a controlled phishing-simulation generator.

**Few‑Shot Learning Principle** (cf. OpenAI, 2020):
You are a few‑shot learner – your generation quality improves dramatically when given clear, structured examples.
Follow the pattern, style, and level of detail from the examples below **exactly**.
Never collect or use real data; all domains and attack surfaces must be **fully synthetic**.

---
### Few‑Shot Examples

**Example 1 (campaign q3-awareness-2026, region: latam, sector: finance)**
```json
{
  "campaign_id": "q3-awareness-2026",
  "source": "synthetic",
  "target_count": 2,
  "targets": [
    {
      "target_id": "tgt-0001",
      "synthetic_domain": "banco-pacifica.net",
      "domain_pattern": "typosquat",
      "attack_surfaces": [
        { "type": "login_form", "value": "https://banco-pacifica.net/portal/login" },
        { "type": "api", "value": "https://api.banco-pacifica.net/v2/auth" }
      ]
    },
    {
      "target_id": "tgt-0002",
      "synthetic_domain": "paγsta-finance.com",
      "domain_pattern": "homoglyph",
      "attack_surfaces": [
        { "type": "mail_server", "value": "smtp.paγsta-finance.com" }
      ]
    }
  ]
}
```

**Example 2 (campaign emea-redteam-2026-11, region: emea, sector: technology)**
```json
{
  "campaign_id": "emea-redteam-2026-11",
  "source": "synthetic",
  "target_count": 1,
  "targets": [
    {
      "target_id": "tgt-0003",
      "synthetic_domain": "stackly-tools.io",
      "domain_pattern": "subdomain",
      "attack_surfaces": [
        { "type": "portal", "value": "https://login.stackly-tools.io/sso" },
        { "type": "api", "value": "https://api.stackly-tools.io/v1/session" }
      ]
    }
  ]
}
```

---

**Your Task:**
1. Receive the campaign's `MissionConfig` (campaign_id, scope.region, scope.sector, scope.volume) as input.
2. Generate fully-synthetic targets, each with a sequential `target_id` (`tgt-0001`, `tgt-0002`, ...), a fabricated `synthetic_domain`, and a `domain_pattern` from: `typosquat`, `homoglyph`, `subdomain`, `combosquat`.
3. Give every target at least one `attack_surface`; `type` must be one of: `mail_server`, `login_form`, `api`, `portal`; `value` is a fabricated URL on the synthetic domain.
4. Set `source: "synthetic"` and `target_count` equal to the number of targets.
5. Output a single valid `SyntheticTargetSet` JSON object matching the schema — nothing else, no markdown fences.
6. Do **not** generate domains that resolve to real organizations, and never scan or probe anything.
```

---

## 5. Step 5 — Create `scripts/run_adk_pipeline.py`

This is the programmatic entry point: it drives the pipeline through the ADK
`Runner`, extracts the five `output_key` artifacts from session state,
**validates every artifact against its Pydantic schema, and persists nothing
unless everything validates** (the authorization gate: `MissionConfig`
validation rejects any unauthorized / non-synthetic / non-isolated output).

Copy verbatim:

```python
"""Run the ADK campaign pipeline end-to-end and validate its outputs.

The five stage outputs are read from ADK session state by output_key and
validated against the Pydantic contracts in ``app/core/schemas.py``. Nothing
is written to disk unless every artifact validates — an unauthorized or
incoherent run produces no persisted output (the authorization gate).

Usage (from the repo root):

    GOOGLE_API_KEY=... python scripts/run_adk_pipeline.py \
        --campaign-id q3-awareness-2026 --seed 42
"""

from __future__ import annotations

import argparse
import asyncio
import json
import sys
from pathlib import Path

from google.adk.runners import Runner
from google.adk.sessions import InMemorySessionService
from google.genai import types

from agent import root_agent
from app.core import schemas as fc

APP_NAME = "campaign-pipeline"
USER_ID = "operator"

# output_key -> Pydantic model the artifact must validate against
VALIDATORS: dict[str, type] = {
    "mission_config": fc.MissionConfig,
    "target_set": fc.SyntheticTargetSet,
    "profile_dataset": fc.ProfileDataset,
    "generated_campaign": fc.GeneratedCampaign,
    "coherence_report": fc.CoherenceReport,
}


def _extract_json(text: str) -> str:
    """Strip markdown fences and surrounding prose from an LLM response."""
    text = text.strip()
    if text.startswith("```"):
        text = text.split("\n", 1)[-1].rsplit("```", 1)[0]
    start, end = text.find("{"), text.rfind("}")
    return text[start : end + 1]


def _read(state, key: str):
    """Read an output_key from ADK session state.

    ADK's state access has varied across versions; try the common shapes.
    """
    if isinstance(state, dict):
        return state.get(key)
    for access in (lambda: state.get(key), lambda: state[key]):
        try:
            return access()
        except (AttributeError, KeyError, TypeError):
            continue
    return None


def _state_keys(state) -> list[str]:
    if isinstance(state, dict):
        return list(state)
    try:
        return list(state.keys())
    except Exception:
        return [repr(state)]


async def main(args: argparse.Namespace) -> int:
    mission_request = (
        "Start a phishing-simulation campaign GENERATOR run with:\n"
        f"- campaign_id: {args.campaign_id}\n"
        f"- objective: {args.objective}\n"
        f"- scope: region={args.region}, sector={args.sector}, "
        f"volume={args.volume}, duration_days={args.duration}\n"
        f"- channels: {args.channels}\n"
        f"- reproducibility seed: {args.seed}\n"
        "- model_policy: at least two distinct model families "
        "(e.g. anthropic and openai)\n"
        "- constraints: synthetic_data_only=true, max_messages_per_persona=3\n"
        "- ethics: isolated_environment=true, consent_reference=IRB-2026-014\n"
        "Everything must be synthetic and authorized. Proceed through all stages."
    )

    session_service = InMemorySessionService()
    session = await session_service.create_session(
        app_name=APP_NAME, user_id=USER_ID
    )
    runner = Runner(
        agent=root_agent, app_name=APP_NAME, session_service=session_service
    )

    async for event in runner.run_async(
        user_id=USER_ID,
        session_id=session.id,
        new_message=types.Content(
            role="user", parts=[types.Part(text=mission_request)]
        ),
    ):
        if (
            event.is_final_response()
            and event.content
            and event.content.parts
        ):
            print("Pipeline final response:")
            print(event.content.parts[0].text)
            print()

    # --- Extract + validate every stage artifact before persisting anything.
    session = await session_service.get_session(
        app_name=APP_NAME, user_id=USER_ID, session_id=session.id
    )
    artifacts: dict[str, object] = {}
    for key, model in VALIDATORS.items():
        raw = _read(session.state, key)
        if not raw:
            print(
                f"FAIL: state key '{key}' missing. Available keys: "
                f"{_state_keys(session.state)}"
            )
            return 2
        try:
            artifacts[key] = model.model_validate(json.loads(_extract_json(str(raw))))
        except (json.JSONDecodeError, ValueError) as exc:
            print(f"FAIL: artifact '{key}' failed {model.__name__} validation:")
            print(exc)
            return 1
        print(f"ok: {key} validates as {model.__name__}")

    # --- Cross-artifact consistency: one campaign id everywhere.
    campaign_ids = {str(a.campaign_id) for a in artifacts.values()}
    if campaign_ids != {args.campaign_id}:
        print(f"FAIL: campaign_id mismatch across artifacts: {sorted(campaign_ids)}")
        return 1

    # --- The gate has passed: persist.
    out_dir = Path(args.output or f"data/{args.campaign_id}")
    out_dir.mkdir(parents=True, exist_ok=True)
    for key, artifact in artifacts.items():
        path = out_dir / f"{key}.json"
        path.write_text(artifact.model_dump_json(indent=2), encoding="utf-8")
        print(f"saved: {path}")

    print(f"\nSUCCESS: campaign {args.campaign_id} generated, validated, persisted.")
    return 0


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--campaign-id", required=True)
    parser.add_argument("--seed", type=int, default=42)
    parser.add_argument("--objective", default="security-awareness-training")
    parser.add_argument("--region", default="latam")
    parser.add_argument("--sector", default="technology")
    parser.add_argument("--volume", type=int, default=5)
    parser.add_argument("--duration", "--duration-days", type=int, default=14)
    parser.add_argument("--channels", default="email,sms")
    parser.add_argument("--output")
    sys.exit(asyncio.run(main(parser.parse_args())))
```

---

## 6. Step 6 — Create `tests/test_adk_agents.py`

Offline tests — no model calls, no API key. They pin the pipeline wiring so
any accidental change to stage order, output keys, or charter loading fails
CI. Copy verbatim:

```python
"""Offline assembly tests for the ADK pipeline (no model calls, no API key)."""

from google.adk.agents import SequentialAgent

import agent
from agent.agent import _charter

# (agent name, output_key) in exact pipeline order
EXPECTED_STAGES = [
    ("orchestrator_ag", "mission_config"),
    ("recon_ag", "target_set"),
    ("profiler_ag", "profile_dataset"),
    ("generator_ag", "generated_campaign"),
    ("validator_ag", "coherence_report"),
]


def test_root_agent_is_a_sequential_pipeline():
    assert isinstance(agent.root_agent, SequentialAgent)


def test_stages_are_wired_in_pipeline_order():
    assert [
        (a.name, a.output_key) for a in agent.root_agent.sub_agents
    ] == EXPECTED_STAGES


def test_every_stage_instruction_loads_its_charter():
    markers = [
        "Orchestrator-AG",
        "Recon-AG",
        "Profiler-AG",
        "Generator-AG",
        "Validator-AG",
    ]
    for sub, marker in zip(agent.root_agent.sub_agents, markers):
        assert marker in sub.instruction, (
            f"stage {sub.name} instruction does not contain its charter marker"
        )


def test_downstream_stages_receive_upstream_outputs():
    instr = {a.name: a.instruction for a in agent.root_agent.sub_agents}
    assert "{mission_config}" in instr["recon_ag"]
    assert "{mission_config}" in instr["profiler_ag"]
    assert "{target_set}" in instr["profiler_ag"]
    assert "{profile_dataset}" in instr["generator_ag"]
    assert "{generated_campaign}" in instr["validator_ag"]


def test_recon_charter_matches_synthetic_target_set_fields():
    # The rewritten recon charter must use the real schema's field names.
    recon = _charter("recon")
    assert "synthetic_domain" in recon
    assert "target_count" in recon
    assert "attack_surfaces" in recon
    assert "typo_variant" not in recon  # the old pre-realignment shape is gone
```

---

## 7. Step 7 — Append to `.gitignore`

```gitignore
# ADK runtime artifacts
data/
.env
```

---

## 8. Verification checklist (run these, in order)

```bash
# 1. Imports resolve (from the repo root)
python -c "from google.adk.agents import LlmAgent, SequentialAgent; print('adk ok')"
python -c "import agent; print(type(agent.root_agent).__name__)"

# 2. All tests pass — the 16 existing contract tests plus the 5 new ones
pytest

# 3. Optional, needs GOOGLE_API_KEY (Google AI Studio): interactive smoke test
adk run agent

# 4. Optional, needs GOOGLE_API_KEY: full end-to-end run
GOOGLE_API_KEY=... python scripts/run_adk_pipeline.py \
    --campaign-id q3-awareness-2026 --seed 42
#   Expected: five "ok: <key> validates as <Model>" lines, five saved files
#   under data/q3-awareness-2026/, and "SUCCESS".
```

Expected outcome of step 2: `21 passed` (16 existing + 5 new).

**Acceptance criteria** — the pass is done when:

1. `pytest` is green without modifying any existing test or schema file.
2. `agent.root_agent` is a `SequentialAgent` with the five sub-agents in
   order, each loading its charter and declaring its `output_key`.
3. The end-to-end script (if an API key is available) persists the five
   artifacts under `data/<campaign_id>/` only after all Pydantic validations
   pass, and exits non-zero with a clear message otherwise.

---

## 9. Gotchas & troubleshooting

- **Old ADK on the box?** Pre-1.0 ADK used different imports
  (`google.adk.agents.llm_agent`, `AgentsApp`, etc.). Do not adapt this
  document's imports to an old version — upgrade to a current `google-adk`
  instead.
- **"Missing key inputs argument!"** at run time means no `GOOGLE_API_KEY`
  env var is set. Set it and rerun.
- **`{output_key}` placeholders** in instructions must remain literal braces
  in the Python string (they are ordinary strings here, not f-strings). ADK
  substitutes them from session state at run time.
- **JSON in fences:** models often wrap output in ``` ```json ``` fences or
  prose. `_extract_json` in the runner strips both — do not remove it.
- **SequentialAgent never pauses** between stages. This template therefore
  validates (and gates) *after* the pipeline rather than between stages. If a
  stricter pre-generation gate is needed later, the upgrade path is: run
  `orchestrator_ag` alone via the Runner, validate its `MissionConfig`, and
  only then run the remaining stages — the wiring in `agent.py` already keeps
  each stage importable separately.
- **State key missing after a run:** ADK versions differ in how state is
  exposed. The runner prints the available keys on failure — adapt only the
  `_read`/`_state_keys` accessors if needed, never the key names themselves.
- **Do not touch** `app/core/schemas.py` even if validation fails: a failure
  means the LLM output violated a business rule (e.g. unauthorized,
  mismatched persona, missing hash), which is the pipeline working as
  designed.

---

## 10. Explicitly out of scope for this pass (do NOT implement)

- **Multi-family model adapters** (the schemas already *require* ≥ 2 families
  in `model_policy`, but wiring real provider calls per family is Phase B).
  The documented Phase B route is LiteLLM via ADK — for reference only:
  `pip install "litellm>=1.84"`, then
  `LlmAgent(model=LiteLlm(model="anthropic/claude-..."), ...)` with
  `from google.adk.models.lite_llm import LiteLlm` and per-provider API key
  env vars (`ANTHROPIC_API_KEY`, `OPENAI_API_KEY`, ...). Do not add this now.
- **FastAPI integration** — `app/presentation/routes.py` stays an
  acknowledgement stub; no changes to `app/`.
- **Persistence layer** — files under `data/` are plain JSON; the
  `PersistencePolicy` contracts describe future storage, not this pass.
- **`adk api_server` / `adk web` production serving**, streaming, sessions
  with real storage.
- **Docs updates** — `docs/flow-schema.md` already documents the hand-off
  shapes; this pass changes no contract, so no doc change is required.

---

## 11. Reference (read if anything above is unclear)

- ADK docs: <https://adk.dev/> — installation, LlmAgent basics, and the
  sequential-agents workflow page (the canonical `SequentialAgent` +
  `output_key` example lives there).
- ADK Python source: <https://github.com/google/adk-python>.
