"""CLI: run Generator-AG standalone.

    python -m generator_agent.run [options]

With no ``--mission``, a demo ``MissionConfig`` (authorized, synthetic,
two model families, seed 42) is built inline and the recipient is taken from
``org/fantazylabz_org.json`` (first non-executive employee, or ``--recipient-id
N``). The only external requirement is a model: set ``LMQL_MODEL`` (default
``openai/gpt-4o``) and the provider's API key env var.

Output is written to ``data/<campaign_id>/generated_campaign.json``. With
``--send`` it is then delivered to a local MailHog SMTP sink (``docker compose
up -d``) in one shot — generate and send.
"""

from __future__ import annotations

import argparse
import asyncio
import json
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
ORG_FILE = REPO_ROOT / "org" / "fantazylabz_org.json"

DEMO_MISSION = {
    "campaign_id": "q3-awareness-2026",
    "authorized": True,
    "objective": "security-awareness-training",
    "scope": {
        "region": "latam",
        "sector": "technology",
        "volume": 5,
        "duration_days": 14,
    },
    "constraints": {
        "synthetic_data_only": True,
        "channels": ["email", "sms"],
        "max_messages_per_persona": 3,
    },
    "model_policy": {
        "models": [
            {"family": "anthropic", "name": "claude-opus-5", "adapter_version": "1.0"},
            {"family": "openai", "name": "gpt-4.1", "adapter_version": "1.0"},
        ]
    },
    "reproducibility": {"seed": 42, "deterministic": True},
    "ethics": {"consent_reference": "IRB-2026-014", "isolated_environment": True},
}


def _load_org() -> dict:
    return json.loads(ORG_FILE.read_text(encoding="utf-8"))


def _demo_profile(org: dict, recipient_id: int | None) -> dict:
    employees = org["employees"]
    employee = (
        next(e for e in employees if e["id"] == recipient_id)
        if recipient_id is not None
        else next(e for e in employees if e["level"] != 1)
    )
    return {
        "profile_id": f"prf-{employee['id']:04d}",
        "target_id": "tgt-0001",
        "recipient": {
            "email": employee["email"],
            "full_name": employee["name"],
            "role": employee["position"],
            "department": employee["department"],
        },
        "attributes": {
            "seniority": "senior",
            "devices": ["windows"],
            "language": "en",
            "language_patterns": ["formal"],
        },
        "labels": {"segment": employee["department"].lower(), "risk_tier": "medium"},
    }


async def _generate(args: argparse.Namespace) -> None:
    from generator_agent.agent import generator_ag  # lazy: needs lmql installed

    mission = (
        json.loads(Path(args.mission).read_text(encoding="utf-8"))
        if args.mission
        else DEMO_MISSION
    )
    profile = _demo_profile(_load_org(), args.recipient_id)

    print(
        f"Generator-AG: campaign={mission['campaign_id']} "
        f"recipient={profile['recipient']['full_name']} "
        f"pretext={args.pretext} tone={args.tone} difficulty={args.difficulty}"
    )
    campaign = await generator_ag(
        mission, profile, args.pretext, args.tone, args.difficulty
    )

    out = Path(args.output or f"data/{mission['campaign_id']}/generated_campaign.json")
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(campaign.model_dump_json(indent=2), encoding="utf-8")
    print(f"saved: {out}")
    print(
        f"persona: {campaign.persona.display_name} <{campaign.persona.email}> — "
        f"{len(campaign.messages)} messages"
    )

    if args.send:
        from generator_agent.send import send_campaign  # deliver to the SMTP sink

        to_addr = profile["recipient"]["email"]
        try:
            n = send_campaign(str(out), to_addr, args.smtp_host, args.smtp_port)
        except ConnectionRefusedError:
            raise SystemExit(
                f"no SMTP sink at {args.smtp_host}:{args.smtp_port} — "
                "start MailHog: docker compose up -d"
            )
        print(f"delivered {n} messages — open http://localhost:8025")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--mission", help="path to a mission_config.json")
    parser.add_argument("--recipient-id", type=int, help="org employee id to target")
    parser.add_argument("--pretext", default="executive_request")
    parser.add_argument("--tone", default="urgent")
    parser.add_argument("--difficulty", default="medium")
    parser.add_argument("--output")
    parser.add_argument(
        "--send", action="store_true", help="also deliver the campaign to MailHog"
    )
    parser.add_argument("--smtp-host", default="localhost")
    parser.add_argument("--smtp-port", type=int, default=1025)
    asyncio.run(_generate(parser.parse_args()))


if __name__ == "__main__":
    main()
