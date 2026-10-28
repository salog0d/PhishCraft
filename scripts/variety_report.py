"""Aggregate report + matplotlib charts for the variety experiment.

Reads ``<out>/runs.jsonl`` (the append-only manifest the experiment writes)
and produces:

    <out>/quality.json     — the full aggregate payload
    <out>/summary.md       — markdown summary (tables + embedded charts)
    <out>/charts/*.png     — matplotlib charts of the accumulated metrics

Usage:

    python scripts/variety_report.py --out experiment/variety-<timestamp>

Re-run any time (also mid-run, to watch the accumulation): it only reads the
manifest, so the numbers always reflect every run recorded so far.
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from collections import Counter, defaultdict
from datetime import datetime, timezone
from difflib import SequenceMatcher
from pathlib import Path

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt  # noqa: E402

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT / "src"))

from quality_agent.scan import CHECK_NAMES as QUALITY_CHECKS
CONTAMINATION_CHECKS = [c for c in QUALITY_CHECKS if "contamination" in c]
COHERENCE_CHECKS = (
    "persona_identity",
    "timing",
    "cross_channel_reference",
    "link_consistency",
    "sender_recipient",
)
LABEL_KEYS = ("pretext", "tone", "difficulty")

# Per-model chart colors, stable across regenerations (unknown models fall
# back to a palette).
COLORS = {
    "qwen3:8b": "#4C72B0",
    "qwen3:4b": "#8DA0CB",
    "phi4-mini:latest": "#DD8452",
    "llama3.2:3b": "#55A868",
    "llama3.1:8b": "#CCB974",
    "gemma4:latest": "#C44E52",
}
_FALLBACK = [
    "#8172B3", "#937860", "#8C8C8C", "#6ACC64", "#E1BE6A", "#648FFF",
]
_PALETTE = [
    "#4C72B0", "#DD8452", "#55A868", "#C44E52", "#8172B3", "#CCB974",
    "#64B5CD", "#8C8C8C", "#6ACC64", "#E1BE6A",
]


def color_for(model: str) -> str:
    if model in COLORS:
        return COLORS[model]
    index = hash(model) % len(_FALLBACK)
    return _FALLBACK[index]


def model_color_map(models: list[str]) -> dict[str, str]:
    """Stable colors: known models first, unknowns appended in fixed order."""
    known = [m for m in models if m in COLORS]
    unknown = sorted(m for m in models if m not in COLORS)
    out = {m: COLORS[m] for m in known}
    for i, m in enumerate(unknown):
        out[m] = _FALLBACK[i % len(_FALLBACK)]
    return out


# --------------------------------------------------------------------------- #
# Loading
# --------------------------------------------------------------------------- #

def load_records(out: Path) -> tuple[list[dict], dict]:
    """(records, plan) — deduped by run_id (last manifest line wins)."""
    manifest = out / "runs.jsonl"
    plan = json.loads((out / "plan.json").read_text(encoding="utf-8")) \
        if (out / "plan.json").exists() else {}
    by_id: dict[str, dict] = {}
    if manifest.exists():
        for line in manifest.read_text(encoding="utf-8").splitlines():
            if not line.strip():
                continue
            try:
                rec = json.loads(line)
            except json.JSONDecodeError:
                continue
            by_id[rec["run_id"]] = rec
    # Keep manifest order for the cumulative charts.
    return list(by_id.values()), plan


# --------------------------------------------------------------------------- #
# Aggregation
# --------------------------------------------------------------------------- #

_URL = re.compile(r"https?://[^\s]+")


def _norm_prose(text: str) -> str:
    """Lowercase + strip URLs/punctuation so seed-derived tokens don't mask
    semantic duplicates (two runs whose only difference is the tracking URL
    count as the *same* message for variety purposes)."""
    text = _URL.sub(" ", text)
    text = re.sub(r"[^a-z0-9 ]", " ", text.lower())
    return " ".join(text.split())


def _prose_for(out: Path, rec: dict) -> str | None:
    """The concatenated (subject + body) prose of a run, normalized; None when
    the artifact is missing (failed/timeout runs)."""
    if not rec.get("dir"):
        return None
    path = out / rec["dir"] / "generated_campaign.json"
    if not path.exists():
        return None
    try:
        obj = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None
    parts = []
    for m in obj.get("messages", []):
        if m.get("subject"):
            parts.append(m["subject"])
        if m.get("body"):
            parts.append(m["body"])
    return _norm_prose(" ".join(parts))


def _variety(prose_list: list[str]) -> dict:
    """Variety metrics over a list of prose blobs: unique ratio and the
    near-duplicate (>=0.85 similarity) pair rate."""
    nonempty = [p for p in prose_list if p]
    n = len(nonempty)
    if n == 0:
        return {"n": 0, "unique_ratio": None, "near_dup_rate": None}
    unique = len(set(nonempty))
    near = 0
    pairs = 0
    for i in range(n):
        for j in range(i + 1, n):
            pairs += 1
            if SequenceMatcher(None, nonempty[i], nonempty[j]).ratio() >= 0.85:
                near += 1
    return {
        "n": n,
        "unique_ratio": round(unique / n, 4),
        "near_dup_rate": round(near / pairs, 4) if pairs else None,
    }


def aggregate(out: Path, records: list[dict]) -> dict:
    ok = [r for r in records if r["status"] == "ok"]

    status_counts = Counter(r["status"] for r in records)
    error_counts = Counter(
        (r["error"] or "unknown").split(":", 1)[0]
        for r in records if r["status"] != "ok"
    )

    # Quality flags: findings + flagged campaigns per check.
    finding_counts = Counter()
    flag_counts = Counter()
    per_pretext = defaultdict(lambda: {"n": 0, "flagged": 0})
    per_model = defaultdict(
        lambda: {
            "n": 0, "flagged": 0, "contaminated": 0, "label_mismatch": 0,
            "coherence_fail": 0, "strip_affected": 0, "durations": [],
            "n_attempts": [], "refined": 0, "raw_violations": [],
        }
    )
    # Temperature axis: retry/flag/attempt/refinement stats per temperature,
    # plus the variety metrics read back from the delivered prose.
    per_temp = defaultdict(
        lambda: {"n": 0, "flagged": 0, "attempts": [], "refined": 0,
                 "prose": []}
    )
    for r in ok:
        spec = r.get("spec", {})
        q = r.get("quality") or {}
        counts = r.get("quality_counts") or {}
        temp = (r.get("spec", {}).get("params", {}) or {}).get("temperature")
        per_model[r["model"]]["n"] += 1
        per_model[r["model"]]["durations"].append(r.get("duration_ms") or 0)
        per_model[r["model"]]["n_attempts"].append(
            (r.get("run_info") or {}).get("n_attempts", 0) or 0
        )
        if (r.get("run_info") or {}).get("refined"):
            per_model[r["model"]]["refined"] += 1
        if r.get("raw_link_violations"):
            per_model[r["model"]]["raw_violations"].append(
                r["raw_link_violations"]
            )
        if r.get("failing_checks"):
            per_model[r["model"]]["coherence_fail"] += 1
        if q.get("any_flag"):
            per_model[r["model"]]["flagged"] += 1
            per_pretext[spec.get("pretext", "?")]["flagged"] += 1
        if q.get("contamination"):
            per_model[r["model"]]["contaminated"] += 1
        if q.get("label_mismatches"):
            per_model[r["model"]]["label_mismatch"] += 1
        if q.get("strip_affected_messages"):
            per_model[r["model"]]["strip_affected"] += 1
        per_pretext[spec.get("pretext", "?")]["n"] += 1
        for check, count in counts.items():
            finding_counts[check] += count
            if count:
                flag_counts[check] += 1
        # Temperature axis accumulation.
        if temp is not None:
            bt = per_temp[temp]
            bt["n"] += 1
            bt["attempts"].append(
                (r.get("run_info") or {}).get("n_attempts", 0) or 0
            )
            if (r.get("run_info") or {}).get("refined"):
                bt["refined"] += 1
            if q.get("any_flag"):
                bt["flagged"] += 1
            prose = _prose_for(out, r)
            if prose:
                bt["prose"].append(prose)

    n_ok = len(ok)
    rate = lambda n: round(n / n_ok, 4) if n_ok else None  # noqa: E731

    def group_rate(count: int, base: int) -> float | None:
        """Rate over one group (model / pretext), not the whole run."""
        return round(count / base, 4) if base else None

    # Contamination.
    contamination_counts = Counter(
        c for r in ok for c in (r.get("quality") or {}).get("contamination", [])
    )
    per_pretext_contamination = defaultdict(lambda: {"n": 0, "contaminated": 0})
    for r in ok:
        p = (r.get("spec") or {}).get("pretext", "?")
        per_pretext_contamination[p]["n"] += 1
        if (r.get("quality") or {}).get("contamination"):
            per_pretext_contamination[p]["contaminated"] += 1

    # Label audit.
    label_mismatch = Counter()
    label_unverifiable = Counter()
    corrections = defaultdict(Counter)  # label -> {spec_value: runs}
    for r in ok:
        q = r.get("quality") or {}
        spec = r.get("spec") or {}
        for label in q.get("label_mismatches", []):
            label_mismatch[label] += 1
            corrections[label][spec.get(label)] += 1
        for label, status in (q.get("label_statuses") or {}).items():
            if status == "unverifiable":
                label_unverifiable[label] += 1

    # Coherence (validator) failures per check.
    coherence_counts = Counter(
        c for r in ok for c in r.get("failing_checks", [])
    )

    # Stripping.
    strip_messages = sum(
        (r.get("quality") or {}).get("strip_affected_messages", 0) for r in ok
    )
    strip_chars = sum(
        (r.get("quality") or {}).get("strip_stripped_chars", 0) for r in ok
    )

    # Refinement activity.
    refinement = {
        "n_campaigns_refined": sum(1 for r in ok
                                   if (r.get("run_info") or {}).get("refined")),
        "n_attempts_total": sum(
            (r.get("run_info") or {}).get("n_attempts", 0) or 0 for r in ok
        ),
        "raw_link_violations_total": sum(r.get("raw_link_violations") or 0
                                         for r in ok),
        "first_attempt_raw_violations_total": sum(
            (r.get("run_info") or {}).get("first_attempt_raw_link_violations")
            or 0 for r in ok
        ),
    }

    per_model_out = {
        m: {
            **{k: v for k, v in s.items()
               if k not in ("durations", "n_attempts", "raw_violations")},
            "duration_ms_median": (
                int(sorted(s["durations"])[len(s["durations"]) // 2])
                if s["durations"] else None
            ),
            "duration_ms_mean": (
                round(sum(s["durations"]) / len(s["durations"]))
                if s["durations"] else None
            ),
            "quality_flag_rate": group_rate(s["flagged"], s["n"]),
            "contamination_rate": group_rate(s["contaminated"], s["n"]),
            "label_correction_rate": group_rate(s["label_mismatch"], s["n"]),
            "coherence_failure_rate": group_rate(s["coherence_fail"], s["n"]),
            "strip_affected_rate": group_rate(s["strip_affected"], s["n"]),
            "refinement_rate": group_rate(s["refined"], s["n"]),
            "mean_attempts": (
                round(sum(s["n_attempts"]) / len(s["n_attempts"]), 2)
                if s["n_attempts"] else None
            ),
            "mean_raw_link_violations": (
                round(sum(s["raw_violations"]) / len(s["raw_violations"]), 2)
                if s["raw_violations"] else 0.0
            ),
        }
        for m, s in per_model.items()
    }

    per_temperature_out = {
        str(t): {
            "n": s["n"],
            "mean_attempts": (
                round(sum(s["attempts"]) / len(s["attempts"]), 2)
                if s["attempts"] else None
            ),
            "retry_rate": group_rate(
                sum(1 for a in s["attempts"] if a > 1), s["n"]
            ),
            "quality_flag_rate": group_rate(s["flagged"], s["n"]),
            "refinement_rate": group_rate(s["refined"], s["n"]),
            **_variety(s["prose"]),
        }
        for t, s in per_temp.items()
    }

    payload = {
        "generated_at": datetime.now(timezone.utc).isoformat()
        .replace("+00:00", "Z"),
        "out_dir": str(out),
        "n_runs": len(records),
        "n_ok": n_ok,
        "status_counts": dict(status_counts),
        "error_counts": dict(error_counts),
        # Quality flags.
        "n_campaigns_with_quality_flags": sum(
            1 for r in ok if (r.get("quality") or {}).get("any_flag")
        ),
        "quality_flag_rate": rate(sum(
            1 for r in ok if (r.get("quality") or {}).get("any_flag")
        )),
        "finding_counts": {
            c: finding_counts.get(c, 0) for c in QUALITY_CHECKS
        },
        "flag_counts": {c: flag_counts.get(c, 0) for c in QUALITY_CHECKS},
        "per_pretext": {
            p: {**s, "rate": group_rate(s["flagged"], s["n"])}
            for p, s in sorted(per_pretext.items())
        },
        # Contamination.
        "n_campaigns_with_contamination": sum(
            1 for r in ok if (r.get("quality") or {}).get("contamination")
        ),
        "contamination_rate": rate(sum(
            1 for r in ok if (r.get("quality") or {}).get("contamination")
        )),
        "contamination_counts": {
            c: contamination_counts.get(c, 0) for c in CONTAMINATION_CHECKS
        },
        "per_pretext_contamination": {
            p: {
                "n": s["n"],
                "contaminated": s["contaminated"],
                "rate": group_rate(s["contaminated"], s["n"]),
            }
            for p, s in sorted(per_pretext_contamination.items())
        },
        # Label audit.
        "n_campaigns_with_label_mismatch": sum(
            1 for r in ok if (r.get("quality") or {}).get("label_mismatches")
        ),
        "label_correction_rate": rate(sum(
            1 for r in ok if (r.get("quality") or {}).get("label_mismatches")
        )),
        "label_mismatch_counts": {
            k: label_mismatch.get(k, 0) for k in LABEL_KEYS
        },
        "label_unverifiable_counts": {
            k: label_unverifiable.get(k, 0) for k in LABEL_KEYS
        },
        "most_common_corrections": {
            k: dict(v.most_common(5)) for k, v in corrections.items()
        },
        # Stripping.
        "n_campaigns_with_strip_affected": sum(
            1 for r in ok
            if (r.get("quality") or {}).get("strip_affected_messages")
        ),
        "strip_affected_rate": rate(sum(
            1 for r in ok
            if (r.get("quality") or {}).get("strip_affected_messages")
        )),
        "total_strip_affected_messages": strip_messages,
        "total_stripped_chars": strip_chars,
        # Coherence (validator) + refinement.
        "coherence_failing_counts": {
            c: coherence_counts.get(c, 0) for c in COHERENCE_CHECKS
        },
        "refinement": refinement,
        # Per model.
        "per_model": per_model_out,
        # Per temperature (the sweep axis): variety / retry / flag rate.
        "per_temperature": per_temperature_out,
    }
    return payload


# --------------------------------------------------------------------------- #
# Charts
# --------------------------------------------------------------------------- #

def _style_axes(ax) -> None:
    ax.spines["top"].set_visible(False)
    ax.spines["right"].set_visible(False)
    ax.tick_params(labelsize=9)


def chart_quality_by_check(payload: dict, charts: Path, cmap: dict) -> None:
    checks = [c.replace("_", "\n") for c in QUALITY_CHECKS]
    findings = [payload["finding_counts"][c] for c in QUALITY_CHECKS]
    flagged = [payload["flag_counts"][c] for c in QUALITY_CHECKS]
    x = range(len(QUALITY_CHECKS))
    fig, ax = plt.subplots(figsize=(9, 4.5))
    ax.bar([i - 0.2 for i in x], findings, width=0.4, label="findings",
           color="#4C72B0")
    ax.bar([i + 0.2 for i in x], flagged, width=0.4,
           label="campaigns flagged", color="#DD8452")
    ax.set_xticks(list(x), checks)
    ax.set_ylabel("count")
    ax.set_title(f"Quality findings by check "
                 f"({payload['n_ok']} campaigns)")
    ax.legend(frameon=False)
    _style_axes(ax)
    fig.tight_layout()
    fig.savefig(charts / "quality_by_check.png", dpi=150)
    plt.close(fig)


def chart_quality_by_pretext(payload: dict, charts: Path) -> None:
    pre = payload["per_pretext"]
    names = sorted(pre)
    flag_rates = [pre[p]["rate"] or 0 for p in names]
    cont_rates = [
        payload["per_pretext_contamination"].get(p, {}).get("rate") or 0
        for p in names
    ]
    fig, axes = plt.subplots(1, 2, figsize=(11, 4))
    axes[0].barh(names, flag_rates, color="#4C72B0")
    axes[0].set_title("quality flag rate by pretext")
    axes[0].set_xlabel("rate")
    axes[1].barh(names, cont_rates, color="#C44E52")
    axes[1].set_title("contamination rate by pretext")
    axes[1].set_xlabel("rate")
    for ax in axes:
        _style_axes(ax)
    fig.tight_layout()
    fig.savefig(charts / "quality_by_pretext.png", dpi=150)
    plt.close(fig)


def chart_by_model(payload: dict, charts: Path, cmap: dict) -> None:
    models = sorted(payload["per_model"])
    metrics = [
        ("quality flag rate", "quality_flag_rate"),
        ("contamination rate", "contamination_rate"),
        ("label correction rate", "label_correction_rate"),
        ("coherence failure rate", "coherence_failure_rate"),
    ]
    fig, axes = plt.subplots(2, 2, figsize=(11, 7))
    for ax, (title, key) in zip(axes.flat, metrics):
        values = [payload["per_model"][m][key] or 0 for m in models]
        ax.bar(models, values, color=[cmap[m] for m in models])
        ax.set_title(title)
        ax.set_ylim(0, max(values + [0.05]) * 1.15)
        ax.tick_params(axis="x", labelrotation=30, labelsize=8)
        _style_axes(ax)
    fig.suptitle("Quality metrics by model", fontsize=12)
    fig.tight_layout()
    fig.savefig(charts / "by_model.png", dpi=150)
    plt.close(fig)


def chart_contamination(payload: dict, charts: Path) -> None:
    cats = [c.replace("_", "\n") for c in CONTAMINATION_CHECKS]
    counts = [payload["contamination_counts"][c] for c in CONTAMINATION_CHECKS]
    fig, ax = plt.subplots(figsize=(7, 4))
    ax.bar(cats, counts, color="#C44E52")
    ax.set_title("Contamination findings by category")
    ax.set_ylabel("campaigns contaminated")
    for i, v in enumerate(counts):
        if v:
            ax.text(i, v, str(v), ha="center", va="bottom", fontsize=9)
    _style_axes(ax)
    fig.tight_layout()
    fig.savefig(charts / "contamination_by_category.png", dpi=150)
    plt.close(fig)


def chart_label_audit(payload: dict, charts: Path) -> None:
    labels = list(LABEL_KEYS)
    mismatch = [payload["label_mismatch_counts"][k] for k in labels]
    unverifiable = [payload["label_unverifiable_counts"][k] for k in labels]
    x = range(len(labels))
    fig, ax = plt.subplots(figsize=(6.5, 4))
    ax.bar([i - 0.2 for i in x], mismatch, width=0.4, label="mismatch",
           color="#C44E52")
    ax.bar([i + 0.2 for i in x], unverifiable, width=0.4,
           label="unverifiable (deferred)", color="#8C8C8C")
    ax.set_xticks(list(x), labels)
    ax.set_title(
        f"Automated label audit — correction rate "
        f"{payload['label_correction_rate']}"
    )
    ax.legend(frameon=False)
    _style_axes(ax)
    fig.tight_layout()
    fig.savefig(charts / "label_audit.png", dpi=150)
    plt.close(fig)


def chart_coherence(payload: dict, charts: Path) -> None:
    checks = [c.replace("_", "\n") for c in COHERENCE_CHECKS]
    counts = [payload["coherence_failing_counts"][c] for c in COHERENCE_CHECKS]
    fig, ax = plt.subplots(figsize=(7, 4))
    ax.bar(checks, counts, color="#55A868")
    ax.set_title(f"Coherence (validator) failures by check "
                 f"({payload['n_ok']} campaigns)")
    for i, v in enumerate(counts):
        if v:
            ax.text(i, v, str(v), ha="center", va="bottom", fontsize=9)
    _style_axes(ax)
    fig.tight_layout()
    fig.savefig(charts / "coherence_by_check.png", dpi=150)
    plt.close(fig)


def chart_heatmap(payload: dict, charts: Path, records: list[dict]) -> None:
    ok = [r for r in records if r["status"] == "ok"]
    pre = sorted({(r.get("spec") or {}).get("pretext", "?") for r in ok})
    grid = {p: Counter() for p in pre}
    for r in ok:
        p = (r.get("spec") or {}).get("pretext", "?")
        for check, count in (r.get("quality_counts") or {}).items():
            grid[p][check] += count
    matrix = [[grid[p].get(c, 0) for c in QUALITY_CHECKS] for p in pre]
    fig, ax = plt.subplots(figsize=(11, 4.5))
    im = ax.imshow(matrix, aspect="auto", cmap="YlOrRd")
    ax.set_xticks(range(len(QUALITY_CHECKS)),
                  [c.replace("_", "\n") for c in QUALITY_CHECKS])
    ax.set_yticks(range(len(pre)), pre)
    ax.tick_params(labelsize=8)
    fig.colorbar(im, ax=ax, label="findings (accumulated)")
    ax.set_title("Accumulated quality findings — pretext x check heatmap")
    fig.tight_layout()
    fig.savefig(charts / "heatmap_pretext_check.png", dpi=150)
    plt.close(fig)


def chart_durations(payload: dict, charts: Path, records: list[dict],
                    cmap: dict) -> None:
    ok = [r for r in records if r["status"] == "ok"]
    models = sorted({r["model"] for r in ok})
    data = [
        [(r.get("duration_ms") or 0) / 1000 for r in ok if r["model"] == m]
        for m in models
    ]
    fig, ax = plt.subplots(figsize=(8, 4.5))
    bp = ax.boxplot(data, tick_labels=models, patch_artist=True,
                    showmeans=True)
    for patch, m in zip(bp["boxes"], models):
        patch.set_facecolor(cmap[m])
        patch.set_alpha(0.7)
    ax.set_ylabel("seconds per campaign")
    ax.set_title("Generation duration by model")
    _style_axes(ax)
    fig.tight_layout()
    fig.savefig(charts / "duration_by_model.png", dpi=150)
    plt.close(fig)


def chart_cumulative(payload: dict, charts: Path, records: list[dict]) -> None:
    """Accumulated findings per check category as runs complete (run order)."""
    ordered = [r for r in records if r["status"] == "ok"]
    running = {c: 0 for c in QUALITY_CHECKS}
    series = {c: [] for c in QUALITY_CHECKS}
    x = []
    for i, r in enumerate(ordered):
        x.append(i + 1)
        for check, count in (r.get("quality_counts") or {}).items():
            running[check] += count
        for c in QUALITY_CHECKS:
            series[c].append(running[c])
    fig, ax = plt.subplots(figsize=(11, 5))
    colors = [_PALETTE[i % len(_PALETTE)] for i in range(len(QUALITY_CHECKS))]
    for check, color in zip(QUALITY_CHECKS, colors):
        ax.plot(x, series[check], label=check.replace("_", " "), color=color,
                linewidth=1.6)
    ax.set_xlabel("campaigns completed")
    ax.set_ylabel("accumulated findings")
    ax.set_title("Accumulated quality findings over the run "
                 f"(total {payload['n_ok']} campaigns)")
    ax.legend(fontsize=8, ncol=2, frameon=False)
    _style_axes(ax)
    fig.tight_layout()
    fig.savefig(charts / "cumulative_findings.png", dpi=150)
    plt.close(fig)


def chart_strip(payload: dict, charts: Path, cmap: dict) -> None:
    models = sorted(payload["per_model"])
    rates = [payload["per_model"][m]["strip_affected_rate"] or 0 for m in models]
    fig, ax = plt.subplots(figsize=(7, 4))
    ax.bar(models, rates, color=[cmap[m] for m in models])
    ax.set_ylabel("campaigns with strip-affected messages (rate)")
    ax.set_title(
        f"Stage-direction stripping — {payload['total_stripped_chars']} chars "
        f"would be removed across {payload['total_strip_affected_messages']} "
        f"messages"
    )
    ax.tick_params(axis="x", labelrotation=30, labelsize=8)
    _style_axes(ax)
    fig.tight_layout()
    fig.savefig(charts / "strip_stats.png", dpi=150)
    plt.close(fig)


def chart_temperature(payload: dict, charts: Path) -> None:
    """The temperature sweep axis: semantic variety, retry rate, refinement
    rate, and quality flag rate as a function of sampling temperature."""
    pt = payload["per_temperature"]
    if not pt:
        return
    temps = sorted(pt, key=float)
    unique = [pt[t]["unique_ratio"] or 0 for t in temps]
    near_dup = [pt[t]["near_dup_rate"] or 0 for t in temps]
    retry = [pt[t]["retry_rate"] or 0 for t in temps]
    flag = [pt[t]["quality_flag_rate"] or 0 for t in temps]
    refine = [pt[t]["refinement_rate"] or 0 for t in temps]

    fig, axes = plt.subplots(1, 4, figsize=(16, 4))
    axes[0].plot(temps, unique, marker="o", color="#4C72B0", label="unique")
    axes[0].plot(temps, near_dup, marker="s", color="#C44E52",
                 label="near-duplicate")
    axes[0].set_title("Semantic variety vs temperature")
    axes[0].set_xlabel("temperature")
    axes[0].set_ylabel("ratio")
    axes[0].set_ylim(0, 1.05)
    axes[0].legend(frameon=False, fontsize=8)

    axes[1].plot(temps, retry, marker="o", color="#DD8452")
    axes[1].set_title("Rejection-sampling retry rate")
    axes[1].set_xlabel("temperature")
    axes[1].set_ylabel("runs needing retry")

    axes[2].plot(temps, refine, marker="o", color="#8172B3")
    axes[2].set_title("Self-refinement rate (critic)")
    axes[2].set_xlabel("temperature")
    axes[2].set_ylabel("runs refined")

    axes[3].plot(temps, flag, marker="o", color="#55A868")
    axes[3].set_title("Quality flag rate")
    axes[3].set_xlabel("temperature")
    axes[3].set_ylabel("rate")

    for ax in axes:
        _style_axes(ax)
    fig.suptitle("Temperature sweep — variety, refinement, and robustness "
                 f"({payload['n_ok']} campaigns)", fontsize=12)
    fig.tight_layout()
    fig.savefig(charts / "temperature_sweep.png", dpi=150)
    plt.close(fig)


def render_charts(out: Path, payload: dict, records: list[dict]) -> list[Path]:
    charts = out / "charts"
    charts.mkdir(parents=True, exist_ok=True)
    cmap = model_color_map(sorted(payload["per_model"]))
    chart_quality_by_check(payload, charts, cmap)
    chart_quality_by_pretext(payload, charts)
    chart_by_model(payload, charts, cmap)
    chart_contamination(payload, charts)
    chart_label_audit(payload, charts)
    chart_coherence(payload, charts)
    chart_heatmap(payload, charts, records)
    chart_durations(payload, charts, records, cmap)
    chart_cumulative(payload, charts, records)
    chart_strip(payload, charts, cmap)
    chart_temperature(payload, charts)
    return sorted(charts.glob("*.png"))


# --------------------------------------------------------------------------- #
# Summary markdown
# --------------------------------------------------------------------------- #

def render_summary(out: Path, payload: dict, charts: list[Path]) -> None:
    ok = payload["n_ok"]
    lines = [
        "# Variety experiment — quality lifecycle summary",
        "",
        f"- generated: `{payload['generated_at']}` · dir: `{payload['out_dir']}`",
        f"- runs: {payload['n_runs']} (ok {ok}, "
        f"{', '.join(f'{k}={v}' for k, v in payload['status_counts'].items())})",
    ]
    if payload["error_counts"]:
        lines.append(
            f"- generation errors: "
            f"{', '.join(f'{k}: {v}' for k, v in payload['error_counts'].items())}"
        )
    lines += [
        f"- campaigns with >= 1 quality flag: "
        f"{payload['n_campaigns_with_quality_flags']}/{ok} "
        f"(rate {payload['quality_flag_rate']})",
        f"- contaminated campaigns: "
        f"{payload['n_campaigns_with_contamination']}/{ok} "
        f"(rate {payload['contamination_rate']})",
        f"- label-correction rate: {payload['label_correction_rate']} "
        f"(mismatch {payload['label_mismatch_counts']}, unverifiable "
        f"{payload['label_unverifiable_counts']})",
        f"- strip-affected campaigns: "
        f"{payload['n_campaigns_with_strip_affected']}/{ok} "
        f"(rate {payload['strip_affected_rate']}); "
        f"{payload['total_stripped_chars']} chars would be removed from "
        f"{payload['total_strip_affected_messages']} messages",
        "",
        "## Findings by check",
        "",
        "| check | findings | campaigns flagged |",
        "|---|---|---|",
    ]
    for c in QUALITY_CHECKS:
        lines.append(
            f"| `{c}` | {payload['finding_counts'][c]} | "
            f"{payload['flag_counts'][c]} |"
        )
    lines += [
        "",
        "## Contamination by category",
        "",
        "| category | campaigns |",
        "|---|---|",
    ]
    for c in CONTAMINATION_CHECKS:
        lines.append(f"| `{c}` | {payload['contamination_counts'][c]} |")
    lines += [
        "",
        "## Coherence (validator) failures",
        "",
        "| check | campaigns failing |",
        "|---|---|",
    ]
    for c in COHERENCE_CHECKS:
        lines.append(
            f"| `{c}` | {payload['coherence_failing_counts'][c]} |"
        )
    lines += [
        "",
        "## Per model",
        "",
        "| model | runs | quality flag rate | contamination rate | "
        "label correction rate | coherence failure rate | median duration |",
        "|---|---|---|---|---|---|---|",
    ]
    for m, s in payload["per_model"].items():
        lines.append(
            f"| `{m}` | {s['n']} | {s['quality_flag_rate']} | "
            f"{s['contamination_rate']} | {s['label_correction_rate']} | "
            f"{s['coherence_failure_rate']} | "
            f"{(s['duration_ms_median'] or 0) / 1000:.1f}s |"
        )
    lines += [
        "",
        "## Per temperature (sweep)",
        "",
        "| temperature | runs | unique-body ratio | near-dup rate | "
        "retry rate | refinement rate | quality flag rate | mean attempts |",
        "|---|---|---|---|---|---|---|---|",
    ]
    for t, s in payload["per_temperature"].items():
        lines.append(
            f"| `{t}` | {s['n']} | {s['unique_ratio']} | {s['near_dup_rate']} | "
            f"{s['retry_rate']} | {s['refinement_rate']} | "
            f"{s['quality_flag_rate']} | {s['mean_attempts']} |"
        )
    lines += [
        "",
        "## Flag rate by pretext",
        "",
        "| pretext | runs | flagged | rate | contaminated | contamination rate |",
        "|---|---|---|---|---|---|",
    ]
    for p, s in payload["per_pretext"].items():
        c = payload["per_pretext_contamination"].get(p, {})
        lines.append(
            f"| `{p}` | {s['n']} | {s['flagged']} | {s['rate']} | "
            f"{c.get('contaminated', 0)} | {c.get('rate')} |"
        )
    corrections = payload["most_common_corrections"]
    if any(corrections.values()):
        lines += [
            "",
            "### Most common label corrections (spec label -> runs)",
            "",
        ]
        for label in LABEL_KEYS:
            if corrections.get(label):
                detail = ", ".join(
                    f"{spec}->{n}" for spec, n in corrections[label].items()
                )
                lines.append(f"- `{label}`: {detail}")
    lines += [
        "",
        "## Refinement activity",
        "",
        f"- campaigns refined: {payload['refinement']['n_campaigns_refined']} "
        f"({payload['refinement']['n_campaigns_refined']}/{ok})",
        f"- total attempts: {payload['refinement']['n_attempts_total']} "
        f"(mean per campaign "
        f"{round(payload['refinement']['n_attempts_total'] / ok, 2) if ok else '—'})",
        f"- raw link violations (final artifact): "
        f"{payload['refinement']['raw_link_violations_total']} "
        f"(first-attempt: "
        f"{payload['refinement']['first_attempt_raw_violations_total']})",
        "",
        "## Charts",
        "",
    ]
    for chart in charts:
        lines.append(f"![{chart.stem}]({chart.relative_to(out)})")
        lines.append("")
    lines += [
        "> Quality findings are evidence, never repairs: the delivered "
        "campaigns are untouched by the scan, and every number above measures "
        "the generator, not a cleanup of its output.",
    ]
    (out / "summary.md").write_text("\n".join(lines) + "\n", encoding="utf-8")


# --------------------------------------------------------------------------- #

def render(out: Path) -> dict:
    records, _plan = load_records(out)
    if not records:
        raise SystemExit(f"no runs recorded in {out / 'runs.jsonl'} yet")
    payload = aggregate(out, records)
    (out / "quality.json").write_text(
        json.dumps(payload, indent=2), encoding="utf-8"
    )
    charts = render_charts(out, payload, records)
    render_summary(out, payload, charts)
    print(f"records: {len(records)} (ok {payload['n_ok']})")
    print(f"saved: {out / 'quality.json'}")
    print(f"saved: {out / 'summary.md'}")
    print(f"charts: {len(charts)} in {out / 'charts'}")
    return payload


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--out", required=True,
                        help="experiment output directory")
    args = parser.parse_args()
    render(Path(args.out))


if __name__ == "__main__":
    main()
