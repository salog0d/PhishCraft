"""Programmatic driver for the ADK pipeline (used by the CLI and the harness).

Seeds the session with the campaign spec, mission, and profile, runs the
SequentialAgent through the ADK Runner, and returns the GeneratedCampaign and
CoherenceReport read back from session state.

Two feedback mechanisms operate at this level, both bounded and deterministic:

- **Request-level rejection sampling** — if an attempt produces no valid
  campaign (e.g. the model echoed a placeholder), the run is retried with a
  stricter format instruction, mirroring the pre-ADK DeepSeek adapter.
- **Self-refinement (Reflexion-style)** — if an attempt *parses* but the LLM
  wrote stale tracking tokens (its ``link_fixes`` are non-empty), the run is
  retried with a critique built from those fixes: what it wrote vs. the
  correct token, and the ``{{cta-link}}`` placeholder convention. Only
  subject/body text is regenerated — the deterministic layer is untouched, so
  the reproducibility guarantee is preserved.

The refinement critique is a *runtime amendment* to the prompt, exactly like
STRICT_FORMAT: it is not part of the prompt template, so the ``prompt_hash``
recorded in provenance stays the hash of the base rendered prompt.
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
MAX_ATTEMPTS = 3          # parse-level rejection sampling
REFINE_EXTRA_ATTEMPTS = 2  # refinement rounds once a campaign parses

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


def raw_link_violations(campaign: GeneratedCampaign) -> int:
    """Count the stale tracking tokens the LLM wrote (pre-assembler evidence).

    This is the refinement trigger: the post-assembler artifact never fails
    ``link_consistency`` (the assembler normalizes tokens), so the feedback
    signal must come from ``link_fixes``, not from the CoherenceReport.
    """
    return sum(len(m.link_fixes) for m in campaign.messages)


def build_refinement(campaign: GeneratedCampaign) -> str:
    """Turn the previous attempt's ``link_fixes`` into a critique instruction.

    Reflexion-style feedback without a critic LLM: the deterministic validator
    already knows exactly what went wrong. The critique lists what the model
    wrote vs. the correct token per field, then re-states the ``{{cta-link}}``
    placeholder convention — the only reliable fix, since the token is
    seed-derived and cannot be guessed or copied from examples.
    """
    lines = []
    for message in campaign.messages:
        token = (
            str(message.call_to_action.landing_url).rstrip("/").rsplit("/", 1)[-1]
        )
        for fix in message.link_fixes:
            lines.append(
                f"- {fix.field}: you wrote '{fix.replaced_token}', the correct "
                f"token is '{token}'"
            )
    return (
        "\n\nYour previous output violated the link rule. The tracking link "
        "is deterministic and cannot be guessed or copied from examples:\n"
        + "\n".join(lines)
        + "\nNever write URLs or tracking tokens anywhere. Where the link "
        "should appear, write exactly the placeholder {{cta-link}}. "
        "Rewrite the 8 lines fixing only the link text; keep everything "
        "else unchanged."
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


async def _attempt(
    spec, mission, profile, strict: bool, refinement: str | None = None
):
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
    message = render_user_message(spec, mission, profile)
    if refinement:
        message += refinement
    if strict:
        message += STRICT_FORMAT
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
) -> tuple[GeneratedCampaign, CoherenceReport, dict]:
    if profile is None:
        from generator_agent.catalog import profile_for

        profile = profile_for(spec["recipient_id"], pretext=spec["pretext"])

    # Phase 1 — parse-level rejection sampling (unchanged semantics): an
    # attempt that yields no valid campaign is retried with STRICT_FORMAT.
    last_error: Exception | None = None
    campaign = report = None
    attempts = 0
    for attempt in range(1, MAX_ATTEMPTS + 1):
        attempts = attempt
        try:
            campaign, report = await _attempt(
                spec, mission, profile, strict=attempt > 1
            )
            break
        except Exception as exc:  # parse/validation/provider failures -> retry
            last_error = exc
            print(
                f"attempt {attempt}/{MAX_ATTEMPTS} produced no valid campaign "
                f"({type(exc).__name__}: {exc}); retrying"
            )
    else:
        raise RuntimeError(
            f"no valid campaign after {MAX_ATTEMPTS} attempts: {last_error}"
        )

    # Phase 2 — self-refinement: a campaign that parses but carries stale
    # link tokens is regenerated with the critique from build_refinement.
    # The first-attempt violation count is kept for the reliability metric.
    info = {
        "n_attempts": attempts,
        "refined": False,
        "first_attempt_raw_link_violations": raw_link_violations(campaign),
    }
    for _ in range(REFINE_EXTRA_ATTEMPTS):
        if raw_link_violations(campaign) == 0:
            break
        info["refined"] = True
        info["n_attempts"] += 1
        critique = build_refinement(campaign)
        try:
            campaign, report = await _attempt(
                spec, mission, profile, strict=True, refinement=critique
            )
        except Exception as exc:
            # A refinement that fails to parse keeps the previous valid
            # campaign — the backstop (assembler normalization) still holds.
            print(
                f"refinement produced no valid campaign "
                f"({type(exc).__name__}: {exc}); keeping the previous attempt"
            )
            break
    return campaign, report, info


def run_pipeline(
    spec: dict, mission: dict, profile: dict | None = None
) -> tuple[GeneratedCampaign, CoherenceReport]:
    """Synchronous wrapper: one spec -> (campaign, report)."""
    campaign, report, _info = asyncio.run(_run_async(spec, mission, profile))
    return campaign, report


def run_pipeline_with_info(
    spec: dict, mission: dict, profile: dict | None = None
) -> tuple[GeneratedCampaign, CoherenceReport, dict]:
    """Synchronous wrapper: one spec -> (campaign, report, run_info).

    ``run_info`` carries the refinement metadata the reliability harness
    reports: ``n_attempts``, ``refined`` (whether any refinement round ran),
    and ``first_attempt_raw_link_violations`` (the pre-refinement raw metric).
    """
    return asyncio.run(_run_async(spec, mission, profile))
