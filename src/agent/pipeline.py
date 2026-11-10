"""Google ADK pipeline: generate -> assemble -> verify (linear, no autonomy).

Root agent = SequentialAgent running, in order:
    generator_content_agent (LlmAgent)   -> raw_bindings
    assembler_agent         (BaseAgent)  -> generated_campaign
    validator_agent         (BaseAgent)  -> coherence_report

There is no Orchestrator-LLM: the SequentialAgent IS the orchestrator. The LLM
only writes content; ids, persona, URLs, references, schedule, and provenance
are decided by the deterministic assembler (generator_agent.assemble).
"""

from __future__ import annotations

import warnings

from google.adk.agents import LlmAgent, SequentialAgent
from google.genai import types

from agent.assembler import AssemblerAgent
from agent.config import resolve_model
from agent.model_trace import (
    after_model_callback,
    before_model_callback,
    on_model_error_callback,
)
from agent.validator import ValidatorAgent
from generator_agent.assemble import CHARTER

# SequentialAgent is deprecated in favor of Workflow in ADK >= 2.9; the
# Workflow (node/edge) API cannot yet express "run these three stages in
# order" as cleanly, so we keep SequentialAgent and silence the warning.
warnings.filterwarnings(
    "ignore", message=".*SequentialAgent is deprecated.*", category=DeprecationWarning
)

BINDINGS_CONTRACT = """

---
ANSWER FORMAT — answer with EXACTLY these 8 lines, one per line, no markdown,
no extra text:
- display name: <value>
- role: <value>
- from address: <value>
- subject: <value>
- body: <value>
- scheduled at: <value>
- body: <value>
- scheduled at: <value>
"""

_CONTENT_AGENT_DESCRIPTION = (
    "Emit the 8 content bindings (persona echo + email subject/body + SMS "
    "body) for one synthetic recipient. The persona is decided by the "
    "deterministic layer; this agent only echoes it and writes the prose."
)


def _generation_config(params: dict | None) -> types.GenerateContentConfig | None:
    """A per-run ``GenerateContentConfig`` from the spec's ``params`` block.

    ADK reads ``temperature`` / ``top_p`` / ``max_output_tokens`` out of the
    LlmRequest config at call time, so this is where semantic variety is
    injected. With no ``params`` block, default to temperature 0.9 so runs are
    diverse by default (the old path pinned 0.0 and mode-collapsed).
    """
    config_kwargs: dict = {"temperature": 0.9} if not params else {}
    if params:
        for src, dst in (
            ("temperature", "temperature"),
            ("top_p", "top_p"),
            ("max_tokens", "max_output_tokens"),
            ("seed", "seed"),
        ):
            value = params.get(src)
            if value is not None:
                config_kwargs[dst] = value
    return types.GenerateContentConfig(**config_kwargs)


def build_content_agent(params: dict | None = None) -> LlmAgent:
    """The content LlmAgent, optionally carrying per-run generation params."""
    return LlmAgent(
        model=resolve_model(),
        name="generator_content_agent",
        description=_CONTENT_AGENT_DESCRIPTION,
        # ADK renders this instruction with {var} state injection — any brace
        # group whose inner text is a valid identifier raises KeyError. The
        # {{cta-link}} placeholder is identifier-invalid on purpose (see
        # generator_agent.assemble.LINK_PLACEHOLDER and test_refinement.py).
        instruction=CHARTER + BINDINGS_CONTRACT,
        output_key="raw_bindings",
        generate_content_config=_generation_config(params),
        # Full-trace hooks: no-ops unless ADK_MODEL_TRACE_FILE is set (the
        # experiment harness points it at output-<model>/llm_trace.jsonl so
        # every model's thinking process is saved next to its artifacts).
        before_model_callback=before_model_callback,
        after_model_callback=after_model_callback,
        on_model_error_callback=on_model_error_callback,
    )


def build_pipeline(params: dict | None = None) -> SequentialAgent:
    """A fresh SequentialAgent; ``params`` carries per-run generation settings."""
    return SequentialAgent(
        name="campaign_generator_pipeline",
        sub_agents=[
            build_content_agent(params),
            AssemblerAgent(name="assembler_agent"),
            ValidatorAgent(name="validator_agent"),
        ],
        description=(
            "Configurable, reproducible generator of synthetic phishing-simulation "
            "campaigns (email + SMS) for authorized security-awareness research."
        ),
    )


# Default single pipeline (temperature/provider defaults) kept as the module
# global for CLI/tests that import ``root_agent`` directly.
generator_content_agent = build_content_agent()
root_agent = SequentialAgent(
    name="campaign_generator_pipeline",
    sub_agents=[
        generator_content_agent,
        AssemblerAgent(name="assembler_agent"),
        ValidatorAgent(name="validator_agent"),
    ],
    description=(
        "Configurable, reproducible generator of synthetic phishing-simulation "
        "campaigns (email + SMS) for authorized security-awareness research."
    ),
)
