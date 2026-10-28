"""URL/token extraction for the link_consistency coherence check."""

from __future__ import annotations

import re

# A tracking token is 12 lowercase hex chars (the assembler derives it from
# sha256). Constrain to exactly that so stray text that a model glued onto the
# end of a URL (literal ``\n`` escapes, signatures, etc.) never leaks into the
# extracted token and produces a false ``link_consistency`` failure.
TOKEN_RE = re.compile(r"[0-9a-f]{12}")

# Stop a URL at backslashes too: some models embed literal ``\n`` (backslash-n)
# as text when they split a long body into one escaped line. ``\s`` alone does
# not stop on the two characters ``\`` and ``n``, so the ``\n`` sequence is
# swallowed into the match and pollutes the token.
FULL_URL = re.compile(r"https?://[^\s\\\]\"'>]+")

# Bare reference (no scheme): permissive on length/shape so a *mismatched* bare
# token is still found — catching it is the whole point of link_consistency.
# The clean 12-hex constraint is applied at extraction time in ``_token``, not
# here, so a bare `abc123`-style mismatch is never silently ignored.
BARE_REF = re.compile(r"\bsim\.[a-z0-9.-]+/t/[A-Za-z0-9._-]+")
_TRAILING = re.compile(r"[.,;:)\]]+$")


def _strip(url: str) -> str:
    return _TRAILING.sub("", url.rstrip())


def _token(url: str) -> str:
    """The tracking token from a URL, constrained to the 12-hex form.

    Falls back to the raw last ``/``-segment only when no 12-hex token is
    present (legacy UCTs); the constrained form is authoritative for the
    seed-derived tokens this generator emits.
    """
    stripped = _strip(url).rstrip("/")
    m = TOKEN_RE.search(stripped)
    if m:
        return m.group(0)
    return stripped.rsplit("/", 1)[-1]


def tokens_in(text: str) -> set[str]:
    """Tracking tokens that appear in message prose (full URLs or bare refs)."""
    found = set()
    for m in FULL_URL.finditer(text):
        found.add(_token(m.group(0)))
    for m in BARE_REF.finditer(text):
        found.add(_token(m.group(0)))
    return found
