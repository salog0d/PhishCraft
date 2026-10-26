"""Quality lifecycle suite: the paper's post-generation quality checks at scale.

    python -m measurement.quality --adapter adk --runs 1
    python -m measurement.quality --adapter stub

Runs every spec through the pipeline and the post-run quality scan
(``quality_agent.scan``), then writes ``<out>/quality.json`` and a
human-readable ``<out>/quality-summary.md`` reporting the COVA-X-style
lifecycle numbers:

- **Generation-artifact flag rates** — per check category (dialogue collapse,
  stage direction, turn overflow, meta bleed, loop detection) and per pretext
  (the paper's Table II per-scam-type breakdown).
- **Contamination scan** — cross-pretext lexicon bleed, roster-name drift,
  wrong-brand mentions, non-Latin script; per category and per pretext.
- **Stage-direction stripping** — how many messages a strip pass would touch
  and how many characters it would remove (measured on a copy, never applied;
  the original artifacts stay untouched).
- **Automated label audit** — heuristic-implied pretext/tone/difficulty vs.
  the spec labels, with the correction rate (the paper's label-correction
  analogue) and the most common corrections.

The quality scan never repairs anything: findings are evidence, and every
number is a measurement of the generator, not a cleanup of its output.
"""

from __future__ import annotations

import argparse
import json
from collections import Counter, defaultdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Union

from measurement.adapters import get_adapter
from measurement.runner import run_spec
from measurement.specs import baseline_specs
from quality_agent.scan import CHECK_NAMES as QUALITY_CHECKS

REPO_ROOT = Path(__file__).resolve().parent.parent

ARTIFACT_CHECKS = [c for c in QUALITY_CHECKS if "contamination" not in c]
CONTAMINATION_CHECKS = [c for c in QUALITY_CHECKS if "contamination" in c]
LABEL_KEYS = ("pretext", "tone", "difficulty")


def _default_mission() -> dict:
    return json.loads(
        (REPO_ROOT / "config" / "q3-awareness-2026.mission.json").read_text()
    )


def run(
    adapter_name: str = "stub",
    runs: int = 1,
    out: Union[str, Path, None] = None,
) -> dict:
    """Run the quality suite, persist the artifacts, return the payload."""
    adapter = get_adapter(adapter_name)
    mission = _default_mission()
    specs = baseline_specs()
    out = Path(
        out
        or f"data/measurements/quality-{adapter.name}-"
        f"{datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%SZ')}"
    )
    out.mkdir(parents=True, exist_ok=True)

    records = []
    for spec in specs:
        for i in range(1, runs + 1):
            record = run_spec(spec, adapter, i, mission)
            records.append(record)
            print(
                f"{spec.spec_id} run={i} status={record.status} "
                f"quality_flags={record.quality_flags} "
                f"label_mismatches={record.label_mismatches or '-'}"
            )

    ok = [r for r in records if r.status == "ok"]

    # Per-check finding counts and per-pretext flag rates (Table II analogue).
    finding_counts = Counter()
    flag_counts = Counter()
    per_pretext = defaultdict(lambda: {"n": 0, "flagged": 0})
    for r in ok:
        pretext = (r.quality_report or {}).get("pretext") or "unknown"
        per_pretext[pretext]["n"] += 1
        if r.quality_flags:
            per_pretext[pretext]["flagged"] += 1
        for res in (r.quality_report or {}).get("results", []):
            if res["count"]:
                flag_counts[res["check"]] += 1
            finding_counts[res["check"]] += res["count"]

    contamination_counts = Counter()
    per_pretext_contamination = defaultdict(lambda: {"n": 0, "contaminated": 0})
    for r in ok:
        pretext = (r.quality_report or {}).get("pretext") or "unknown"
        if r.contamination:
            per_pretext_contamination[pretext]["contaminated"] += 1
            for check in r.contamination:
                contamination_counts[check] += 1

    label_mismatch = Counter()
    per_label_corrections = defaultdict(Counter)  # label -> {spec -> predicted}
    for r in ok:
        audit = (r.quality_report or {}).get("label_audit") or {}
        for label in r.label_mismatches:
            label_mismatch[label] += 1
            per_label_corrections[label][
                (audit.get("spec_labels") or {}).get(label)
            ] += 1
        if audit.get("available"):
            for label, status in (audit.get("statuses") or {}).items():
                if status == "unverifiable":
                    label_mismatch[f"{label} (unverifiable)"] += 1

    n_quality = sum(1 for r in ok if r.quality_flags > 0)
    n_contaminated = sum(1 for r in ok if r.contamination)
    n_label = sum(1 for r in ok if r.label_mismatches)
    n_strip = sum(1 for r in ok if r.strip_affected_messages > 0)

    payload = {
        "adapter": adapter.name,
        "model": specs[0].model["name"],
        "n_specs": len(specs),
        "n_runs": len(records),
        "n_generation_errors": len(records) - len(ok),
        # Quality flags.
        "n_campaigns_with_quality_flags": n_quality,
        "quality_flag_rate": round(n_quality / len(ok), 4) if ok else None,
        "finding_counts": {c: finding_counts.get(c, 0) for c in QUALITY_CHECKS},
        "flag_counts": {c: flag_counts.get(c, 0) for c in QUALITY_CHECKS},
        "per_pretext": {
            pretext: {
                **dict(stats),
                "rate": round(stats["flagged"] / stats["n"], 4) if stats["n"] else None,
            }
            for pretext, stats in sorted(per_pretext.items())
        },
        # Contamination.
        "n_campaigns_with_contamination": n_contaminated,
        "contamination_rate": round(n_contaminated / len(ok), 4) if ok else None,
        "contamination_counts": {
            c: contamination_counts.get(c, 0) for c in CONTAMINATION_CHECKS
        },
        "per_pretext_contamination": {
            pretext: {
                "n": stats["n"],
                "contaminated": stats["contaminated"],
                "rate": round(stats["contaminated"] / stats["n"], 4)
                if stats["n"] else None,
            }
            for pretext, stats in sorted(per_pretext_contamination.items())
        },
        # Label audit.
        "n_campaigns_with_label_mismatch": n_label,
        "label_correction_rate": round(n_label / len(ok), 4) if ok else None,
        "label_mismatch_counts": {
            label: label_mismatch.get(label, 0) for label in LABEL_KEYS
        },
        "unverifiable_counts": {
            key: label_mismatch.get(f"{key} (unverifiable)", 0)
            for key in LABEL_KEYS
        },
        "most_common_corrections": {
            label: dict(counts.most_common(5))
            for label, counts in per_label_corrections.items()
        },
        # Stripping (measured on a copy, never applied).
        "n_campaigns_with_strip_affected": n_strip,
        "strip_affected_rate": round(n_strip / len(ok), 4) if ok else None,
        "total_stripped_chars": sum(r.strip_stripped_chars for r in ok),
        "total_strip_affected_messages": sum(
            r.strip_affected_messages for r in ok
        ),
        "per_spec": [
            {
                "spec_id": r.spec_id,
                "run": r.run_index,
                "seed": r.seed,
                "status": r.status,
                "quality_flags": r.quality_flags,
                "quality_failing": r.quality_failing,
                "contamination": r.contamination,
                "label_mismatches": r.label_mismatches,
                "strip_affected_messages": r.strip_affected_messages,
                "strip_stripped_chars": r.strip_stripped_chars,
                "error": r.error,
            }
            for r in records
        ],
        "out_dir": str(out),
    }
    (out / "quality.json").write_text(
        json.dumps(payload, indent=2), encoding="utf-8"
    )

    lines = [
        "# Quality lifecycle — summary",
        "",
        f"- adapter: `{payload['adapter']}` · model: `{payload['model']}`",
        f"- specs: {payload['n_specs']} · runs: {payload['n_runs']} · "
        f"generation errors: {payload['n_generation_errors']}",
        "",
        f"- campaigns with ≥ 1 quality flag: "
        f"{payload['n_campaigns_with_quality_flags']}/{len(ok)} "
        f"(rate {payload['quality_flag_rate']})",
        "",
        "## Generation-artifact flag rates by check",
        "",
        "| check | findings | campaigns flagged |",
        "|---|---|---|",
    ]
    for check in ARTIFACT_CHECKS:
        lines.append(
            f"| `{check}` | {payload['finding_counts'][check]} | "
            f"{payload['flag_counts'][check]} |"
        )
    lines += [
        "",
        "## Flag rate by pretext (Table II analogue)",
        "",
        "| pretext | runs | flagged | rate |",
        "|---|---|---|---|",
    ]
    for pretext, stats in payload["per_pretext"].items():
        lines.append(
            f"| `{pretext}` | {stats['n']} | {stats['flagged']} | "
            f"{stats['rate']} |"
        )
    lines += [
        "",
        "## Contamination scan",
        "",
        f"- contaminated campaigns: "
        f"{payload['n_campaigns_with_contamination']}/{len(ok)} "
        f"(rate {payload['contamination_rate']})",
        "",
        "| category | findings |",
        "|---|---|",
    ]
    for check in CONTAMINATION_CHECKS:
        lines.append(
            f"| `{check}` | {payload['contamination_counts'][check]} |"
        )
    lines += [
        "",
        "| pretext | runs | contaminated | rate |",
        "|---|---|---|---|",
    ]
    for pretext, stats in payload["per_pretext_contamination"].items():
        lines.append(
            f"| `{pretext}` | {stats['n']} | {stats['contaminated']} | "
            f"{stats['rate']} |"
        )
    lines += [
        "",
        "## Automated label audit",
        "",
        f"- campaigns with a label mismatch: "
        f"{payload['n_campaigns_with_label_mismatch']}/{len(ok)} "
        f"(correction rate {payload['label_correction_rate']})",
        "",
        "| label | mismatches | unverifiable |",
        "|---|---|---|",
    ]
    for label in LABEL_KEYS:
        lines.append(
            f"| `{label}` | {payload['label_mismatch_counts'][label]} | "
            f"{payload['unverifiable_counts'][label]} |"
        )
    corrections = payload["most_common_corrections"]
    if any(corrections.values()):
        lines += [
            "",
            "Most common corrections (spec label -> number of runs):",
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
        "## Stage-direction stripping (measured on a copy, never applied)",
        "",
        f"- campaigns with strip-affected messages: "
        f"{payload['n_campaigns_with_strip_affected']}/{len(ok)} "
        f"(rate {payload['strip_affected_rate']})",
        f"- affected messages: {payload['total_strip_affected_messages']} · "
        f"chars that would be removed: {payload['total_stripped_chars']}",
        "",
        "## Per-spec results",
        "",
        "| spec | run | seed | status | quality flags | failing checks | "
        "contamination | label mismatches |",
        "|---|---|---|---|---|---|---|---|",
    ]
    for r in records:
        lines.append(
            f"| {r.spec_id} | {r.run_index} | {r.seed} | {r.status} | "
            f"{r.quality_flags} | "
            f"{', '.join(r.quality_failing) or '—'} | "
            f"{', '.join(r.contamination) or '—'} | "
            f"{', '.join(r.label_mismatches) or '—'} |"
        )
    lines += [
        "",
        "> Quality findings are evidence, never repairs: the delivered "
        "campaigns are untouched by the scan, and every number above measures "
        "the generator, not a cleanup of its output.",
    ]
    (out / "quality-summary.md").write_text(
        "\n".join(lines) + "\n", encoding="utf-8"
    )

    print(f"saved: {out / 'quality.json'}")
    print(f"saved: {out / 'quality-summary.md'}")
    return payload


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--runs", type=int, default=1)
    parser.add_argument("--adapter", default="stub")
    parser.add_argument("--out", default=None)
    args = parser.parse_args()
    run(adapter_name=args.adapter, runs=args.runs, out=args.out)


if __name__ == "__main__":
    main()
