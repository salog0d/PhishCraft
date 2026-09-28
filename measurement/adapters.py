"""Adapters for the measurement harness.

- ``AdkPipelineAdapter`` — the real path: drives the ADK pipeline
  (``agent.driver.run_pipeline``) so the measured artifact is the actual ADK
  output. The model is whatever the ADK config resolves from the environment.
- ``StubAdapter`` — offline path: fixed bindings through the same
  deterministic assembler + validator, no LLM, no API key. For testing the
  harness and CI only.
"""

from __future__ import annotations

from generator_agent.catalog import profile_for

# Fixed offline bindings (mirror the 8-binding contract of the content agent).
# The persona bindings are placeholders: the deterministic persona derived from
# the (pretext, recipient) pair overrides them in ``assemble_campaign``.
STUB_BINDINGS = {
    "PERSONA_NAME": "IT Service Desk",
    "PERSONA_ROLE": "IT Service Desk",
    "PERSONA_EMAIL": "helpdesk@fantazylabz.tech",
    "EMAIL_SUBJECT": "Action required before end of day",
    "EMAIL_BODY": "Please review the summary we discussed and confirm today.",
    "EMAIL_TIME": "2026-08-20T09:00:00Z",
    "SMS_BODY": "Did you get my email? Please confirm before end of day.",
    "SMS_TIME": "2026-08-20T10:15:00Z",
}


class AdkPipelineAdapter:
    """Real measurement path: the ADK SequentialAgent, driven by the Runner."""

    name = "adk"

    def run(self, spec: dict, mission: dict):
        from agent.driver import run_pipeline

        profile = profile_for(spec["recipient_id"], pretext=spec["pretext"])
        return run_pipeline(spec, mission, profile)


class StubAdapter:
    """Offline path: deterministic assembly + validation, no model call."""

    name = "stub"

    def run(self, spec: dict, mission: dict):
        from datetime import datetime, timezone

        from generator_agent.assemble import assemble_campaign
        from validator_agent.validate import validate_campaign

        profile = profile_for(spec["recipient_id"], pretext=spec["pretext"])
        campaign = assemble_campaign(
            STUB_BINDINGS,
            mission,
            profile,
            spec["pretext"],
            spec["tone"],
            spec["difficulty"],
            generated_at=datetime.fromisoformat(
                spec["start_at"].replace("Z", "+00:00")
            ).astimezone(timezone.utc),
            scheduled=(spec["start_at"], spec["start_at"]),
            persona_override=profile.get("persona"),
        )
        return campaign, validate_campaign(campaign)


ADAPTERS = {
    "adk": AdkPipelineAdapter(),
    "stub": StubAdapter(),
}


def get_adapter(name: str):
    if name not in ADAPTERS:
        raise SystemExit(f"unknown adapter '{name}' (choose from {sorted(ADAPTERS)})")
    return ADAPTERS[name]
