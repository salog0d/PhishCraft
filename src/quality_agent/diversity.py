"""Inter-campaign diversity metrics (mode-collapse evidence).

The quality scan catches repetition *within* one campaign (``loop_detection``).
It is blind to the complementary failure: a generator that, across many runs of
the same pretext, keeps writing the *same* email. That homogenization is the
documented risk of low-temperature local models (Padmakumar & He 2024) and is
measured in the text-generation literature with:

- **distinct-n** (Li et al. 2016): unique n-grams / total n-grams over a
  corpus — higher is more diverse.
- **mean pairwise similarity**: the average ``difflib`` ratio over every pair
  of campaigns — higher means the set collapses toward one template.

Self-BLEU (Zhu et al. 2018) measures the same collapse more precisely but
needs an n-gram BLEU stack; distinct-n + pairwise ratio is the cheap, stdlib
sufficient pair.
"""

from __future__ import annotations

import re
from difflib import SequenceMatcher
from itertools import combinations

_WORD = re.compile(r"\w+")


def _tokens(text: str) -> list[str]:
    return _WORD.findall(text.casefold())


def distinct_n(texts: list[str], n: int = 2) -> float | None:
    """Unique n-grams / total n-grams across ``texts`` (None if too short)."""
    grams: list[tuple[str, ...]] = []
    for text in texts:
        toks = _tokens(text)
        grams += [tuple(toks[i:i + n]) for i in range(len(toks) - n + 1)]
    if not grams:
        return None
    return round(len(set(grams)) / len(grams), 4)


def mean_pairwise_similarity(texts: list[str]) -> float | None:
    """Mean ``SequenceMatcher`` ratio over all text pairs (None if < 2 texts).

    ponytail: O(n²) pairwise scan — fine for the per-pretext bucket sizes here
    (tens of campaigns). Sample the pairs if a bucket ever reaches thousands.
    """
    nonempty = [t for t in texts if t and t.strip()]
    if len(nonempty) < 2:
        return None
    ratios = [
        SequenceMatcher(None, a.casefold(), b.casefold()).ratio()
        for a, b in combinations(nonempty, 2)
    ]
    return round(sum(ratios) / len(ratios), 4)


def diversity_report(texts: list[str]) -> dict:
    """distinct-1/2 and mean pairwise similarity for one corpus of campaigns."""
    return {
        "n": len(texts),
        "distinct_1": distinct_n(texts, 1),
        "distinct_2": distinct_n(texts, 2),
        "mean_pairwise_similarity": mean_pairwise_similarity(texts),
    }
