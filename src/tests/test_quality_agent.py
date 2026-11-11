"""The post-run quality scanner: deterministic lifecycle checks (no LLM).

Covers the COVA-X-style quality pipeline added on top of the coherence
validator:

- the five generation-artifact scanners (dialogue collapse, stage direction,
  turn overflow, meta bleed, loop detection),
- the four contamination scanners (pretext, name, brand, script),
- the stage-direction stripping pass (measured on a copy),
- the automated label audit (heuristic-implied labels vs. the spec labels),
- the harness integration (every run records the scan's variables).
"""

from pathlib import Path

import pytest
from pydantic import ValidationError

from app.core.schemas import GeneratedCampaign
from quality_agent.scan import CHECK_NAMES, scan_campaign
from quality_agent.strip import strip_stage_directions
from tests.test_generator_agent import BINDINGS, MISSION, PROFILE, assemble_campaign

SPEC = {
    "spec_id": "S1",
    "pretext": "executive_request",
    "tone": "urgent",
    "difficulty": "medium",
    "language": "en",
}


def _clean_bindings() -> dict:
    bindings = dict(BINDINGS)
    bindings.update(
        {
            # v2 charter: no banned openers ("Hi"/"Dear"), no "before end of day",
            # no "confirm", no "please review". Genuinely urgent + medium so the
            # labeler still agrees with SPEC, but clean of repetition phrases.
            "EMAIL_SUBJECT": "Urgent: Q3 vendor statement requires approval today",
            "EMAIL_BODY": (
                "The third-quarter vendor statement has been posted to the "
                "portal and requires your sign-off immediately. Failure to "
                "approve delays the board meeting. A summary of the outstanding "
                "line items is attached to your account record for "
                "reconciliation. — Elena"
            ),
            "SMS_BODY": (
                "Portal sync complete — a new line item was added late yesterday "
                "and is awaiting your approval today."
            ),
        }
    )
    return bindings


def _dirty_bindings() -> dict:
    bindings = dict(BINDINGS)
    bindings.update(
        {
            "EMAIL_SUBJECT": "Action needed [EMAIL_SUBJECT] — please reset your password",
            "EMAIL_BODY": (
                "Dear Marcus, here is the message you requested: I cannot "
                "assist with illegal activity. Please review the invoice and "
                "wire the payment today.\n"
                "Please review the invoice and wire the payment today.\n"
                "— Bruno Costa"
            ),
            "SMS_BODY": (
                "Dear Marcus, here is the message you requested. Please review "
                "the invoice and wire the payment today. {{cta-link}} "
                "使用してください"
            ),
        }
    )
    return bindings


def _campaign(bindings: dict) -> GeneratedCampaign:
    return assemble_campaign(
        bindings, MISSION, PROFILE, "executive_request", "urgent", "medium"
    )


def _by_check(report):
    return {r.check: r for r in report.results}


# --------------------------------------------------------------------------- #
# The clean campaign passes everything
# --------------------------------------------------------------------------- #


def test_clean_campaign_has_no_findings_and_ok_labels():
    report = scan_campaign(_campaign(_clean_bindings()), spec=SPEC)
    assert report.n_flags == 0
    assert report.any_flag is False
    assert all(r.passed for r in report.results)
    assert set(_by_check(report)) == set(CHECK_NAMES)
    assert report.label_audit.available is True
    assert report.label_audit.mismatches == []
    assert report.label_audit.statuses == {
        "pretext": "ok", "tone": "ok", "difficulty": "ok"
    }
    assert report.strip_stats.affected_messages == 0


# --------------------------------------------------------------------------- #
# The dirty campaign flags every artifact family
# --------------------------------------------------------------------------- #


def test_dirty_campaign_flags_generation_artifacts():
    report = scan_campaign(_campaign(_dirty_bindings()), spec=SPEC)
    by_check = _by_check(report)
    assert by_check["stage_direction"].count >= 2  # [EMAIL_SUBJECT] + {{cta-link}}
    assert by_check["meta_bleed"].count >= 2       # "here is the message" + refusal
    assert by_check["dialogue_collapse"].count >= 2  # "Dear Marcus" + "— Bruno Costa"
    assert report.any_flag is True


def test_greeting_to_wrong_name_flags_dialogue_collapse():
    """A greeting to a name outside the roster (few-shot leak, e.g. 'Alex')
    must flag dialogue_collapse, and a correct recipient greeting must not."""
    from quality_agent.artifacts import scan_dialogue_collapse

    names = ("Rebecca Stern", "Samuel Adeyemi", "Gregory Whitfield")
    leaked = scan_dialogue_collapse(
        "Good morning Alex, the vendor statement is ready.",
        field="email_body",
        persona_name="Samuel Adeyemi",
        recipient_name="Rebecca Stern",
        known_names=names,
    )
    assert any("'Alex'" in f.detail for f in leaked)

    ok = scan_dialogue_collapse(
        "Good morning Rebecca, the statement is ready.",
        field="email_body",
        persona_name="Samuel Adeyemi",
        recipient_name="Rebecca Stern",
        known_names=names,
    )
    assert ok == []


def test_dirty_campaign_flags_contamination_and_script():
    report = scan_campaign(_campaign(_dirty_bindings()), spec=SPEC)
    by_check = _by_check(report)
    # invoice/payment vocabulary inside an executive_request campaign.
    assert by_check["pretext_contamination"].passed is False
    assert any("invoice_payment" in f.detail
               for f in by_check["pretext_contamination"].findings)
    # "Marcus" is a roster name that is neither persona nor recipient.
    assert by_check["name_contamination"].passed is False
    assert any("Marcus" in f.detail
               for f in by_check["name_contamination"].findings)
    # Non-Latin script in the SMS body.
    assert by_check["script_contamination"].passed is False


def test_dirty_campaign_label_audit_reports_mismatches():
    report = scan_campaign(_campaign(_dirty_bindings()), spec=SPEC)
    audit = report.label_audit
    assert audit.available is True
    # Invoice vocabulary outvotes executive_request vocabulary; the friendly
    # "Dear" opening and the hard threats outvote the urgent/medium spec.
    assert "pretext" in audit.mismatches
    assert audit.statuses["pretext"] == "mismatch"


def test_strip_pass_is_measured_but_not_applied():
    campaign = _campaign(_dirty_bindings())
    original = campaign.messages[1].body
    report = scan_campaign(campaign, spec=SPEC)
    assert report.strip_stats.affected_messages >= 1
    assert report.strip_stats.stripped_chars > 0
    # Evidence preserved: the delivered artifact is untouched by the scan.
    assert campaign.messages[1].body == original


# --------------------------------------------------------------------------- #
# Stage-direction stripping (unit level)
# --------------------------------------------------------------------------- #


@pytest.mark.parametrize(
    "text,expected",
    [
        ("Review [EMAIL_SUBJECT] today", "Review today"),
        ("Open the link {{cta-link}} now", "Open the link now"),
        ("Click { CTA-link } please", "Click please"),
        ("(insert urgency here) act now", "act now"),
        ("[HOSTAGE VOICE]: help me", "help me"),
        (": \"Mom! Help!\"", "\"Mom! Help!\""),
        ("clean text, nothing to strip", "clean text, nothing to strip"),
    ],
)
def test_strip_stage_directions_removes_artifacts(text, expected):
    cleaned, removed = strip_stage_directions(text)
    assert cleaned == expected
    assert removed == len(text) - len(expected)


# --------------------------------------------------------------------------- #
# Labeler unit behaviour
# --------------------------------------------------------------------------- #


def test_labeler_reports_unverifiable_when_there_is_no_signal():
    from quality_agent.labels import predict_tone

    # A truly unmarked message (no urgent/friendly/authoritative/neutral cues)
    # must be unverifiable, not forced into a tone.
    campaign = _campaign(dict(
        BINDINGS,
        EMAIL_SUBJECT="Quarterly summary",
        EMAIL_BODY="The third-quarter summary is attached for your records.",
        SMS_BODY="The summary has been posted to the portal.",
    ))
    assert predict_tone(campaign) is None  # ambiguous -> unverifiable, not forced


def test_audit_without_spec_is_unavailable():
    report = scan_campaign(_campaign(_clean_bindings()))
    assert report.label_audit.available is False
    assert report.spec_id is None
    assert report.pretext is None


# --------------------------------------------------------------------------- #
# Report contract
# --------------------------------------------------------------------------- #


def test_quality_report_rejects_repeated_check_categories():
    report = scan_campaign(_campaign(_clean_bindings()), spec=SPEC)
    from app.core.schemas import QualityReport

    payload = report.model_dump()
    payload["results"].append(payload["results"][0])
    with pytest.raises(ValidationError):
        QualityReport.model_validate(payload)


def test_quality_report_declares_a_persistence_policy():
    from app.core import schemas as fc

    report = scan_campaign(_campaign(_clean_bindings()), spec=SPEC)
    policy = fc.QualityReport.PERSISTENCE
    assert policy.store == "quality-reports"
    assert policy.pii is fc.PiiClass.NONE
    assert policy.immutable is True
    assert report.PERSISTENCE is policy


# --------------------------------------------------------------------------- #
# Harness integration: every run records the scan's variables
# --------------------------------------------------------------------------- #


def test_run_spec_records_quality_variables():
    from measurement.adapters import get_adapter
    from measurement.runner import run_spec
    from measurement.specs import baseline_specs

    spec = baseline_specs()[0]  # S1: executive_request, urgent, medium
    record = run_spec(spec, get_adapter("stub"), 1, MISSION)
    assert record.status == "ok"
    assert isinstance(record.quality_flags, int)
    assert record.quality_report is not None
    assert set(record.quality_report["results"][0].keys()) >= {"check", "passed", "count"}
    # The stub's terse fixed prose is below the underdeveloped floor.
    assert "turn_overflow" in record.quality_failing


def test_reliability_payload_carries_quality_aggregates():
    from measurement.reliability import run as run_reliability

    payload = run_reliability(
        adapter_name="stub", runs=1, out="/tmp/opencode/reliability-quality-test"
    )
    for key in (
        "n_campaigns_with_quality_flags",
        "quality_flag_rate",
        "quality_finding_counts",
        "n_campaigns_with_contamination",
        "label_correction_rate",
        "label_mismatch_counts",
        "strip_affected_rate",
        "total_stripped_chars",
    ):
        assert key in payload
    row = payload["per_spec"][0]
    for key in (
        "quality_flags", "quality_failing", "contamination",
        "label_mismatches", "strip_affected_messages",
    ):
        assert key in row
    # summary.md must exist and mention the quality section.
    summary = (Path(payload["out_dir"]) / "summary.md").read_text()
    assert "Post-run quality scan" in summary


def test_quality_suite_writes_both_artifacts(tmp_path):
    from measurement.quality import run as run_quality

    payload = run_quality(adapter_name="stub", runs=1, out=tmp_path)
    assert (tmp_path / "quality.json").exists()
    summary = (tmp_path / "quality-summary.md").read_text()
    assert "Generation-artifact flag rates by check" in summary
    assert "Flag rate by pretext" in summary
    assert "Contamination scan" in summary
    assert "Automated label audit" in summary
    assert "Stage-direction stripping" in summary
    assert payload["n_runs"] == 10
