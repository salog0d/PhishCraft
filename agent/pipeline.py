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

generator_content_agent = LlmAgent(
    model=resolve_model(),
    name="generator_content_agent",
    description=(
        "Emit the 8 content bindings (persona echo + email subject/body + SMS "
        "body) for one synthetic recipient. The persona is decided by the "
        "deterministic layer; this agent only echoes it and writes the prose."
    ),
    # ADK renders this instruction with {var} state injection — any brace
    # group whose inner text is a valid identifier raises KeyError. The
    # {{cta-link}} placeholder is identifier-invalid on purpose (see
    # generator_agent.assemble.LINK_PLACEHOLDER and test_refinement.py).
    instruction=CHARTER + BINDINGS_CONTRACT,
    output_key="raw_bindings",
    # Full-trace hooks: no-ops unless ADK_MODEL_TRACE_FILE is set (the
    # experiment harness points it at output-<model>/llm_trace.jsonl so every
    # model's thinking process is saved next to its artifacts).
    before_model_callback=before_model_callback,
    after_model_callback=after_model_callback,
    on_model_error_callback=on_model_error_callback,
)

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
