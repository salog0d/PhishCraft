"""Persistent shell configuration (Claude-Code-style settings file).

Settings live in a JSON file — default ``~/.pt-shell/config.json``, override
with the ``PTSHELL_CONFIG`` env var. Keys missing from the file fall back to
the defaults below, so a partial file is fine. Keys are flat so they can be
set from the shell with ``/config <key> <value>``.

The loader self-heals: an empty file is treated as "no settings yet" and a
corrupt file is moved aside (``*.corrupt-<ts>``) before falling back to
defaults, so a bad file never blocks startup and is never silently lost.
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
import time
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

# Local Ollama discovery: cached briefly because the tab-completer calls it
# on every keystroke; a new `ollama pull` shows up after the TTL expires.
_ollama_cache: list[str] = []
_ollama_checked_at: float = 0.0
_OLLAMA_TTL = 10.0


def ollama_models() -> list[str]:
    """Bare model names served by the local Ollama daemon (``ollama list``).

    Fails soft — no ``ollama`` binary or an unreachable daemon yields an empty
    list, so the shell keeps working offline. The LiteLlm model id for a name
    returned here is ``ollama/<name>``.
    """
    now = time.time()
    global _ollama_cache, _ollama_checked_at
    if now - _ollama_checked_at < _OLLAMA_TTL:
        return _ollama_cache
    models: list[str] = []
    try:
        out = subprocess.run(
            ["ollama", "list"],
            capture_output=True,
            text=True,
            check=True,
            timeout=5,
        ).stdout
    except (FileNotFoundError, subprocess.CalledProcessError,
            subprocess.TimeoutExpired):
        pass
    else:
        for line in out.splitlines()[1:]:  # skip the header row
            fields = line.split()
            if fields:
                models.append(fields[0])
    _ollama_checked_at = now
    _ollama_cache = models
    return models


def config_path() -> Path:
    return Path(
        os.environ.get("PTSHELL_CONFIG")
        or Path.home() / ".pt-shell" / "config.json"
    )


def load() -> dict:
    """Defaults merged with the stored settings file (if any).

    Self-heals broken files instead of warning on every launch:
    * missing file → defaults, untouched;
    * empty file → defaults (written back so the next start is quiet);
    * corrupt JSON → backed up next to the original, then defaults.
    """
    cfg = dict(DEFAULTS)
    path = config_path()
    if not path.exists():
        return cfg
    try:
        raw = path.read_text(encoding="utf-8")
    except OSError as exc:
        print(f"warning: could not read {path} ({exc}); using defaults",
              file=sys.stderr)
        return cfg
    if not raw.strip():
        # Empty file (e.g. a crash mid-write or an accidental `touch`):
        # start fresh and persist the defaults so it becomes valid JSON.
        save(cfg)
        return cfg
    try:
        stored = json.loads(raw)
    except json.JSONDecodeError as exc:
        backup = path.with_name(
            f"{path.name}.corrupt-{int(time.time())}"
        )
        try:
            path.rename(backup)
            print(
                f"warning: {path} is not valid JSON ({exc}); moved it to "
                f"{backup} and using defaults",
                file=sys.stderr,
            )
        except OSError:
            print(f"warning: could not read {path} ({exc}); using defaults",
                  file=sys.stderr)
        save(cfg)
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
