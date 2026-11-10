"""Stage 2: deterministic assembler. No LLM, no randomness."""

from __future__ import annotations

import json
import re
from datetime import datetime, timedelta

from google.adk.agents import BaseAgent
from google.adk.events import Event, EventActions
from google.genai import types

from generator_agent.assemble import assemble_campaign

_LABELS = (
    ("PERSONA_NAME", "display name"),
    ("PERSONA_ROLE", "role"),
    ("PERSONA_EMAIL", "from address"),
    ("EMAIL_SUBJECT", "subject"),
    ("EMAIL_BODY", "body"),
    ("EMAIL_TIME", "scheduled at"),
    ("SMS_BODY", "body"),
    ("SMS_TIME", "scheduled at"),
)


def parse_bindings(text: str) -> dict[str, str]:
    """Extract the 8 bindings from the content agent's reply, in label order."""
    lines = [
        re.sub(r"^[\s\-*•>]+", "", line).strip()
        for line in text.splitlines()
        if line.strip()
    ]
    bindings: dict[str, str] = {}
    cursor = 0
    for key, label in _LABELS:
        while cursor < len(lines) and f"{label}:" not in lines[cursor].lower():
            cursor += 1
        if cursor >= len(lines):
            raise ValueError(f"bindings missing '{label}'")
        bindings[key] = lines[cursor].split(":", 1)[-1].strip()
        cursor += 1
    for key, value in bindings.items():
        # Square brackets are the model's own prompt labels ([EMAIL_BODY] ...);
        # angle brackets are example placeholders (<recipient first name> ...).
        # Either means a substitution was skipped, so reject rather than emit
        # a placeholder a recipient would see verbatim.
        if "[" in value or "]" in value or "<" in value or ">" in value:
            raise ValueError(
                f"binding {key} echoed a prompt placeholder instead of a value: "
                f"{value!r}"
            )
    # Some models (qwen3:4b especially) embed literal ``\n`` (backslash-n) into
    # a body when they write it to a single escaped line. Unescape so the
    # delivered artifact carries real line breaks, not backslash-n text a
    # recipient would see verbatim. Applied to every binding: only the two body
    # bindings ever contain prose with line breaks, and unescaping the others
    # is a no-op.
    for key in bindings:
        value = bindings[key]
        value = value.replace("\\n", "\n").replace("\\t", "\t")
        value = value.replace("\\\\", "\\")
        bindings[key] = value
    return bindings


class AssemblerAgent(BaseAgent):
    """Deterministic assembly: bindings + spec -> GeneratedCampaign."""

    async def _run_async_impl(self, ctx):
        state = ctx.session.state
        spec = json.loads(state["campaign_spec"])
        mission = json.loads(state["mission_config"])
        profile = json.loads(state["profile"])
        raw = state.get("raw_bindings", "")
        bindings = parse_bindings(raw)

        start = datetime.fromisoformat(spec["start_at"].replace("Z", "+00:00"))
        email_at = start.isoformat().replace("+00:00", "Z")
        sms_at = (
            start + timedelta(minutes=spec["followup_minutes"])
        ).isoformat().replace("+00:00", "Z")

        campaign = assemble_campaign(
            bindings,
            mission,
            profile,
            spec["pretext"],
            spec["tone"],
            spec["difficulty"],
            generated_at=start,           # fixed clock (W1)
            scheduled=(email_at, sms_at),  # spec-derived schedule (W1)
            actual_model=spec.get("model"),
            runtime={"sdk": "google-adk", "adapter": "adk"},
            language=spec.get("language", "en"),
            # deterministic persona (pretext x recipient), not the model echo
            persona_override=profile.get("persona"),
            # unique per-run seed -> unique tracking token per campaign
            seed=spec.get("seed"),
            # per-run sampling params (temperature/top_p/max_tokens) -> provenance
            generation_params=spec.get("params"),
        )
        yield Event(
            author=self.name,
            actions=EventActions(
                state_delta={"generated_campaign": campaign.model_dump_json()}
            ),
            content=types.Content(
                role="model", parts=[types.Part(text="assembled campaign")]
            ),
        )
