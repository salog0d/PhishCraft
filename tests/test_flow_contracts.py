"""Business-rule and persistence-rule tests for the generator contracts.

Each test states one scenario and its expected outcome. Valid payloads mirror
the examples in ``docs/flow-schema.md``; invalid payloads assert that a specific
business rule is enforced. The project is a *campaign generator*: the tests
cover constraint satisfaction, model-family policy, coherence, and provenance —
not victim interaction or campaign KPIs (those are out of scope).
"""

import pytest
from pydantic import ValidationError

from app.core import schemas as fc


# --------------------------------------------------------------------------- #
# Builders for valid fixtures
# --------------------------------------------------------------------------- #

HASH = "a" * 64  # a well-formed sha256 hex digest


def _provenance(**over):
    data = dict(
        model={"family": "anthropic", "name": "claude-opus-5"},
        params={"seed": 42},
        prompt_template_id="tpl-0001",
        prompt_hash=HASH,
        generated_at="2026-08-20T09:00:00Z",
    )
    data.update(over)
    return data


def _persona(**over):
    data = dict(display_name="Elena Marchetti", email="ceo@fantazylabz.tech", role="CEO")
    data.update(over)
    return data


def _sender_matching_persona():
    return {"display_name": "Elena Marchetti", "from_address": "ceo@fantazylabz.tech"}


def _email(msg_id="msg-0001", at="2026-08-20T09:00:00Z", **over):
    data = dict(
        message_id=msg_id,
        channel="email",
        scheduled_at=at,
        sender=_sender_matching_persona(),
        subject="Quick approval needed",
        body="Please review the attached document.",
        call_to_action={"type": "click_link"},
        provenance=_provenance(),
    )
    data.update(over)
    return data


def _sms(msg_id="msg-0002", at="2026-08-20T10:00:00Z", refs=("msg-0001",), **over):
    data = dict(
        message_id=msg_id,
        channel="sms",
        scheduled_at=at,
        sender=_sender_matching_persona(),
        body="Did you get my email? Please action it today.",
        call_to_action={"type": "reply"},
        references=list(refs),
        include=None,
        provenance=_provenance(),
    )
    data.pop("include")
    data.update(over)
    return data


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


def test_generated_campaign_accepts_coherent_email_then_sms():
    campaign = fc.GeneratedCampaign(
        campaign_id="q3-awareness-2026",
        persona=_persona(),
        messages=[_email(), _sms()],
    )
    assert [m.channel.value for m in campaign.messages] == ["email", "sms"]


def test_mission_config_accepts_two_family_policy():
    config = fc.MissionConfig(
        campaign_id="q3-awareness-2026",
        authorized=True,
        objective="security-awareness-training",
        scope={"region": "LATAM", "sector": "finance", "volume": 50, "duration_days": 14},
        constraints={
            "synthetic_data_only": True,
            "channels": ["email", "sms"],
            "max_messages_per_persona": 3,
        },
        model_policy={
            "models": [
                {"family": "anthropic", "name": "claude-opus-5"},
                {"family": "openai", "name": "gpt-4.1"},
            ]
        },
        reproducibility={"seed": 42},
        ethics={"consent_reference": "IRB-2026-014", "isolated_environment": True},
    )
    assert config.reproducibility.seed == 42


# --------------------------------------------------------------------------- #
# Business rules (invalid payloads must be rejected)
# --------------------------------------------------------------------------- #


def test_mission_rejects_non_synthetic_data():
    with pytest.raises(ValidationError):
        fc.MissionConstraints(
            synthetic_data_only=False,
            channels=["email"],
            max_messages_per_persona=1,
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


def test_tracking_link_requires_url_and_token():
    with pytest.raises(ValidationError):
        fc.PayloadAsset(asset_id="ast-0003", type="tracking_link", simulated=True)


def test_envelope_rejects_self_addressed_message():
    with pytest.raises(ValidationError):
        fc.MessageEnvelope(
            campaign_id="q3", phase=1,
            from_agent="Generator-AG", to_agent="Generator-AG",
            emitted_at="2026-08-19T14:30:00Z", authorized=True, payload={},
        )


# --- Point 3: at least two model families -------------------------------- #


def test_model_policy_requires_two_distinct_families():
    with pytest.raises(ValidationError):
        fc.ModelPolicy(
            models=[
                {"family": "anthropic", "name": "claude-opus-5"},
                {"family": "anthropic", "name": "claude-sonnet-5"},
            ]
        )


def test_generation_params_require_a_seed():
    with pytest.raises(ValidationError):
        fc.GenerationParams(temperature=0.5)  # no seed -> not reproducible


def test_bad_prompt_hash_is_rejected():
    with pytest.raises(ValidationError):
        fc.GenerationProvenance(**_provenance(prompt_hash="not-a-hash"))


# --- Point 1: email + SMS channel shaping -------------------------------- #


def test_sms_request_rejects_email_only_fields():
    common = dict(
        campaign_id="q3", authorized=True,
        recipient={"email": "e@x.com"},
        sender=_sender_matching_persona(),
        pretext="it_support",
        call_to_action={"type": "reply"},
        model={"family": "anthropic", "name": "claude-opus-5"},
        params={"seed": 1},
    )
    # tracking pixel defaults True -> invalid for SMS
    with pytest.raises(ValidationError):
        fc.PhishingGenerationRequest(channel="sms", **common)
    # but explicitly disabling the email-only fields is fine
    ok = fc.PhishingGenerationRequest(
        channel="sms", include_tracking_pixel=False, **common
    )
    assert ok.channel is fc.Channel.SMS


def test_sms_message_must_not_have_subject():
    with pytest.raises(ValidationError):
        fc.GeneratedMessage(**_sms(subject="nope"))


def test_email_message_requires_subject():
    with pytest.raises(ValidationError):
        fc.GeneratedMessage(**_email(subject=None))


# --- Point 3: coherence validators --------------------------------------- #


def test_campaign_rejects_inconsistent_persona():
    # A different "CEO" on the SMS breaks persona identity coherence.
    bad_sms = _sms(sender={"display_name": "Someone Else", "from_address": "x@y.com"})
    with pytest.raises(ValidationError):
        fc.GeneratedCampaign(
            campaign_id="q3", persona=_persona(), messages=[_email(), bad_sms]
        )


def test_campaign_rejects_reference_to_missing_message():
    orphan = _sms(refs=("msg-9999",))
    with pytest.raises(ValidationError):
        fc.GeneratedCampaign(
            campaign_id="q3", persona=_persona(), messages=[_email(), orphan]
        )


def test_campaign_rejects_followup_scheduled_before_its_reference():
    # SMS references the email but is scheduled an hour *before* it.
    early_sms = _sms(at="2026-08-20T08:00:00Z", refs=("msg-0001",))
    with pytest.raises(ValidationError):
        fc.GeneratedCampaign(
            campaign_id="q3", persona=_persona(),
            messages=[_email(at="2026-08-20T09:00:00Z"), early_sms],
        )


def test_coherence_report_all_passed_must_match_results():
    results = [
        {"check": "persona_identity", "passed": True},
        {"check": "timing", "passed": True},
        {"check": "cross_channel_reference", "passed": False},
    ]
    with pytest.raises(ValidationError):
        fc.CoherenceReport(campaign_id="q3", results=results, all_passed=True)


# --------------------------------------------------------------------------- #
# Persistence rules (every contract carries a storage policy)
# --------------------------------------------------------------------------- #


@pytest.mark.parametrize(
    "contract",
    [
        fc.MissionConfig, fc.SyntheticTargetSet, fc.ProfileDataset, fc.TemplateSet,
        fc.PayloadAssets, fc.DeploymentManifest, fc.GeneratedCampaign,
        fc.CoherenceReport, fc.ProvenanceLog, fc.MessageEnvelope,
    ],
)
def test_every_contract_declares_a_persistence_policy(contract):
    policy = contract.PERSISTENCE
    assert isinstance(policy, fc.PersistencePolicy)
    assert policy.retention_days >= 1
    assert policy.immutable is True


def test_synthetic_datasets_are_classified_synthetic():
    assert fc.SyntheticTargetSet.PERSISTENCE.pii is fc.PiiClass.SYNTHETIC
    assert fc.ProfileDataset.PERSISTENCE.pii is fc.PiiClass.SYNTHETIC
    assert fc.GeneratedCampaign.PERSISTENCE.pii is fc.PiiClass.SYNTHETIC
