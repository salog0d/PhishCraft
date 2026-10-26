"""Contamination scanners (COVA-X §IV-C contamination scan).

Four cross-campaign contamination categories, each a per-campaign check:

- ``pretext_contamination`` — lexicon bleed: terms tightly associated with a
  *different* pretext appearing in the campaign's prose (the paper's
  grandparent-opener bleed across scam types).
- ``name_contamination`` — cross-conversation name drift: another roster
  member's name in the prose, including concatenated-name artifacts
  (the paper's "JessicaEmily" finding).
- ``brand_contamination`` — a known external brand mentioned in a campaign
  that does not impersonate that brand.
- ``script_contamination`` — non-Latin script in an English campaign
  (the paper's non-Latin-script filter).

Like the paper's legacy-contamination treatment, contamination is *preserved
as data* — recorded, never silently corrected post-hoc.
"""

from __future__ import annotations

import re

from app.core.schemas import QualityFinding

from quality_agent.lexicon import (
    KNOWN_BRANDS,
    PRETEXT_TERMS,
    is_latin_typo,
    term_hits,
)

# One shared word is noise (an executive request about vendor payments may
# legitimately say "payment"); two *distinct* terms from another pretext's
# lexicon is bleed. Mirrors the paper's conservative flag threshold.
MIN_DISTINCT_TERMS = 2


def scan_pretext_contamination(
    texts: list[tuple[str, str]],
    pretext: str | None,
) -> list[QualityFinding]:
    """Terms from other pretexts' lexicons appearing in this campaign."""
    if not pretext or pretext not in PRETEXT_TERMS:
        return []
    findings: list[QualityFinding] = []
    foreign: dict[str, list[str]] = {}  # source pretext -> foreign terms found
    for field, text in texts:
        for other, terms in PRETEXT_TERMS.items():
            if other == pretext:
                continue
            hits = term_hits(text, terms)
            for term, count in hits.items():
                foreign.setdefault(other, [])
                foreign[other].append((term, count, field, text))
    for other, hits in foreign.items():
        distinct = {h[0] for h in hits}
        if len(distinct) >= MIN_DISTINCT_TERMS:
            term, _count, field, text = hits[0]
            findings.append(QualityFinding(
                check="pretext_contamination",
                field=field,
                excerpt=_excerpt(text, term),
                detail=f"{other} vocabulary bleeds into a {pretext} campaign "
                       f"({len(distinct)} distinct terms: "
                       f"{', '.join(sorted(distinct))})",
            ))
    return findings


def scan_name_contamination(
    texts: list[tuple[str, str]],
    *,
    persona_name: str,
    recipient_name: str | None,
    known_names: tuple[str, ...],
) -> list[QualityFinding]:
    """Other roster names — or concatenated-name artifacts — in the prose."""
    exclude = {persona_name.casefold(), persona_name.split()[0].casefold()}
    if recipient_name:
        exclude.add(recipient_name.casefold())
        exclude.add(recipient_name.split()[0].casefold())
    first_names = sorted({n for n in known_names if " " not in n},
                         key=len, reverse=True)
    findings: list[QualityFinding] = []
    for field, text in texts:
        for name in known_names:
            if name.casefold() in exclude:
                continue
            pattern = re.compile(r"(?<![\w])" + re.escape(name) + r"(?![\w])",
                                 re.IGNORECASE)
            if pattern.search(text):
                findings.append(QualityFinding(
                    check="name_contamination",
                    field=field,
                    excerpt=_excerpt(text, name),
                    detail=f"roster name '{name}' appears in a campaign that "
                           f"neither impersonates nor targets it",
                ))
        # Concatenated-name artifact: two known first names fused without a
        # separator (the paper's "JessicaEmily" finding).
        for first in first_names:
            for second in first_names:
                fused = first + second
                if len(fused) < 8:
                    continue
                index = text.casefold().find(fused.casefold())
                if index >= 0:
                    findings.append(QualityFinding(
                        check="name_contamination",
                        field=field,
                        excerpt=_excerpt(text, (index, index + len(fused))),
                        detail=f"concatenated-name artifact '{fused}' "
                               f"({first} + {second})",
                    ))
    return findings


def scan_brand_contamination(
    texts: list[tuple[str, str]],
    *,
    persona_name: str,
) -> list[QualityFinding]:
    """A known brand mentioned by a campaign that does not impersonate it."""
    allowed = {brand for brand in KNOWN_BRANDS
               if brand in persona_name.casefold()}
    findings: list[QualityFinding] = []
    for field, text in texts:
        for brand in KNOWN_BRANDS:
            if brand in allowed:
                continue
            pattern = re.compile(r"(?<![\w])" + re.escape(brand) + r"(?![\w])",
                                 re.IGNORECASE)
            match = pattern.search(text)
            if match:
                findings.append(QualityFinding(
                    check="brand_contamination",
                    field=field,
                    excerpt=_excerpt(text, match.span()),
                    detail=f"brand '{brand}' mentioned by a campaign that does "
                           f"not impersonate it",
                ))
    return findings


def scan_script_contamination(
    texts: list[tuple[str, str]],
) -> list[QualityFinding]:
    """Non-Latin script characters in prose (flagged, never filtered away)."""
    findings: list[QualityFinding] = []
    for field, text in texts:
        offenders: list[str] = []
        for char in text:
            if not is_latin_typo(char) and char not in offenders:
                offenders.append(char)
                if len(offenders) == 8:
                    break
        if offenders:
            first = text.index(offenders[0])
            findings.append(QualityFinding(
                check="script_contamination",
                field=field,
                excerpt=_excerpt(text, (first, first + 1)),
                detail=f"non-Latin script characters: "
                       f"{' '.join(offenders)} ({len(offenders)}+ distinct)",
            ))
    return findings


def _excerpt(text: str, needle, width: int = 80) -> str:
    """A trimmed evidence snippet centered on the first ``needle`` match.

    ``needle`` is either a search string or a ``(start, end)`` span.
    """
    if isinstance(needle, tuple):
        index, end = needle[0], needle[1]
    else:
        index = text.casefold().find(needle.casefold())
        end = index + len(needle)
    left = max(0, index - width // 2)
    right = min(len(text), max(end, index) + width // 2)
    snippet = text[left:right].replace("\n", " ")
    prefix = "…" if left > 0 else ""
    suffix = "…" if right < len(text) else ""
    return f"{prefix}{snippet.strip()}{suffix}"
