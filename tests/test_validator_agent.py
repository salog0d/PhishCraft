"""The deterministic validator must catch the known failures.

Two regression fixtures pin the validator's ground truth:

- ``generated_campaign.json`` — the original cross-channel link bug
  (`abc123` vs `d6db8064874a`), caught by `link_consistency`.
- ``ceo_self_impersonation.json`` — a run where the campaign persona (the CEO)
  addresses its own recipient ("Elena, I'm finalizing… — Elena"); every
  structural check passed and only the `sender_recipient` check catches it.
  This artifact documents a gap the 4-check suite could not see.
"""

from pathlib import Path

from app.core.schemas import GeneratedCampaign
from validator_agent.validate import validate_campaign

KNOWN_BAD = Path(__file__).resolve().parent.parent / "data" / "measurements" / \
    "known-case" / "generated_campaign.json"

CEO_SELF = Path(__file__).resolve().parent.parent / "data" / "measurements" / \
    "known-case" / "ceo_self_impersonation.json"

ALL_CHECKS = {
    "persona_identity",
    "timing",
    "cross_channel_reference",
    "link_consistency",
    "sender_recipient",
}


def test_known_bad_campaign_fails_link_consistency():
    campaign = GeneratedCampaign.model_validate_json(KNOWN_BAD.read_text())
    report = validate_campaign(campaign)
    by_check = {r.check.value: r for r in report.results}
    assert set(by_check) == ALL_CHECKS
    assert by_check["link_consistency"].passed is False
    assert "abc123" in by_check["link_consistency"].detail
    assert "d6db8064874a" in by_check["link_consistency"].detail
    assert report.all_passed is False


def test_ceo_self_impersonation_fails_sender_recipient():
    """The CEO addressing herself must fail sender_recipient — and only that."""
    campaign = GeneratedCampaign.model_validate_json(CEO_SELF.read_text())
    report = validate_campaign(campaign)
    by_check = {r.check.value: r for r in report.results}
    assert set(by_check) == ALL_CHECKS
    assert by_check["sender_recipient"].passed is False
    assert "own recipient" in by_check["sender_recipient"].detail
    # Every structural check passed on this artifact — that is the gap the
    # 5th check closes.
    for check in ("persona_identity", "timing", "cross_channel_reference"):
        assert by_check[check].passed is True
    assert report.all_passed is False


def test_campaign_without_recipient_fails_sender_recipient():
    """No recipient recorded -> the separation cannot be verified -> fail."""
    campaign = GeneratedCampaign.model_validate_json(KNOWN_BAD.read_text()).model_copy(
        update={"recipient": None}
    )
    report = validate_campaign(campaign)
    by_check = {r.check.value: r for r in report.results}
    assert by_check["sender_recipient"].passed is False
    assert "cannot be verified" in by_check["sender_recipient"].detail


def test_coherent_campaign_passes_all_checks():
    from tests.test_generator_agent import CAMPAIGN  # assembled fixture

    report = validate_campaign(CAMPAIGN)
    assert report.all_passed is True
    assert len(report.results) == 5
    by_check = {r.check.value: r for r in report.results}
    assert by_check["sender_recipient"].passed is True
