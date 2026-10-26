"""Run manifest + provenance logging for the interactive harness.

Every execution (``/generate`` or ``/replay``) leaves two artifacts in the
harness's output directory (``<output_dir>``, default ``data/shell``):

- ``<output_dir>/runs.json`` — the **run manifest**: an append-only list, one
  entry per execution, recording what ran (adapter, model, spec, files,
  refinement metadata, validator verdict, quality scan summary) and which run
  a replay re-ran.
- ``<output_dir>/<campaign_id>/provenance.json`` — the **provenance log**:
  the campaign-level identity plus every message's ``GenerationProvenance``
  (model, params, prompt template id, prompt hash, runtime) and its
  ``link_fixes``.

Every run also gets the post-run quality scan (``quality_agent.scan``); the
full ``QualityReport`` is saved next to the campaign as
``quality_report.json`` and its summary lands in the manifest entry.

``/replay`` reads the manifest's last entry to re-run the last execution;
``/replay-logs`` renders the manifest entry and provenance log in the
terminal. All helpers here are pure file I/O — no LLM, no ADK imports — so
they are testable offline.
"""

from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path


def utcnow() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def manifest_path(output_dir) -> Path:
    return Path(output_dir) / "runs.json"


def load_manifest(output_dir) -> list[dict]:
    """The manifest entries, oldest first; ``[]`` when missing or unreadable."""
    path = manifest_path(output_dir)
    if not path.exists():
        return []
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return []
    return data if isinstance(data, list) else []


def append_manifest(output_dir, entry: dict) -> dict:
    """Append one entry to the manifest (create the file if needed)."""
    entries = load_manifest(output_dir)
    entries.append(entry)
    path = manifest_path(output_dir)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(entries, indent=2) + "\n", encoding="utf-8")
    return entry


def last_entry(output_dir) -> dict | None:
    entries = load_manifest(output_dir)
    return entries[-1] if entries else None


def next_run_id(output_dir) -> str:
    """Sequential, sortable run id: run-<seq>-<HHMMSS> (UTC)."""
    seq = len(load_manifest(output_dir)) + 1
    stamp = datetime.now(timezone.utc).strftime("%H%M%S")
    return f"run-{seq:03d}-{stamp}"


def build_entry(
    *,
    run_id: str,
    kind: str,               # "generate" | "replay"
    parent_run_id: str | None,
    adapter: str,
    model: str,
    spec: dict,
    files: dict,
    run_info: dict | None,
    report=None,
    quality=None,
) -> dict:
    """One manifest entry: everything needed to replay or audit the run."""
    return {
        "run_id": run_id,
        "kind": kind,
        "parent_run_id": parent_run_id,
        "started_at": utcnow(),
        "adapter": adapter,
        "model": model,
        "campaign_id": spec["campaign_id"],
        "spec": spec,
        "files": {k: str(v) for k, v in files.items()},
        "refinement": run_info or {},
        "report": (
            {
                "all_passed": report.all_passed,
                "failing": [r.check.value for r in report.results if not r.passed],
            }
            if report is not None
            else None
        ),
        "quality": (
            {
                "n_flags": quality.n_flags,
                "any_flag": quality.any_flag,
                "failing": [r.check for r in quality.results if not r.passed],
                "label_mismatches": list(quality.label_audit.mismatches),
                "strip_affected_messages": quality.strip_stats.affected_messages,
                "strip_stripped_chars": quality.strip_stats.stripped_chars,
            }
            if quality is not None
            else None
        ),
        "status": "ok",
    }


def provenance_payload(campaign) -> dict:
    """The provenance log: campaign identity + per-message provenance."""
    return {
        "campaign_id": campaign.campaign_id,
        "persona": campaign.persona.model_dump(),
        "logged_at": utcnow(),
        "messages": [
            {
                "message_id": m.message_id,
                "channel": m.channel.value,
                "link_fixes": [f.model_dump() for f in m.link_fixes],
                "provenance": m.provenance.model_dump(mode="json"),
            }
            for m in campaign.messages
        ],
    }


def write_provenance(campaign, campaign_dir) -> Path:
    """Write the provenance log into the campaign's output directory."""
    path = Path(campaign_dir) / "provenance.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(provenance_payload(campaign), indent=2) + "\n",
        encoding="utf-8",
    )
    return path
