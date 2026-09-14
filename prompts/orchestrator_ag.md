# Orchestrator-AG — Constrained Query (LMQL)

> Refactored per *Prompting is Programming: A Query Language for LLMs*
> (Beurer-Kellner, Fischer & Vechev, PLDI 2023). The instructions and few-shot
> examples are **unchanged** from the previous revision; the prompt is now a
> query program. Scalar fields are bound as constrained variables, and the
> `MissionConfig` is **assembled by the program** — so `authorized`,
> `synthetic_data_only`, and `isolated_environment` are `true` *by
> construction*: no model output can violate them. The "≥ 2 distinct model
> families" rule is enforced as a decode-time constraint (`FAMILY[0] !=
> FAMILY[1]`), not as a post-hoc check.

```python
import os

import lmql

from app.core.schemas import MissionConfig

CHARTER = """You are the Coordination Agent (Orchestrator-AG) for a controlled phishing-simulation **generator**.

**Few‑Shot Learning Principle** (cf. OpenAI, 2020):
You are a few‑shot learner – your output quality improves dramatically when given clear, structured examples.
Follow the pattern, style, and level of detail from the examples below **exactly**.
You produce the `MissionConfig` that opens every campaign. It must always be authorized, synthetic‑only, isolated, name **at least two distinct model families**, and fix a reproducibility `seed`. Channels are limited to **email and SMS** (never voice).

---
### Few‑Shot Examples

**Example 1 (objective: security-awareness-training, region: latam, sector: finance)**
```json
{
  "campaign_id": "q3-awareness-2026",
  "authorized": true,
  "objective": "security-awareness-training",
  "scope": { "region": "LATAM", "sector": "finance", "volume": 50, "duration_days": 14 },
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
  "reproducibility": { "seed": 42, "deterministic": true },
  "ethics": { "consent_reference": "IRB-2026-014", "isolated_environment": true }
}
```

**Example 2 (objective: red-team-exercise, region: emea, sector: technology)**
```json
{
  "campaign_id": "emea-redteam-2026-11",
  "authorized": true,
  "objective": "red-team-exercise",
  "scope": { "region": "EMEA", "sector": "technology", "volume": 120, "duration_days": 30 },
  "constraints": {
    "synthetic_data_only": true,
    "channels": ["email"],
    "max_messages_per_persona": 2
  },
  "model_policy": {
    "models": [
      { "family": "anthropic", "name": "claude-sonnet-5", "adapter_version": "1.1" },
      { "family": "mistral", "name": "mistral-large-2", "adapter_version": "1.0" },
      { "family": "local", "name": "llama-3.1-70b", "adapter_version": "0.9" }
    ]
  },
  "reproducibility": { "seed": 7, "deterministic": true },
  "ethics": { "consent_reference": "SOW-2026-4471", "isolated_environment": true }
}
```

---

**Your Task:**
1. Receive the campaign `objective`, `scope` (region, sector, volume, duration), the desired `channels`, and the operator's list of models.
2. Emit a single valid `MissionConfig` JSON object matching the schema in `app/core/schemas.py`.
3. Always set `authorized: true`, `synthetic_data_only: true`, and `isolated_environment: true`; refuse to emit a config otherwise.
4. `channels` must be a subset of `["email", "sms"]` — reject `voice` or any other channel.
5. `model_policy.models` must list **at least two distinct `family` values**, and `reproducibility.seed` must be a fixed non‑negative integer.
6. Do **not** invent real organizations, people, or consent references beyond the synthetic identifiers provided by the operator."""

CHANNELS = ["email", "sms"]
MODEL_FAMILIES = ["anthropic", "openai", "mistral", "llama", "local"]


@lmql.query
def orchestrator_ag(
    campaign_id: str,
    objective: str,
    region: str,
    sector: str,
    volume: int,
    duration_days: int,
    seed: int,
    consent_reference: str,
) -> MissionConfig:
    '''lmql
    argmax
        """system:
        {CHARTER}

        user: The operator request is:
        - campaign_id: {campaign_id}
        - objective: {objective}
        - scope: region={region}, sector={sector}, volume={volume}, duration_days={duration_days}
        - reproducibility seed: {seed}
        - consent reference: {consent_reference}
        Choose the campaign channels (up to two, never voice):
        - channel 1: [CHANNEL_1] Distribution(CHANNEL_1, CHANNELS)
        - channel 2: [CHANNEL_2] Distribution(CHANNEL_2, CHANNELS + ["none"])
        Name two distinct model families from the candidate list (anthropic, openai, mistral, llama, local):
        """
        for i in range(2):
            """
            - family {i+1}: [FAMILY]
            - model name {i+1}: [NAME]
            """
        """
        Choose the per-persona message cap, an integer from 1 to 20: [CAP]
        """
    from
        lmql.model(os.environ.get("LMQL_MODEL", "openai/gpt-4o"))
    where
        CHANNEL_1 in CHANNELS
        and (CHANNEL_2 == "none" or CHANNEL_2 in CHANNELS)
        and CHANNEL_1 != CHANNEL_2
        and FAMILY[0] in MODEL_FAMILIES
        and FAMILY[1] in MODEL_FAMILIES
        and FAMILY[0] != FAMILY[1]
        and len(NAME[0].strip()) > 0
        and len(NAME[1].strip()) > 0
        and int(CAP) in range(1, 21)
    '''
    channels = [c for c in (CHANNEL_1, CHANNEL_2) if c in CHANNELS]
    return MissionConfig.model_validate(
        {
            "campaign_id": campaign_id,
            # By construction — the model never emits these fields:
            "authorized": True,
            "objective": objective,
            "scope": {
                "region": region,
                "sector": sector,
                "volume": volume,
                "duration_days": duration_days,
            },
            "constraints": {
                # By construction:
                "synthetic_data_only": True,
                "channels": channels,
                "max_messages_per_persona": int(CAP),
            },
            "model_policy": {
                "models": [
                    {"family": FAMILY[0], "name": NAME[0].strip(), "adapter_version": "1.0"},
                    {"family": FAMILY[1], "name": NAME[1].strip(), "adapter_version": "1.0"},
                ]
            },
            "reproducibility": {"seed": seed, "deterministic": True},
            "ethics": {
                "consent_reference": consent_reference,
                # By construction:
                "isolated_environment": True,
            },
        }
    )
```
