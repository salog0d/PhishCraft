"""Deterministic coherence validation of a GeneratedCampaign (no LLM).

The five checks mirror ``GeneratedCampaign._coherent`` plus the link rule and
the sender-vs-recipient separation. Every check returns a result object; this
module never raises on bad content — failures are data, not exceptions.
"""

from __future__ import annotations

from app.core.schemas import (
    CoherenceCheckResult,
    CoherenceReport,
    GeneratedCampaign,
)
from validator_agent.links import tokens_in


def _token_of(url) -> str:
    return str(url).rstrip("/").rsplit("/", 1)[-1]


def _check_persona(campaign: GeneratedCampaign) -> CoherenceCheckResult:
    bad = [
        m.message_id
        for m in campaign.messages
        if m.sender.display_name != campaign.persona.display_name
        or str(m.sender.from_address) != str(campaign.persona.email)
    ]
    return CoherenceCheckResult(
        check="persona_identity",
        passed=not bad,
        detail=(
            f"all {len(campaign.messages)} messages match the persona"
            if not bad
            else f"sender mismatch in: {', '.join(bad)}"
        ),
    )


def _check_timing(campaign: GeneratedCampaign) -> CoherenceCheckResult:
    by_id = {m.message_id: m for m in campaign.messages}
    bad = [
        f"{m.message_id} before {ref}"
        for m in campaign.messages
        for ref in m.references
        if ref in by_id and by_id[ref].scheduled_at > m.scheduled_at
    ]
    return CoherenceCheckResult(
        check="timing",
        passed=not bad,
        detail="no ordering violations" if not bad else "; ".join(bad),
    )


def _check_references(campaign: GeneratedCampaign) -> CoherenceCheckResult:
    by_id = {m.message_id: m for m in campaign.messages}
    bad = [
        f"{m.message_id} -> {ref}"
        for m in campaign.messages
        for ref in m.references
        if ref not in by_id or ref == m.message_id
    ]
    return CoherenceCheckResult(
        check="cross_channel_reference",
        passed=not bad,
        detail="all references resolve" if not bad else "; ".join(bad),
    )


def _check_links(campaign: GeneratedCampaign) -> CoherenceCheckResult:
    by_id = {m.message_id: m for m in campaign.messages}
    problems: list[str] = []
    for m in campaign.messages:
        allowed = {_token_of(m.call_to_action.landing_url)}
        for ref in m.references:
            if ref in by_id:
                allowed.add(_token_of(by_id[ref].call_to_action.landing_url))
        for tok in sorted(tokens_in(m.body) - allowed):
            problems.append(
                f"{m.message_id} body token '{tok}' not in CTA tokens "
                f"({', '.join(sorted(allowed)) or 'none'})"
            )
        # cross-channel: a follow-up must point at the same link it cites
        for ref in m.references:
            if (
                ref in by_id
                and _token_of(by_id[ref].call_to_action.landing_url)
                != _token_of(m.call_to_action.landing_url)
            ):
                problems.append(
                    f"{m.message_id} CTA token "
                    f"'{_token_of(m.call_to_action.landing_url)}' != {ref} CTA "
                    f"token '{_token_of(by_id[ref].call_to_action.landing_url)}'"
                )
    return CoherenceCheckResult(
        check="link_consistency",
        passed=not problems,
        detail="all body links match the CTA" if not problems else "; ".join(problems),
    )


def _check_sender_recipient(campaign: GeneratedCampaign) -> CoherenceCheckResult:
    """The impersonated persona must never be the campaign's own recipient.

    A campaign that has the CEO writing to herself ("Elena, I'm finalizing… —
    Elena") is semantically broken even when every structural rule holds; this
    check catches it. Campaigns without a recorded recipient fail it: the
    separation cannot be verified, and unverifiable is not the same as clean.
    """
    if campaign.recipient is None:
        return CoherenceCheckResult(
            check="sender_recipient",
            passed=False,
            detail=(
                "campaign carries no recipient — sender-recipient separation "
                "cannot be verified"
            ),
        )
    same_name = (
        campaign.recipient.full_name is not None
        and campaign.recipient.full_name.strip().casefold()
        == campaign.persona.display_name.strip().casefold()
    )
    same_email = (
        str(campaign.recipient.email).strip().casefold()
        == str(campaign.persona.email).strip().casefold()
    )
    if same_name or same_email:
        return CoherenceCheckResult(
            check="sender_recipient",
            passed=False,
            detail=(
                f"persona '{campaign.persona.display_name}' "
                f"<{campaign.persona.email}> impersonates its own recipient "
                f"'{campaign.recipient.full_name}' <{campaign.recipient.email}>"
            ),
        )
    return CoherenceCheckResult(
        check="sender_recipient",
        passed=True,
        detail=(
            f"persona '{campaign.persona.display_name}' is not the recipient "
            f"'{campaign.recipient.full_name}'"
        ),
    )


def validate_campaign(campaign: GeneratedCampaign) -> CoherenceReport:
    """Run the five coherence checks. Never raises on incoherent content."""
    results = [
        _check_persona(campaign),
        _check_timing(campaign),
        _check_references(campaign),
        _check_links(campaign),
        _check_sender_recipient(campaign),
    ]
    return CoherenceReport(
        campaign_id=campaign.campaign_id,
        results=results,
        all_passed=all(r.passed for r in results),
    )
