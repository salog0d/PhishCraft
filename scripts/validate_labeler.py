#!/usr/bin/env python3
"""Validate the deterministic labeler against human gold labels.

The automated label audit (``quality_agent/labels.py``) predicts pretext, tone
and difficulty from prose via argmax over lexicons. Before trusting the
``achieved_*`` relabel (and the tone/difficulty mismatch rates) as real signal,
the labeler's own accuracy must be measured against human judgment on a sample.

Steps:

    # 1. sample N campaigns and emit an annotation sheet for a human reviewer
    python scripts/validate_labeler.py --sample experiment/reliability-final-<ts> --n 40

        -> writes <out>/labeler_validation_sheet.csv
           (run_id, model, spec_*, email_subject/body, sms_body, empty human_*)

    # 2. after a human fills the human_* columns, score agreement
    python scripts/validate_labeler.py --score-from-experiment experiment/reliability-final-<ts>

        -> prints per-label exact-match rate + Cohen's kappa

`unverifiable` is defined operationally as: the labeler's argmax found no
signal (zero hits) or an ambiguous tie — reported as ``(unverifiable)``, never
a forced label.
"""

from __future__ import annotations

import argparse
import csv
import json
import sys
from collections import Counter
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT / "src"))

from app.core.schemas import GeneratedCampaign  # noqa: E402

LABELS = ("pretext", "tone", "difficulty")


def _campaign_texts(campaign) -> tuple[str, str, str]:
    subj = body = sms = ""
    for m in campaign.messages:
        if m.channel.value == "email":
            subj = m.subject or ""
            body = m.body or ""
        else:
            sms = m.body or ""
    return subj, body, sms


# --------------------------------------------------------------------------- #
# Step 1 — sample + emit the annotation sheet
# --------------------------------------------------------------------------- #

def sample(out: Path, n: int) -> None:
    manifest = out / "runs.jsonl"
    if not manifest.exists():
        raise SystemExit(f"no runs.jsonl at {manifest}")
    rows = [json.loads(l) for l in manifest.read_text(encoding="utf-8").splitlines()
            if l.strip()]
    by_id = {r["run_id"]: r for r in rows}
    ok = [r for r in by_id.values() if r.get("status") == "ok" and r.get("dir")]
    sample_rows = ok[:n]

    fieldnames = (
        "run_id", "model", "spec_pretext", "spec_tone", "spec_difficulty",
        "email_subject", "email_body", "sms_body",
        "human_pretext", "human_tone", "human_difficulty",
    )
    dest = out / "labeler_validation_sheet.csv"
    with dest.open("w", newline="", encoding="utf-8") as fh:
        w = csv.DictWriter(fh, fieldnames=fieldnames)
        w.writeheader()
        for r in sample_rows:
            campaign = GeneratedCampaign.model_validate_json(
                (out / r["dir"] / "generated_campaign.json").read_text(encoding="utf-8"))
            subj, body, sms = _campaign_texts(campaign)
            w.writerow({
                "run_id": r["run_id"],
                "model": r.get("model"),
                "spec_pretext": r.get("pretext"),
                "spec_tone": r.get("tone"),
                "spec_difficulty": r.get("difficulty"),
                "email_subject": subj,
                "email_body": body,
                "sms_body": sms,
                "human_pretext": "",
                "human_tone": "",
                "human_difficulty": "",
            })
    print(f"annotation sheet: {dest} ({len(sample_rows)} rows)")
    print("fill the human_* columns, then run --score-from-experiment.")


# --------------------------------------------------------------------------- #
# Step 2 — score agreement (exact + Cohen's kappa)
# --------------------------------------------------------------------------- #

def _kappa(observed: Counter, n: int) -> float:
    """Cohen's kappa for a multiclass agreement from a Counter of (human, model)."""
    if n == 0:
        return 0.0
    classes = sorted({k for tup in observed for k in tup})
    if len(classes) <= 1:
        return 1.0
    idx = {c: i for i, c in enumerate(classes)}
    m = len(classes)
    conf = [[0] * m for _ in range(m)]
    for (a, b), cnt in observed.items():
        conf[idx[a]][idx[b]] += cnt
    po = sum(observed[(c, c)] for c in classes) / n
    pe = 0.0
    for i in range(m):
        row = sum(conf[i])
        col = sum(conf[j][i] for j in range(m))
        pe += (row / n) * (col / n)
    return (po - pe) / (1 - pe) if 1 - pe != 0 else 1.0


def score_from_experiment(out: Path, sheet: Path) -> None:
    # human labels from the filled sheet
    human = {}
    for r in csv.DictReader(sheet.open(encoding="utf-8")):
        human[r["run_id"]] = {
            "pretext": (r.get("human_pretext") or "").strip().lower(),
            "tone": (r.get("human_tone") or "").strip().lower(),
            "difficulty": (r.get("human_difficulty") or "").strip().lower(),
        }
    # predicted labels from the experiment's stored label_predicted
    rows = [json.loads(l) for l in (out / "runs.jsonl").read_text(encoding="utf-8").splitlines()
            if l.strip()]
    by_id = {r["run_id"]: r for r in rows}

    per_label: dict[str, Counter] = {lab: Counter() for lab in LABELS}
    n_per: dict[str, int] = {lab: 0 for lab in LABELS}
    for run_id, h in human.items():
        rec = by_id.get(run_id)
        if not rec:
            continue
        pred = (rec.get("quality") or {}).get("label_predicted") or {}
        for lab in LABELS:
            hv = h[lab]
            if not hv:
                continue  # human skipped this label
            pv = pred.get(lab) or "(unverifiable)"
            n_per[lab] += 1
            per_label[lab][(hv, pv)] += 1

    print(f"{'label':12} {'n':>3}  {'exact':>6}  {'kappa':>6}")
    print("-" * 34)
    for lab in LABELS:
        n = n_per[lab]
        if n == 0:
            print(f"{lab:12}   0    —      —")
            continue
        exact = sum(cnt for (a, b), cnt in per_label[lab].items() if a == b) / n
        k = _kappa(per_label[lab], n)
        print(f"{lab:12} {n:3}  {exact * 100:5.1f}%  {k:6.3f}")


def main() -> int:
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--sample", metavar="OUT", help="experiment dir -> emit annotation sheet")
    p.add_argument("--n", type=int, default=40, help="sample size (default 40)")
    p.add_argument("--score-from-experiment", metavar="OUT",
                   help="experiment dir; reads <OUT>/labeler_validation_sheet.csv")
    args = p.parse_args()

    if args.sample:
        sample(Path(args.sample), args.n)
        return 0
    if args.score_from_experiment:
        out = Path(args.score_from_experiment)
        sheet = out / "labeler_validation_sheet.csv"
        if not sheet.exists():
            raise SystemExit(f"no {sheet}")
        score_from_experiment(out, sheet)
        return 0
    p.error("specify --sample or --score-from-experiment")


if __name__ == "__main__":
    raise SystemExit(main())
