"""Offline tests for the driver-level self-refinement loop (A).

The pure helpers under test live in ``agent.driver``; importing the module
pulls in google-adk (installed) but no model call happens here. The loop
itself is exercised end-to-end by the measurement harness.
"""

from agent.driver import build_refinement, raw_link_violations
from generator_agent.assemble import assemble_campaign

MISSION = {
    "campaign_id": "q3-awareness-2026",
    "model_policy": {
        "models": [
            {"family": "anthropic", "name": "claude-opus-5", "adapter_version": "1.0"},
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

TOKEN = "8b9dc310f705"  # sha256("q3-awareness-2026:42")[:12]


def _campaign_with(sms_body: str):
    return assemble_campaign(
        dict(BINDINGS, SMS_BODY=sms_body),
        MISSION, PROFILE, "executive_request", "urgent", "medium",
    )


def test_raw_link_violations_is_zero_for_clean_prose():
    campaign = _campaign_with("Hi Rebecca, action needed before EOD.")
    assert raw_link_violations(campaign) == 0


def test_raw_link_violations_counts_stale_tokens_across_messages():
    bindings = dict(
        BINDINGS,
        EMAIL_BODY="Open sim.fantazylabz.tech/t/abc123 now",
        SMS_BODY="Hi Rebecca - link: sim.fantazylabz.tech/t/abc123",
    )
    campaign = assemble_campaign(
        bindings, MISSION, PROFILE, "executive_request", "urgent", "medium"
    )
    assert raw_link_violations(campaign) == 2


def test_build_refinement_names_field_stale_and_correct_token():
    campaign = _campaign_with("link: sim.fantazylabz.tech/t/abc123")
    critique = build_refinement(campaign)
    assert "sms_body" in critique
    assert "'abc123'" in critique
    assert f"'{TOKEN}'" in critique


def test_build_refinement_restates_the_placeholder_convention():
    campaign = _campaign_with("link: sim.fantazylabz.tech/t/abc123")
    assert "{{cta-link}}" in build_refinement(campaign)


def test_build_refinement_lists_every_fix():
    campaign = _campaign_with(
        "a sim.fantazylabz.tech/t/abc123 and sim.fantazylabz.tech/t/def456"
    )
    critique = build_refinement(campaign)
    assert critique.count("you wrote") == 2
    assert "'def456'" in critique


def test_adk_instruction_survives_state_injection():
    """Regression: the placeholder must be identifier-invalid.

    ADK renders the LlmAgent instruction with the regex ``{+[^{}]*}+`` and
    raises ``KeyError: Context variable not found`` when the inner text is a
    valid Python identifier (``cta_link`` was; ``cta-link`` is not). No brace
    group in the instruction may therefore carry a valid identifier.
    """
    import re

    from agent.pipeline import generator_content_agent

    instruction = generator_content_agent.instruction
    pattern = re.compile(r"{+[^{}]*}+")
    for match in pattern.finditer(instruction):
        name = match.group().lstrip("{").rstrip("}").strip()
        assert not name.isidentifier(), (
            f"instruction brace group {match.group()!r} would be read as ADK "
            f"context variable '{name}'"
        )
    assert "{{cta-link}}" in instruction


def test_findings_summary_extracts_structural_issues():
    """The critic receives coherence failures + stage-direction/meta-bleed
    findings, and ignores benign/clean reports."""
    from app.core.schemas import (
        CoherenceCheckResult,
        CoherenceReport,
    )
    from quality_agent.scan import scan_campaign
    from agent.critic import findings_summary

    campaign = _campaign_with("click [HOSTAGE VOICE] the {{cta-link}}")
    quality = scan_campaign(campaign, spec={"pretext": "executive_request"})
    failing = CoherenceReport(
        campaign_id=campaign.campaign_id,
        results=[
            CoherenceCheckResult(check="persona_identity", passed=True),
            CoherenceCheckResult(check="timing", passed=True),
            CoherenceCheckResult(check="cross_channel_reference", passed=True),
            CoherenceCheckResult(check="link_consistency", passed=False,
                                 detail="body token not in CTA"),
            CoherenceCheckResult(check="sender_recipient", passed=True),
        ],
        all_passed=False,
    )
    problems = findings_summary(campaign, failing, quality)
    assert any(p.startswith("[coherence:link_consistency]") for p in problems)
    assert any(p.startswith("[stage_direction]") for p in problems)


def test_findings_summary_is_empty_when_campaign_is_clean():
    from app.core.schemas import CoherenceCheckResult, CoherenceReport
    from quality_agent.scan import scan_campaign
    from agent.critic import findings_summary

    campaign = assemble_campaign(
        dict(
            BINDINGS,
            EMAIL_SUBJECT="The quarterly review is ready in the portal",
            EMAIL_BODY="The third-quarter statement is attached to your "
                       "account record for reconciliation.",
            SMS_BODY="Portal sync complete — a new line item was added late "
                     "yesterday and is awaiting your review.",
        ),
        MISSION, PROFILE, "executive_request", "urgent", "medium",
    )
    quality = scan_campaign(campaign, spec={"pretext": "executive_request"})
    clean = CoherenceReport(
        campaign_id=campaign.campaign_id,
        results=[
            CoherenceCheckResult(check=c, passed=True)
            for c in ("persona_identity", "timing", "cross_channel_reference",
                      "link_consistency", "sender_recipient")
        ],
        all_passed=True,
    )
    assert findings_summary(campaign, clean, quality) == []
