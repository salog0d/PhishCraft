# Recon-AG — Constrained Query (LMQL)

> Refactored per *Prompting is Programming: A Query Language for LLMs*
> (Beurer-Kellner, Fischer & Vechev, PLDI 2023). The instructions and few-shot
> examples are **unchanged**; the prompt is now a query program. Per-target
> fields are bound as constrained variables inside a loop (`domain`, `pattern`,
> `surfaces`), the `domain_pattern` is constrained to the schema's enum via
> `Distribution`, and the final `SyntheticTargetSet` is **assembled by the
> program** — so `source: "synthetic"` and the `tgt-NNNN` id scheme hold *by
> construction*. (The few-shot JSON below predates the schemas realignment and
> now guides realism only; the program emits the authoritative shape.)

```python
import os

import lmql

from app.core.schemas import SyntheticTargetSet

CHARTER = """You are the Intelligence Agent (Recon-AG) for a controlled phishing investigation.

**Few‑Shot Learning Principle** (cf. OpenAI, 2020):
You are a few‑shot learner – your generation quality improves dramatically when given clear, structured examples.
Follow the pattern, style, and level of detail from the examples below **exactly**.
Never collect or use real data; all domains, typo variants, and attack surfaces must be **fully synthetic**.

---
### Few‑Shot Examples

**Example 1 (region: emea, sector: fintech)**
```json
{
  "targets": [
    {
      "domain": "paystream-finance.eu",
      "typo_variant": "paystream-finance-eu.com",
      "sector": "fintech",
      "attack_surfaces": [
        {"service": "webmail", "url_template": "https://{domain}/mail"},
        {"service": "customer-portal", "url_template": "https://{domain}/portal/login"},
        {"service": "api", "url_template": "https://api.{domain}/v2/auth"}
      ]
    },
    {
      "domain": "swiftcapital-financial.co.uk",
      "typo_variant": "swiftcapital-financial.uk",
      "sector": "fintech",
      "attack_surfaces": [
        {"service": "mail", "url_template": "https://{domain}/owa"},
        {"service": "admin-panel", "url_template": "https://{domain}/admin"}
      ]
    }
  ],
  "campaign_region": "emea",
  "total_targets": 2
}
```

**Example 2 (region: apac, sector: healthcare)**
```json
{
  "targets": [
    {
      "domain": "wellnesshub-healthcare.asia",
      "typo_variant": "wellnesshub-healthcare.com",
      "sector": "healthcare",
      "attack_surfaces": [
        {"service": "patient-portal", "url_template": "https://{domain}/patient/login"},
        {"service": "api", "url_template": "https://api.{domain}/v1/records"}
      ]
    }
  ],
  "campaign_region": "apac",
  "total_targets": 1
}
```

**Example 3 (region: us, sector: technology)**
```json
{
  "targets": [
    {
      "domain": "cloudforge-tech.inc",
      "typo_variant": "cloudforge-tech.net",
      "sector": "technology",
      "attack_surfaces": [
        {"service": "sso", "url_template": "https://{domain}/sso/login"},
        {"service": "devops-dashboard", "url_template": "https://{domain}/jenkins"},
        {"service": "mail", "url_template": "https://{domain}/exchange"},
        {"service": "file-upload", "url_template": "https://{domain}/upload"}
      ]
    }
  ],
  "campaign_region": "us",
  "total_targets": 1
}
```
---

**Your Task:**
1. Receive `region`, `sector`, and `count` from the Orchestrator.
2. Generate `count` synthetic targets – each with a plausible domain, a typo variant, and a list of attack surfaces (at least 2 per target). Use the examples as templates for realism.
3. Vary domain names and surface types so they look authentic but are completely fabricated.
4. Always output a valid JSON object matching the provided schema.
5. Do **not** perform any external scanning, DNS lookups, or OSINT – everything is generated from internal knowledge and the examples."""

DOMAIN_PATTERNS = ["typosquat", "homoglyph", "subdomain", "combosquat"]
SURFACE_TYPES = ["mail_server", "login_form", "api", "portal"]


@lmql.query
def recon_ag(mission_config: dict, max_targets: int = 10) -> SyntheticTargetSet:
    target_count = min(mission_config["scope"]["volume"], max_targets)
    region = mission_config["scope"]["region"]
    sector = mission_config["scope"]["sector"]
    '''lmql
    argmax
        """system:
        {CHARTER}

        user: MissionConfig scope: region={region}, sector={sector}, requested volume={volume}. The template caps this run at {target_count} targets. For each target, produce:
        - a fabricated domain (never a real organization's)
        - one domain pattern
        - 1-2 attack surfaces, each as 'type|url' entries separated by ';' (type from mail_server, login_form, api, portal; url fabricated on the domain)
        """
        for i in range(target_count):
            """
            Target {i+1}:
            - domain: [DOMAIN]
            - pattern: [PATTERN] Distribution(PATTERN, DOMAIN_PATTERNS)
            - surfaces: [SURFACES]
            """
    from
        lmql.model(os.environ.get("LMQL_MODEL", "openai/gpt-4o"))
    where
        (target_count < 2) or len(set(DOMAIN)) == target_count
        and all("|" in s for s in SURFACES)
        and all(p in DOMAIN_PATTERNS for p in PATTERN)
    '''
    targets = []
    for i in range(target_count):
        surfaces = []
        for entry in SURFACES[i].split(";"):
            stype, _, value = entry.partition("|")
            if stype.strip() in SURFACE_TYPES and value.strip():
                surfaces.append({"type": stype.strip(), "value": value.strip()})
        targets.append(
            {
                "target_id": f"tgt-{i+1:04d}",  # by construction — sequential ids
                "synthetic_domain": DOMAIN[i].strip(),
                "domain_pattern": PATTERN[i],
                "attack_surfaces": surfaces,
            }
        )
    return SyntheticTargetSet.model_validate(
        {
            "campaign_id": mission_config["campaign_id"],
            "source": "synthetic",  # by construction — the model never emits this
            "target_count": len(targets),
            "targets": targets,
        }
    )
```
