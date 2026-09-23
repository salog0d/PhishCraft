"""The deterministic validator must catch the known cross-channel link failure."""

from pathlib import Path

from app.core.schemas import GeneratedCampaign
from validator_agent.validate import validate_campaign

KNOWN_BAD = Path(__file__).resolve().parent.parent / "data" / "measurements" / \
    "known-case" / "generated_campaign.json"


def test_known_bad_campaign_fails_link_consistency():
    campaign = GeneratedCampaign.model_validate_json(KNOWN_BAD.read_text())
    report = validate_campaign(campaign)
    by_check = {r.check.value: r for r in report.results}
    assert set(by_check) == {
        "persona_identity",
        "timing",
        "cross_channel_reference",
        "link_consistency",
    }
    assert by_check["link_consistency"].passed is False
    assert "abc123" in by_check["link_consistency"].detail
    assert "d6db8064874a" in by_check["link_consistency"].detail
    assert report.all_passed is False


def test_coherent_campaign_passes_all_checks():
    from tests.test_generator_agent import CAMPAIGN  # assembled fixture

    report = validate_campaign(CAMPAIGN)
    assert report.all_passed is True
    assert len(report.results) == 4
