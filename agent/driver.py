"""Programmatic driver for the ADK pipeline (used by the CLI and the harness).

Seeds the session with the campaign spec, mission, and profile, runs the
SequentialAgent through the ADK Runner, and returns the GeneratedCampaign and
CoherenceReport read back from session state.

The content agent's 8-line answer is validated by the deterministic assembler;
if an attempt produces no valid campaign (e.g. the model echoed a placeholder),
the run is retried with a stricter format instruction — request-level rejection
sampling, mirroring the pre-ADK DeepSeek adapter.
"""

from __future__ import annotations

import asyncio
import json

from google.adk.runners import Runner
from google.adk.sessions import InMemorySessionService
from google.genai import types

from agent.pipeline import root_agent
from app.core.schemas import CoherenceReport, GeneratedCampaign

APP_NAME = "campaign-pipeline"
USER_ID = "operator"
MAX_ATTEMPTS = 3

STRICT_FORMAT = (
    "\n\nAnswer with EXACTLY these 8 lines, one per line, no markdown, no extra "
    "text — replace every <value> with real content, never echo the bracketed "
    "labels:\n"
    "- display name: <value>\n"
    "- role: <value>\n"
    "- from address: <value>\n"
    "- subject: <value>\n"
    "- body: <value>\n"
    "- scheduled at: <value>\n"
    "- body: <value>\n"
    "- scheduled at: <value>"
)


def render_user_message(spec: dict, mission: dict, profile: dict) -> str:
    """The user turn given to the content agent.

    Delegates to ``generator_agent.assemble.user_prompt`` so the message sent
    matches the prompt whose hash is recorded in provenance.
    """
    from generator_agent.assemble import user_prompt

    return user_prompt(
        mission,
        profile,
        spec["pretext"],
        spec["tone"],
        spec["difficulty"],
        language=spec.get("language", "en"),
    )


async def _attempt(spec, mission, profile, strict: bool):
    """One pipeline run: seed state, run the Runner, read back the artifacts."""
    svc = InMemorySessionService()
    session = await svc.create_session(
        app_name=APP_NAME,
        user_id=USER_ID,
        state={
            "campaign_spec": json.dumps(spec),
            "mission_config": json.dumps(mission),
            "profile": json.dumps(profile),
        },
    )
    runner = Runner(agent=root_agent, app_name=APP_NAME, session_service=svc)
    message = render_user_message(spec, mission, profile) + (
        STRICT_FORMAT if strict else ""
    )
    async for _event in runner.run_async(
        user_id=USER_ID,
        session_id=session.id,
        new_message=types.Content(
            role="user", parts=[types.Part(text=message)]
        ),
    ):
        pass
    final = await svc.get_session(
        app_name=APP_NAME, user_id=USER_ID, session_id=session.id
    )
    state = final.state
    campaign = GeneratedCampaign.model_validate_json(state["generated_campaign"])
    report = CoherenceReport.model_validate_json(state["coherence_report"])
    return campaign, report


async def _run_async(
    spec: dict, mission: dict, profile: dict | None
) -> tuple[GeneratedCampaign, CoherenceReport]:
    if profile is None:
        from generator_agent.catalog import profile_for

        profile = profile_for(spec["recipient_id"])

    last_error: Exception | None = None
    for attempt in range(1, MAX_ATTEMPTS + 1):
        try:
            return await _attempt(spec, mission, profile, strict=attempt > 1)
        except Exception as exc:  # parse/validation/provider failures -> retry
            last_error = exc
            print(
                f"attempt {attempt}/{MAX_ATTEMPTS} produced no valid campaign "
                f"({type(exc).__name__}: {exc}); retrying"
            )
    raise RuntimeError(
        f"no valid campaign after {MAX_ATTEMPTS} attempts: {last_error}"
    )


def run_pipeline(
    spec: dict, mission: dict, profile: dict | None = None
) -> tuple[GeneratedCampaign, CoherenceReport]:
    """Synchronous wrapper: one spec -> (campaign, report)."""
    return asyncio.run(_run_async(spec, mission, profile))
