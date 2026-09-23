"""Reproducibility experiment: run the same spec N times and compare.

    python -m measurement.reproduce --adapter adk --spec-id S1 --runs 2
    python -m measurement.reproduce --adapter stub --runs 2   # all specs

Writes ``<out>/reproducibility.json`` and one artifact pair per run under
``<out>/runs/<spec_id>/``. The deterministic layer (ids, persona, URLs,
references, schedule, provenance) must match across runs; the content layer
(LLM-written subject/body) is the measured result.
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from measurement.adapters import get_adapter
from measurement.runner import canonical_hash, deterministic_layer_hash
from measurement.specs import baseline_specs

REPO_ROOT = Path(__file__).resolve().parent.parent


def _default_mission() -> dict:
    return json.loads(
        (REPO_ROOT / "config" / "q3-awareness-2026.mission.json").read_text()
    )


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--spec-id", help="run one spec (default: all)")
    parser.add_argument("--runs", type=int, default=2)
    parser.add_argument("--adapter", default="stub")
    parser.add_argument("--out", default=None)
    args = parser.parse_args()

    adapter = get_adapter(args.adapter)
    mission = _default_mission()
    out = Path(args.out or f"data/measurements/reproduce-{args.adapter}")
    specs = [s for s in baseline_specs() if not args.spec_id or s.spec_id == args.spec_id]

    results: dict = {"adapter": adapter.name, "specs": {}}
    for spec in specs:
        rows = []
        for i in range(1, args.runs + 1):
            run_dir = out / "runs" / spec.spec_id
            run_dir.mkdir(parents=True, exist_ok=True)
            try:
                campaign, report = adapter.run(spec.to_dict(), mission)
                (run_dir / f"run-{i:02d}.campaign.json").write_text(
                    campaign.model_dump_json(indent=2), encoding="utf-8"
                )
                (run_dir / f"run-{i:02d}.report.json").write_text(
                    report.model_dump_json(indent=2), encoding="utf-8"
                )
                rows.append(
                    {
                        "run": i,
                        "status": "ok",
                        "campaign_hash": canonical_hash(campaign),
                        "deterministic_layer_hash": deterministic_layer_hash(campaign),
                    }
                )
            except Exception as exc:
                rows.append(
                    {"run": i, "status": "generation_error",
                     "error": f"{type(exc).__name__}: {exc}"}
                )
        hashes = [r["campaign_hash"] for r in rows if r["status"] == "ok"]
        layer_hashes = [
            r["deterministic_layer_hash"] for r in rows if r["status"] == "ok"
        ]
        results["specs"][spec.spec_id] = {
            "seed": spec.seed,
            "model": spec.model["name"],
            "runs": rows,
            "identical": len(hashes) == len(rows) and len(set(hashes)) <= 1,
            "deterministic_layer_identical": (
                len(layer_hashes) == len(rows) and len(set(layer_hashes)) <= 1
            ),
        }
        print(
            f"{spec.spec_id}: identical={results['specs'][spec.spec_id]['identical']} "
            f"deterministic_layer_identical="
            f"{results['specs'][spec.spec_id]['deterministic_layer_identical']} "
            f"(runs={len(rows)}, errors={sum(1 for r in rows if r['status'] != 'ok')})"
        )

    out.mkdir(parents=True, exist_ok=True)
    (out / "reproducibility.json").write_text(
        json.dumps(results, indent=2), encoding="utf-8"
    )
    print(f"saved: {out / 'reproducibility.json'}")


if __name__ == "__main__":
    main()
