#!/usr/bin/env python3
"""Generate architectural diagrams for the campaign generator paper.

Context: controlled research investigation. The diagrams describe the
three-stage Google ADK pipeline (generate -> assemble -> verify) plus the
measurement harness -- boxes, arrows, phases only; no operational tooling.
The content mirrors ``docs/architecture.md``.

Environment setup
-----------------
System Graphviz (the `dot` binary) is required:
    Linux : sudo apt-get install graphviz
    macOS : brew install graphviz

Python packages:
    pip install graphviz

Each diagram is rendered to a high-resolution PNG under ``diagrams_output/``
as ``diagram_1.png`` ... ``diagram_5.png``.
"""

from __future__ import annotations

import os
import sys

try:
    import graphviz
    from graphviz.backend import ExecutableNotFound
except ImportError:
    sys.exit(
        "The 'graphviz' Python package is not installed.\n"
        "Install it with:  pip install graphviz\n"
        "You also need the system Graphviz binary (apt-get install graphviz "
        "or brew install graphviz)."
    )

# --------------------------------------------------------------------------- #
# Shared configuration
# --------------------------------------------------------------------------- #

OUTPUT_DIR = os.path.join(
    os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "diagrams_output")
RENDER_DPI = "300"          # high-resolution export
FONT = "Helvetica"

# A restrained, professional palette keyed by logical sub-system.
PALETTE = {
    "orchestration": "#2C3E50",   # dark slate
    "content": "#8E44AD",         # purple (LLM content step)
    "deterministic": "#2980B9",   # blue (deterministic code)
    "verification": "#16A085",    # teal (validator)
    "evidence": "#C0392B",        # red (measurement / artifacts)
    "neutral": "#7F8C8D",         # grey
}


def _base_graph(name: str, comment: str, rankdir: str = "TB") -> graphviz.Digraph:
    """Create a Digraph with consistent house style applied."""
    dot = graphviz.Digraph(name=name, comment=comment, format="png")
    dot.attr(rankdir=rankdir, dpi=RENDER_DPI, bgcolor="white",
             fontname=FONT, splines="spline", nodesep="0.5", ranksep="0.7")
    dot.attr("node", fontname=FONT, fontsize="12", style="filled,rounded",
             shape="box", color="#34495E", fillcolor="#ECF0F1",
             fontcolor="#2C3E50", margin="0.18,0.12")
    dot.attr("edge", fontname=FONT, fontsize="10", color="#34495E",
             fontcolor="#34495E", arrowsize="0.8")
    return dot


def _agent_node(dot: graphviz.Digraph, node_id: str, label: str, fill: str) -> None:
    """Add a filled agent box with white text."""
    dot.node(node_id, label, fillcolor=fill, fontcolor="white",
             color=fill, penwidth="1.4")


def _render(dot: graphviz.Digraph, stem: str) -> str:
    """Render a graph to diagrams_output/<stem>.png and return its path."""
    path = dot.render(filename=stem, directory=OUTPUT_DIR, cleanup=True)
    return os.path.abspath(path)


# --------------------------------------------------------------------------- #
# Diagram 1 -- Overall System Architecture (ADK pipeline)
# --------------------------------------------------------------------------- #

def diagram_1_system_architecture() -> str:
    dot = _base_graph("system_architecture", "Overall System Architecture")
    dot.attr(label="Diagram 1 -- Overall System Architecture (ADK pipeline)",
             labelloc="t", fontsize="18", fontcolor="#2C3E50")

    # Inputs.
    dot.node("mission", "MissionConfig\n(config file)", shape="box",
             fillcolor="#EAECEE", color=PALETTE["orchestration"],
             fontcolor="#1B2631")
    dot.node("catalog", "TargetCatalog\n(12 internal + 3 external personas)\npersona_for(pretext, recipient)", shape="box",
             fillcolor="#EAECEE", color=PALETTE["orchestration"],
             fontcolor="#1B2631")

    # The ADK SequentialAgent cluster (the orchestrator).
    with dot.subgraph(name="cluster_pipeline") as c:
        c.attr(label="ADK SequentialAgent (the orchestrator — no autonomy)",
               style="rounded,filled", color=PALETTE["orchestration"],
               fillcolor="#F4F6F7", fontcolor=PALETTE["orchestration"],
               fontsize="14")
        _agent_node(c, "content", "1. generator_content_agent\n(LlmAgent)\ncontent bindings only",
                    PALETTE["content"])
        _agent_node(c, "assembler", "2. assembler_agent\n(BaseAgent, deterministic)\nids · URLs · schedule · provenance",
                    PALETTE["deterministic"])
        _agent_node(c, "validator", "3. validator_agent\n(BaseAgent, deterministic)\n5 coherence checks",
                    PALETTE["verification"])

    # Outputs.
    dot.node("campaign", "GeneratedCampaign\n(email + SMS)", shape="box",
             fillcolor="#EAECEE", color=PALETTE["neutral"], fontcolor="#1B2631")
    dot.node("report", "CoherenceReport\n(5 checks)", shape="box",
             fillcolor="#EAECEE", color=PALETTE["neutral"], fontcolor="#1B2631")

    # One-way flow; no feedback edge.
    dot.edge("mission", "content", label="spec")
    dot.edge("catalog", "content", label="recipient")
    dot.edge("content", "assembler", label="raw_bindings")
    dot.edge("assembler", "validator", label="generated_campaign")
    dot.edge("assembler", "campaign")
    dot.edge("validator", "report")

    return _render(dot, "diagram_1")


# --------------------------------------------------------------------------- #
# Diagram 2 -- Artifact Flow Across Phases
# --------------------------------------------------------------------------- #

def diagram_2_artifact_flow() -> str:
    dot = _base_graph("artifact_flow", "Data & Artifact Flow", rankdir="LR")
    dot.attr(label="Diagram 2 -- Data & Artifact Flow Across Phases",
             labelloc="t", fontsize="18", fontcolor="#2C3E50")
    dot.attr("node", shape="box", style="filled,rounded")

    phases = [
        ("p0", "Phase 0: Planning (config file)",
         "MissionConfig + CampaignSpec (fixed seed)"),
        ("p1", "Phase 1: Generation (Generator-AG)",
         "GeneratedCampaign (email + SMS, provenance)"),
        ("p2", "Phase 2: Verification (Validator-AG)",
         "CoherenceReport (5 checks) + ProvenanceLog"),
        ("p3", "Measurement (harness, drives ADK Runner)",
         "reproducibility.json + reliability.json + summary.md"),
    ]

    for node_id, title, artifact in phases:
        label = f"{title}\n----------\nArtifact: {artifact}"
        dot.node(node_id, label, fillcolor="#EAF2F8",
                 color=PALETTE["deterministic"], fontcolor="#1B2631")

    for (a, _, _), (b, _, _) in zip(phases, phases[1:]):
        dot.edge(a, b)

    # One-way only: verification feeds the measurement, never back into
    # generation (no success-optimization loop).
    dot.edge("p2", "p3", label="evidence")

    return _render(dot, "diagram_2")


# --------------------------------------------------------------------------- #
# Diagram 3 -- Pipeline Sequence (Runner through the three stages)
# --------------------------------------------------------------------------- #

def diagram_3_sequence() -> str:
    """Sequence of the ADK run: seed state, content, assemble, verify."""
    dot = _base_graph("sequence", "Pipeline Sequence")
    dot.attr(label="Diagram 3 -- Pipeline Sequence (one ADK run)",
             labelloc="t", fontsize="18", fontcolor="#2C3E50")
    dot.attr(rankdir="TB", splines="false", nodesep="0.9", ranksep="0.35")

    participants = ["Runner", "content\n(LlmAgent)", "assembler\n(BaseAgent)",
                    "validator\n(BaseAgent)", "Harness"]

    messages = [
        ("Runner", "content", "seed state (spec, mission, profile)", False),
        ("content", "assembler", "raw_bindings (state_delta)", False),
        ("assembler", "validator", "generated_campaign (state_delta)", False),
        ("validator", "Harness", "coherence_report (state_delta)", False),
    ]
    steps = len(messages)

    def lifeline_id(name: str, step: int) -> str:
        return f"{name}_{step}".replace("\n", "")

    with dot.subgraph() as row:
        row.attr(rank="same")
        for name in participants:
            _agent_node(row, lifeline_id(name, 0), name,
                        PALETTE["orchestration"])
        for left, right in zip(participants, participants[1:]):
            row.edge(lifeline_id(left, 0), lifeline_id(right, 0),
                     style="invis")

    for step in range(1, steps + 1):
        with dot.subgraph() as row:
            row.attr(rank="same")
            for name in participants:
                row.node(lifeline_id(name, step), shape="point",
                         width="0.05", color="#95A5A6")

    for name in participants:
        for step in range(steps):
            dot.edge(lifeline_id(name, step), lifeline_id(name, step + 1),
                     arrowhead="none", style="dotted", color="#B2BABB",
                     weight="10")

    for idx, (src, dst, label, _is_return) in enumerate(messages, start=1):
        dot.edge(
            lifeline_id(src, idx), lifeline_id(dst, idx),
            label=f"{idx}. {label}",
            style="solid",
            color=PALETTE["deterministic"],
            fontcolor="#2C3E50",
            constraint="false", weight="1",
            arrowsize="0.7",
        )

    return _render(dot, "diagram_3")


# --------------------------------------------------------------------------- #
# Diagram 4 -- The five coherence checks (the verification gate)
# --------------------------------------------------------------------------- #

def diagram_4_coherence_checks() -> str:
    dot = _base_graph("coherence_checks", "Coherence Checks")
    dot.attr(label="Diagram 4 -- The Five Coherence Checks (deterministic)",
             labelloc="t", fontsize="18", fontcolor="#2C3E50")
    dot.attr(ranksep="0.8")

    _agent_node(dot, "campaign", "GeneratedCampaign\n(persona + recipient + messages)",
                PALETTE["deterministic"])

    dot.node("c1", "persona_identity\nsender == persona\neverywhere",
             shape="box", fillcolor="#F4ECF7", color=PALETTE["content"],
             fontcolor="#1B2631")
    dot.node("c2", "timing\nfollow-up never precedes\nwhat it cites",
             shape="box", fillcolor="#F4ECF7", color=PALETTE["content"],
             fontcolor="#1B2631")
    dot.node("c3", "cross_channel_reference\nevery referenced id exists",
             shape="box", fillcolor="#F4ECF7", color=PALETTE["content"],
             fontcolor="#1B2631")
    dot.node("c4", "link_consistency\nbody links match the CTA;\nsame link across channels",
             shape="box", fillcolor="#F4ECF7", color=PALETTE["content"],
             fontcolor="#1B2631")
    dot.node("c5", "sender_recipient\npersona never impersonates\nits own recipient",
             shape="box", fillcolor="#F4ECF7", color=PALETTE["content"],
             fontcolor="#1B2631")

    _agent_node(dot, "report", "CoherenceReport\nall_passed = AND",
                PALETTE["verification"])

    for check in ("c1", "c2", "c3", "c4", "c5"):
        dot.edge("campaign", check)
        dot.edge(check, "report")

    return _render(dot, "diagram_4")


# --------------------------------------------------------------------------- #
# Diagram 5 -- Measurement harness (reproducibility + reliability)
# --------------------------------------------------------------------------- #

def diagram_5_measurement() -> str:
    dot = _base_graph("measurement", "Measurement Harness")
    dot.attr(label="Diagram 5 -- Measurement Harness (reproducibility + reliability)",
             labelloc="t", fontsize="18", fontcolor="#2C3E50")
    dot.attr(rankdir="TB", ranksep="0.9")

    dot.node("specs", "10 CampaignSpecs\n(S1..S10, seed 42 ...)", shape="box",
             fillcolor="#EAECEE", color=PALETTE["orchestration"],
             fontcolor="#1B2631")
    _agent_node(dot, "runner", "ADK Runner\n(adapter: adk | stub)",
                PALETTE["deterministic"])

    dot.node("repro", "Reproducibility\nsame spec x2\nidentical? + layer hash",
             shape="box", fillcolor="#F4ECF7", color=PALETTE["content"],
             fontcolor="#1B2631")
    dot.node("reliab", "Reliability\n10 specs\nviolations per check",
             shape="box", fillcolor="#F4ECF7", color=PALETTE["content"],
             fontcolor="#1B2631")

    dot.node("summary", "summary.md\nraw link rate (reliability)\n+ post rate (guarantee)",
             shape="box", fillcolor="#FDEDEC", color=PALETTE["evidence"],
             fontcolor="#1B2631")

    dot.edge("specs", "runner")
    dot.edge("runner", "repro", label="run twice")
    dot.edge("runner", "reliab", label="run all")
    dot.edge("repro", "summary")
    dot.edge("reliab", "summary")

    return _render(dot, "diagram_5")


# --------------------------------------------------------------------------- #
# Runner
# --------------------------------------------------------------------------- #

DIAGRAMS = [
    diagram_1_system_architecture,
    diagram_2_artifact_flow,
    diagram_3_sequence,
    diagram_4_coherence_checks,
    diagram_5_measurement,
]


def main() -> int:
    os.makedirs(OUTPUT_DIR, exist_ok=True)
    generated: list[str] = []

    for build in DIAGRAMS:
        try:
            generated.append(build())
        except ExecutableNotFound:
            print(
                "ERROR: The Graphviz 'dot' executable was not found.\n"
                "Install the system package and re-run:\n"
                "    Linux : sudo apt-get install graphviz\n"
                "    macOS : brew install graphviz\n"
                "    Windows: https://graphviz.org/download/",
                file=sys.stderr,
            )
            return 1

    print("\nGenerated diagrams:")
    for path in generated:
        print(f"  {path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
