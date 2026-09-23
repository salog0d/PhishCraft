"""Deterministic coherence validation of a GeneratedCampaign (no LLM).

The four checks mirror ``GeneratedCampaign._coherent`` plus the link rule.
Every check returns a result object; this module never raises on bad content —
failures are data, not exceptions.
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


def validate_campaign(campaign: GeneratedCampaign) -> CoherenceReport:
    """Run the four coherence checks. Never raises on incoherent content."""
    results = [
        _check_persona(campaign),
        _check_timing(campaign),
        _check_references(campaign),
        _check_links(campaign),
    ]
    return CoherenceReport(
        campaign_id=campaign.campaign_id,
        results=results,
        all_passed=all(r.passed for r in results),
    )
