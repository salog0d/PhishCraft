"""Pydantic schemas for the phishing-campaign **generator**.

Scope
-----
This project is a *configurable, reproducible generator* of synthetic
phishing-simulation campaigns over two channels — **email and SMS**. Its
scientific contribution is not measuring whether a message deceives a victim,
but whether the generator **reliably and reproducibly satisfies the campaign
constraints**. There is therefore no interaction-tracking, KPI, or
success-optimization feedback loop in these contracts.

This module is the single source of truth for the system's data contracts:

* The **generation contract** (``PhishingGenerationRequest`` / ``Response`` and
  ``GeneratedMessage``) validated at the API boundary for authorized
  security-awareness simulations.
* The **model-adapter contracts** (``ModelSpec`` / ``ModelPolicy`` /
  ``GenerationParams``) that let the generator target **at least two model
  families** so results are comparable and reproducible across families.
* The **coherence contracts** (``GeneratedCampaign`` / ``CoherenceReport``) that
  enforce, across a multi-message campaign, a consistent impersonated persona
  ("the CEO is the same everywhere"), a coherent send timeline, the existence
  of every cross-channel reference, and link consistency (every URL written
  into a message body must match the CTA link; a follow-up points at the same
  link it cites).
* The **provenance contracts** (``GenerationProvenance`` / ``ProvenanceLog``)
  that record which model, prompt, parameters, and seed produced each artifact,
  making every generation reproducible.
* The **quality lifecycle contracts** (``QualityReport`` / ``QualityCheckResult``
  / ``QualityFinding`` / ``LabelAudit`` / ``StripStats``) that record the
  post-run content-quality scan (generation artifacts, contamination, automated
  label audit, stage-direction stripping stats) as evidence — never repairs.
* The remaining **flow contracts** — one model per hand-off between stages
  (documented in ``docs/reference/flow-schema.md``) — each carrying a
  ``PersistencePolicy`` describing how its artifacts may be stored.
"""

from __future__ import annotations

from datetime import datetime, timezone
from enum import Enum
from typing import Annotated, ClassVar, Optional
from uuid import UUID, uuid4

from pydantic import (
    BaseModel,
    EmailStr,
    Field,
    HttpUrl,
    StringConstraints,
    field_validator,
    model_validator,
)


# =========================================================================== #
# Shared value types & enums
# =========================================================================== #


class Channel(str, Enum):
    """Delivery channels in scope. Voice is intentionally excluded."""

    EMAIL = "email"
    SMS = "sms"


class Pretext(str, Enum):
    """The social-engineering scenario the message is built around.

    Pretexts are tagged by :class:`PretextCategory` so consumer-brand lures
    (password reset, account suspension, package delivery) are kept separate
    from business/enterprise lures (BEC: executive request, invoice payment,
    shared document, HR notice, IT support)."""

    PASSWORD_RESET = "password_reset"
    INVOICE_PAYMENT = "invoice_payment"
    PACKAGE_DELIVERY = "package_delivery"
    IT_SUPPORT = "it_support"
    HR_NOTICE = "hr_notice"
    EXECUTIVE_REQUEST = "executive_request"
    SHARED_DOCUMENT = "shared_document"
    ACCOUNT_SUSPENSION = "account_suspension"
    # BEC variants (FBI / industry taxonomy) — expanded per the BEC taxonomy
    # report: vendor bank-detail change, account takeover, attorney
    # impersonation, data/W-2 theft, payroll diversion, and gift-card fraud.
    BANK_DETAIL_CHANGE = "bank_detail_change"
    ACCOUNT_COMPROMISE = "account_compromise"
    ATTORNEY_IMPERSONATION = "attorney_impersonation"
    DATA_THEFT = "data_theft"
    PAYROLL_DIVERSION = "payroll_diversion"
    GIFT_CARD = "gift_card"

    @property
    def category(self) -> "PretextCategory":
        return PRETEXT_CATEGORY[self]


class PretextCategory(str, Enum):
    """Coarse scenario family: consumer-brand phishing vs BEC/enterprise."""

    CONSUMER = "consumer"
    BEC = "bec"


PRETEXT_CATEGORY = {
    # Consumer-brand lures: a brand (bank / carrier / service) asking the
    # recipient to act on their personal account or parcel.
    Pretext.PASSWORD_RESET: PretextCategory.CONSUMER,
    Pretext.ACCOUNT_SUSPENSION: PretextCategory.CONSUMER,
    Pretext.PACKAGE_DELIVERY: PretextCategory.CONSUMER,
    # BEC / enterprise lures: an authority inside (or supplying) the company
    # asking an employee to act on business money, documents, or accounts.
    Pretext.EXECUTIVE_REQUEST: PretextCategory.BEC,
    Pretext.INVOICE_PAYMENT: PretextCategory.BEC,
    Pretext.SHARED_DOCUMENT: PretextCategory.BEC,
    Pretext.HR_NOTICE: PretextCategory.BEC,
    Pretext.IT_SUPPORT: PretextCategory.BEC,
    Pretext.BANK_DETAIL_CHANGE: PretextCategory.BEC,
    Pretext.ACCOUNT_COMPROMISE: PretextCategory.BEC,
    Pretext.ATTORNEY_IMPERSONATION: PretextCategory.BEC,
    Pretext.DATA_THEFT: PretextCategory.BEC,
    Pretext.PAYROLL_DIVERSION: PretextCategory.BEC,
    Pretext.GIFT_CARD: PretextCategory.BEC,
}


class CallToActionType(str, Enum):
    """What the recipient is lured into doing (the trackable action)."""

    CLICK_LINK = "click_link"
    ENTER_CREDENTIALS = "enter_credentials"
    OPEN_ATTACHMENT = "open_attachment"
    REPLY = "reply"


class Difficulty(str, Enum):
    """How many red flags the generated message exposes."""

    EASY = "easy"
    MEDIUM = "medium"
    HARD = "hard"


class Tone(str, Enum):
    URGENT = "urgent"
    FRIENDLY = "friendly"
    AUTHORITATIVE = "authoritative"
    NEUTRAL = "neutral"


class Recipient(BaseModel):
    """Target of the simulation, used to personalize the message."""

    email: EmailStr
    full_name: Optional[str] = Field(default=None, max_length=120)
    role: Optional[str] = Field(default=None, max_length=120)
    department: Optional[str] = Field(default=None, max_length=120)


class SenderPersona(BaseModel):
    """The identity a message appears to come from."""

    display_name: str = Field(..., min_length=1, max_length=120)
    from_address: EmailStr
    impersonated_brand: Optional[str] = Field(
        default=None,
        max_length=120,
        description="Brand/organization the persona imitates, if any.",
    )


class CallToAction(BaseModel):
    type: CallToActionType
    landing_url: Optional[HttpUrl] = Field(
        default=None,
        description="Simulation landing/tracking page for link or credential actions.",
    )
    button_label: Optional[str] = Field(default=None, max_length=60)


# =========================================================================== #
# Model adapters (the core: at least two model families)
# =========================================================================== #


class ModelFamily(str, Enum):
    """Supported LLM adapter families. A campaign must exercise >= 2 of these
    so the generator's constraint-satisfaction can be compared across families."""

    ANTHROPIC = "anthropic"
    OPENAI = "openai"
    MISTRAL = "mistral"
    LLAMA = "llama"
    LOCAL = "local"
    DEEPSEEK = "deepseek"


class ModelSpec(BaseModel, frozen=True):
    """One concrete adapter target: a family + a model name + adapter version.

    Frozen so it is hashable and can be compared / de-duplicated by family."""

    family: ModelFamily
    name: str = Field(
        ...,
        min_length=1,
        max_length=80,
        description="Provider model id, e.g. 'claude-opus-5' or 'gpt-4.1'.",
    )
    adapter_version: str = Field(
        default="1.0",
        pattern=r"^\d+\.\d+(\.\d+)?$",
        description="Version of the local adapter wrapping this model.",
    )


class GenerationParams(BaseModel):
    """Decoding parameters. ``seed`` makes a generation reproducible."""

    temperature: float = Field(default=0.9, ge=0.0, le=2.0)
    top_p: float = Field(default=1.0, ge=0.0, le=1.0)
    max_tokens: int = Field(default=1024, ge=1, le=32768)
    seed: int = Field(
        ...,
        ge=0,
        description="Fixed seed; same request + model + seed must reproduce output.",
    )


# =========================================================================== #
# Shared identifier types (business rule: IDs are prefixed and well-formed)
# =========================================================================== #

CampaignId = Annotated[str, StringConstraints(pattern=r"^[A-Za-z0-9._-]{1,64}$")]
TemplateId = Annotated[str, StringConstraints(pattern=r"^tpl-\d{4,}$")]
MessageId = Annotated[str, StringConstraints(pattern=r"^msg-\d{4,}$")]
BatchId = Annotated[str, StringConstraints(pattern=r"^bat-\d{2,}$")]
Sha256Hex = Annotated[str, StringConstraints(pattern=r"^[a-f0-9]{64}$")]


def _require_unique(ids: list[str], label: str) -> None:
    """Business rule helper: reject duplicate identifiers in a collection."""
    if len(ids) != len(set(ids)):
        raise ValueError(f"duplicate {label} detected")


# =========================================================================== #
# Provenance (reproducibility log)
# =========================================================================== #


class GenerationProvenance(BaseModel):
    """Everything needed to reproduce one generated artifact."""

    model: ModelSpec
    params: GenerationParams
    prompt_template_id: TemplateId
    prompt_hash: Sha256Hex = Field(
        ..., description="sha256 of the fully-rendered prompt actually sent."
    )
    generated_at: datetime
    adapter_latency_ms: Optional[int] = Field(default=None, ge=0)
    runtime: dict[str, str] = Field(
        default_factory=dict,
        description="Library/runtime versions (e.g. {'sdk': '0.40.0'}).",
    )

    @field_validator("generated_at")
    @classmethod
    def _must_be_timezone_aware(cls, value: datetime) -> datetime:
        if value.tzinfo is None:
            raise ValueError("generated_at must be timezone-aware (UTC)")
        return value


# =========================================================================== #
# Generation contract (API boundary)
# =========================================================================== #


class PhishingGenerationRequest(BaseModel):
    """Everything the engine needs to generate one simulation message.

    Channel-shaped: ``subject_hint`` and ``include_tracking_pixel`` apply to
    email only; an SMS request must leave them unset/false."""

    campaign_id: str = Field(..., min_length=1, max_length=64)
    authorized: bool = Field(
        ...,
        description="Must be true; caller attests the campaign is authorized.",
    )
    channel: Channel = Channel.EMAIL
    recipient: Recipient
    sender: SenderPersona
    pretext: Pretext
    call_to_action: CallToAction
    model: ModelSpec
    params: GenerationParams
    tone: Tone = Tone.NEUTRAL
    difficulty: Difficulty = Difficulty.MEDIUM
    language: str = Field(
        default="en",
        pattern=r"^[a-z]{2}(-[A-Z]{2})?$",
        description="BCP-47-ish locale, e.g. 'en' or 'es-MX'.",
    )
    subject_hint: Optional[str] = Field(
        default=None,
        max_length=200,
        description="Email only: optional steer for the subject line.",
    )
    include_tracking_pixel: bool = True

    @model_validator(mode="after")
    def _email_only_fields(self) -> "PhishingGenerationRequest":
        if self.channel != Channel.EMAIL:
            if self.subject_hint is not None:
                raise ValueError("subject_hint applies to the email channel only")
            if self.include_tracking_pixel:
                raise ValueError(
                    "include_tracking_pixel applies to the email channel only"
                )
        return self

    model_config = {
        "json_schema_extra": {
            "example": {
                "campaign_id": "q3-awareness-2026",
                "authorized": True,
                "channel": "email",
                "recipient": {
                    "email": "employee@example.com",
                    "full_name": "Jordan Lee",
                    "role": "Accountant",
                    "department": "Finance",
                },
                "sender": {
                    "display_name": "IT Service Desk",
                    "from_address": "it-support@example-corp.com",
                    "impersonated_brand": "Example Corp IT",
                },
                "pretext": "password_reset",
                "call_to_action": {
                    "type": "click_link",
                    "landing_url": "https://sim.example-corp.com/t/abc123",
                    "button_label": "Reset Password",
                },
                "model": {
                    "family": "anthropic",
                    "name": "claude-opus-5",
                    "adapter_version": "1.0",
                },
                "params": {
                    "temperature": 0.7,
                    "top_p": 1.0,
                    "max_tokens": 1024,
                    "seed": 42,
                },
                "tone": "urgent",
                "difficulty": "medium",
                "language": "en",
                "subject_hint": "Action required: password expires today",
                "include_tracking_pixel": True,
            }
        }
    }


class GenerationStatus(str, Enum):
    QUEUED = "queued"


class PhishingGenerationResponse(BaseModel):
    """Acknowledgement that a generation request was accepted."""

    generation_id: UUID = Field(default_factory=uuid4)
    campaign_id: str
    status: GenerationStatus = GenerationStatus.QUEUED
    accepted_at: datetime = Field(
        default_factory=lambda: datetime.now(timezone.utc)
    )
    message: str = "Generation request accepted."


class LinkFix(BaseModel):
    """One tracking-token rewrite the assembler applied to model prose.

    The raw pre-assembler link-consistency metric is derived from these: a
    message with any ``link_fixes`` had a link the LLM wrote that did not
    match the campaign's tracking token before normalization.
    """

    field: str = Field(
        ...,
        description="The prose field the stale token appeared in: "
                    "email_subject | email_body | sms_body.",
    )
    replaced_token: str = Field(
        ...,
        description="The tracking token the model actually wrote (stale).",
    )


class GeneratedMessage(BaseModel):
    """One message produced by the generator, with its provenance attached."""

    message_id: MessageId
    channel: Channel
    scheduled_at: datetime
    sender: SenderPersona
    subject: Optional[str] = Field(default=None, max_length=200)
    body: str = Field(..., min_length=1, max_length=20_000)
    call_to_action: CallToAction
    references: list[MessageId] = Field(
        default_factory=list,
        description="Ids of earlier messages this one refers to (cross-channel).",
    )
    link_fixes: list[LinkFix] = Field(
        default_factory=list,
        description=(
            "Tracking-token rewrites the assembler applied to the LLM's raw "
            "prose. Empty means the model wrote no stale link token; this is "
            "the evidence behind the raw (pre-assembler) reliability metric."
        ),
    )
    provenance: GenerationProvenance

    @field_validator("scheduled_at")
    @classmethod
    def _must_be_timezone_aware(cls, value: datetime) -> datetime:
        if value.tzinfo is None:
            raise ValueError("scheduled_at must be timezone-aware (UTC)")
        return value

    @model_validator(mode="after")
    def _channel_shaped(self) -> "GeneratedMessage":
        if self.channel == Channel.EMAIL and not self.subject:
            raise ValueError("email messages require a subject")
        if self.channel == Channel.SMS:
            if self.subject:
                raise ValueError("sms messages must not carry a subject")
            if len(self.body) > 1600:
                raise ValueError("sms body exceeds 1600 characters")
        if self.message_id in self.references:
            raise ValueError("a message cannot reference itself")
        return self


# =========================================================================== #
# Coherence contracts (persona / timing / cross-channel references)
# =========================================================================== #


class ImpersonatedPersona(BaseModel, frozen=True):
    """The single impersonated identity a campaign speaks as (e.g. the CEO).

    Frozen so it can be compared by value against every message's sender."""

    display_name: str = Field(..., min_length=1, max_length=120)
    email: EmailStr
    role: Optional[str] = Field(default=None, max_length=120)
    department: Optional[str] = Field(default=None, max_length=120)
    organization: Optional[str] = Field(default=None, max_length=120)


class GeneratedCampaign(BaseModel):
    """A coherent multi-channel bundle of generated messages for one persona.

    Enforces the three construction coherence rules that are this project's
    contribution: persona identity, send timing, and cross-channel reference
    existence. The remaining checks (link consistency, sender-vs-recipient) are
    deliberately **not** enforced here — they are evaluated by the
    deterministic validator, so a violation is recorded as data instead of
    being silently repaired (or made unfalsifiable) by construction.

    ``recipient`` records the simulation target the campaign was generated
    for; it lets the validator check that the impersonated persona never
    impersonates its own recipient."""

    PERSISTENCE: ClassVar["PersistencePolicy"]

    campaign_id: CampaignId
    persona: ImpersonatedPersona
    recipient: Optional[Recipient] = Field(
        default=None,
        description=(
            "The simulation target (the person the messages are addressed to). "
            "The impersonated persona must never be the recipient."
        ),
    )
    messages: list[GeneratedMessage] = Field(..., min_length=1)

    @model_validator(mode="after")
    def _coherent(self) -> "GeneratedCampaign":
        _require_unique([m.message_id for m in self.messages], "message_id")

        # 1. Persona identity coherence -- the impersonated identity (the CEO)
        #    must be the same in every message's sender.
        for m in self.messages:
            if (
                m.sender.display_name != self.persona.display_name
                or str(m.sender.from_address) != str(self.persona.email)
            ):
                raise ValueError(
                    f"message {m.message_id} sender does not match the campaign "
                    f"persona '{self.persona.display_name}'"
                )

        by_id = {m.message_id: m for m in self.messages}
        for m in self.messages:
            for ref in m.references:
                # 2. Cross-channel reference existence.
                if ref not in by_id:
                    raise ValueError(
                        f"message {m.message_id} references unknown message {ref}"
                    )
                # 3. Timing coherence -- a follow-up cannot precede what it cites.
                if by_id[ref].scheduled_at > m.scheduled_at:
                    raise ValueError(
                        f"message {m.message_id} is scheduled before the message "
                        f"{ref} it references"
                    )
        return self


class CoherenceCheck(str, Enum):
    PERSONA_IDENTITY = "persona_identity"
    TIMING = "timing"
    CROSS_CHANNEL_REFERENCE = "cross_channel_reference"
    LINK_CONSISTENCY = "link_consistency"
    SENDER_RECIPIENT = "sender_recipient"


class CoherenceCheckResult(BaseModel):
    check: CoherenceCheck
    passed: bool
    detail: Optional[str] = Field(default=None, max_length=200)


class CoherenceReport(BaseModel):
    """The recorded outcome of validating a ``GeneratedCampaign``.

    This is the evidence artifact for 'the generator satisfies its
    constraints' -- the project's reproducible result, not a victim metric.

    Covers the five coherence checks: persona identity, send timing,
    cross-channel reference existence, cross-channel link consistency (every
    URL written into a message body must match the CTA link, and a follow-up
    must point at the same link it cites), and sender-vs-recipient separation
    (the impersonated persona must never be the campaign's own recipient)."""

    PERSISTENCE: ClassVar["PersistencePolicy"]

    campaign_id: CampaignId
    results: list[CoherenceCheckResult] = Field(..., min_length=5)
    all_passed: bool

    @model_validator(mode="after")
    def _report_is_consistent(self) -> "CoherenceReport":
        covered = {r.check for r in self.results}
        if covered != set(CoherenceCheck):
            raise ValueError("report must cover every coherence check exactly once")
        if len(self.results) != len(covered):
            raise ValueError("duplicate coherence check in report")
        if self.all_passed != all(r.passed for r in self.results):
            raise ValueError("all_passed must match the individual check results")
        return self


# =========================================================================== #
# Quality lifecycle contracts (post-run content-quality scan)
# =========================================================================== #
#
# The deterministic quality scanner (``quality_agent/scan.py``) runs on every
# generated campaign and records content-quality findings as data — the
# COVA-X style quality lifecycle: five generation-artifact types (dialogue
# collapse, stage direction, turn overflow, meta bleed, loop detection), four
# contamination categories (pretext, name, brand, script), an automated label
# audit, and stage-direction stripping statistics. Like ``CoherenceReport``,
# these are evidence artifacts, never repair mechanisms: the scanner never
# mutates the campaign and never raises on bad content.


class QualityFinding(BaseModel):
    """One content-quality finding: what was found, where, and the evidence."""

    check: str = Field(..., max_length=40)
    field: str = Field(
        ...,
        max_length=40,
        description="The prose field the finding came from: "
                    "email_subject | email_body | sms_body | campaign.",
    )
    excerpt: Optional[str] = Field(
        default=None,
        max_length=200,
        description="A trimmed snippet of the offending text (the evidence).",
    )
    detail: str = Field(..., max_length=300)


class QualityCheckResult(BaseModel):
    """The outcome of one quality check category."""

    check: str = Field(..., max_length=40)
    passed: bool
    count: int = Field(..., ge=0)
    findings: list[QualityFinding] = Field(default_factory=list)

    @model_validator(mode="after")
    def _result_is_consistent(self) -> "QualityCheckResult":
        if self.count != len(self.findings):
            raise ValueError("count must equal the number of findings")
        if self.passed != (self.count == 0):
            raise ValueError("passed must be false when the check has findings")
        return self


class LabelAudit(BaseModel):
    """Automated label audit: heuristic-implied labels vs. the spec labels.

    The deterministic labeler (``quality_agent/labels.py``) predicts pretext,
    tone, and difficulty from the message prose. Each label gets a status:
    ``ok`` (prediction matches the spec), ``mismatch`` (prediction disagrees —
    a candidate relabel, the paper's label-correction analogue), or
    ``unverifiable`` (no heuristic signal either way — deferred, like the
    paper's deferred audit findings).
    """

    available: bool = Field(
        default=False,
        description="False when no spec was supplied, so no ground truth exists.",
    )
    spec_labels: dict[str, str] = Field(default_factory=dict)
    predicted_labels: dict[str, str] = Field(default_factory=dict)
    statuses: dict[str, str] = Field(default_factory=dict)
    mismatches: list[str] = Field(default_factory=list)


class StripStats(BaseModel):
    """Stage-direction stripping statistics (measured on a copy, never applied).

    ``strip_stage_directions`` removes bracket/parenthetical directions and
    leftover placeholder artifacts from a copy of the prose; the original
    artifact is never mutated. The stats record how much *would* be removed —
    the paper's "affected-turn rate" analogue.
    """

    affected_messages: int = Field(default=0, ge=0)
    stripped_chars: int = Field(default=0, ge=0)
    per_message: dict[str, int] = Field(default_factory=dict)


class QualityReport(BaseModel):
    """The recorded outcome of the post-run quality scan of a campaign.

    One ``QualityCheckResult`` per check category (5 generation-artifact
    checks + 4 contamination checks), plus the label audit and the stripping
    stats. ``n_flags`` is the total finding count across all checks.
    """

    PERSISTENCE: ClassVar["PersistencePolicy"]

    campaign_id: CampaignId
    spec_id: Optional[str] = Field(default=None, max_length=40)
    pretext: Optional[str] = Field(default=None, max_length=40)
    results: list[QualityCheckResult] = Field(..., min_length=1)
    label_audit: LabelAudit = Field(default_factory=LabelAudit)
    strip_stats: StripStats = Field(default_factory=StripStats)
    n_flags: int = Field(..., ge=0)
    any_flag: bool

    @model_validator(mode="after")
    def _report_is_consistent(self) -> "QualityReport":
        checks = [r.check for r in self.results]
        if len(checks) != len(set(checks)):
            raise ValueError("quality report must not repeat a check category")
        if self.n_flags != sum(r.count for r in self.results):
            raise ValueError("n_flags must equal the total finding count")
        if self.any_flag != (self.n_flags > 0):
            raise ValueError("any_flag must match n_flags")
        return self


# =========================================================================== #
# Flow contracts (see docs/reference/flow-schema.md)
# =========================================================================== #


class Agent(str, Enum):
    """Generator-centric stages (no attack-execution or monitoring agents).

    The Orchestrator is the ADK SequentialAgent itself; Generator and
    Validator are the two surviving pipeline stages."""

    ORCHESTRATOR = "Orchestrator-AG"
    GENERATOR = "Generator-AG"    # LLM content + deterministic assembly
    VALIDATOR = "Validator-AG"    # coherence checks + provenance recording


# --------------------------------------------------------------------------- #
# Persistence policy (data-persistence rules of the flow)
# --------------------------------------------------------------------------- #


class PiiClass(str, Enum):
    """Sensitivity of the data an artifact may hold, for storage decisions."""

    NONE = "none"
    SYNTHETIC = "synthetic"   # synthetic personal-shaped data


class PersistencePolicy(BaseModel, frozen=True):
    """How a contract's artifacts are stored. Read by the persistence layer."""

    store: str = Field(..., description="Logical store the artifact lands in.")
    retention_days: int = Field(..., ge=1, le=3650)
    pii: PiiClass
    immutable: bool = True            # append-only; never updated in place
    encrypted_at_rest: bool = True


# Coherence/provenance artifacts declared above receive their policy here, once
# PersistencePolicy exists.
GeneratedCampaign.PERSISTENCE = PersistencePolicy(
    store="generated-campaigns", retention_days=365, pii=PiiClass.SYNTHETIC
)
CoherenceReport.PERSISTENCE = PersistencePolicy(
    store="coherence-reports", retention_days=365, pii=PiiClass.NONE
)
QualityReport.PERSISTENCE = PersistencePolicy(
    store="quality-reports", retention_days=365, pii=PiiClass.NONE
)


# --------------------------------------------------------------------------- #
# Message envelope
# --------------------------------------------------------------------------- #


class MessageEnvelope(BaseModel):
    """Transport wrapper for every inter-stage message."""

    PERSISTENCE: ClassVar[PersistencePolicy] = PersistencePolicy(
        store="bus-audit-log", retention_days=90, pii=PiiClass.NONE
    )

    message_id: UUID = Field(default_factory=uuid4)
    schema_version: str = Field(default="1.0", pattern=r"^\d+\.\d+$")
    campaign_id: CampaignId
    phase: int = Field(..., ge=0, le=2, description="0=config, 1=generation, 2=verification")
    from_agent: Agent
    to_agent: Agent
    emitted_at: datetime
    authorized: bool
    payload: dict

    @field_validator("emitted_at")
    @classmethod
    def _must_be_timezone_aware(cls, value: datetime) -> datetime:
        if value.tzinfo is None:
            raise ValueError("emitted_at must be timezone-aware (UTC)")
        return value

    @field_validator("authorized")
    @classmethod
    def _must_be_authorized(cls, value: bool) -> bool:
        if not value:
            raise ValueError("unauthorized message rejected")
        return value

    @model_validator(mode="after")
    def _sender_is_not_receiver(self) -> "MessageEnvelope":
        if self.from_agent == self.to_agent:
            raise ValueError("from_agent and to_agent must differ")
        return self


# --------------------------------------------------------------------------- #
# Phase 0 -- MissionConfig
# --------------------------------------------------------------------------- #


class MissionScope(BaseModel):
    region: str = Field(..., min_length=1, max_length=60)
    sector: str = Field(..., min_length=1, max_length=60)
    volume: int = Field(..., ge=1, le=100_000)
    duration_days: int = Field(..., ge=1, le=365)


class MissionConstraints(BaseModel):
    synthetic_data_only: bool
    channels: list[Channel] = Field(..., min_length=1)
    max_messages_per_persona: int = Field(..., ge=1, le=20)

    @field_validator("synthetic_data_only")
    @classmethod
    def _synthetic_only(cls, value: bool) -> bool:
        if not value:
            raise ValueError("synthetic_data_only must be true in this pipeline")
        return value

    @field_validator("channels")
    @classmethod
    def _channels_unique(cls, value: list[Channel]) -> list[Channel]:
        _require_unique([c.value for c in value], "channel")
        return value


class ModelPolicy(BaseModel):
    """The models a campaign may use. Requires at least two distinct families
    so the generator's behaviour can be compared and reproduced across them."""

    models: list[ModelSpec] = Field(..., min_length=2)

    @model_validator(mode="after")
    def _at_least_two_families(self) -> "ModelPolicy":
        families = {m.family for m in self.models}
        if len(families) < 2:
            raise ValueError(
                "model_policy must reference at least two distinct model families"
            )
        return self


class ReproducibilityPolicy(BaseModel):
    """Reproducibility guarantees for the campaign."""

    seed: int = Field(..., ge=0)
    deterministic: bool = True


class MissionEthics(BaseModel):
    consent_reference: str = Field(..., min_length=1, max_length=120)
    isolated_environment: bool

    @field_validator("isolated_environment")
    @classmethod
    def _must_be_isolated(cls, value: bool) -> bool:
        if not value:
            raise ValueError("campaigns must run in an isolated environment")
        return value


class MissionConfig(BaseModel):
    PERSISTENCE: ClassVar[PersistencePolicy] = PersistencePolicy(
        store="campaign-configs", retention_days=365, pii=PiiClass.NONE
    )

    campaign_id: CampaignId
    authorized: bool
    objective: str = Field(..., min_length=1, max_length=120)
    scope: MissionScope
    constraints: MissionConstraints
    model_policy: ModelPolicy
    reproducibility: ReproducibilityPolicy
    ethics: MissionEthics

    @field_validator("authorized")
    @classmethod
    def _must_be_authorized(cls, value: bool) -> bool:
        if not value:
            raise ValueError("campaign must be attested as authorized")
        return value


# --------------------------------------------------------------------------- #
# Phase 3 -- DeploymentManifest (the generation/dispatch plan)
# --------------------------------------------------------------------------- #


class DeploymentBatch(BaseModel):
    batch_id: BatchId
    channel: Channel
    scheduled_at: datetime
    # Each request is validated by PhishingGenerationRequest at the engine
    # boundary; here we only require the batch to be non-empty.
    requests: list[dict] = Field(..., min_length=1)

    @field_validator("scheduled_at")
    @classmethod
    def _must_be_timezone_aware(cls, value: datetime) -> datetime:
        if value.tzinfo is None:
            raise ValueError("scheduled_at must be timezone-aware (UTC)")
        return value


class DeploymentManifest(BaseModel):
    PERSISTENCE: ClassVar[PersistencePolicy] = PersistencePolicy(
        store="campaign-schedules", retention_days=365, pii=PiiClass.SYNTHETIC
    )

    campaign_id: CampaignId
    authorized: bool
    batches: list[DeploymentBatch] = Field(..., min_length=1)

    @field_validator("authorized")
    @classmethod
    def _must_be_authorized(cls, value: bool) -> bool:
        if not value:
            raise ValueError("deployment must be attested as authorized")
        return value

    @model_validator(mode="after")
    def _batch_ids_unique(self) -> "DeploymentManifest":
        _require_unique([b.batch_id for b in self.batches], "batch_id")
        return self


# --------------------------------------------------------------------------- #
# Phase 4 -- ProvenanceLog (append-only reproducibility record)
# --------------------------------------------------------------------------- #


class ProvenanceLog(BaseModel):
    PERSISTENCE: ClassVar[PersistencePolicy] = PersistencePolicy(
        store="provenance-log", retention_days=730, pii=PiiClass.NONE
    )

    campaign_id: CampaignId
    entries: list[GenerationProvenance] = Field(..., min_length=1)
