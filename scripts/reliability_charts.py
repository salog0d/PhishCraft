#!/usr/bin/env python3
"""Charts for the generator reliability matrix experiment.

Reads the experiment manifest (``runs.jsonl``) directly (not just
``summary.json``) so the charts surface the *real* finding of the study: the
generator passes every structural coherence check by construction, yet the
*content quality* — quality-scan flags and label-mismatch rates — varies
measurably across models and temperatures.

Charts rendered to ``diagrams_output/experiment/``:

- quality_flags.png     — failing quality checks per model x temperature
- label_mismatch.png    — label audit (pretext/tone/difficulty) per model
- effort.png            — mean attempts + critic calls + refined runs
- duration.png          — duration distribution per model (boxplot)
- refinement.png        — refinement rate per model x temperature

Usage:

    python scripts/reliability_charts.py experiment/reliability-final-<ts>
"""

from __future__ import annotations

import argparse
import json
from collections import Counter, defaultdict
from pathlib import Path

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt  # noqa: E402

REPO_ROOT = Path(__file__).resolve().parent.parent

# Stable per-model colors (shared with variety_report.py).
COLORS = {
    "qwen3": "#4C72B0",
    "phi4": "#DD8452",
    "llama3.1": "#55A868",
}
_FALLBACK = ["#8172B3", "#937860", "#8C8C8C", "#6ACC64", "#E1BE6A", "#648FFF"]


def color_for(model: str) -> str:
    for key, color in COLORS.items():
        if model.startswith(key):
            return color
    return _FALLBACK[hash(model) % len(_FALLBACK)]


def short_model(model: str) -> str:
    """'qwen3:8b-q4km-20261110' -> 'qwen3:8b' (readable legend labels)."""
    name = model
    if "/" in name:
        name = name.rsplit("/", 1)[1]
    # drop the frozen-tag version suffix
    for cut in ("-q4km-", "-Q4_K_M"):
        if cut in name:
            name = name.split(cut)[0]
    # drop the :size when redundant? keep base
    return name


def _load(out: Path) -> tuple[list[dict], list[str]]:
    manifest = out / "runs.jsonl"
    if not manifest.exists():
        raise SystemExit(f"no runs.jsonl at {manifest}")
    rows = [json.loads(l) for l in manifest.read_text(encoding="utf-8").splitlines()
            if l.strip()]
    by_id = {r["run_id"]: r for r in rows}  # last line wins
    records = list(by_id.values())
    models = []
    seen = set()
    for r in records:
        if r["model"] not in seen:
            seen.add(r["model"])
            models.append(r["model"])
    return records, models


def _ok(records: list[dict]) -> list[dict]:
    return [r for r in records if r["status"] == "ok"]


def _save(fig, stem: str) -> Path:
    d = REPO_ROOT / "diagrams_output" / "experiment"
    d.mkdir(parents=True, exist_ok=True)
    path = d / f"{stem}.png"
    fig.savefig(path, dpi=150, bbox_inches="tight")
    plt.close(fig)
    return path


# --------------------------------------------------------------------------- #
# Chart 1 — failing quality checks per model (the real "compliance" gap)
# --------------------------------------------------------------------------- #

def chart_quality_flags(records: list[dict]) -> Path:
    ok = _ok(records)
    # model -> counter of failing check names
    by_model = defaultdict(Counter)
    temp_names = set()
    for r in ok:
        m = short_model(r["model"])
        temp_names.add(r["temperature"])
        for c in (r.get("quality", {}) or {}).get("failing") or []:
            by_model[m][c] += 1
    models = list(by_model)
    checks = sorted({c for cnt in by_model.values() for c in cnt})

    fig, ax = plt.subplots(figsize=(9, 4.5))
    width = 0.8 / len(models)
    for i, m in enumerate(models):
        vals = [by_model[m].get(c, 0) for c in checks]
        x = [j + i * width for j in range(len(checks))]
        ax.bar(x, vals, width, label=m, color=color_for(m), alpha=0.88)
    ax.set_xticks([j + width * (len(models) - 1) / 2 for j in range(len(checks))])
    ax.set_xticklabels([c.replace("_", "\n") for c in checks], fontsize=8)
    ax.set_ylabel("campaigns failing")
    ax.set_title("Quality-scan failures per model (content, not structure)")
    ax.legend(fontsize=9, framealpha=0.9)
    ax.grid(axis="y", alpha=0.3)
    fig.tight_layout()
    return _save(fig, "quality_flags")


# --------------------------------------------------------------------------- #
# Chart 2 — label audit: mismatch rate per label x model
# --------------------------------------------------------------------------- #

def chart_label_mismatch(records: list[dict]) -> Path:
    ok = _ok(records)
    # model -> label -> Counter(status)
    by_model = defaultdict(lambda: defaultdict(Counter))
    for r in ok:
        m = short_model(r["model"])
        st = (r.get("quality", {}) or {}).get("label_statuses") or {}
        for label, val in st.items():
            by_model[m][label][val] += 1
    models = list(by_model)
    labels = ("pretext", "tone", "difficulty")

    fig, axes = plt.subplots(1, 3, figsize=(14, 4), sharey=True)
    for ax, label in zip(axes, labels):
        mismatch = [by_model[m][label]["mismatch"] for m in models]
        unver = [by_model[m][label]["unverifiable"] for m in models]
        okcount = [by_model[m][label]["ok"] for m in models]
        total = [mm + u + o for mm, u, o in zip(mismatch, unver, okcount)]
        rate = [mm / t if t else 0 for mm, t in zip(mismatch, total)]
        x = range(len(models))
        ax.bar(x, rate, color=[color_for(m) for m in models], alpha=0.85)
        ax.set_xticks(list(x))
        ax.set_xticklabels(models, fontsize=8, rotation=15, ha="right")
        ax.set_title(f"{label} mismatch rate", fontsize=11)
        ax.set_ylim(0, 1)
        ax.grid(axis="y", alpha=0.3)
        if ax is axes[0]:
            ax.set_ylabel("mismatch / total")
    fig.suptitle("Label audit — how often content does not match the requested label",
                 fontsize=12)
    fig.tight_layout()
    return _save(fig, "label_mismatch")


# --------------------------------------------------------------------------- #
# Chart 3 — effort per model x temperature
# --------------------------------------------------------------------------- #

def chart_effort(records: list[dict]) -> Path:
    ok = _ok(records)
    # model -> temp -> aggregates
    agg = defaultdict(lambda: defaultdict(lambda: {"n": 0, "attempts": 0,
                                                   "critic": 0, "refined": 0,
                                                   "tokens": 0}))
    for r in ok:
        m = short_model(r["model"]); t = r["temperature"]
        a = agg[m][t]
        a["n"] += 1
        a["attempts"] += (r.get("run_info") or {}).get("n_attempts", 0) or 0
        a["critic"] += (r.get("trace") or {}).get("critic_calls", 0) or 0
        a["refined"] += 1 if (r.get("run_info") or {}).get("refined") else 0
        a["tokens"] += (r.get("trace") or {}).get("total_tokens", 0) or 0

    models = list(agg)
    temps = sorted({t for m in agg for t in agg[m]})

    fig, axes = plt.subplots(2, 2, figsize=(13, 7))
    # (0,0) mean attempts
    ax = axes[0, 0]
    for m in models:
        vals = [agg[m][t]["attempts"] / agg[m][t]["n"] for t in temps]
        ax.plot(temps, vals, "o-", label=m, color=color_for(m))
    ax.set_title("mean attempts"); ax.set_ylabel("attempts")
    ax.grid(alpha=0.3)
    # (0,1) mean critic calls
    ax = axes[0, 1]
    for m in models:
        vals = [agg[m][t]["critic"] / agg[m][t]["n"] for t in temps]
        ax.plot(temps, vals, "o-", label=m, color=color_for(m))
    ax.set_title("mean critic calls"); ax.set_ylabel("calls")
    ax.grid(alpha=0.3)
    # (1,0) mean tokens
    ax = axes[1, 0]
    for m in models:
        vals = [agg[m][t]["tokens"] / agg[m][t]["n"] for t in temps]
        ax.plot(temps, vals, "o-", label=m, color=color_for(m))
    ax.set_title("mean total tokens"); ax.set_ylabel("tokens"); ax.set_xlabel("temperature")
    ax.grid(alpha=0.3)
    # (1,1) refined rate
    ax = axes[1, 1]
    for m in models:
        vals = [agg[m][t]["refined"] / agg[m][t]["n"] for t in temps]
        ax.plot(temps, vals, "o-", label=m, color=color_for(m))
    ax.set_title("refinement rate"); ax.set_ylabel("refined / total"); ax.set_xlabel("temperature")
    ax.set_ylim(0, 1)
    ax.grid(alpha=0.3)

    handles, labels = ax.get_legend_handles_labels()
    fig.legend(handles, labels, loc="lower center", ncol=len(models), fontsize=9,
               frameon=False)
    fig.suptitle("Effort required to reach a valid campaign, by model × temperature",
                 fontsize=13)
    fig.tight_layout(rect=[0, 0.05, 1, 0.96])
    return _save(fig, "effort")


# --------------------------------------------------------------------------- #
# Chart 4 — duration distribution per model (boxplot)
# --------------------------------------------------------------------------- #

def chart_duration(records: list[dict]) -> Path:
    ok = _ok(records)
    by_model = defaultdict(list)
    for r in ok:
        by_model[short_model(r["model"])].append(r.get("duration_ms", 0) / 1000)
    models = list(by_model)
    data = [by_model[m] for m in models]

    fig, ax = plt.subplots(figsize=(8, 4.5))
    bp = ax.boxplot(data, patch_artist=True, showmeans=True)
    for patch, m in zip(bp["boxes"], models):
        patch.set_facecolor(color_for(m)); patch.set_alpha(0.6)
    ax.set_xticks(range(1, len(models) + 1))
    ax.set_xticklabels(models)
    ax.set_ylabel("duration (s)")
    ax.set_title("Wall-clock duration per campaign, by model")
    ax.grid(axis="y", alpha=0.3)
    fig.tight_layout()
    return _save(fig, "duration")


# --------------------------------------------------------------------------- #
# Chart 5 — refinement rate per model x temperature (heatmap)
# --------------------------------------------------------------------------- #

def chart_refinement(records: list[dict]) -> Path:
    ok = _ok(records)
    agg = defaultdict(lambda: defaultdict(lambda: [0, 0]))  # model x temp -> [refined, n]
    for r in ok:
        a = agg[short_model(r["model"])][r["temperature"]]
        a[1] += 1
        if (r.get("run_info") or {}).get("refined"):
            a[0] += 1
    models = list(agg)
    temps = sorted({t for m in agg for t in agg[m]})
    grid = [[agg[m][t][0] / agg[m][t][1] if agg[m][t][1] else 0 for t in temps]
            for m in models]

    fig, ax = plt.subplots(figsize=(7, 4))
    im = ax.imshow(grid, cmap="RdYlGn_r", aspect="auto", vmin=0, vmax=1)
    ax.set_xticks(range(len(temps))); ax.set_xticklabels(temps)
    ax.set_yticks(range(len(models))); ax.set_yticklabels(models)
    ax.set_xlabel("temperature"); ax.set_ylabel("model")
    ax.set_title("Refinement rate (share of campaigns needing correction)")
    for i in range(len(models)):
        for j in range(len(temps)):
            ax.text(j, i, f"{grid[i][j]:.2f}", ha="center", va="center",
                    color="black" if grid[i][j] < 0.6 else "white", fontsize=9)
    fig.colorbar(im, ax=ax, label="refined / total")
    fig.tight_layout()
    return _save(fig, "refinement")


# --------------------------------------------------------------------------- #
# Runner
# --------------------------------------------------------------------------- #

def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("out", help="experiment output directory (has runs.jsonl)")
    args = parser.parse_args()
    records, _models = _load(Path(args.out))
    charts = [
        chart_quality_flags(records),
        chart_label_mismatch(records),
        chart_effort(records),
        chart_duration(records),
        chart_refinement(records),
    ]
    print("Generated experiment charts:")
    for p in charts:
        print(f"  {p}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
