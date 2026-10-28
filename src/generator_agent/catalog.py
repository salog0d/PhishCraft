"""Unified persona/recipient catalog: 12 internal + external BEC personas.

Role split, by construction:
- A catalog entry selected by id is a simulation **target** (the recipient).
- The **persona** — the identity a message appears to come from — is never
  invented by the model and never hardcoded in prompt examples. It is derived
  deterministically from the ``(pretext, recipient)`` pair by ``persona_for``:
  org-chart lookups for internal pretexts (executive_request -> the recipient's
  manager), the internal service desk for IT pretexts, and the external
  personas (supplier / carrier / bank) for BEC pretexts.
"""

from __future__ import annotations

import json
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent.parent
ORG_FILE = REPO_ROOT / "org" / "fantazylabz_org.json"
EXT_FILE = REPO_ROOT / "org" / "external_personas.json"

# Internal aliases that are not people (deterministic impersonation sources).
_HELP_DESK = {
    "display_name": "IT Service Desk",
    "email": "helpdesk@fantazylabz.tech",
    "role": "IT Service Desk",
}

_PEOPLE_OPS = {
    "display_name": "People Operations",
    "email": "peopleops@fantazylabz.tech",
    "role": "People Operations",
}

# Org level -> coarse seniority label for the profile attributes.
SENIORITY_BY_LEVEL = {
    1: "senior",
    2: "senior",
    3: "mid",
    4: "mid",
    5: "junior",
}

# Fallbacks used when a recipient has no manager (e.g. the CEO) — data-backed
# identities from the org chart, not free-form strings.
_FALLBACK_EXECUTIVE = "Sofia Reyes"      # CFO — asks for sign-offs
_FALLBACK_TOP = "Elena Marchetti"        # CEO — shares documents / last resort


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
            "level": e["level"],
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
            "level": None,
            "supports_pretexts": p["supports_pretexts"],
        }
        for p in json.loads(EXT_FILE.read_text(encoding="utf-8"))["personas"]
    ]
    return internal + external


def _org_employees() -> dict[str, dict]:
    return {
        str(e["id"]): e
        for e in json.loads(ORG_FILE.read_text(encoding="utf-8"))["employees"]
    }


def _external_personas() -> list[dict]:
    return json.loads(EXT_FILE.read_text(encoding="utf-8"))["personas"]


def _employee_persona(entry: dict) -> dict:
    return {
        "display_name": entry["name"],
        "email": entry["email"],
        "role": entry["position"],
    }


def _employee_named(name: str) -> dict:
    for entry in _org_employees().values():
        if entry["name"] == name:
            return entry
    raise KeyError(f"org chart has no employee named '{name}'")


def _manager_of(recipient_id: str) -> dict | None:
    """The recipient's direct manager from the org chart, as a persona."""
    entry = _org_employees().get(recipient_id)
    if not entry or not entry.get("reports_to"):
        return None
    manager = _org_employees().get(str(entry["reports_to"]["id"]))
    return _employee_persona(manager) if manager else None


def _external_for_pretext(pretext: str) -> dict | None:
    """The first external persona whose ``supports_pretexts`` lists the pretext."""
    for p in _external_personas():
        if pretext in p.get("supports_pretexts", []):
            return {
                "display_name": p["display_name"],
                "email": p["email"],
                "role": None,
            }
    return None


def persona_for(pretext: str, recipient_id) -> dict:
    """Deterministic impersonated identity for a ``(pretext, recipient)`` pair.

    - ``executive_request`` / ``shared_document`` -> the recipient's direct
      manager from the org chart (the CFO for a managerless executive).
    - ``hr_notice`` -> the People Operations department alias.
    - ``it_support`` / ``password_reset`` -> the internal IT service desk.
    - ``invoice_payment`` / ``package_delivery`` / ``account_suspension`` ->
      the external persona supporting the pretext (supplier / carrier / bank).
    - A persona never impersonates its own recipient: on a collision it falls
      back to the service desk (internal target) or the CEO (external target).
    """
    catalog = {str(p["id"]): p for p in load_catalog()}
    recipient = catalog.get(str(recipient_id))
    if recipient is None:
        raise KeyError(f"no catalog entry for id '{recipient_id}'")

    if pretext in ("executive_request", "shared_document"):
        candidate = _manager_of(str(recipient_id))
        if candidate is None:
            candidate = _employee_persona(_employee_named(_FALLBACK_EXECUTIVE))
    elif pretext == "hr_notice":
        candidate = dict(_PEOPLE_OPS)
    elif pretext in ("it_support", "password_reset"):
        candidate = dict(_HELP_DESK)
    elif pretext in ("invoice_payment", "package_delivery", "account_suspension"):
        candidate = _external_for_pretext(pretext) or dict(_HELP_DESK)
    else:
        candidate = _manager_of(str(recipient_id)) or _employee_persona(
            _employee_named(_FALLBACK_TOP)
        )

    if str(candidate["email"]).lower() == str(recipient["email"]).lower():
        candidate = (
            dict(_HELP_DESK)
            if recipient["class"] == "internal"
            else _employee_persona(_employee_named(_FALLBACK_TOP))
        )
    return candidate


def profile_for(persona_id, pretext: str | None = None) -> dict:
    """Build a generator profile dict for one catalog entry (the target).

    With ``pretext`` given, the impersonated persona is derived from the
    ``(pretext, target)`` pair and included as ``profile["persona"]`` — the
    value the deterministic assembler stamps into every message sender.
    """
    p = next(p for p in load_catalog() if str(p["id"]) == str(persona_id))
    profile = {
        "profile_id": f"prf-{persona_id}",
        "target_id": f"tgt-{persona_id}",
        "recipient": {
            "email": p["email"],
            "full_name": p["display_name"],
            "role": p["role"],
            "department": p["department"],
        },
        "attributes": {
            "seniority": SENIORITY_BY_LEVEL.get(p["level"]),
            "devices": ["windows"],
            "language": "en",
            "language_patterns": ["formal"],
        },
        "labels": {"segment": str(p["org_type"]), "risk_tier": "medium"},
    }
    if pretext is not None:
        profile["persona"] = persona_for(pretext, persona_id)
    return profile
