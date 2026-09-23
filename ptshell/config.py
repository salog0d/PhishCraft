"""Persistent shell configuration (Claude-Code-style settings file).

Settings live in a JSON file — default ``~/.pt-shell/config.json``, override
with the ``PTSHELL_CONFIG`` env var. Keys missing from the file fall back to
the defaults below, so a partial file is fine. Keys are flat so they can be
set from the shell with ``/config <key> <value>``.
"""

from __future__ import annotations

import json
import os
import sys
from pathlib import Path

from app.core.schemas import Difficulty, Pretext, Tone

DEFAULTS: dict[str, object] = {
    "model": "deepseek/deepseek-chat",
    "pretext": "executive_request",
    "tone": "urgent",
    "difficulty": "medium",
    "language": "en",
    "seed": 42,
    "recipient_id": "",           # empty -> first non-executive internal person
    "start_at": "2026-08-20T09:00:00Z",
    "followup_minutes": 75,
    "adapter": "adk",             # "adk" (real ADK pipeline) | "stub" (offline)
    "mission": "config/q3-awareness-2026.mission.json",
    "output_dir": "data/shell",   # never data/<campaign_id> — that holds evidence
}

VALID_VALUES: dict[str, list[str]] = {
    "pretext": [p.value for p in Pretext],
    "tone": [t.value for t in Tone],
    "difficulty": [d.value for d in Difficulty],
    "adapter": ["adk", "stub"],
}

INT_KEYS = {"seed", "followup_minutes"}

KNOWN_MODELS = [
    "deepseek/deepseek-chat",
    "deepseek/deepseek-reasoner",
    "gemini-2.5-flash",
    "anthropic/claude-opus-5",   # LiteLlm, needs ANTHROPIC_API_KEY
    "openai/gpt-4.1",            # LiteLlm, needs OPENAI_API_KEY
]


def config_path() -> Path:
    return Path(
        os.environ.get("PTSHELL_CONFIG")
        or Path.home() / ".pt-shell" / "config.json"
    )


def load() -> dict:
    """Defaults merged with the stored settings file (if any)."""
    cfg = dict(DEFAULTS)
    path = config_path()
    if path.exists():
        try:
            stored = json.loads(path.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError) as exc:
            print(
                f"warning: could not read {path} ({exc}); using defaults",
                file=sys.stderr,
            )
            return cfg
        for key, value in stored.items():
            if key in DEFAULTS:
                cfg[key] = coerce(key, value)
    return cfg


def save(cfg: dict) -> Path:
    """Persist the settings dict; returns the file path."""
    path = config_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(cfg, indent=2) + "\n", encoding="utf-8")
    return path


def reset() -> None:
    """Drop the stored settings file (back to defaults)."""
    path = config_path()
    if path.exists():
        path.unlink()


def coerce(key: str, value):
    """Normalize a raw value (e.g. '42' -> 42 for integer keys)."""
    if key in INT_KEYS:
        return int(value)
    return value


def validate(key: str, value) -> str | None:
    """Return an error message for an invalid key/value, else None."""
    if key not in DEFAULTS:
        return f"unknown key '{key}' (valid: {', '.join(sorted(DEFAULTS))})"
    if key in INT_KEYS:
        try:
            int(value)
        except (TypeError, ValueError):
            return f"'{key}' must be an integer"
        if key == "seed" and int(value) < 0:
            return "seed must be >= 0"
        return None
    if key in VALID_VALUES and value not in VALID_VALUES[key]:
        return f"'{key}' must be one of: {', '.join(VALID_VALUES[key])}"
    return None
