"""Business-rule and persistence-rule tests for the flow contracts.

Each test states one scenario and its expected outcome. Valid payloads mirror
the examples in ``docs/flow-schema.md``; invalid payloads assert that a specific
business rule is enforced.
"""

import pytest
from pydantic import ValidationError

from app.core import schemas as fc


# --------------------------------------------------------------------------- #
# Valid contracts (the documented examples must parse)
# --------------------------------------------------------------------------- #


def test_synthetic_target_set_accepts_documented_example():
    target_set = fc.SyntheticTargetSet(
        campaign_id="q3-awareness-2026",
        source="synthetic",
        target_count=1,
        targets=[
            {
                "target_id": "tgt-0001",
                "synthetic_domain": "examp1e-corp.com",
                "domain_pattern": "typosquat",
                "attack_surfaces": [{"type": "api", "value": "https://api"}],
            }
        ],
    )
    assert target_set.targets[0].target_id == "tgt-0001"


def test_interaction_result_accepts_matching_card_and_type():
    result = fc.InteractionResult(
        campaign_id="q3-awareness-2026",
        event_id="evt-0001",
        profile_id="prf-0001",
        selected_card="A",
        card_type="credentials",
        channel="voice",
        outcome="submitted",
        captured_fields=["username", "password"],
        logged_at="2026-08-20T09:15:30Z",
    )
    assert result.card_type is fc.CardType.CREDENTIALS


# --------------------------------------------------------------------------- #
# Business rules (invalid payloads must be rejected)
# --------------------------------------------------------------------------- #


def test_mission_rejects_non_synthetic_data():
    with pytest.raises(ValidationError):
        fc.MissionConstraints(
            synthetic_data_only=False,
            channels=["email"],
            max_interactions_per_target=1,
        )


def test_target_count_must_match_number_of_targets():
    with pytest.raises(ValidationError):
        fc.SyntheticTargetSet(
            campaign_id="q3",
            source="synthetic",
            target_count=2,
            targets=[
                {
                    "target_id": "tgt-0001",
                    "synthetic_domain": "d",
                    "domain_pattern": "typosquat",
                    "attack_surfaces": [{"type": "api", "value": "x"}],
                }
            ],
        )


def test_kpi_funnel_must_be_monotonic():
    with pytest.raises(ValidationError):
        fc.CampaignKpis(
            delivered=10, opened=20, clicked=1, converted=0, reported_as_spam=0,
            delivery_rate=1, open_rate=1, click_rate=0.1, conversion_rate=0,
            bounce_rate=0,
        )


def test_interaction_result_rejects_card_type_mismatch():
    with pytest.raises(ValidationError):
        fc.InteractionResult(
            campaign_id="q3", event_id="evt-0001", profile_id="prf-0001",
            selected_card="A", card_type="fake_support", channel="email",
            outcome="submitted", logged_at="2026-08-20T09:15:30Z",
        )


def test_tracking_link_requires_url_and_token():
    with pytest.raises(ValidationError):
        fc.PayloadAsset(asset_id="ast-0003", type="tracking_link", simulated=True)


def test_failed_exploit_requires_parameter_adjustments():
    with pytest.raises(ValidationError):
        fc.FeedbackDirective(
            campaign_id="q3",
            exploit_successful=False,
            directives=[{"target_agent": "Design-AG", "action": "optimize_templates"}],
        )


def test_envelope_rejects_self_addressed_message():
    with pytest.raises(ValidationError):
        fc.MessageEnvelope(
            campaign_id="q3", phase=1, from_agent="Recon-AG", to_agent="Recon-AG",
            emitted_at="2026-08-19T14:30:00Z", authorized=True, payload={},
        )


def test_captured_fields_rejects_raw_values():
    # A raw value (contains '@') must not pass the field-name pattern:
    # persistence rule -- only field names are ever stored.
    with pytest.raises(ValidationError):
        fc.InteractionResult(
            campaign_id="q3", event_id="evt-0001", profile_id="prf-0001",
            selected_card="A", card_type="credentials", channel="email",
            outcome="submitted", captured_fields=["victim@example.com"],
            logged_at="2026-08-20T09:15:30Z",
        )


def test_call_direction_only_valid_for_voice():
    with pytest.raises(ValidationError):
        fc.InteractionEvent(
            campaign_id="q3", event_id="evt-0001",
            generation_id="9f8e7d6c-5b4a-3210-fedc-ba9876543210",
            profile_id="prf-0001", channel="email", action="click_link",
            occurred_at="2026-08-20T09:15:00Z",
            context={"call_direction": "inbound"},
        )


# --------------------------------------------------------------------------- #
# Persistence rules (every contract carries a storage policy)
# --------------------------------------------------------------------------- #


@pytest.mark.parametrize(
    "contract",
    [
        fc.MissionConfig, fc.SyntheticTargetSet, fc.ProfileDataset, fc.TemplateSet,
        fc.PayloadAssets, fc.DeploymentManifest, fc.InteractionEvent,
        fc.InteractionResult, fc.MetricsReport, fc.FeedbackDirective,
        fc.MessageEnvelope,
    ],
)
def test_every_contract_declares_a_persistence_policy(contract):
    policy = contract.PERSISTENCE
    assert isinstance(policy, fc.PersistencePolicy)
    assert policy.retention_days >= 1
    assert policy.immutable is True


def test_interaction_data_is_classified_sensitive():
    assert fc.InteractionResult.PERSISTENCE.pii is fc.PiiClass.SENSITIVE
    assert fc.InteractionEvent.PERSISTENCE.pii is fc.PiiClass.SENSITIVE
