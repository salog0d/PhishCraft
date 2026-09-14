# Profiler-AG — Constrained Query (LMQL)

> Refactored per *Prompting is Programming: A Query Language for LLMs*
> (Beurer-Kellner, Fischer & Vechev, PLDI 2023). The instructions and few-shot
> examples are **unchanged**; the prompt is now a query program. Profile fields
> are bound as constrained variables (language is enforced with a `REGEX`
> locale constraint), and the `ProfileDataset` is **assembled by the
> program** — so `source: "synthetic"`, the `prf-NNNN` id scheme, the
> `record_count` equality, and the `target_id` linkage hold *by construction*.

```python
import os
from itertools import cycle

import lmql

from app.core.schemas import ProfileDataset

CHARTER = """You are the Synthetic-Data Agent (Profiler-AG) for a controlled phishing-simulation generator.

**Few‑Shot Learning Principle** (cf. OpenAI, 2020):
You are a few‑shot learner – your generation quality improves dramatically when given clear, structured examples.
Follow the pattern, style, and level of detail from the examples below **exactly**.
Never collect or use real data; every recipient, role, and attribute must be **fully synthetic**. You consume the `SyntheticTargetSet` produced by Recon-AG and emit a `ProfileDataset`.

---
### Few‑Shot Examples

**Example 1 (target: fantazylabz.tech, sector: technology)**
```json
{
  "campaign_id": "q3-awareness-2026",
  "source": "synthetic",
  "format": "json",
  "record_count": 2,
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
    },
    {
      "profile_id": "prf-0002",
      "target_id": "tgt-0001",
      "recipient": {
        "email": "bruno.costa@fantazylabz.tech",
        "full_name": "Bruno Costa",
        "role": "IT Support Specialist",
        "department": "IT"
      },
      "attributes": {
        "seniority": "junior",
        "devices": ["windows", "android"],
        "language": "en",
        "language_patterns": ["casual", "technical"]
      },
      "labels": { "segment": "it", "risk_tier": "low" }
    }
  ]
}
```

**Example 2 (target: paystream-finance.eu, sector: fintech)**
```json
{
  "campaign_id": "emea-redteam-2026-11",
  "source": "synthetic",
  "format": "json",
  "record_count": 1,
  "profiles": [
    {
      "profile_id": "prf-0001",
      "target_id": "tgt-0003",
      "recipient": {
        "email": "l.moreau@paystream-finance.eu",
        "full_name": "Louise Moreau",
        "role": "Treasury Manager",
        "department": "Finance"
      },
      "attributes": {
        "seniority": "senior",
        "devices": ["macos", "ios"],
        "language": "fr",
        "language_patterns": ["formal"]
      },
      "labels": { "segment": "finance", "risk_tier": "high" }
    }
  ]
}
```

---

**Your Task:**
1. Receive a validated `SyntheticTargetSet` (targets with `target_id` and `synthetic_domain`) plus a requested profile `count`.
2. Generate `count` synthetic recipient profiles, each tied to an existing `target_id`, with a plausible email on that target's domain, name, role, and department.
3. Assign realistic `attributes` (seniority, devices, language, language_patterns) and useful `labels` (e.g. segment, risk_tier).
4. Use sequential `prf-NNNN` ids, set `source: "synthetic"`, and make `record_count` equal the number of profiles.
5. Output a single valid `ProfileDataset` JSON object matching the schema.
6. Do **not** reuse real people; every identity is fabricated from internal knowledge and the examples."""


@lmql.query
def profiler_ag(
    mission_config: dict, target_set: dict, profiles_per_target: int = 2
) -> ProfileDataset:
    targets = target_set["targets"]
    total = len(targets) * profiles_per_target
    target_summary = "\n".join(
        f"- {t['target_id']}: {t['synthetic_domain']}" for t in targets
    )
    '''lmql
    argmax
        """system:
        {CHARTER}

        user: The synthetic targets to profile:
        {target_summary}
        Generate {total} profiles, cycling through the targets in order. For each profile, output:
        - full name: [NAME]
        - role: [ROLE]
        - department: [DEPARTMENT]
        - seniority: [SENIORITY]
        - devices (comma-separated): [DEVICES]
        - language (BCP-47-ish, e.g. en or es-MX): [LANGUAGE]
        - language patterns (comma-separated): [PATTERNS]
        """
    from
        lmql.model(os.environ.get("LMQL_MODEL", "openai/gpt-4o"))
    where
        all(len(n.strip()) > 0 for n in NAME)
        and all(len(r.strip()) > 0 for r in ROLE)
        and all(len(d.strip()) > 0 for d in DEPARTMENT)
        and all(len(s.strip()) > 0 for s in SENIORITY)
        and all(REGEX(l, r"^[a-z]{2}(-[A-Z]{2})?$") for l in LANGUAGE)
    '''
    profiles = []
    for i, target in zip(range(total), cycle(targets)):
        name = NAME[i].strip()
        profiles.append(
            {
                "profile_id": f"prf-{i+1:04d}",  # by construction — sequential ids
                "target_id": target["target_id"],  # by construction — linkage
                "recipient": {
                    "email": f"{name.lower().replace(' ', '.')}@{target['synthetic_domain']}",
                    "full_name": name,
                    "role": ROLE[i].strip(),
                    "department": DEPARTMENT[i].strip(),
                },
                "attributes": {
                    "seniority": SENIORITY[i].strip(),
                    "devices": [d.strip() for d in DEVICES[i].split(",") if d.strip()],
                    "language": LANGUAGE[i].strip(),
                    "language_patterns": [
                        p.strip() for p in PATTERNS[i].split(",") if p.strip()
                    ],
                },
                "labels": {
                    "segment": DEPARTMENT[i].strip().lower(),
                    "risk_tier": "medium",
                },
            }
        )
    return ProfileDataset.model_validate(
        {
            "campaign_id": mission_config["campaign_id"],
            "source": "synthetic",  # by construction — the model never emits this
            "format": "json",
            "record_count": len(profiles),  # by construction — equality guaranteed
            "profiles": profiles,
        }
    )
```
