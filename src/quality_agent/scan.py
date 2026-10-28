"""Post-run quality scan: one entry point for the whole quality lifecycle.

``scan_campaign`` runs, on a delivered ``GeneratedCampaign``:

1. the five generation-artifact checks (``quality_agent.artifacts``),
2. the four contamination checks (``quality_agent.contamination``),
3. the stage-direction stripping pass (``quality_agent.strip``), measured on
   a copy, and
4. the automated label audit (``quality_agent.labels``) when a spec is given.

The result is a ``QualityReport`` — evidence, never repair: the campaign is
never mutated, and the scanner never raises on bad content (a finding is a
data point, not an exception). This mirrors the paper's post-generation
quality scan run over every produced conversation, extended with the
contamination scan, the stripping pass, and the relabeling audit.
"""

from __future__ import annotations

from app.core.schemas import (
    GeneratedCampaign,
    QualityCheckResult,
    QualityFinding,
    QualityReport,
    StripStats,
)
from quality_agent.lexicon import catalog_names

from . import artifacts, contamination, labels, strip

# The nine check categories, in report order (5 artifacts + 4 contamination).
CHECK_NAMES = (
    "dialogue_collapse",
    "stage_direction",
    "turn_overflow",
    "meta_bleed",
    "loop_detection",
    "pretext_contamination",
    "name_contamination",
    "brand_contamination",
    "script_contamination",
)


def _fields(campaign: GeneratedCampaign) -> list[tuple[str, str]]:
    """All prose fields of the campaign as ``(field, text)`` pairs."""
    fields: list[tuple[str, str]] = []
    for message in campaign.messages:
        if message.subject:
            fields.append(("email_subject", message.subject))
        fields.append(("email_body" if message.channel.value == "email"
                       else "sms_body", message.body))
    return fields


def _persona_names(campaign: GeneratedCampaign) -> tuple[str, str | None]:
    persona_name = campaign.persona.display_name
    recipient_name = (
        campaign.recipient.full_name if campaign.recipient else None
    )
    return persona_name, recipient_name


def scan_campaign(
    campaign: GeneratedCampaign,
    spec: dict | None = None,
    mission: dict | None = None,
    *,
    known_names: tuple[str, ...] | None = None,
) -> QualityReport:
    """Run the full quality lifecycle over one campaign.

    ``spec`` / ``mission`` supply the ground-truth labels (pretext, tone,
    difficulty, language) for the label audit and the pretext-contamination
    scan; both are optional so the scanner also works on bare saved
    artifacts. ``known_names`` overrides the org-chart roster (tests).
    """
    names = tuple(known_names) if known_names is not None else catalog_names()
    fields = _fields(campaign)
    persona_name, recipient_name = _persona_names(campaign)
    pretext = spec.get("pretext") if spec else None

    findings: dict[str, list[QualityFinding]] = {
        name: [] for name in CHECK_NAMES
    }

    # 1. Generation artifacts (per field, except the campaign-level loop check).
    email_subject = next((t for f, t in fields if f == "email_subject"), None)
    email_body = next((t for f, t in fields if f == "email_body"), "")
    sms_body = next((t for f, t in fields if f == "sms_body"), "")
    for field, text in fields:
        findings["dialogue_collapse"] += artifacts.scan_dialogue_collapse(
            text, field=field, persona_name=persona_name,
            recipient_name=recipient_name, known_names=names,
        )
        findings["stage_direction"] += artifacts.scan_stage_direction(
            text, field=field
        )
        findings["turn_overflow"] += artifacts.scan_turn_overflow(
            text, field=field
        )
        findings["meta_bleed"] += artifacts.scan_meta_bleed(text, field=field)
    findings["loop_detection"] = artifacts.scan_loop_detection(
        email_subject, email_body, sms_body
    )

    # 2. Contamination (campaign level).
    findings["pretext_contamination"] = \
        contamination.scan_pretext_contamination(fields, pretext)
    findings["name_contamination"] = contamination.scan_name_contamination(
        fields, persona_name=persona_name, recipient_name=recipient_name,
        known_names=names,
    )
    findings["brand_contamination"] = contamination.scan_brand_contamination(
        fields, persona_name=persona_name
    )
    findings["script_contamination"] = contamination.scan_script_contamination(
        fields
    )

    # 3. Stage-direction stripping (measured on a copy, never applied).
    strip_stats = StripStats()
    for message in campaign.messages:
        texts = ([message.subject] if message.subject else []) + [message.body]
        removed = sum(strip.strip_stage_directions(t)[1] for t in texts)
        if removed:
            strip_stats.affected_messages += 1
            strip_stats.stripped_chars += removed
            strip_stats.per_message[message.message_id] = removed

    # 4. Automated label audit (needs the spec's ground-truth labels).
    label_audit = labels.audit_labels(campaign, spec)

    results = [
        QualityCheckResult(
            check=name,
            passed=not findings[name],
            count=len(findings[name]),
            findings=findings[name],
        )
        for name in CHECK_NAMES
    ]
    return QualityReport(
        campaign_id=campaign.campaign_id,
        spec_id=spec.get("spec_id") if spec else None,
        pretext=pretext,
        results=results,
        label_audit=label_audit,
        strip_stats=strip_stats,
        n_flags=sum(r.count for r in results),
        any_flag=any(not r.passed for r in results),
    )
