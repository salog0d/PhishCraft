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


def profile_for(persona_id) -> dict:
    """Build a generator profile dict for one catalog entry."""
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
        "attributes": {
            "seniority": "senior",
            "devices": ["windows"],
            "language": "en",
            "language_patterns": ["formal"],
        },
        "labels": {"segment": str(p["org_type"]), "risk_tier": "medium"},
    }
