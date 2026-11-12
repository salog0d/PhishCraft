#!/usr/bin/env python3
"""Export the campaign + quality-scan dataset in standardized formats.

Reads an experiment's ``runs.jsonl`` manifest and the per-run artifacts and
emits the *campaign corpus* (one row per completed campaign: metadata, message
content, and the flattened quality-scan + label-audit results) in three
interchangeable formats, plus a `Datasheets for Datasets`-style datasheet
describing motivation, composition, collection, preprocessing, uses,
distribution and maintenance.

Output (under ``<out>/dataset/``):

- ``campaigns.json``  — array of campaign records (structured, nested)
- ``campaigns.csv``   — flat table, one campaign per row
- ``campaigns.md``    — markdown table of the same rows
- ``datasheet.md``    — the datasheet (Gebru et al. sections)

Usage:

    python scripts/export_dataset.py experiment/reliability-final-<ts>
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


# --------------------------------------------------------------------------- #
# Loading
# --------------------------------------------------------------------------- #

QUALITY_CHECKS = (
    "dialogue_collapse", "stage_direction", "turn_overflow", "meta_bleed",
    "loop_detection", "pretext_contamination", "name_contamination",
    "brand_contamination", "script_contamination",
)


def _load_records(out: Path) -> list[dict]:
    manifest = out / "runs.jsonl"
    if not manifest.exists():
        raise SystemExit(f"no runs.jsonl at {manifest}")
    by_id: dict[str, dict] = {}
    for line in manifest.read_text(encoding="utf-8").splitlines():
        if not line.strip():
            continue
        rec = json.loads(line)
        by_id[rec["run_id"]] = rec  # last line wins
    return list(by_id.values())


def _campaign_row(rec: dict, out: Path) -> dict:
    """One flattened campaign record (metadata + content + quality + labels)."""
    campaign = None
    if rec.get("dir"):
        p = out / rec["dir"] / "generated_campaign.json"
        if p.exists():
            campaign = GeneratedCampaign.model_validate_json(
                p.read_text(encoding="utf-8"))

    quality = rec.get("quality") or {}
    run_info = rec.get("run_info") or {}
    label_statuses = quality.get("label_statuses") or {}
    label_predicted = quality.get("label_predicted") or {}

    # message content
    email = sms = None
    if campaign is not None:
        for m in campaign.messages:
            if m.channel.value == "email":
                email = m
            else:
                sms = m

    row = {
        # datasheet §Composition: identifiers + metadata
        "run_id": rec.get("run_id"),
        "case_id": rec.get("case_id"),
        "campaign_id": (campaign.campaign_id if campaign else None),
        "model": rec.get("model"),
        "temperature": rec.get("temperature"),
        "seed": rec.get("seed"),
        "pretext": rec.get("pretext"),
        "tone": rec.get("tone"),
        "difficulty": rec.get("difficulty"),
        "status": rec.get("status"),
        # message content (the instance "raw" data)
        "sender": (campaign.persona.display_name if campaign else None),
        "sender_email": (campaign.persona.email if campaign else None),
        "recipient": (campaign.recipient.full_name if campaign and campaign.recipient else None),
        "email_subject": (email.subject if email else None),
        "email_body": (email.body if email else None),
        "sms_body": (sms.body if sms else None),
        "landing_url": (
            str(email.call_to_action.landing_url)
            if email and email.call_to_action and email.call_to_action.landing_url else None
        ),
        # quality scan §Preprocessing/labeling: per-check flags + label audit
        "n_flags": quality.get("n_flags"),
        "any_flag": quality.get("any_flag"),
        "failing_checks": quality.get("failing") or [],
        "label_pretext_status": label_statuses.get("pretext"),
        "label_tone_status": label_statuses.get("tone"),
        "label_difficulty_status": label_statuses.get("difficulty"),
        # honest relabel: what the labeler actually detected (achieved), not
        # what was requested (spec).
        "achieved_pretext": label_predicted.get("pretext"),
        "achieved_tone": label_predicted.get("tone"),
        "achieved_difficulty": label_predicted.get("difficulty"),
        # refinement + effort evidence
        "n_parse_attempts": run_info.get("n_parse_attempts"),
        "n_refine_rounds": run_info.get("n_refine_rounds"),
        "refined": run_info.get("refined"),
        "refinement_improved": run_info.get("refinement_improved"),
        "total_tokens": (rec.get("trace") or {}).get("total_tokens"),
        "critic_calls": (rec.get("trace") or {}).get("critic_calls"),
        "duration_ms": rec.get("duration_ms"),
    }
    # expand the 9 checks into explicit boolean columns (flat/CSV-friendly)
    failing = set(row["failing_checks"])
    for check in QUALITY_CHECKS:
        row[f"check_{check}"] = check not in failing
    return row


# --------------------------------------------------------------------------- #
# Exporters
# --------------------------------------------------------------------------- #

def _write_json(rows: list[dict], path: Path) -> None:
    path.write_text(json.dumps(rows, indent=2, ensure_ascii=False), encoding="utf-8")


def _write_csv(rows: list[dict], path: Path) -> None:
    if not rows:
        path.write_text("", encoding="utf-8")
        return
    # keep nested/empty lists flattened into strings for CSV cells
    flat = []
    for r in rows:
        copy = {}
        for k, v in r.items():
            if isinstance(v, (list, dict)):
                copy[k] = json.dumps(v, ensure_ascii=False)
            else:
                copy[k] = v
        flat.append(copy)
    # column order: fixed, deterministic, with the 9 checks last
    cols = [k for k in flat[0] if not k.startswith("check_")]
    cols += list(QUALITY_CHECKS)  # recompute via the check_ prefix keys
    # fix: QUALITY_CHECKS are stored as check_<name>, so map back
    cols = [k for k in flat[0] if not k.startswith("check_")]
    cols += [f"check_{c}" for c in QUALITY_CHECKS if f"check_{c}" in flat[0]]
    with path.open("w", newline="", encoding="utf-8") as fh:
        w = csv.DictWriter(fh, fieldnames=cols, extrasaction="ignore")
        w.writeheader()
        for r in flat:
            w.writerow(r)


def _write_md(rows: list[dict], path: Path) -> None:
    if not rows:
        path.write_text("", encoding="utf-8")
        return
    # readable subset — not every column, keep the table legible
    keep = ("run_id", "model", "temperature", "seed", "pretext", "tone",
            "difficulty", "status", "n_flags", "label_pretext_status",
            "label_tone_status", "label_difficulty_status", "n_parse_attempts",
            "n_refine_rounds", "refined")
    lines = ["# Campaign corpus", ""]
    lines.append(f"{len(rows)} campaigns.")
    lines.append("")
    lines.append("| " + " | ".join(keep) + " |")
    lines.append("|" + "|".join("---" for _ in keep) + "|")
    for r in rows:
        cells = [str(r[k]) if r[k] is not None else "" for k in keep]
        lines.append("| " + " | ".join(cells) + " |")
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


# --------------------------------------------------------------------------- #
# Datasheet (§ Motivation → § Maintenance)
# --------------------------------------------------------------------------- #

def _datasheet(rows: list[dict], out: Path, models: list[str]) -> str:
    ok = [r for r in rows if r["status"] == "ok"]
    n = len(ok)
    by_pretext = Counter(r["pretext"] for r in ok)
    by_model = Counter(r["model"] for r in ok)
    n_flags = sum(r["n_flags"] or 0 for r in ok)
    label_mismatch = Counter()
    for r in ok:
        for lab in ("pretext", "tone", "difficulty"):
            if r[f"label_{lab}_status"] == "mismatch":
                label_mismatch[lab] += 1

    return f"""# Datasheet — Synthetic Phishing-Simulation Campaign Corpus

> Prepared following **Datasheets for Datasets** (Gebru et al., 2021).

## Motivation

**For what purpose was the dataset created?**
To evaluate how reliably a deterministic, constraint-driven generator
produces synthetic phishing-simulation campaigns (email + SMS), measured across
three open instruct models and three temperatures. The dataset records both the
*generated campaign* and its *post-run quality scan*, so a consumer can
reproduce the compliance and content-quality analysis.

**Who created the dataset, and on behalf of which entity?**
Generated by the PhishCraft pipeline (this repository), authored by the
project maintainers. No external data sources are used — all content is
synthetic.

**Who funded the creation?**
No external funding.

## Composition

**What do the instances represent?**
Each instance is one synthetic email+SMS campaign (persona, recipient,
subject/body, tracking link) plus the deterministic quality-scan verdicts
(9 content checks + 3-label audit) for that campaign.

**How many instances are there?**
{n} completed campaigns (of 324 executions; {len(rows) - n} failed/timeout).
Distribution by pretext: {dict(by_pretext)}. By model: {dict(by_model)}.

**Is it a sample of a larger set?**
Yes — a designed matrix: 3 models × 3 temperatures × 12 cases × 3 seeds.

**What data does each instance consist of?**
Raw generated text (subject/body) plus derived features (quality flags, label
audit, effort metrics). Every instance carries provenance (model, temperature,
seed) and a unique `run_id`.

**Is there a label/target?**
Yes — the spec's ground-truth `pretext`/`tone`/`difficulty`, against which the
deterministic labeler is compared (the `label_*_status` fields).

**Does it contain confidential/sensitive data?**
No. All personas, recipients, domains and details are synthetic (`.example`
TLDs, fictional rosters). No real individuals, no live infrastructure.

## Collection Process

**How was the data acquired?**
Generated programmatically via the ADK pipeline (`agent.driver`), not observed
or reported by people. The only "externality" is the LLM's own generation.

**Sampling strategy?**
Fully deterministic matrix over a fixed seed set (101/202/303), frozen model
tags, and temperature 0.0/0.5/1.0.

**Ethical review?**
Authorized awareness-research simulation only (`authorized: true`,
`synthetic_data_only: true`, `isolated_environment: true` in the mission).

## Preprocessing / cleaning / labeling

**Was any preprocessing done?**
The deterministic assembler normalizes persona, tracking token, schedule and
references by construction; the model writes only subject/body. Stage-direction
stripping is *measured on a copy*, never applied — the raw artifact is preserved
intact and the strip stats are recorded.

**Was the raw data saved?**
Yes — `generated_campaign.json` and `quality_report.json` per run retain the
full artifact and its findings.

**Is the software available?**
Yes — this repository (the harness, assembler, validator and quality scanner).

## Uses

**What tasks has it been used for?**
Generator reliability (constraint compliance) and content-quality analysis
across models/temperatures.

**What other tasks could it be used for?**
Cross-model comparison of instruction-following on a constrained generation
task; few-shot/self-refinement ablation studies.

**Tasks NOT to use it for.**
Nothing operational — it is synthetic training/awareness content only, not a
measure of real phishing efficacy, and contains no real victim interaction.

## Distribution

**How is it distributed?**
Multi-format export: `campaigns.json` (structured), `campaigns.csv` (flat
table), `campaigns.md` (human-readable). No DOI yet.

**License / ToU?**
Subject to this repository's license. No third-party IP restrictions.

## Maintenance

**Who maintains it?**
The project maintainers; regenerate with:
`python scripts/export_dataset.py {out.name}`.

**Is there an erratum?**
Not at this time.

**Will it be updated?**
Re-exported when the generator or the experiment is re-run with a new matrix.

**How to contact the maintainer?**
Via the repository's issue tracker.
"""


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("out", help="experiment output directory (has runs.jsonl)")
    args = parser.parse_args()
    out = Path(args.out)
    records = _load_records(out)
    rows = [_campaign_row(r, out) for r in records]
    models = sorted({r["model"] for r in rows})

    dest = out / "dataset"
    dest.mkdir(parents=True, exist_ok=True)
    _write_json(rows, dest / "campaigns.json")
    _write_csv(rows, dest / "campaigns.csv")
    _write_md(rows, dest / "campaigns.md")
    (dest / "datasheet.md").write_text(_datasheet(rows, out, models),
                                       encoding="utf-8")

    print(f"dataset exported to {dest}/")
    print(f"  campaigns.json   ({len(rows)} records)")
    print(f"  campaigns.csv    ({len(rows)} rows)")
    print(f"  campaigns.md     (table)")
    print(f"  datasheet.md     (datasheet)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
