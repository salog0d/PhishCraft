"""Reliability experiment: run the spec set and count constraint violations.

    python -m measurement.reliability --adapter adk --runs 1
    python -m measurement.reliability --adapter stub

Aggregates over every spec x run: how many campaigns violate at least one
coherence constraint, broken down by check. Writes ``<out>/reliability.json``
and a human-readable ``<out>/summary.md`` — the failure rate is the paper's
first result. The interactive shell calls ``run()`` directly.
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

REPO_ROOT = Path(__file__).resolve().parent.parent

CHECKS = [
    "persona_identity",
    "timing",
    "cross_channel_reference",
    "link_consistency",
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
        "violation_counts": {c: violation_counts.get(c, 0) for c in CHECKS},
        "per_spec": [
            {
                "spec_id": r.spec_id,
                "run": r.run_index,
                "seed": r.seed,
                "status": r.status,
                "campaign_hash": r.campaign_hash,
                "failing_checks": r.failing_checks,
                "error": r.error,
                "duration_ms": r.duration_ms,
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
        f"- **campaigns with ≥ 1 violation: {payload['n_campaigns_with_violation']}"
        f"/{len(ok)} (failure rate {payload['failure_rate']})**",
        "",
        "## Violations by coherence check",
        "",
        "| check | violations |",
        "|---|---|",
    ]
    for check in CHECKS:
        lines.append(f"| `{check}` | {payload['violation_counts'][check]} |")
    lines += [
        "",
        "## Per-spec results",
        "",
        "| spec | run | seed | status | failing checks |",
        "|---|---|---|---|---|",
    ]
    for r in records:
        lines.append(
            f"| {r.spec_id} | {r.run_index} | {r.seed} | {r.status} | "
            f"{', '.join(r.failing_checks) or '—'} |"
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
