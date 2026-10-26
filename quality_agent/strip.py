"""Stage-direction stripping (COVA-X §IV-D ``strip_stage_directions()``).

Removes stage-direction artifacts from a **copy** of the prose:

- bracketed placeholders and structural tags (``[EMAIL_SUBJECT]``,
  ``[HOSTAGE VOICE]``),
- parenthetical writing directions (``(insert urgency here)``),
- leftover ``{{cta-link}}`` placeholder variants,
- bare-colon speech-tag artifacts at line start.

The original text is never mutated — the strip is applied to a copy so the
scanner can report the *would-be* cleanup without destroying evidence, the
same way the paper applies its filters to preprocessed copies and keeps the
pre-cleanup numbers as the three-point evidence chain's baseline.
"""

from __future__ import annotations

import re

from quality_agent.lexicon import STAGE_DIRECTION_PATTERNS, compile_patterns

_STRIP = compile_patterns(STAGE_DIRECTION_PATTERNS)

# Parenthetical directions are not all strip-able with the same regex, but the
# pattern above already covers them; this one collapses the residue into
# nothing when the whole parenthesis is a direction.
_PAREN_DIRECTION = re.compile(
    r"\s*\((insert|mention|note|state|write|add|replace|use|tone|"
    r"urgent tone|friendly tone)[^)]{0,60}\)",
    re.IGNORECASE,
)


def strip_stage_directions(text: str) -> tuple[str, int]:
    """Return ``(cleaned_copy, removed_chars)`` for one prose field.

    The removed-char count measures how much stage-direction content the
    artifact carries; aggregated over messages it is the paper's
    "affected-turn rate" analogue.
    """
    cleaned = text
    for pattern in _STRIP:
        cleaned = pattern.sub("", cleaned)
    cleaned = _PAREN_DIRECTION.sub("", cleaned)
    # Collapse whitespace the removals left behind.
    cleaned = re.sub(r"[ \t]{2,}", " ", cleaned)
    cleaned = re.sub(r"\n{2,}", "\n", cleaned).strip()
    return cleaned, len(text) - len(cleaned)
