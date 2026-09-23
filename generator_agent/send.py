"""Send a generated campaign to a local SMTP sink (MailHog) — end-to-end test.

    docker compose up -d            # MailHog: SMTP :1025, web UI http://localhost:8025
    python -m generator_agent.run   # writes data/<id>/generated_campaign.json
    python -m generator_agent.send  # delivers it; open http://localhost:8025

Uses stdlib smtplib against MailHog's unauthenticated SMTP on :1025. Email
messages go out as email; SMS messages go out as email tagged ``[SMS]`` (MailHog
is email-only) so the whole campaign lands in one inbox. The campaign JSON has
no recipient, so ``--to`` supplies it (default: first non-exec org employee,
matching generator_agent.run's demo target).
"""

from __future__ import annotations

import argparse
import json
import smtplib
from email.message import EmailMessage
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent


def _default_to() -> str:
    from generator_agent.catalog import load_catalog

    internal = [p for p in load_catalog() if p["class"] == "internal"]
    return next(p for p in internal if p["level"] != 1)["email"]


def build_email(msg: dict, to_addr: str) -> EmailMessage:
    """One campaign message -> an RFC-5322 email; SMS is tagged in the subject."""
    email = EmailMessage()
    sender = msg["sender"]
    email["From"] = f'{sender["display_name"]} <{sender["from_address"]}>'
    email["To"] = to_addr
    if msg["channel"] == "email":
        email["Subject"] = msg["subject"]
    else:  # sms carries no subject; surface the channel so it's legible in the inbox
        email["Subject"] = f'[SMS] {msg["body"][:40]}'
    email["X-Campaign-Channel"] = msg["channel"]
    email["X-Message-Id"] = msg["message_id"]
    body = msg["body"]
    cta = msg.get("call_to_action") or {}
    if cta.get("landing_url"):
        body += f'\n\n{cta.get("button_label") or "Open"}: {cta["landing_url"]}'
    email.set_content(body)
    return email


def send_campaign(path: str, to_addr: str, host: str, port: int) -> int:
    campaign = json.loads(Path(path).read_text(encoding="utf-8"))
    messages = campaign["messages"]
    with smtplib.SMTP(host, port) as smtp:
        for m in messages:
            smtp.send_message(build_email(m, to_addr))
            print(f'sent {m["message_id"]} ({m["channel"]}) -> {to_addr}')
    return len(messages)


def main() -> None:
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument(
        "--campaign",
        default="data/q3-awareness-2026/generated_campaign.json",
        help="path to a generated_campaign.json",
    )
    p.add_argument("--to", help="recipient address (default: demo org target)")
    p.add_argument("--host", default="localhost")
    p.add_argument("--port", type=int, default=1025)
    args = p.parse_args()
    to_addr = args.to or _default_to()
    try:
        n = send_campaign(args.campaign, to_addr, args.host, args.port)
    except ConnectionRefusedError:
        raise SystemExit(
            f"no SMTP sink at {args.host}:{args.port} — start MailHog: docker compose up -d"
        )
    print(f"delivered {n} messages — open http://localhost:8025")


if __name__ == "__main__":
    main()
