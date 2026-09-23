"""CLI: run the ADK campaign pipeline end-to-end.

    python -m generator_agent.run [options]

Loads a mission config from ``config/q3-awareness-2026.mission.json`` (or
``--mission``), picks a recipient from the persona catalog, and drives the ADK
pipeline (``agent.pipeline``): the LLM writes content, the deterministic
assembler builds the ``GeneratedCampaign``, and the deterministic validator
emits the ``CoherenceReport``.

Output is written to ``data/<campaign_id>/generated_campaign.json`` and
``data/<campaign_id>/coherence_report.json``. With ``--send`` the campaign is
then delivered to a local MailHog SMTP sink (``docker compose up -d``).
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from agent.driver import run_pipeline
from generator_agent.catalog import load_catalog, profile_for

REPO_ROOT = Path(__file__).resolve().parent.parent
DEFAULT_MISSION = REPO_ROOT / "config" / "q3-awareness-2026.mission.json"


def _load_mission(path: str | None) -> dict:
    return json.loads(Path(path or DEFAULT_MISSION).read_text(encoding="utf-8"))


def _default_recipient_id() -> str:
    internal = [p for p in load_catalog() if p["class"] == "internal"]
    return str(next(p for p in internal if p["level"] != 1)["id"])


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--mission", help="path to a mission_config.json")
    parser.add_argument("--recipient-id", help="catalog persona id to target")
    parser.add_argument("--pretext", default="executive_request")
    parser.add_argument("--tone", default="urgent")
    parser.add_argument("--difficulty", default="medium")
    parser.add_argument("--language", default="en")
    parser.add_argument("--seed", type=int, default=42)
    parser.add_argument("--start-at", default="2026-08-20T09:00:00Z")
    parser.add_argument("--followup-minutes", type=int, default=75)
    parser.add_argument("--model", help="e.g. deepseek/deepseek-chat (env ADK_MODEL)")
    parser.add_argument("--output")
    parser.add_argument(
        "--send", action="store_true", help="also deliver the campaign to MailHog"
    )
    parser.add_argument("--smtp-host", default="localhost")
    parser.add_argument("--smtp-port", type=int, default=1025)
    args = parser.parse_args()

    mission = _load_mission(args.mission)
    recipient_id = args.recipient_id or _default_recipient_id()
    profile = profile_for(recipient_id)
    spec = {
        "spec_id": "cli",
        "campaign_id": mission["campaign_id"],
        "pretext": args.pretext,
        "tone": args.tone,
        "difficulty": args.difficulty,
        "language": args.language,
        "seed": args.seed,
        "model": (
            {"family": "deepseek", "name": args.model.split("/", 1)[-1],
             "adapter_version": "1.0"}
            if args.model
            else mission["model_policy"]["models"][0]
        ),
        "recipient_id": recipient_id,
        "start_at": args.start_at,
        "followup_minutes": args.followup_minutes,
    }

    print(
        f"pipeline: campaign={mission['campaign_id']} "
        f"recipient={profile['recipient']['full_name']} "
        f"pretext={args.pretext} tone={args.tone} difficulty={args.difficulty} "
        f"seed={args.seed}"
    )
    campaign, report = run_pipeline(spec, mission, profile)

    out = Path(args.output or f"data/{mission['campaign_id']}")
    out.mkdir(parents=True, exist_ok=True)
    (out / "generated_campaign.json").write_text(
        campaign.model_dump_json(indent=2), encoding="utf-8"
    )
    (out / "coherence_report.json").write_text(
        report.model_dump_json(indent=2), encoding="utf-8"
    )
    print(f"saved: {out / 'generated_campaign.json'}")
    print(f"saved: {out / 'coherence_report.json'}")
    print(
        f"persona: {campaign.persona.display_name} <{campaign.persona.email}> — "
        f"{len(campaign.messages)} messages"
    )
    print(
        f"validator: all_passed={report.all_passed} "
        f"({', '.join(r.check.value + '=' + str(r.passed).lower() for r in report.results)})"
    )

    if args.send:
        from generator_agent.send import send_campaign  # deliver to the SMTP sink

        to_addr = profile["recipient"]["email"]
        try:
            n = send_campaign(str(out / "generated_campaign.json"), to_addr,
                              args.smtp_host, args.smtp_port)
        except ConnectionRefusedError:
            raise SystemExit(
                f"no SMTP sink at {args.smtp_host}:{args.smtp_port} — "
                "start MailHog: docker compose up -d"
            )
        print(f"delivered {n} messages — open http://localhost:8025")


if __name__ == "__main__":
    main()
