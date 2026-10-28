"""Automated label audit (COVA-X §IV-E ``audit_outcome_labels_v2.py``).

A deterministic heuristic labeler predicts the campaign's pretext, tone, and
difficulty from the message prose, and the audit compares those predictions
against the spec's ground-truth labels. The resulting mismatch rate is the
label-correction-rate analogue (the paper: 49.8% -> 3.9%).

The labeler is deliberately simple and transparent — lexicons in
``quality_agent/lexicon.py``, argmax scoring — because the metric of interest
is label *self-consistency*, not classifier accuracy. Predictions with no
signal are reported as ``unverifiable`` (the paper's deferred findings)
rather than forced into a mismatch.
"""

from __future__ import annotations

from app.core.schemas import GeneratedCampaign, LabelAudit

from quality_agent.lexicon import (
    DIFFICULTY_BANDS,
    DIFFICULTY_MARKERS,
    PRETEXT_TERMS,
    TONE_MARKERS,
    term_hits,
)

# Labels the audit covers.
LABEL_KEYS = ("pretext", "tone", "difficulty")


def _texts(campaign: GeneratedCampaign) -> list[str]:
    """All prose of the campaign (subjects + bodies), for label prediction."""
    texts = []
    for message in campaign.messages:
        if message.subject:
            texts.append(message.subject)
        texts.append(message.body)
    return texts


def _argmax(scores: dict[str, int]) -> str | None:
    """The argmax label; None when there is no signal or an ambiguous tie."""
    if not scores:
        return None
    best = max(scores.values())
    if best == 0:
        return None
    winners = [label for label, score in scores.items() if score == best]
    return winners[0] if len(winners) == 1 else None


def predict_pretext(campaign: GeneratedCampaign) -> str | None:
    scores: dict[str, int] = {}
    for pretext, terms in PRETEXT_TERMS.items():
        total = 0
        for text in _texts(campaign):
            total += sum(term_hits(text, terms).values())
        scores[pretext] = total
    return _argmax(scores)


def predict_tone(campaign: GeneratedCampaign) -> str | None:
    scores: dict[str, int] = {}
    for tone, terms in TONE_MARKERS.items():
        total = 0
        for text in _texts(campaign):
            total += sum(term_hits(text, terms).values())
        scores[tone] = total
    return _argmax(scores)


def predict_difficulty(campaign: GeneratedCampaign) -> str | None:
    """Red-flag count banded into easy/medium/hard.

    Urgency, requested actions, and impersonation cues weigh 1; threats and
    consequences weigh 2.
    """
    score = 0
    for text in _texts(campaign):
        for group, terms in DIFFICULTY_MARKERS.items():
            weight = 2 if group == "threat" else 1
            score += weight * sum(term_hits(text, terms).values())
    for low, high, label in DIFFICULTY_BANDS:
        if low <= score <= high:
            return label
    return None  # unreachable, but honest


def audit_labels(
    campaign: GeneratedCampaign, spec: dict | None
) -> LabelAudit:
    """Compare heuristic-implied labels against the spec's labels.

    ``spec`` is the campaign spec dict (as produced by
    ``measurement.specs.CampaignSpec.to_dict``). Without a spec there is no
    ground truth, so the audit reports itself unavailable.
    """
    if not spec:
        return LabelAudit(available=False)
    spec_labels = {key: spec.get(key) for key in LABEL_KEYS}
    predicted = {
        "pretext": predict_pretext(campaign),
        "tone": predict_tone(campaign),
        "difficulty": predict_difficulty(campaign),
    }
    statuses: dict[str, str] = {}
    mismatches: list[str] = []
    for key in LABEL_KEYS:
        if predicted[key] is None:
            statuses[key] = "unverifiable"
        elif predicted[key] == spec_labels.get(key):
            statuses[key] = "ok"
        else:
            statuses[key] = "mismatch"
            mismatches.append(key)
    return LabelAudit(
        available=True,
        spec_labels={k: v for k, v in spec_labels.items() if v is not None},
        predicted_labels={k: v for k, v in predicted.items() if v is not None},
        statuses=statuses,
        mismatches=mismatches,
    )
