#!/usr/bin/env python3
"""Re-scan already-generated campaigns with the current quality detector.

Rewrites each run's ``quality_report.json`` and the ``quality`` block in the
append-only ``runs.jsonl`` manifest using the *current* ``quality_agent`` code.
This is for re-instrumenting an existing experiment after a detector fix
(e.g. the meta_bleed false-positive cleanup) without re-generating campaigns.

Usage:

    python scripts/rescan_quality.py experiment/reliability-final-<ts>
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT / "src"))

from app.core.schemas import GeneratedCampaign  # noqa: E402
from quality_agent.scan import scan_campaign  # noqa: E402


def quality_block(quality) -> dict:
    """The manifest's compact `quality` summary derived from a QualityReport."""
    return {
        "n_flags": quality.n_flags,
        "any_flag": quality.any_flag,
        "failing": [r.check for r in quality.results if not r.passed],
        "label_mismatches": list(quality.label_audit.mismatches),
        "label_statuses": dict(quality.label_audit.statuses),
    }


def rescan(out: Path) -> None:
    manifest = out / "runs.jsonl"
    if not manifest.exists():
        raise SystemExit(f"no runs.jsonl at {manifest}")

    lines = manifest.read_text(encoding="utf-8").splitlines()
    out_lines: list[str] = []
    rescanned = 0
    for line in lines:
        if not line.strip():
            continue
        rec = json.loads(line)
        if rec.get("status") != "ok" or not rec.get("dir"):
            out_lines.append(json.dumps(rec, ensure_ascii=False))
            continue
        run_dir = out / rec["dir"]
        campaign_path = run_dir / "generated_campaign.json"
        run_path = run_dir / "run.json"
        if not campaign_path.exists():
            out_lines.append(json.dumps(rec, ensure_ascii=False))
            continue

        campaign = GeneratedCampaign.model_validate_json(
            campaign_path.read_text(encoding="utf-8"))
        # spec provides pretext/tone/difficulty for the label audit + contamination.
        spec = rec.get("config") or {}
        if not spec and run_path.exists():
            spec = json.loads(run_path.read_text(encoding="utf-8")).get("config", {})
        quality = scan_campaign(campaign, spec=spec)

        # rewrite quality_report.json (full report)
        (run_dir / "quality_report.json").write_text(
            quality.model_dump_json(indent=2), encoding="utf-8")

        # update the manifest's compact quality summary
        rec["quality"] = quality_block(quality)
        # keep run.json's quality in sync too
        if run_path.exists():
            run_rec = json.loads(run_path.read_text(encoding="utf-8"))
            run_rec.setdefault("quality", quality_block(quality))
            run_path.write_text(json.dumps(run_rec, indent=2, ensure_ascii=False),
                                encoding="utf-8")

        out_lines.append(json.dumps(rec, ensure_ascii=False))
        rescanned += 1

    # Rewrite the manifest preserving append-only line format (no trailing NUL).
    manifest.write_text("\n".join(out_lines) + "\n", encoding="utf-8")
    print(f"rescanned {rescanned} ok campaigns; rewrote {manifest.name} + "
          f"per-run quality_report.json")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("out", help="experiment output directory (has runs.jsonl)")
    args = parser.parse_args()
    rescan(Path(args.out))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
