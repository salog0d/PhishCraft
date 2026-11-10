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
        rendered_prompt(MISSION, PROFILE, "executive_request", "urgent", "medium",
                        seed=42).encode()
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


def test_tracking_token_varies_with_per_run_seed():
    """Regression: the per-run ``spec["seed"]`` must drive a unique token.

    Every run in the variety experiment gets seed 1000+i; the assembled
    landing URL must differ per seed rather than collapsing to the mission's
    fixed reproducibility seed.
    """
    from generator_agent.assemble import tracking_token

    def token_for(seed: int) -> str:
        campaign = assemble_campaign(
            BINDINGS, MISSION, PROFILE, "executive_request", "urgent", "medium",
            seed=seed,
        )
        tokens = {
            str(m.call_to_action.landing_url).split("/t/")[-1]
            for m in campaign.messages
        }
        assert len(tokens) == 1  # both messages share the campaign token
        return tokens.pop()

    a, b = token_for(1001), token_for(1002)
    assert a != b
    assert a == tracking_token("q3-awareness-2026", 1001)
    assert b == tracking_token("q3-awareness-2026", 1002)
    # Backward-compatible default still uses the mission seed.
    assert token_for(42) == tracking_token("q3-awareness-2026", 42)


def test_per_run_seed_is_reflected_in_prompt_hash():
    """Different seeds render different prompts, so the provenance hash differs."""
    h1 = assemble_campaign(
        BINDINGS, MISSION, PROFILE, "executive_request", "urgent", "medium",
        seed=1001,
    ).messages[0].provenance.prompt_hash
    h2 = assemble_campaign(
        BINDINGS, MISSION, PROFILE, "executive_request", "urgent", "medium",
        seed=1002,
    ).messages[0].provenance.prompt_hash
    assert h1 != h2


def test_normalize_body_links_rewrites_stale_tokens():
    """Stale tokens copied into prose are rewritten to the campaign token."""
    from generator_agent.assemble import normalize_body_links

    token = "8b9dc310f705"
    full = "Click here: https://sim.fantazylabz.tech/t/abc123 today."
    assert normalize_body_links(full, token) == \
        "Click here: https://sim.fantazylabz.tech/t/8b9dc310f705 today."
    bare = "link: sim.fantazylabz.tech/t/abc123, hurry"
    assert normalize_body_links(bare, token) == \
        "link: sim.fantazylabz.tech/t/8b9dc310f705, hurry"
    # non-tracking urls and unrelated text are untouched
    untouched = "see https://example.com/a/b and nothing else"
    assert normalize_body_links(untouched, token) == untouched


def test_fix_body_links_reports_the_stale_tokens():
    """The pre-assembler evidence: which tokens the model actually wrote."""
    from generator_agent.assemble import fix_body_links

    token = "8b9dc310f705"
    text = "see sim.fantazylabz.tech/t/abc123 and sim.fantazylabz.tech/t/abc123 again"
    fixed, replaced = fix_body_links(text, token)
    assert "abc123" not in fixed
    assert replaced == ["abc123", "abc123"]
    # correct tokens and non-tracking urls produce no replacement records
    _, replaced = fix_body_links(
        f"see sim.fantazylabz.tech/t/{token} and https://example.com/x", token
    )
    assert replaced == []


def test_expand_link_placeholders_substitutes_the_landing_url():
    """The {{cta-link}} convention expands to the real landing URL."""
    from generator_agent.assemble import expand_link_placeholders

    url = "https://sim.fantazylabz.tech/t/8b9dc310f705"
    assert expand_link_placeholders("Click {{cta-link}} now", url) == \
        f"Click {url} now"
    assert expand_link_placeholders("no link here", url) == "no link here"


def test_parse_bindings_unescapes_literal_newlines():
    """Regression: literal ``\\n`` text (qwen3:4b) becomes real line breaks.

    Some models escape line breaks inside a single-line body as ``\\n``. The
    assembler must unescape them so the delivered artifact carries actual
    newlines instead of backslash-n text a recipient would see verbatim.
    """
    from agent.assembler import parse_bindings

    raw = (
        "display name: IT Service Desk\n"
        "role: IT Service Desk\n"
        "from address: helpdesk@fantazylabz.tech\n"
        "subject: Urgent reset\n"
        "body: Hi there,\\n\\nPlease click the link below.\\n\\nThanks,\\nSupport\n"
        "scheduled at: 2026-08-20T09:00:00Z\n"
        "body: Did you get my email? See link.\\n\\n— Support\n"
        "scheduled at: 2026-08-20T09:15:00Z"
    )
    bindings = parse_bindings(raw)
    assert bindings["EMAIL_BODY"] == (
        "Hi there,\n\nPlease click the link below.\n\nThanks,\nSupport"
    )
    assert bindings["SMS_BODY"] == "Did you get my email? See link.\n\n— Support"
    assert "\\n" not in bindings["EMAIL_BODY"]
    assert "\\n" not in bindings["SMS_BODY"]


def test_placeholder_is_expanded_and_not_recorded_as_a_link_fix():
    """Writing {{cta-link}} is correct behavior — expansion is not a fix."""
    placeholder = dict(BINDINGS, SMS_BODY="Hi Rebecca, click {{cta-link}} now.")
    campaign = assemble_campaign(
        placeholder, MISSION, PROFILE, "executive_request", "urgent", "medium"
    )
    email, sms = campaign.messages
    assert sms.link_fixes == []
    assert email.link_fixes == []
    assert "8b9dc310f705" in sms.body          # the real token was substituted
    assert "{{cta-link}}" not in sms.body     # no literal placeholder survives


def test_placeholder_in_subject_is_expanded_too():
    placeholder = dict(BINDINGS, EMAIL_SUBJECT="Open {{cta-link}} before EOD")
    campaign = assemble_campaign(
        placeholder, MISSION, PROFILE, "executive_request", "urgent", "medium"
    )
    assert "8b9dc310f705" in campaign.messages[0].subject
    assert "{{cta-link}}" not in campaign.messages[0].subject


def test_user_prompt_instructs_the_placeholder_convention():
    from generator_agent.assemble import user_prompt

    prompt = user_prompt(
        MISSION, PROFILE, "executive_request", "urgent", "medium"
    )
    assert "{{cta-link}}" in prompt


def test_assemble_normalizes_a_stale_sms_link():
    """A model-written 'abc123' in the SMS body is fixed by construction."""
    stale = dict(BINDINGS, SMS_BODY=(
        "Hi Rebecca, need it today - link: sim.fantazylabz.tech/t/abc123"
    ))
    campaign = assemble_campaign(
        stale, MISSION, PROFILE, "executive_request", "urgent", "medium"
    )
    token = campaign.messages[0].call_to_action.landing_url
    assert str(token).endswith("8b9dc310f705")
    assert "abc123" not in campaign.messages[1].body
    assert "8b9dc310f705" in campaign.messages[1].body


def test_assemble_records_link_fixes_as_raw_evidence():
    """The stale-token rewrite is logged on the message (raw metric source)."""
    stale = dict(BINDINGS, SMS_BODY=(
        "Hi Rebecca, need it today - link: sim.fantazylabz.tech/t/abc123"
    ))
    campaign = assemble_campaign(
        stale, MISSION, PROFILE, "executive_request", "urgent", "medium"
    )
    email, sms = campaign.messages
    assert email.link_fixes == []  # the email bindings were clean
    assert [f.model_dump() for f in sms.link_fixes] == [
        {"field": "sms_body", "replaced_token": "abc123"}
    ]


def test_assemble_records_no_link_fixes_when_prose_is_clean():
    campaign = assemble_campaign(
        BINDINGS, MISSION, PROFILE, "executive_request", "urgent", "medium"
    )
    assert all(m.link_fixes == [] for m in campaign.messages)


# --------------------------------------------------------------------------- #
# Deterministic persona selection (catalog.persona_for + persona_override)
# --------------------------------------------------------------------------- #


def test_persona_for_executive_request_is_the_recipients_manager():
    from generator_agent.catalog import persona_for

    p = persona_for("executive_request", 41)  # Bruno -> IT Manager
    assert p["display_name"] == "Natalia Popov"
    assert p["email"] == "natalia.popov@fantazylabz.tech"
    assert p["role"] == "IT Manager"


def test_persona_for_executive_request_falls_back_for_a_managerless_exec():
    from generator_agent.catalog import persona_for

    p = persona_for("executive_request", 1)  # CEO has no reports_to -> CFO
    assert p["display_name"] == "Sofia Reyes"
    assert p["email"] == "sofia.reyes@fantazylabz.tech"


def test_persona_for_it_pretexts_is_the_service_desk():
    from generator_agent.catalog import persona_for

    for pretext in ("it_support", "password_reset"):
        p = persona_for(pretext, 41)
        assert p["email"] == "helpdesk@fantazylabz.tech"


def test_persona_for_hr_notice_is_the_people_ops_alias():
    from generator_agent.catalog import persona_for

    # The HR director herself receives HR notices from the department alias —
    # a named director would self-impersonate, so the alias avoids collisions.
    for target in (41, 16):
        p = persona_for("hr_notice", target)
        assert p["email"] == "peopleops@fantazylabz.tech"


def test_persona_for_invoice_payment_is_the_external_supplier():
    from generator_agent.catalog import persona_for

    p = persona_for("invoice_payment", 24)
    assert p["email"] == "ap@northwind-supplies.example"


def test_persona_for_account_suspension_is_the_external_bank():
    from generator_agent.catalog import persona_for

    p = persona_for("account_suspension", 40)
    assert p["email"] == "alerts@meridianbank.example"


def test_persona_for_package_delivery_is_the_external_carrier():
    from generator_agent.catalog import persona_for

    p = persona_for("package_delivery", 41)
    assert p["email"] == "notifications@swiftship.example"


def test_persona_for_bank_detail_change_is_the_external_supplier():
    from generator_agent.catalog import persona_for

    p = persona_for("bank_detail_change", 24)
    assert p["email"] == "ap@northwind-supplies.example"


def test_persona_for_attorney_impersonation_is_the_external_law_firm():
    from generator_agent.catalog import persona_for

    p = persona_for("attorney_impersonation", 3)
    assert p["email"] == "counsel@hartwellvance.example"


def test_persona_for_data_theft_and_gift_card_is_the_manager():
    from generator_agent.catalog import persona_for

    # Rebecca Stern (40) reports to Samuel Adeyemi (24).
    for pretext in ("data_theft", "gift_card"):
        p = persona_for(pretext, 40)
        assert p["email"] == "samuel.adeyemi@fantazylabz.tech"


def test_persona_for_account_compromise_and_payroll_is_the_manager():
    from generator_agent.catalog import persona_for

    for pretext in ("account_compromise", "payroll_diversion"):
        p = persona_for(pretext, 40)
        assert p["email"] == "samuel.adeyemi@fantazylabz.tech"


def test_persona_for_never_impersonates_its_own_recipient():
    from generator_agent.catalog import persona_for

    # The helpdesk aliases IT pretexts, so an IT-persona target collides with
    # an internal alias only if they shared the address; guard the fallback:
    p = persona_for("shared_document", 41)  # Bruno -> manager, not Bruno
    assert p["email"] != "bruno.costa@fantazylabz.tech"


def test_profile_for_derives_persona_and_uses_the_target_id():
    from generator_agent.catalog import profile_for

    pr = profile_for(41, "executive_request")
    assert pr["target_id"] == "tgt-41"          # not the hardcoded tgt-0001
    assert pr["attributes"]["seniority"] == "junior"  # level 5, not 'senior'
    assert pr["persona"]["display_name"] == "Natalia Popov"


def test_persona_override_stamps_the_deterministic_persona():
    """The model's echoed persona is discarded when an override is supplied."""
    override = {
        "display_name": "Natalia Popov",
        "email": "natalia.popov@fantazylabz.tech",
        "role": "IT Manager",
    }
    campaign = assemble_campaign(
        BINDINGS, MISSION, PROFILE, "executive_request", "urgent", "medium",
        persona_override=override,
    )
    assert campaign.persona.display_name == "Natalia Popov"
    for message in campaign.messages:
        assert message.sender.display_name == "Natalia Popov"
        assert str(message.sender.from_address) == "natalia.popov@fantazylabz.tech"


def test_user_prompt_carries_the_concrete_persona_when_present():
    from generator_agent.assemble import user_prompt

    prompt = user_prompt(
        MISSION, {**PROFILE, "persona": {
            "display_name": "Natalia Popov",
            "email": "natalia.popov@fantazylabz.tech",
            "role": "IT Manager",
        }},
        "executive_request", "urgent", "medium",
    )
    assert "Natalia Popov" in prompt
    assert "natalia.popov@fantazylabz.tech" in prompt
    assert "[PERSONA_NAME]" not in prompt


def test_generation_params_are_recorded_in_provenance():
    """Per-run sampling params (temperature/top_p/max_tokens) flow into the
    provenance, with the seed merged in; absent params fall back to temp 0.9.
    """
    campaign = assemble_campaign(
        BINDINGS, MISSION, PROFILE, "executive_request", "urgent", "medium",
        seed=42,
        generation_params={"temperature": 0.8, "top_p": 0.95, "max_tokens": 700},
    )
    params = campaign.messages[0].provenance.params
    assert params.temperature == 0.8
    assert params.top_p == 0.95
    assert params.max_tokens == 700
    assert params.seed == 42


def test_generation_params_default_to_temperature_point_nine():
    """No params block -> the adapter default temperature (0.9) is recorded."""
    campaign = assemble_campaign(
        BINDINGS, MISSION, PROFILE, "executive_request", "urgent", "medium",
        seed=42,
    )
    params = campaign.messages[0].provenance.params
    assert params.temperature == 0.9
    assert params.seed == 42
