#!/usr/bin/env python3
"""Generate architectural diagrams for a distributed phishing pipeline paper.

Context: controlled research investigation. The diagrams describe an
agent-based system architecture (boxes, arrows, phases) only -- there is
no operational tooling here. The content mirrors ``docs/architecture.md``.

Environment setup
-----------------
System Graphviz (the `dot` binary) is required:
    Linux : sudo apt-get install graphviz
    macOS : brew install graphviz

Python packages:
    pip install graphviz diagrams

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
    "intelligence": "#2980B9",    # blue
    "content": "#8E44AD",         # purple
    "execution": "#C0392B",       # red
    "monitor": "#16A085",         # teal
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
# Diagram 1 -- Overall System Architecture
# --------------------------------------------------------------------------- #

def diagram_1_system_architecture() -> str:
    dot = _base_graph("system_architecture", "Overall System Architecture")
    dot.attr(label="Diagram 1 -- Overall System Architecture",
             labelloc="t", fontsize="18", fontcolor="#2C3E50")

    # Sub-system clusters. Labels carry each agent's role from docs/architecture.md.
    with dot.subgraph(name="cluster_orchestration") as c:
        c.attr(label="Orchestration", style="rounded,filled",
               color=PALETTE["orchestration"], fillcolor="#EAECEE",
               fontcolor=PALETTE["orchestration"], fontsize="14")
        _agent_node(c, "orchestrator", "Orchestrator-AG\n(Coordination)",
                    PALETTE["orchestration"])
        _agent_node(c, "monitor", "Monitor-AG\n(Analytics)", PALETTE["monitor"])

    with dot.subgraph(name="cluster_intelligence") as c:
        c.attr(label="Data Intelligence", style="rounded,filled",
               color=PALETTE["intelligence"], fillcolor="#EAF2F8",
               fontcolor=PALETTE["intelligence"], fontsize="14")
        _agent_node(c, "recon", "Recon-AG\n(Intelligence: synthetic data)",
                    PALETTE["intelligence"])
        _agent_node(c, "harvest", "Harvest-AG\n(Collection)", PALETTE["intelligence"])

    with dot.subgraph(name="cluster_content") as c:
        c.attr(label="Content Generation", style="rounded,filled",
               color=PALETTE["content"], fillcolor="#F4ECF7",
               fontcolor=PALETTE["content"], fontsize="14")
        _agent_node(c, "design", "Design-AG\n(Creative)", PALETTE["content"])
        _agent_node(c, "payload", "Payload-AG\n(Technical)", PALETTE["content"])

    with dot.subgraph(name="cluster_execution") as c:
        c.attr(label="Execution", style="rounded,filled",
               color=PALETTE["execution"], fillcolor="#FDEDEC",
               fontcolor=PALETTE["execution"], fontsize="14")
        _agent_node(c, "responder",
                    "Responder-AG\n(Interaction: email / SMS / voice)",
                    PALETTE["execution"])

    # Main data / control flow (mirrors the docs/architecture.md communication graph).
    dot.edge("orchestrator", "recon", label="start recon")
    dot.edge("recon", "harvest", label="synthetic targets")
    dot.edge("harvest", "design", label="synthetic profiles")
    dot.edge("harvest", "payload", label="synthetic profiles")
    dot.edge("design", "orchestrator", label="templates")
    dot.edge("payload", "orchestrator", label="assets")
    dot.edge("orchestrator", "responder", label="deploy")
    dot.edge("responder", "monitor", label="interactions")

    # Monitor's success-driven optimisation fan-out.
    dot.edge("monitor", "orchestrator", label="feedback / adjust",
             style="dashed", color=PALETTE["monitor"], fontcolor=PALETTE["monitor"])
    dot.edge("monitor", "design", label="optimise", style="dashed",
             color=PALETTE["monitor"], fontcolor=PALETTE["monitor"],
             constraint="false")
    dot.edge("monitor", "harvest", label="enrich", style="dashed",
             color=PALETTE["monitor"], fontcolor=PALETTE["monitor"],
             constraint="false")

    return _render(dot, "diagram_1")


# --------------------------------------------------------------------------- #
# Diagram 2 -- Data & Artifact Flow Across Phases
# --------------------------------------------------------------------------- #

def diagram_2_artifact_flow() -> str:
    dot = _base_graph("artifact_flow", "Data & Artifact Flow", rankdir="LR")
    dot.attr(label="Diagram 2 -- Data & Artifact Flow Across Phases",
             labelloc="t", fontsize="18", fontcolor="#2C3E50")
    dot.attr("node", shape="box", style="filled,rounded")

    # Phases 0-7 follow docs/architecture.md (Phase 5 = Responder-AG interaction handling).
    phases = [
        ("p0", "Phase 0: Planning (Orchestrator-AG)",
         "Objectives, parameters & ethics rules"),
        ("p1", "Phase 1: Synthetic Recon (Recon-AG)",
         "Synthetic targets + attack surfaces"),
        ("p2", "Phase 2: Dataset Construction (Harvest-AG)",
         "Labeled synthetic dataset (JSON/CSV)"),
        ("p3", "Phase 3: Content Generation (Design-AG + Payload-AG)",
         "Campaign set ready to deploy"),
        ("p4", "Phase 4: Controlled Launch (Orchestrator-AG)",
         "Segmented batches + send schedule"),
        ("p5", "Phase 5: Interaction Handling (Responder-AG)",
         "Interaction transcripts (email / SMS / voice)"),
        ("p6", "Phase 6: Monitoring & KPIs (Monitor-AG)",
         "KPIs, dashboards & anomaly alerts"),
        ("p7", "Phase 7: Feedback (Orchestrator-AG + Monitor-AG)",
         "Updated dataset & optimized templates"),
    ]

    for node_id, title, artifact in phases:
        label = f"{title}\n----------\nArtifact: {artifact}"
        dot.node(node_id, label, fillcolor="#EAF2F8",
                 color=PALETTE["intelligence"], fontcolor="#1B2631")

    for (a, _, _), (b, _, _) in zip(phases, phases[1:]):
        dot.edge(a, b)

    # Iterative-refinement feedback loops from Phase 7 back upstream.
    dot.edge("p7", "p2", label="update profiles", style="dashed",
             color=PALETTE["monitor"], fontcolor=PALETTE["monitor"],
             constraint="false")
    dot.edge("p7", "p3", label="refine templates", style="dashed",
             color=PALETTE["monitor"], fontcolor=PALETTE["monitor"],
             constraint="false")

    return _render(dot, "diagram_2")


# --------------------------------------------------------------------------- #
# Diagram 3 -- Agent Communication Sequence Diagram
# --------------------------------------------------------------------------- #

def diagram_3_sequence() -> str:
    """UML-style sequence diagram emulated with Graphviz lifelines."""
    dot = _base_graph("sequence", "Agent Communication Sequence")
    dot.attr(label="Diagram 3 -- Agent Communication Sequence Diagram",
             labelloc="t", fontsize="18", fontcolor="#2C3E50")
    dot.attr(rankdir="TB", splines="false", nodesep="0.9", ranksep="0.35")

    participants = ["Orchestrator", "Recon", "Harvest",
                    "Design", "Payload", "Responder", "Monitor"]

    # (sender, receiver, label, is_return) -- mirrors the docs/architecture.md flow.
    messages = [
        ("Orchestrator", "Recon", "start recon", False),
        ("Recon", "Harvest", "synthetic targets", False),
        ("Harvest", "Design", "synthetic profiles", False),
        ("Harvest", "Payload", "synthetic profiles", False),
        ("Design", "Orchestrator", "templates", True),
        ("Payload", "Orchestrator", "payload assets", True),
        ("Orchestrator", "Responder", "deploy campaign", False),
        ("Responder", "Monitor", "log interactions", False),
        ("Monitor", "Orchestrator", "feedback / decision", True),
        ("Monitor", "Design", "optimize templates", False),
        ("Monitor", "Harvest", "update profiles", False),
    ]
    steps = len(messages)

    def lifeline_id(name: str, step: int) -> str:
        return f"{name}_{step}"

    # Header row: participant boxes at step 0.
    with dot.subgraph() as row:
        row.attr(rank="same")
        for name in participants:
            _agent_node(row, lifeline_id(name, 0), name, PALETTE["orchestration"])
        # Flat invisible edges lock the left-to-right participant order so
        # Graphviz cannot reshuffle columns to minimise crossings.
        for left, right in zip(participants, participants[1:]):
            row.edge(lifeline_id(left, 0), lifeline_id(right, 0),
                     style="invis")

    # Lifeline points for every subsequent time step.
    for step in range(1, steps + 1):
        with dot.subgraph() as row:
            row.attr(rank="same")
            for name in participants:
                row.node(lifeline_id(name, step), shape="point",
                         width="0.05", color="#95A5A6")

    # Vertical (dotted) lifelines keep each participant's column ordered.
    for name in participants:
        for step in range(steps):
            dot.edge(lifeline_id(name, step), lifeline_id(name, step + 1),
                     arrowhead="none", style="dotted", color="#B2BABB",
                     weight="10")

    # Horizontal message arrows at each time step.
    for idx, (src, dst, label, is_return) in enumerate(messages, start=1):
        dot.edge(
            lifeline_id(src, idx), lifeline_id(dst, idx),
            label=f"{idx}. {label}",
            style="dashed" if is_return else "solid",
            color=PALETTE["monitor"] if is_return else PALETTE["execution"],
            fontcolor="#2C3E50",
            constraint="false", weight="1",
            arrowsize="0.7",
        )

    return _render(dot, "diagram_3")


# --------------------------------------------------------------------------- #
# Diagram 4 -- Responder-AG Decision Tree (Tarjetas / Cards)
# --------------------------------------------------------------------------- #

def diagram_4_decision_tree() -> str:
    dot = _base_graph("responder_decision_tree", "Responder-AG Decision Tree")
    dot.attr(label="Diagram 4 -- Responder-AG Decision Tree (Tarjetas / Cards)",
             labelloc="t", fontsize="18", fontcolor="#2C3E50")
    dot.attr(ranksep="0.8")

    # Root event.
    _agent_node(dot, "event",
                "Interaction Event\n(email / SMS / voice call)",
                PALETTE["execution"])

    # Three response cards.
    dot.node("card_a", "Card A\nCredentials", shape="box",
             fillcolor="#F4ECF7", color=PALETTE["content"], fontcolor="#1B2631")
    dot.node("card_b", "Card B\nFake Support", shape="box",
             fillcolor="#F4ECF7", color=PALETTE["content"], fontcolor="#1B2631")
    dot.node("card_c", "Card C\nVerification Form", shape="box",
             fillcolor="#F4ECF7", color=PALETTE["content"], fontcolor="#1B2631")

    # Convergence and hand-off.
    dot.node("log", "Log Result", shape="box", fillcolor="#EAECEE",
             color=PALETTE["neutral"], fontcolor="#1B2631")
    _agent_node(dot, "monitor", "Monitor-AG", PALETTE["monitor"])

    dot.edge("event", "card_a", label="A")
    dot.edge("event", "card_b", label="B")
    dot.edge("event", "card_c", label="C")

    for card in ("card_a", "card_b", "card_c"):
        dot.edge(card, "log")

    dot.edge("log", "monitor", label="send")

    return _render(dot, "diagram_4")


# --------------------------------------------------------------------------- #
# Diagram 5 -- Feedback Loop & Continuous Optimisation
# --------------------------------------------------------------------------- #

def diagram_5_feedback_loop() -> str:
    dot = _base_graph("feedback_loop", "Feedback Loop & Continuous Optimisation")
    dot.attr(label="Diagram 5 -- Feedback Loop & Continuous Optimisation",
             labelloc="t", fontsize="18", fontcolor="#2C3E50")
    dot.attr(rankdir="TB", ranksep="0.9")

    _agent_node(dot, "monitor", "Monitor-AG\n(central hub)", PALETTE["monitor"])
    dot.node("decision", "Exploit\nsuccessful?", shape="diamond",
             style="filled", fillcolor="#FCF3CF", color="#B7950B",
             fontcolor="#7D6608")
    _agent_node(dot, "design", "Design-AG", PALETTE["content"])
    _agent_node(dot, "harvest", "Harvest-AG", PALETTE["intelligence"])
    _agent_node(dot, "orchestrator", "Orchestrator-AG", PALETTE["orchestration"])
    _agent_node(dot, "execution", "Execution\n(Launch & Responder)", PALETTE["execution"])

    # Monitor evaluates the outcome.
    dot.edge("monitor", "decision", label="KPIs")

    # Success branch: optimise content and enrich profiles.
    dot.edge("decision", "design", label="yes: template optimisation",
             color=PALETTE["monitor"], fontcolor=PALETTE["monitor"])
    dot.edge("decision", "harvest", label="yes: profile enrichment",
             color=PALETTE["monitor"], fontcolor=PALETTE["monitor"])

    # Failure branch: re-tune parameters straight back to the Orchestrator.
    dot.edge("decision", "orchestrator", label="no: parameter adjustment",
             style="dashed", color=PALETTE["neutral"], fontcolor=PALETTE["neutral"],
             constraint="false")

    # Both refinements feed the Orchestrator.
    dot.edge("design", "orchestrator", label="updated templates")
    dot.edge("harvest", "orchestrator", label="updated profiles")

    # Orchestrator drives execution, which reports back to Monitor.
    dot.edge("orchestrator", "execution", label="launch")
    dot.edge("execution", "monitor", label="results (close loop)",
             color=PALETTE["execution"], fontcolor=PALETTE["execution"])

    return _render(dot, "diagram_5")


# --------------------------------------------------------------------------- #
# Runner
# --------------------------------------------------------------------------- #

DIAGRAMS = [
    diagram_1_system_architecture,
    diagram_2_artifact_flow,
    diagram_3_sequence,
    diagram_4_decision_tree,
    diagram_5_feedback_loop,
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
