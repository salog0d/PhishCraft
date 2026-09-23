"""The fixed spec set for the reliability experiment (10 specs)."""

from __future__ import annotations

from dataclasses import asdict, dataclass


@dataclass(frozen=True)
class CampaignSpec:
    spec_id: str
    campaign_id: str
    pretext: str
    tone: str
    difficulty: str
    language: str
    seed: int
    model: dict
    recipient_id: str  # catalog id: int (internal) or persona_id (external)
    start_at: str      # ISO-8601 UTC, fixed
    followup_minutes: int

    def to_dict(self) -> dict:
        return asdict(self)


def baseline_specs() -> list[CampaignSpec]:
    model = {"family": "deepseek", "name": "deepseek-chat", "adapter_version": "1.0"}
    start = "2026-08-20T09:00:00Z"

    def s(spec_id, recipient_id, pretext, tone, difficulty, seed):
        return CampaignSpec(
            spec_id=spec_id,
            campaign_id="q3-awareness-2026",
            pretext=pretext,
            tone=tone,
            difficulty=difficulty,
            language="en",
            seed=seed,
            model=model,
            recipient_id=str(recipient_id),
            start_at=start,
            followup_minutes=75,
        )

    return [
        s("S1", 1, "executive_request", "urgent", "medium", 42),
        s("S2", 1, "executive_request", "urgent", "medium", 42),  # repeat of S1
        s("S3", 40, "invoice_payment", "friendly", "easy", 42),
        s("S4", 24, "invoice_payment", "authoritative", "medium", 7),
        s("S5", 25, "it_support", "urgent", "hard", 13),
        s("S6", 41, "password_reset", "neutral", "easy", 42),
        s("S7", 16, "hr_notice", "friendly", "medium", 99),
        s("S8", "ext-supplier-01", "invoice_payment", "authoritative", "medium", 42),
        s("S9", "ext-bank-01", "account_suspension", "urgent", "hard", 5),
        s("S10", 3, "shared_document", "authoritative", "medium", 42),
    ]
