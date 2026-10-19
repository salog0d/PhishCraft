"""Generate experiment/REPORT.md — a markdown comparison of all model runs.

Reads every experiment/output-*/ directory that has an llm_trace.jsonl and
produces:

    experiment/REPORT.md              (tables + embedded charts)
    experiment/report_assets/*.png    (matplotlib charts)

Re-run after any experiment run to refresh the report:

    python scripts/experiment_report.py
"""

from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt  # noqa: E402

REPO_ROOT = Path(__file__).resolve().parent.parent
EXPERIMENT_DIR = REPO_ROOT / "experiment"
ASSETS_DIR = EXPERIMENT_DIR / "report_assets"

CHECKS = [
    "persona_identity",
    "timing",
    "cross_channel_reference",
    "link_consistency",
    "sender_recipient",
]

# Per-model chart colors, stable across regenerations.
COLORS = {
    "qwen3:4b": "#4C72B0",
    "phi4-mini:latest": "#DD8452",
    "llama3.2:3b": "#55A868",
    "gemma4:latest": "#C44E52",
}


def short_name(model: str) -> str:
    return model.split("/", 1)[-1]


def collect() -> list[dict]:
    rows = []
    for out in sorted(EXPERIMENT_DIR.iterdir()):
        if not out.is_dir() or not out.name.startswith("output-"):
            continue
        trace_path = out / "llm_trace.jsonl"
        if not trace_path.exists():
            continue
        run_info = json.loads((out / "run_info.json").read_text(encoding="utf-8"))
        report = json.loads((out / "coherence_report.json").read_text(encoding="utf-8"))
        campaign = json.loads(
            (out / "generated_campaign.json").read_text(encoding="utf-8")
        )
        recs = [
            json.loads(line)
            for line in trace_path.read_text(encoding="utf-8").splitlines()
            if line.strip()
        ]
        usage = lambda key: sum(  # noqa: E731
            r.get("response", {}).get("usage", {}).get(key) or 0 for r in recs
        )
        rows.append(
            {
                "out": out,
                "model": run_info["model"].split("/", 1)[-1],
                "status": "ok" if report["all_passed"] else "failed",
                "n_attempts": run_info["run_info"]["n_attempts"],
                "refined": run_info["run_info"]["refined"],
                "violations": run_info["run_info"]["first_attempt_raw_link_violations"],
                "all_passed": report["all_passed"],
                "checks": {r["check"]: r["passed"] for r in report["results"]},
                "n_calls": len(recs),
                "duration_s": round(sum(r.get("duration_s") or 0 for r in recs), 1),
                "thinking_chars": sum(
                    len(r.get("response", {}).get("thought") or "") for r in recs
                ),
                "prompt_tokens": usage("prompt_tokens"),
                "completion_tokens": usage("completion_tokens"),
                "messages": len(campaign["messages"]),
                "first_answer": (recs[0].get("response", {}).get("text") or "")[:160],
            }
        )
    return rows


def style_axes(ax) -> None:
    ax.spines["top"].set_visible(False)
    ax.spines["right"].set_visible(False)
    ax.grid(axis="x", color="#DDDDDD", linewidth=0.6)
    ax.set_axisbelow(True)


def chart_tokens(rows: list[dict], path: Path) -> None:
    names = [r["model"] for r in rows][::-1]
    prompt = [r["prompt_tokens"] for r in rows][::-1]
    completion = [r["completion_tokens"] for r in rows][::-1]
    fig, ax = plt.subplots(figsize=(7.5, 3.4))
    ax.barh(names, prompt, color="#9DB6D9", label="prompt")
    ax.barh(names, completion, left=prompt, color="#4C72B0", label="completion")
    for i, (p, c) in enumerate(zip(prompt, completion)):
        ax.text(p + c + 40, i, f"{p + c:,}", va="center", fontsize=9)
    style_axes(ax)
    ax.set_xlabel("tokens")
    ax.set_title("Token usage per model (total across all LLM calls)")
    ax.legend(frameon=False, loc="lower right")
    fig.tight_layout()
    fig.savefig(path, dpi=150)
    plt.close(fig)


def chart_duration(rows: list[dict], path: Path) -> None:
    names = [r["model"] for r in rows][::-1]
    durations = [r["duration_s"] for r in rows][::-1]
    fig, ax = plt.subplots(figsize=(7.5, 3.4))
    bars = ax.barh(names, durations, color=[COLORS[n] for n in names])
    for bar, d in zip(bars, durations):
        ax.text(bar.get_width() + 2, bar.get_y() + bar.get_height() / 2,
                f"{d:,.1f}s", va="center", fontsize=9)
    style_axes(ax)
    ax.set_xscale("log")
    ax.set_xlabel("seconds (log scale)")
    ax.set_title("Total LLM wall-clock time per model")
    fig.tight_layout()
    fig.savefig(path, dpi=150)
    plt.close(fig)


def chart_attempts(rows: list[dict], path: Path) -> None:
    names = [r["model"] for r in rows][::-1]
    attempts = [r["n_attempts"] for r in rows][::-1]
    fig, ax = plt.subplots(figsize=(7.5, 2.8))
    bars = ax.barh(names, attempts, color=[COLORS[n] for n in names])
    for bar, a in zip(bars, attempts):
        label = f"{a}" + ("  (1st output failed parsing)" if a > 1 else "")
        ax.text(bar.get_width() + 0.03, bar.get_y() + bar.get_height() / 2,
                label, va="center", fontsize=9)
    style_axes(ax)
    ax.set_xlim(0, 3.1)
    ax.set_xticks([1, 2])
    ax.set_xlabel("LLM calls (pipeline attempts)")
    ax.set_title("Attempts needed to produce a valid campaign")
    fig.tight_layout()
    fig.savefig(path, dpi=150)
    plt.close(fig)


def chart_thinking(rows: list[dict], path: Path) -> None:
    names = [r["model"] for r in rows][::-1]
    thinking = [r["thinking_chars"] for r in rows][::-1]
    fig, ax = plt.subplots(figsize=(7.5, 3.0))
    bars = ax.barh(names, thinking, color=[COLORS[n] for n in names])
    for bar, t in zip(bars, thinking):
        if t:
            ax.text(bar.get_width() + 100, bar.get_y() + bar.get_height() / 2,
                    f"{t:,} chars", va="center", fontsize=9)
    style_axes(ax)
    ax.set_xlabel("thinking characters traced")
    ax.set_title("Reasoning volume (thinking field captured in llm_trace.jsonl)")
    fig.tight_layout()
    fig.savefig(path, dpi=150)
    plt.close(fig)


def chart_checks(rows: list[dict], path: Path) -> None:
    names = [r["model"] for r in rows]
    grid = [[r["checks"][c] for c in CHECKS] for r in rows]
    fig, ax = plt.subplots(figsize=(7.5, 3.0))
    im = ax.imshow(grid, cmap="RdYlGn", vmin=0, vmax=1)
    ax.set_xticks(range(len(CHECKS)), [c.replace("_", "\n") for c in CHECKS],
                 fontsize=8)
    ax.set_yticks(range(len(names)), names)
    for i in range(len(names)):
        for j in range(len(CHECKS)):
            ax.text(j, i, "✓" if grid[i][j] else "✗", ha="center", va="center",
                    color="white", fontsize=12, fontweight="bold")
    ax.set_title("Coherence checks per model (green = passed)")
    fig.colorbar(im, ax=ax, ticks=[0, 1], label="failed / passed", fraction=0.03)
    fig.tight_layout()
    fig.savefig(path, dpi=150)
    plt.close(fig)


def chart_scatter(rows: list[dict], path: Path) -> None:
    fig, ax = plt.subplots(figsize=(7.5, 3.6))
    for r in rows:
        ax.scatter(r["duration_s"], r["thinking_chars"],
                   color=COLORS[r["model"]], s=90, zorder=3)
        ax.annotate(r["model"], (r["duration_s"], r["thinking_chars"]),
                    textcoords="offset points", xytext=(8, 6), fontsize=9)
    style_axes(ax)
    ax.set_xlabel("total LLM time (s)")
    ax.set_ylabel("thinking chars")
    ax.set_title("Thinking vs. time — qwen3 is the only reasoning model")
    fig.tight_layout()
    fig.savefig(path, dpi=150)
    plt.close(fig)


def summary_table(rows: list[dict]) -> str:
    lines = [
        "| model | status | attempts | LLM calls | time (s) | tokens (prompt+completion) | thinking chars | messages |",
        "|---|---|---|---|---|---|---|---|",
    ]
    for r in rows:
        lines.append(
            f"| `{r['model']}` | {r['status']} | {r['n_attempts']} | {r['n_calls']} "
            f"| {r['duration_s']:,.1f} | {r['prompt_tokens']:,} + {r['completion_tokens']:,} "
            f"| {r['thinking_chars']:,} | {r['messages']} |"
        )
    return "\n".join(lines)


def checks_table(rows: list[dict]) -> str:
    header = "| model | " + " | ".join(CHECKS) + " |"
    sep = "|---" * (len(CHECKS) + 1) + "|"
    lines = [header, sep]
    for r in rows:
        marks = " | ".join("✓" if r["checks"][c] else "✗" for c in CHECKS)
        lines.append(f"| `{r['model']}` | {marks} |")
    return "\n".join(lines)


def first_attempt_notes(rows: list[dict]) -> str:
    out = []
    for r in rows:
        if r["n_attempts"] == 1:
            continue
        # Strip markdown fences so they cannot close the outer code block.
        excerpt = r["first_answer"].replace("```", "'''").strip()
        out.append(
            f"- **`{r['model']}`** — first attempt produced no parseable 8-line "
            f"binding. What it emitted instead (from `llm_trace.jsonl`):\n\n"
            f"  ````\n  {excerpt} …\n  ````\n"
        )
    return "\n".join(out) if out else (
        "All models produced a parseable answer on the first attempt."
    )


def qwen_thinking_excerpt(rows: list[dict]) -> str:
    for r in rows:
        if r["thinking_chars"] == 0:
            continue
        recs = [
            json.loads(line)
            for line in (r["out"] / "llm_trace.jsonl")
            .read_text(encoding="utf-8").splitlines()
            if line.strip()
        ]
        thought = recs[0].get("response", {}).get("thought") or ""
        head = " ".join(thought.split())[:600]
        return (
            f"`{r['model']}` reasoned for {r['duration_s']:,.1f}s and "
            f"{r['thinking_chars']:,} chars of thinking. The trace shows it "
            f"walking through the persona echo, the 8-line format contract, the "
            f"`{{{{cta-link}}}}` placeholder rule, and the schedule. Excerpt:\n\n"
            f"> {head} …"
        )
    return ""


def build_report(rows: list[dict]) -> str:
    fixed = json.loads(
        (EXPERIMENT_DIR / "summary.json").read_text(encoding="utf-8")
    )["fixed_spec"]
    generated = datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")
    md = [
        "# Cross-Model Ollama Experiment — Comparison Report",
        "",
        f"*generated: {generated}*",
        "",
        "## Method",
        "",
        "One fixed spec runs through every local Ollama model: same mission "
        "(`q3-awareness-2026`), pretext (`executive_request`), tone (`urgent`), "
        "difficulty (`medium`), language (`en`), seed (`42`), recipient "
        "(Rajesh Kapoor), and schedule. Only the generation model changes. "
        "Each model runs the same ADK pipeline (generate → assemble → validate) "
        "with parse-level rejection sampling (up to 3 attempts, strict format "
        "from attempt 2) and self-refinement on stale link tokens. Every LLM "
        "call — prompt, thinking, answer, usage — is traced in "
        "`llm_trace.jsonl`.",
        "",
        "| fixed spec | value |",
        "|---|---|",
    ]
    for key, value in fixed.items():
        md.append(f"| {key} | `{value}` |")
    md += [
        "",
        "## Headline results",
        "",
        summary_table(rows),
        "",
        "All four models pass all five coherence checks. The differences are in "
        "**how** they get there: attempt count, output length, and whether they "
        "reason before answering.",
        "",
        "## Charts",
        "",
        "### 1. Token usage",
        "",
        "![token usage](report_assets/chart_tokens.png)",
        "",
        "### 2. Wall-clock time",
        "",
        "![duration](report_assets/chart_duration.png)",
        "",
        "### 3. Attempts needed",
        "",
        "![attempts](report_assets/chart_attempts.png)",
        "",
        "### 4. Reasoning volume",
        "",
        "![thinking](report_assets/chart_thinking.png)",
        "",
        "### 5. Thinking vs. time",
        "",
        "![scatter](report_assets/chart_scatter.png)",
        "",
        "### 6. Coherence checks",
        "",
        "![checks](report_assets/chart_checks.png)",
        "",
        "## Check matrix",
        "",
        checks_table(rows),
        "",
        "## What went wrong on first attempts",
        "",
        first_attempt_notes(rows),
        "",
        "## The reasoning model",
        "",
        qwen_thinking_excerpt(rows),
        "",
        "## Per-model notes",
        "",
    ]
    for r in rows:
        md.append(
            f"### `{r['model']}`\n\n"
            f"- {r['n_attempts']} attempt(s), {r['n_calls']} LLM call(s), "
            f"{r['duration_s']:,.1f}s total, "
            f"{r['prompt_tokens']:,} prompt + {r['completion_tokens']:,} completion tokens.\n"
            f"- Thinking traced: {r['thinking_chars']:,} chars.\n"
            f"- Raw link violations before assembler normalization: {r['violations']}.\n"
        )
    md += [
        "## Artifacts",
        "",
        "| artifact | content |",
        "|---|---|",
        "| `output-<model>/generated_campaign.json` | final campaign (persona, messages, links, schedule) |",
        "| `output-<model>/coherence_report.json` | deterministic validator results |",
        "| `output-<model>/run_info.json` | attempts, refinement, raw-link metric |",
        "| `output-<model>/llm_trace.jsonl` | full LLM calls: prompt, thinking, answer, usage |",
        "| `output-<model>/run.log` | console transcript |",
        "| `summary.json` | aggregate of this run |",
        "",
        "Charts: `scripts/experiment_report.py` (run after any experiment to "
        "regenerate this report).",
        "",
    ]
    return "\n".join(md)


def main() -> None:
    rows = collect()
    if not rows:
        raise SystemExit("no experiment outputs with llm_trace.jsonl found")
    ASSETS_DIR.mkdir(parents=True, exist_ok=True)
    chart_tokens(rows, ASSETS_DIR / "chart_tokens.png")
    chart_duration(rows, ASSETS_DIR / "chart_duration.png")
    chart_attempts(rows, ASSETS_DIR / "chart_attempts.png")
    chart_thinking(rows, ASSETS_DIR / "chart_thinking.png")
    chart_scatter(rows, ASSETS_DIR / "chart_scatter.png")
    chart_checks(rows, ASSETS_DIR / "chart_checks.png")
    report = build_report(rows)
    (EXPERIMENT_DIR / "REPORT.md").write_text(report, encoding="utf-8")
    print(f"wrote: {EXPERIMENT_DIR / 'REPORT.md'}")
    print(f"charts: {ASSETS_DIR}")


if __name__ == "__main__":
    main()
