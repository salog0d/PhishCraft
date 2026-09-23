"""Offline tests for the model-free Generator-AG assembly (no lmql, no key).

``assemble_campaign`` is where the generator's coherence rules are enforced by
construction; these tests pin that process down without a model call.
"""

from hashlib import sha256

import pytest

from generator_agent.assemble import (
    BINDING_KEYS,
    assemble_campaign,
    rendered_prompt,
)

MISSION = {
    "campaign_id": "q3-awareness-2026",
    "model_policy": {
        "models": [
            {"family": "anthropic", "name": "claude-opus-5", "adapter_version": "1.0"},
            {"family": "openai", "name": "gpt-4.1", "adapter_version": "1.0"},
        ]
    },
    "reproducibility": {"seed": 42},
}

PROFILE = {
    "recipient": {
        "email": "rebecca.stern@fantazylabz.tech",
        "full_name": "Rebecca Stern",
        "role": "Staff Accountant",
        "department": "Finance",
    }
}

BINDINGS = {
    "PERSONA_NAME": "Elena Marchetti",
    "PERSONA_ROLE": "CEO",
    "PERSONA_EMAIL": "ceo@fantazylabz.tech",
    "EMAIL_SUBJECT": "Quick approval needed before EOD",
    "EMAIL_BODY": "Rebecca, please review the Q3 summary and confirm.",
    "EMAIL_TIME": "2026-08-20T09:00:00Z",
    "SMS_BODY": "Hi Rebecca, did you get my email? Action needed before EOD.",
    "SMS_TIME": "2026-08-20T10:15:00Z",
}

CAMPAIGN = assemble_campaign(BINDINGS, MISSION, PROFILE, "executive_request", "urgent", "medium")


def test_persona_is_stamped_into_every_sender():
    for message in CAMPAIGN.messages:
        assert message.sender.display_name == "Elena Marchetti"
        assert str(message.sender.from_address) == "ceo@fantazylabz.tech"


def test_channel_shaping_is_structural():
    email, sms = CAMPAIGN.messages
    assert email.channel.value == "email" and email.subject
    assert sms.channel.value == "sms" and sms.subject is None


def test_cross_channel_reference_is_wired_by_the_program():
    email, sms = CAMPAIGN.messages
    assert email.references == []
    assert sms.references == ["msg-0001"]


def test_followup_is_scheduled_after_the_email():
    email, sms = CAMPAIGN.messages
    assert sms.scheduled_at > email.scheduled_at


def test_provenance_hash_matches_the_rendered_prompt():
    expected = sha256(
        rendered_prompt(MISSION, PROFILE, "executive_request", "urgent", "medium").encode()
    ).hexdigest()
    for message in CAMPAIGN.messages:
        assert message.provenance.prompt_hash == expected
        assert message.provenance.params.seed == 42


def test_missing_bindings_are_rejected():
    with pytest.raises(ValueError, match="missing keys"):
        assemble_campaign({}, MISSION, PROFILE, "it_support", "neutral", "easy")


def test_bindings_contract_lists_all_eight_variables():
    assert set(BINDING_KEYS) == set(BINDINGS)


def test_assembly_is_deterministic_with_fixed_clock_and_schedule():
    """Same inputs + fixed clock/schedule -> byte-identical output (W1)."""
    from datetime import datetime, timezone

    fixed = datetime(2026, 8, 20, 9, 0, tzinfo=timezone.utc)
    schedule = ("2026-08-20T09:00:00Z", "2026-08-20T10:15:00Z")
    first = assemble_campaign(
        BINDINGS, MISSION, PROFILE, "executive_request", "urgent", "medium",
        generated_at=fixed, scheduled=schedule,
    )
    second = assemble_campaign(
        BINDINGS, MISSION, PROFILE, "executive_request", "urgent", "medium",
        generated_at=fixed, scheduled=schedule,
    )
    assert first.model_dump() == second.model_dump()


def test_tracking_token_is_seed_derived_not_random():
    """The landing URL token must come from the seed, not uuid4 (W1)."""
    from generator_agent.assemble import tracking_token

    assert tracking_token("q3-awareness-2026", 42) == \
        tracking_token("q3-awareness-2026", 42)
    assert tracking_token("q3-awareness-2026", 42) != \
        tracking_token("q3-awareness-2026", 43)
    for message in CAMPAIGN.messages:
        url = str(message.call_to_action.landing_url)
        assert url.endswith("/t/" + tracking_token("q3-awareness-2026", 42))
