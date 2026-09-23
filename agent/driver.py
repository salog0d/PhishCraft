"""Programmatic driver for the ADK pipeline (used by the CLI and the harness).

Seeds the session with the campaign spec, mission, and profile, runs the
SequentialAgent through the ADK Runner, and returns the GeneratedCampaign and
CoherenceReport read back from session state.
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


def render_user_message(spec: dict, profile: dict) -> str:
    """The user turn given to the content agent."""
    recipient = profile["recipient"]
    return (
        "Generate the campaign.\n"
        f"campaign_id={spec['campaign_id']}, pretext={spec['pretext']}, "
        f"tone={spec['tone']}, difficulty={spec['difficulty']}, "
        f"language={spec['language']}, seed={spec['seed']}.\n"
        f"Recipient: {recipient['full_name']} ({recipient['role']}, "
        f"{recipient['department']})."
    )


async def _run_async(
    spec: dict, mission: dict, profile: dict | None
) -> tuple[GeneratedCampaign, CoherenceReport]:
    if profile is None:
        from generator_agent.catalog import profile_for

        profile = profile_for(spec["recipient_id"])
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
    async for _event in runner.run_async(
        user_id=USER_ID,
        session_id=session.id,
        new_message=types.Content(
            role="user",
            parts=[types.Part(text=render_user_message(spec, profile))],
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


def run_pipeline(
    spec: dict, mission: dict, profile: dict | None = None
) -> tuple[GeneratedCampaign, CoherenceReport]:
    """Synchronous wrapper: one spec -> (campaign, report)."""
    return asyncio.run(_run_async(spec, mission, profile))
