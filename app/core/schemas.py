"""Pydantic schemas for the phishing-simulation pipeline.

This module is the single source of truth for the system's data contracts:

* The **generation contract** (``PhishingGenerationRequest`` / ``Response``)
  validated at the API boundary for authorized security-awareness simulations.
* The **agentic flow contracts** — one model per hand-off between agents
  (Phases 0-7, documented in ``docs/flow-schema.md``) — each enforcing its
  business rules and carrying a ``PersistencePolicy`` describing how its
  artifacts may be stored.
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
# Generation contract (API boundary)
# =========================================================================== #


class Pretext(str, Enum):
    """The social-engineering scenario the email is built around."""

    PASSWORD_RESET = "password_reset"
    INVOICE_PAYMENT = "invoice_payment"
    PACKAGE_DELIVERY = "package_delivery"
    IT_SUPPORT = "it_support"
    HR_NOTICE = "hr_notice"
    EXECUTIVE_REQUEST = "executive_request"
    SHARED_DOCUMENT = "shared_document"
    ACCOUNT_SUSPENSION = "account_suspension"


class CallToActionType(str, Enum):
    """What the recipient is lured into doing (the trackable action)."""

    CLICK_LINK = "click_link"
    ENTER_CREDENTIALS = "enter_credentials"
    OPEN_ATTACHMENT = "open_attachment"
    REPLY = "reply"


class Difficulty(str, Enum):
    """How many red flags the generated email exposes."""

    EASY = "easy"
    MEDIUM = "medium"
    HARD = "hard"


class Tone(str, Enum):
    URGENT = "urgent"
    FRIENDLY = "friendly"
    AUTHORITATIVE = "authoritative"
    NEUTRAL = "neutral"


class Recipient(BaseModel):
    """Target of the simulation, used to personalize the email."""

    email: EmailStr
    full_name: Optional[str] = Field(default=None, max_length=120)
    role: Optional[str] = Field(default=None, max_length=120)
    department: Optional[str] = Field(default=None, max_length=120)


class SenderPersona(BaseModel):
    """The identity the email appears to come from."""

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


class PhishingGenerationRequest(BaseModel):
    """Everything the engine needs to generate one simulation email."""

    campaign_id: str = Field(..., min_length=1, max_length=64)
    authorized: bool = Field(
        ...,
        description="Must be true; caller attests the campaign is authorized.",
    )
    recipient: Recipient
    sender: SenderPersona
    pretext: Pretext
    call_to_action: CallToAction
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
        description="Optional steer for the subject line; engine may override.",
    )
    include_tracking_pixel: bool = True

    model_config = {
        "json_schema_extra": {
            "example": {
                "campaign_id": "q3-awareness-2026",
                "authorized": True,
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


# =========================================================================== #
# Agentic flow contracts (see docs/flow-schema.md)
# =========================================================================== #


# --------------------------------------------------------------------------- #
# Shared identifier types (business rule: IDs are prefixed and well-formed)
# --------------------------------------------------------------------------- #

CampaignId = Annotated[str, StringConstraints(pattern=r"^[A-Za-z0-9._-]{1,64}$")]
TargetId = Annotated[str, StringConstraints(pattern=r"^tgt-\d{4,}$")]
ProfileId = Annotated[str, StringConstraints(pattern=r"^prf-\d{4,}$")]
TemplateId = Annotated[str, StringConstraints(pattern=r"^tpl-\d{4,}$")]
AssetId = Annotated[str, StringConstraints(pattern=r"^ast-\d{4,}$")]
EventId = Annotated[str, StringConstraints(pattern=r"^evt-\d{4,}$")]
BatchId = Annotated[str, StringConstraints(pattern=r"^bat-\d{2,}$")]
Locale = Annotated[str, StringConstraints(pattern=r"^[a-z]{2}(-[A-Z]{2})?$")]
# A field *name* (not a value): lower snake_case, so captured PII values can
# never masquerade as field names in an InteractionResult.
FieldName = Annotated[str, StringConstraints(pattern=r"^[a-z][a-z0-9_]{0,39}$")]
SandboxRef = Annotated[str, StringConstraints(pattern=r"^sandbox://[\w./-]+$")]


class Agent(str, Enum):
    RECON = "Recon-AG"
    HARVEST = "Harvest-AG"
    DESIGN = "Design-AG"
    PAYLOAD = "Payload-AG"
    RESPONDER = "Responder-AG"
    ORCHESTRATOR = "Orchestrator-AG"
    MONITOR = "Monitor-AG"


class Channel(str, Enum):
    EMAIL = "email"
    SMS = "sms"
    VOICE = "voice"


# --------------------------------------------------------------------------- #
# Persistence policy (data-persistence rules of the flow)
# --------------------------------------------------------------------------- #


class PiiClass(str, Enum):
    """Sensitivity of the data an artifact may hold, for storage decisions."""

    NONE = "none"
    SYNTHETIC = "synthetic"   # synthetic personal-shaped data
    SENSITIVE = "sensitive"   # interaction outcomes; field names only


class PersistencePolicy(BaseModel, frozen=True):
    """How a contract's artifacts are stored. Read by the persistence layer."""

    store: str = Field(..., description="Logical store the artifact lands in.")
    retention_days: int = Field(..., ge=1, le=3650)
    pii: PiiClass
    immutable: bool = True            # append-only; never updated in place
    encrypted_at_rest: bool = True


def _require_unique(ids: list[str], label: str) -> None:
    """Business rule helper: reject duplicate identifiers in a collection."""
    if len(ids) != len(set(ids)):
        raise ValueError(f"duplicate {label} detected")


# --------------------------------------------------------------------------- #
# Message envelope
# --------------------------------------------------------------------------- #


class MessageEnvelope(BaseModel):
    """Transport wrapper for every inter-agent message."""

    PERSISTENCE: ClassVar[PersistencePolicy] = PersistencePolicy(
        store="bus-audit-log", retention_days=90, pii=PiiClass.NONE
    )

    message_id: UUID = Field(default_factory=uuid4)
    schema_version: str = Field(default="1.0", pattern=r"^\d+\.\d+$")
    campaign_id: CampaignId
    phase: int = Field(..., ge=0, le=7)
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
    max_interactions_per_target: int = Field(..., ge=1, le=20)

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
    ethics: MissionEthics

    @field_validator("authorized")
    @classmethod
    def _must_be_authorized(cls, value: bool) -> bool:
        if not value:
            raise ValueError("campaign must be attested as authorized")
        return value


# --------------------------------------------------------------------------- #
# Phase 1 -- SyntheticTargetSet
# --------------------------------------------------------------------------- #


class DomainPattern(str, Enum):
    TYPOSQUAT = "typosquat"
    HOMOGLYPH = "homoglyph"
    SUBDOMAIN = "subdomain"
    COMBOSQUAT = "combosquat"


class AttackSurfaceType(str, Enum):
    MAIL_SERVER = "mail_server"
    LOGIN_FORM = "login_form"
    API = "api"
    PORTAL = "portal"


class AttackSurface(BaseModel):
    type: AttackSurfaceType
    value: str = Field(..., min_length=1, max_length=253)


class SyntheticTarget(BaseModel):
    target_id: TargetId
    synthetic_domain: str = Field(..., min_length=1, max_length=253)
    domain_pattern: DomainPattern
    attack_surfaces: list[AttackSurface] = Field(..., min_length=1)


class SyntheticTargetSet(BaseModel):
    PERSISTENCE: ClassVar[PersistencePolicy] = PersistencePolicy(
        store="synthetic-datasets", retention_days=180, pii=PiiClass.SYNTHETIC
    )

    campaign_id: CampaignId
    source: str = Field(..., pattern=r"^synthetic$")
    target_count: int = Field(..., ge=1)
    targets: list[SyntheticTarget] = Field(..., min_length=1)

    @model_validator(mode="after")
    def _count_and_ids_consistent(self) -> "SyntheticTargetSet":
        if self.target_count != len(self.targets):
            raise ValueError("target_count must equal len(targets)")
        _require_unique([t.target_id for t in self.targets], "target_id")
        return self


# --------------------------------------------------------------------------- #
# Phase 2 -- ProfileDataset
# --------------------------------------------------------------------------- #


class ProfileAttributes(BaseModel):
    seniority: str = Field(..., max_length=40)
    devices: list[str] = Field(default_factory=list)
    language: Locale = "en"
    language_patterns: list[str] = Field(default_factory=list)


class SyntheticProfile(BaseModel):
    profile_id: ProfileId
    target_id: TargetId
    recipient: Recipient
    attributes: ProfileAttributes
    labels: dict[str, str] = Field(default_factory=dict)


class ProfileDataset(BaseModel):
    PERSISTENCE: ClassVar[PersistencePolicy] = PersistencePolicy(
        store="synthetic-datasets", retention_days=180, pii=PiiClass.SYNTHETIC
    )

    campaign_id: CampaignId
    source: str = Field(..., pattern=r"^synthetic$")
    format: str = Field(default="json", pattern=r"^(json|csv)$")
    record_count: int = Field(..., ge=1)
    profiles: list[SyntheticProfile] = Field(..., min_length=1)

    @model_validator(mode="after")
    def _count_and_ids_consistent(self) -> "ProfileDataset":
        if self.record_count != len(self.profiles):
            raise ValueError("record_count must equal len(profiles)")
        _require_unique([p.profile_id for p in self.profiles], "profile_id")
        return self


# --------------------------------------------------------------------------- #
# Phase 3 -- TemplateSet (Design-AG)
# --------------------------------------------------------------------------- #


class Template(BaseModel):
    template_id: TemplateId
    channel: Channel
    pretext: Pretext
    tone: Tone = Tone.NEUTRAL
    difficulty: Difficulty = Difficulty.MEDIUM
    language: Locale = "en"
    subject: Optional[str] = Field(default=None, max_length=200)
    body: str = Field(..., min_length=1)
    variables: list[str] = Field(default_factory=list)
    ab_variant: str = Field(default="A", pattern=r"^[A-Z]$")

    @model_validator(mode="after")
    def _email_requires_subject(self) -> "Template":
        if self.channel == Channel.EMAIL and not self.subject:
            raise ValueError("email templates require a subject")
        return self


class TemplateSet(BaseModel):
    PERSISTENCE: ClassVar[PersistencePolicy] = PersistencePolicy(
        store="campaign-content", retention_days=365, pii=PiiClass.NONE
    )

    campaign_id: CampaignId
    templates: list[Template] = Field(..., min_length=1)

    @model_validator(mode="after")
    def _template_ids_unique(self) -> "TemplateSet":
        _require_unique([t.template_id for t in self.templates], "template_id")
        return self


# --------------------------------------------------------------------------- #
# Phase 3 -- PayloadAssets (Payload-AG)
# --------------------------------------------------------------------------- #


class AssetType(str, Enum):
    TRACKING_LINK = "tracking_link"
    ATTACHMENT = "attachment"
    MIRROR_PAGE = "mirror_page"


class PayloadAsset(BaseModel):
    asset_id: AssetId
    type: AssetType
    simulated: bool
    linked_template_id: Optional[TemplateId] = None
    # tracking_link fields
    landing_url: Optional[HttpUrl] = None
    tracking_token: Optional[str] = Field(default=None, max_length=64)
    # attachment / mirror_page fields
    filename: Optional[str] = Field(default=None, max_length=200)
    content_ref: Optional[SandboxRef] = None

    @field_validator("simulated")
    @classmethod
    def _must_be_simulated(cls, value: bool) -> bool:
        if not value:
            raise ValueError("payload assets must be simulated")
        return value

    @model_validator(mode="after")
    def _type_specific_fields_present(self) -> "PayloadAsset":
        if self.type == AssetType.TRACKING_LINK:
            if self.landing_url is None or not self.tracking_token:
                raise ValueError(
                    "tracking_link requires landing_url and tracking_token"
                )
        else:  # attachment or mirror_page must live in the sandbox
            if self.content_ref is None:
                raise ValueError(f"{self.type.value} requires a sandbox content_ref")
        return self


class PayloadAssets(BaseModel):
    PERSISTENCE: ClassVar[PersistencePolicy] = PersistencePolicy(
        store="sandbox-assets", retention_days=90, pii=PiiClass.NONE
    )

    campaign_id: CampaignId
    assets: list[PayloadAsset] = Field(..., min_length=1)

    @model_validator(mode="after")
    def _asset_ids_unique(self) -> "PayloadAssets":
        _require_unique([a.asset_id for a in self.assets], "asset_id")
        return self


# --------------------------------------------------------------------------- #
# Phase 4 -- DeploymentManifest
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
# Phase 5 -- InteractionEvent
# --------------------------------------------------------------------------- #


class CallDirection(str, Enum):
    INBOUND = "inbound"
    OUTBOUND = "outbound"


class InteractionContext(BaseModel):
    call_direction: Optional[CallDirection] = None
    transcript_ref: Optional[SandboxRef] = None


class InteractionEvent(BaseModel):
    PERSISTENCE: ClassVar[PersistencePolicy] = PersistencePolicy(
        store="interaction-log", retention_days=365, pii=PiiClass.SENSITIVE
    )

    campaign_id: CampaignId
    event_id: EventId
    generation_id: UUID
    profile_id: ProfileId
    channel: Channel
    action: CallToActionType
    occurred_at: datetime
    context: InteractionContext = Field(default_factory=InteractionContext)

    @field_validator("occurred_at")
    @classmethod
    def _must_be_timezone_aware(cls, value: datetime) -> datetime:
        if value.tzinfo is None:
            raise ValueError("occurred_at must be timezone-aware (UTC)")
        return value

    @model_validator(mode="after")
    def _call_direction_only_for_voice(self) -> "InteractionEvent":
        if self.context.call_direction and self.channel != Channel.VOICE:
            raise ValueError("call_direction only applies to the voice channel")
        return self


# --------------------------------------------------------------------------- #
# Phase 5 -- InteractionResult
# --------------------------------------------------------------------------- #


class Card(str, Enum):
    A = "A"
    B = "B"
    C = "C"


class CardType(str, Enum):
    CREDENTIALS = "credentials"
    FAKE_SUPPORT = "fake_support"
    VERIFICATION_FORM = "verification_form"


class Outcome(str, Enum):
    SUBMITTED = "submitted"
    IGNORED = "ignored"
    REPORTED = "reported"
    BOUNCED = "bounced"


_CARD_TO_TYPE = {
    Card.A: CardType.CREDENTIALS,
    Card.B: CardType.FAKE_SUPPORT,
    Card.C: CardType.VERIFICATION_FORM,
}


class InteractionResult(BaseModel):
    PERSISTENCE: ClassVar[PersistencePolicy] = PersistencePolicy(
        store="interaction-log", retention_days=365, pii=PiiClass.SENSITIVE
    )

    campaign_id: CampaignId
    event_id: EventId
    profile_id: ProfileId
    selected_card: Card
    card_type: CardType
    channel: Channel
    outcome: Outcome
    # Persistence rule: field NAMES only -- captured values are never stored.
    captured_fields: list[FieldName] = Field(default_factory=list)
    response_ref: Optional[SandboxRef] = None
    logged_at: datetime

    @field_validator("logged_at")
    @classmethod
    def _must_be_timezone_aware(cls, value: datetime) -> datetime:
        if value.tzinfo is None:
            raise ValueError("logged_at must be timezone-aware (UTC)")
        return value

    @model_validator(mode="after")
    def _card_matches_type(self) -> "InteractionResult":
        if _CARD_TO_TYPE[self.selected_card] != self.card_type:
            raise ValueError(
                f"card_type must be {_CARD_TO_TYPE[self.selected_card].value} "
                f"for card {self.selected_card.value}"
            )
        if self.outcome != Outcome.SUBMITTED and self.captured_fields:
            raise ValueError("captured_fields is only valid when outcome=submitted")
        return self


# --------------------------------------------------------------------------- #
# Phase 6 -- MetricsReport
# --------------------------------------------------------------------------- #


class ReportWindow(BaseModel):
    from_: datetime = Field(..., alias="from")
    to: datetime

    model_config = {"populate_by_name": True}

    @model_validator(mode="after")
    def _window_ordered_and_aware(self) -> "ReportWindow":
        if self.from_.tzinfo is None or self.to.tzinfo is None:
            raise ValueError("window bounds must be timezone-aware (UTC)")
        if self.to < self.from_:
            raise ValueError("window 'to' must not precede 'from'")
        return self


class CampaignKpis(BaseModel):
    delivered: int = Field(..., ge=0)
    opened: int = Field(..., ge=0)
    clicked: int = Field(..., ge=0)
    converted: int = Field(..., ge=0)
    reported_as_spam: int = Field(..., ge=0)
    delivery_rate: float = Field(..., ge=0.0, le=1.0)
    open_rate: float = Field(..., ge=0.0, le=1.0)
    click_rate: float = Field(..., ge=0.0, le=1.0)
    conversion_rate: float = Field(..., ge=0.0, le=1.0)
    bounce_rate: float = Field(..., ge=0.0, le=1.0)

    @model_validator(mode="after")
    def _funnel_is_monotonic(self) -> "CampaignKpis":
        # A recipient cannot open without delivery, click without opening, etc.
        if not (self.converted <= self.clicked <= self.opened <= self.delivered):
            raise ValueError(
                "funnel must be monotonic: "
                "converted <= clicked <= opened <= delivered"
            )
        if self.reported_as_spam > self.delivered:
            raise ValueError("reported_as_spam cannot exceed delivered")
        return self


class MetricsReport(BaseModel):
    PERSISTENCE: ClassVar[PersistencePolicy] = PersistencePolicy(
        store="metrics-warehouse", retention_days=730, pii=PiiClass.NONE
    )

    campaign_id: CampaignId
    window: ReportWindow
    kpis: CampaignKpis
    anomalies: list[str] = Field(default_factory=list)
    exploit_successful: bool


# --------------------------------------------------------------------------- #
# Phase 7 -- FeedbackDirective
# --------------------------------------------------------------------------- #


class DirectiveAction(str, Enum):
    OPTIMIZE_TEMPLATES = "optimize_templates"
    UPDATE_PROFILES = "update_profiles"
    ADJUST_PARAMETERS = "adjust_parameters"


_ACTION_TO_AGENT = {
    DirectiveAction.OPTIMIZE_TEMPLATES: Agent.DESIGN,
    DirectiveAction.UPDATE_PROFILES: Agent.HARVEST,
    DirectiveAction.ADJUST_PARAMETERS: Agent.ORCHESTRATOR,
}


class FeedbackItem(BaseModel):
    target_agent: Agent
    action: DirectiveAction
    reason: Optional[str] = Field(default=None, max_length=120)
    template_ids: list[TemplateId] = Field(default_factory=list)
    profile_ids: list[ProfileId] = Field(default_factory=list)
    observed: dict[str, bool] = Field(default_factory=dict)

    @model_validator(mode="after")
    def _action_targets_correct_agent(self) -> "FeedbackItem":
        expected = _ACTION_TO_AGENT[self.action]
        if self.target_agent != expected:
            raise ValueError(
                f"action {self.action.value} must target {expected.value}"
            )
        return self


class FeedbackDirective(BaseModel):
    PERSISTENCE: ClassVar[PersistencePolicy] = PersistencePolicy(
        store="feedback-log", retention_days=365, pii=PiiClass.NONE
    )

    campaign_id: CampaignId
    exploit_successful: bool
    directives: list[FeedbackItem] = Field(..., min_length=1)
    parameter_adjustments: dict[str, str] = Field(default_factory=dict)

    @model_validator(mode="after")
    def _failure_requires_adjustments(self) -> "FeedbackDirective":
        if not self.exploit_successful and not self.parameter_adjustments:
            raise ValueError(
                "parameter_adjustments are required when exploit_successful is false"
            )
        return self
