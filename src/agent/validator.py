"""Stage 3: deterministic validator. No LLM, no randomness."""

from __future__ import annotations

from google.adk.agents import BaseAgent
from google.adk.events import Event, EventActions
from google.genai import types

from app.core.schemas import GeneratedCampaign
from validator_agent.validate import validate_campaign


class ValidatorAgent(BaseAgent):
    """Deterministic validation: GeneratedCampaign -> CoherenceReport."""

    async def _run_async_impl(self, ctx):
        state = ctx.session.state
        campaign = GeneratedCampaign.model_validate_json(state["generated_campaign"])
        report = validate_campaign(campaign)  # always returns, never raises
        yield Event(
            author=self.name,
            actions=EventActions(
                state_delta={"coherence_report": report.model_dump_json()}
            ),
            content=types.Content(
                role="model", parts=[types.Part(text="coherence report")],
            ),
        )
