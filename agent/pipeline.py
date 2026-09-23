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
        "Emit the 8 content bindings (persona + email subject/body + SMS body) "
        "for one synthetic recipient."
    ),
    instruction=CHARTER + BINDINGS_CONTRACT,
    output_key="raw_bindings",
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
