"""Reliability experiment: run the spec set and count constraint violations.

    python -m measurement.reliability --adapter adk --runs 1
    python -m measurement.reliability --adapter stub

Aggregates over every spec x run: how many campaigns violate at least one
coherence constraint, broken down by check. Writes ``<out>/reliability.json``
and a human-readable ``<out>/summary.md``.

Three link-consistency numbers are reported, and they measure different
layers of the pipeline:

- **First-attempt raw violation rate** — from the driver's run_info: the
  stale tokens the LLM wrote on its *first* attempt, before any refinement
  round. This is the generator's *reliability* metric.
- **Post-refinement raw violation rate** (``raw_link_violation_rate``) — the
  stale tokens remaining on the *delivered* artifact after self-refinement
  rounds (from each message's ``link_fixes``). With refinement enabled this
  is expected to be 0.
- **Post-assembler failure rate** (``failure_rate``) — the validator's
  coherence checks on the delivered artifact. By construction this is 0 for
  ``link_consistency`` after the normalization fix: it is the *delivery
  guarantee*, not a model metric.

The stub adapter never refines (no LLM), so its first-attempt and
post-refinement numbers coincide.

Every successful run additionally gets the post-run **quality scan**
(``quality_agent.scan`` — the COVA-X-style lifecycle): the summary reports
quality-flag rates per check category, contamination rates, the automated
label audit's correction rate, and stage-direction stripping statistics.

The interactive shell calls ``run()`` directly.
"""

from __future__ import annotations

import argparse
import json
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path
from typing import Union

from measurement.adapters import get_adapter
from measurement.runner import run_spec
from measurement.specs import baseline_specs
from quality_agent.scan import CHECK_NAMES as QUALITY_CHECKS

REPO_ROOT = Path(__file__).resolve().parent.parent.parent

CHECKS = [
    "persona_identity",
    "timing",
    "cross_channel_reference",
    "link_consistency",
    "sender_recipient",
]

CONTAMINATION_CHECKS = [
    c for c in QUALITY_CHECKS if "contamination" in c
]


def _default_mission() -> dict:
    return json.loads(
        (REPO_ROOT / "config" / "q3-awareness-2026.mission.json").read_text()
    )


def run(
    adapter_name: str = "stub",
    runs: int = 1,
    out: Union[str, Path, None] = None,
) -> dict:
    """Run the reliability suite, persist the artifacts, return the payload."""
    adapter = get_adapter(adapter_name)
    mission = _default_mission()
    specs = baseline_specs()
    out = Path(
        out
        or f"data/measurements/reliability-{adapter.name}-"
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
                f"failing={record.failing_checks or '-'}"
            )

    ok = [r for r in records if r.status == "ok"]
    n_errors = len(records) - len(ok)
    n_with_violation = sum(1 for r in ok if r.failing_checks)
    violation_counts = Counter(
        check for r in ok for check in r.failing_checks
    )
    n_raw = sum(1 for r in ok if r.raw_link_violations > 0)
    n_first = sum(
        1 for r in ok if (r.first_attempt_raw_link_violations or 0) > 0
    )
    n_refined = sum(1 for r in ok if r.refined)
    n_refined_to_clean = sum(
        1 for r in ok if r.refined and r.raw_link_violations == 0
    )
    attempts = [r.n_attempts for r in ok if r.n_attempts is not None]

    # Post-run quality scan aggregates (the paper's lifecycle numbers):
    # findings per check category, contamination per category, the automated
    # label audit's correction rate, and the stripping pass statistics.
    n_quality_flags = sum(1 for r in ok if r.quality_flags > 0)
    quality_flag_counts = Counter(
        check for r in ok for check in r.quality_failing
    )
    quality_finding_counts: dict[str, int] = {}
    for check in QUALITY_CHECKS:
        total = 0
        for r in ok:
            for res in (r.quality_report or {}).get("results", []):
                if res["check"] == check:
                    total += res["count"]
        quality_finding_counts[check] = total
    n_contaminated = sum(1 for r in ok if r.contamination)
    contamination_counts = Counter(
        check for r in ok for check in r.contamination
    )
    n_label_mismatch = sum(1 for r in ok if r.label_mismatches)
    label_mismatch_counts = Counter(
        label for r in ok for label in r.label_mismatches
    )
    n_strip_affected = sum(
        1 for r in ok if r.strip_affected_messages > 0
    )
    strip_chars = sum(r.strip_stripped_chars for r in ok)

    payload = {
        "adapter": adapter.name,
        "model": specs[0].model["name"],
        "n_specs": len(specs),
        "n_runs": len(records),
        "n_generation_errors": n_errors,
        "n_campaigns_with_violation": n_with_violation,
        "failure_rate": (
            round(n_with_violation / len(ok), 4) if ok else None
        ),
        # First-attempt raw link violations (the LLM's output before any
        # refinement round) is the generator's reliability metric.
        "n_campaigns_with_first_attempt_raw_violation": n_first,
        "first_attempt_raw_link_violation_rate": (
            round(n_first / len(ok), 4) if ok else None
        ),
        "total_first_attempt_raw_link_violations": sum(
            r.first_attempt_raw_link_violations or 0 for r in ok
        ),
        # Raw link violations remaining on the delivered artifact, after
        # self-refinement rounds; failure_rate above is the post-assembler
        # delivery guarantee.
        "n_campaigns_with_raw_link_violation": n_raw,
        "raw_link_violation_rate": (round(n_raw / len(ok), 4) if ok else None),
        "total_raw_link_violations": sum(r.raw_link_violations for r in ok),
        # Self-refinement activity (from the driver's run_info).
        "n_refined": n_refined,
        "n_refined_to_clean": n_refined_to_clean,
        "refinement_success_rate": (
            round(n_refined_to_clean / n_refined, 4) if n_refined else None
        ),
        "avg_attempts": (
            round(sum(attempts) / len(attempts), 2) if attempts else None
        ),
        "attempts_distribution": dict(Counter(attempts)),
        "violation_counts": {c: violation_counts.get(c, 0) for c in CHECKS},
        # Post-run quality scan (the paper's lifecycle, on every run).
        "n_campaigns_with_quality_flags": n_quality_flags,
        "quality_flag_rate": (round(n_quality_flags / len(ok), 4) if ok else None),
        "quality_flag_counts": {
            c: quality_flag_counts.get(c, 0) for c in QUALITY_CHECKS
        },
        "quality_finding_counts": {
            c: quality_finding_counts.get(c, 0) for c in QUALITY_CHECKS
        },
        "n_campaigns_with_contamination": n_contaminated,
        "contamination_rate": (
            round(n_contaminated / len(ok), 4) if ok else None
        ),
        "contamination_counts": {
            c: contamination_counts.get(c, 0) for c in CONTAMINATION_CHECKS
        },
        "n_campaigns_with_label_mismatch": n_label_mismatch,
        "label_correction_rate": (
            round(n_label_mismatch / len(ok), 4) if ok else None
        ),
        "label_mismatch_counts": {
            label: label_mismatch_counts.get(label, 0)
            for label in ("pretext", "tone", "difficulty")
        },
        "n_campaigns_with_strip_affected": n_strip_affected,
        "strip_affected_rate": (
            round(n_strip_affected / len(ok), 4) if ok else None
        ),
        "total_stripped_chars": strip_chars,
        "per_spec": [
            {
                "spec_id": r.spec_id,
                "run": r.run_index,
                "seed": r.seed,
                "status": r.status,
                "campaign_hash": r.campaign_hash,
                "failing_checks": r.failing_checks,
                "raw_link_violations": r.raw_link_violations,
                "first_attempt_raw_link_violations": (
                    r.first_attempt_raw_link_violations
                ),
                "n_attempts": r.n_attempts,
                "refined": r.refined,
                "error": r.error,
                "duration_ms": r.duration_ms,
                "quality_flags": r.quality_flags,
                "quality_failing": r.quality_failing,
                "contamination": r.contamination,
                "label_mismatches": r.label_mismatches,
                "strip_affected_messages": r.strip_affected_messages,
                "strip_stripped_chars": r.strip_stripped_chars,
            }
            for r in records
        ],
        "out_dir": str(out),
    }
    (out / "reliability.json").write_text(
        json.dumps(payload, indent=2), encoding="utf-8"
    )

    lines = [
        "# Reliability experiment — summary",
        "",
        f"- adapter: `{payload['adapter']}` · model: `{payload['model']}`",
        f"- specs: {payload['n_specs']} · runs: {payload['n_runs']} · "
        f"generation errors: {payload['n_generation_errors']}",
        "",
        "## Three link-consistency numbers",
        "",
        f"- **First-attempt raw violations — generator reliability:** "
        f"{payload['n_campaigns_with_first_attempt_raw_violation']}/{len(ok)} campaigns "
        f"({payload['first_attempt_raw_link_violation_rate']}); "
        f"{payload['total_first_attempt_raw_link_violations']} stale tokens "
        f"total. Counted from the driver's first parse-successful attempt, "
        f"before any refinement round.",
        f"- **Post-refinement raw violations — delivered artifact:** "
        f"{payload['n_campaigns_with_raw_link_violation']}/{len(ok)} campaigns "
        f"({payload['raw_link_violation_rate']}); "
        f"{payload['total_raw_link_violations']} stale tokens total. The "
        f"`link_fixes` remaining on the final artifact after self-refinement.",
        f"- **Post-assembler violations — delivery guarantee:** "
        f"{payload['n_campaigns_with_violation']}/{len(ok)} campaigns "
        f"(failure rate {payload['failure_rate']}). By construction this is 0 "
        f"for `link_consistency` after the normalization fix; it measures the "
        f"delivered artifact, not the model.",
        "",
        "## Self-refinement",
        "",
        f"- campaigns refined: {payload['n_refined']} · refined to clean: "
        f"{payload['n_refined_to_clean']} (success rate "
        f"{payload['refinement_success_rate']})",
        f"- attempts: avg {payload['avg_attempts']} · distribution "
        f"{payload['attempts_distribution']}",
        "",
        "## Violations by coherence check (post-assembler artifact)",
        "",
        "| check | violations |",
        "|---|---|",
    ]
    for check in CHECKS:
        lines.append(f"| `{check}` | {payload['violation_counts'][check]} |")
    lines += [
        "",
        "## Post-run quality scan (the paper's lifecycle, on every run)",
        "",
        f"- campaigns with ≥ 1 quality flag: "
        f"{payload['n_campaigns_with_quality_flags']}/{len(ok)} "
        f"(rate {payload['quality_flag_rate']})",
        f"- campaigns with contamination: "
        f"{payload['n_campaigns_with_contamination']}/{len(ok)} "
        f"(rate {payload['contamination_rate']})",
        f"- campaigns with a label mismatch (automated audit): "
        f"{payload['n_campaigns_with_label_mismatch']}/{len(ok)} "
        f"(correction rate {payload['label_correction_rate']}; "
        f"by label {payload['label_mismatch_counts']})",
        f"- campaigns with strip-affected messages: "
        f"{payload['n_campaigns_with_strip_affected']}/{len(ok)} "
        f"(rate {payload['strip_affected_rate']}); "
        f"{payload['total_stripped_chars']} chars would be removed",
        "",
        "| quality check | findings | campaigns flagged |",
        "|---|---|---|",
    ]
    for check in QUALITY_CHECKS:
        lines.append(
            f"| `{check}` | {payload['quality_finding_counts'][check]} | "
            f"{payload['quality_flag_counts'][check]} |"
        )
    lines += [
        "",
        "## Per-spec results",
        "",
        "| spec | run | seed | status | attempts | refined | first raw | "
        "final raw | failing checks | quality flags | contamination | "
        "label mismatches |",
        "|---|---|---|---|---|---|---|---|---|---|---|---|",
    ]
    for r in records:
        lines.append(
            f"| {r.spec_id} | {r.run_index} | {r.seed} | {r.status} | "
            f"{r.n_attempts if r.n_attempts is not None else '—'} | "
            f"{'yes' if r.refined else 'no'} | "
            f"{r.first_attempt_raw_link_violations if r.first_attempt_raw_link_violations is not None else '—'} | "
            f"{r.raw_link_violations} | "
            f"{', '.join(r.failing_checks) or '—'} | "
            f"{r.quality_flags} | "
            f"{', '.join(r.contamination) or '—'} | "
            f"{', '.join(r.label_mismatches) or '—'} |"
        )
    (out / "summary.md").write_text("\n".join(lines) + "\n", encoding="utf-8")

    print(f"saved: {out / 'reliability.json'}")
    print(f"saved: {out / 'summary.md'}")
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
