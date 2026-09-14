"""Check the campaign-message -> email mapping (no SMTP, no network)."""

from generator_agent.send import build_email

_SENDER = {"display_name": "Elena Marchetti", "from_address": "ceo@fantazylabz.tech"}


def test_email_carries_subject_from_and_cta():
    e = build_email(
        {
            "message_id": "msg-0001",
            "channel": "email",
            "sender": _SENDER,
            "subject": "Urgent",
            "body": "hello",
            "call_to_action": {"landing_url": "https://sim.x/t/1", "button_label": "Go"},
        },
        "rajesh.kapoor@fantazylabz.tech",
    )
    assert e["To"] == "rajesh.kapoor@fantazylabz.tech"
    assert e["From"] == "Elena Marchetti <ceo@fantazylabz.tech>"
    assert e["Subject"] == "Urgent"
    assert e["X-Campaign-Channel"] == "email"
    assert "Go: https://sim.x/t/1" in e.get_content()


def test_sms_is_tagged_and_channel_labelled():
    e = build_email(
        {
            "message_id": "msg-0002",
            "channel": "sms",
            "sender": _SENDER,
            "subject": None,
            "body": "did you get my email? link: sim.x/t/1",
            "call_to_action": {"landing_url": "https://sim.x/t/1"},
        },
        "rajesh.kapoor@fantazylabz.tech",
    )
    assert e["Subject"].startswith("[SMS]")
    assert e["X-Campaign-Channel"] == "sms"
