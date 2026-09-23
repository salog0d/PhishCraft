"""URL/token extraction for the link_consistency coherence check."""

from __future__ import annotations

import re

FULL_URL = re.compile(r"https?://[^\s)\]\"'>]+")
BARE_REF = re.compile(r"\bsim\.[a-z0-9.-]+/t/[A-Za-z0-9._-]+")
_TRAILING = re.compile(r"[.,;:)\]]+$")


def _strip(url: str) -> str:
    return _TRAILING.sub("", url.rstrip())


def _token(url: str) -> str:
    return _strip(url).rstrip("/").rsplit("/", 1)[-1]


def tokens_in(text: str) -> set[str]:
    """Tracking tokens that appear in message prose (full URLs or bare refs)."""
    found = set()
    for m in FULL_URL.finditer(text):
        found.add(_token(m.group(0)))
    for m in BARE_REF.finditer(text):
        found.add(_token(m.group(0)))
    return found
