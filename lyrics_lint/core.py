"""Core rhyme engine.

Rhymes are quantified the same way as the original rhyme_dict project:
a word's "rhyme pattern" is the sequence of ARPAbet phonemes from the
final stressed vowel to the end of the word. Two words are perfect
rhymes if they share an identical rhyme pattern (including stress).
Slant rhymes are words whose patterns differ by a small Levenshtein
distance (1 = slant, 2 = weak slant).
"""

from __future__ import annotations

import re
from collections import defaultdict

STRESS_TOKEN_RE = re.compile(r"^[A-Z]{2}[12]$")


def levenshtein(a: list[str], b: list[str]) -> int:
    """Standard DP Levenshtein distance over token sequences."""
    if a == b:
        return 0
    if not a:
        return len(b)
    if not b:
        return len(a)
    prev = list(range(len(b) + 1))
    for i, ta in enumerate(a, 1):
        cur = [i]
        for j, tb in enumerate(b, 1):
            cur.append(min(prev[j] + 1,        # deletion
                           cur[j - 1] + 1,     # insertion
                           prev[j - 1] + (0 if ta == tb else 1)))  # substitution
        prev = cur
    return prev[len(b)]


def rhyme_pattern(pronunciation: str) -> str:
    """Return the rhyme pattern (final stressed phoneme .. end) of an ARPAbet string."""
    tokens = pronunciation.split()
    for i in range(len(tokens) - 1, -1, -1):
        if STRESS_TOKEN_RE.match(tokens[i]):
            return " ".join(tokens[i:])
    # No stress marker found (shouldn't happen with cmudict): use whole word.
    return " ".join(tokens)


class RhymeEngine:
    """In-memory rhyme index built from the CMU Pronouncing Dictionary."""

    def __init__(self) -> None:
        import cmudict

        self.dict: dict[str, list[str]] = {}
        self.pattern_words: dict[str, set[str]] = defaultdict(set)

        for word, pron_list in cmudict.dict().items():
            w = word.lower()
            pronunciations = [" ".join(p) for p in pron_list]
            self.dict[w] = pronunciations
            for pron in pronunciations:
                self.pattern_words[rhyme_pattern(pron)].add(w)

        self.unique_patterns: list[str] = list(self.pattern_words.keys())

    # ------------------------------------------------------------------ words

    def patterns(self, word: str) -> list[str]:
        pronunciations = self.dict.get(word.lower(), [])
        return [rhyme_pattern(p) for p in pronunciations]

    def lookup(self, word: str) -> dict:
        """Full info for a word: pronunciations + rhyme patterns."""
        pronunciations = self.dict.get(word.lower(), [])
        patterns = [rhyme_pattern(p) for p in pronunciations]
        return {
            "word": word.lower(),
            "found": bool(pronunciations),
            "pronunciations": pronunciations,
            "patterns": patterns,
        }

    # --------------------------------------------------------------- rhymes

    def rhymes(self, word: str) -> list[str]:
        """Perfect rhymes (identical rhyme pattern) for a word."""
        info = self.lookup(word)
        if not info["found"]:
            return []
        out: set[str] = set()
        for pat in info["patterns"]:
            out.update(self.pattern_words.get(pat, set()))
        out.discard(word.lower())
        return sorted(out)

    def slant_rhymes(
        self, word: str, max_distance: int = 1, limit: int | None = None
    ) -> list[dict]:
        """Slant rhymes ranked by pattern distance (1 = slant, 2 = weak)."""
        info = self.lookup(word)
        if not info["found"]:
            return []
        out: dict[str, int] = {}
        for pat in info["patterns"]:
            for other in self.unique_patterns:
                if other == pat:
                    continue
                dist = levenshtein(pat.split(), other.split())
                if dist <= max_distance:
                    for w in self.pattern_words.get(other, set()):
                        if w == word.lower():
                            continue
                        out[w] = min(out.get(w, 99), dist)
        ranked = sorted(out.items(), key=lambda kv: (kv[1], kv[0]))
        if limit:
            ranked = ranked[:limit]
        return [{"word": w, "distance": d} for w, d in ranked]

    # -------------------------------------------------------- pair checking

    def check_pair(self, word_a: str, word_b: str) -> dict:
        """Check two words: best-case pattern distance + verdict."""
        a = word_a.lower()
        b = word_b.lower()
        pa = self.lookup(a)
        pb = self.lookup(b)

        result = {
            "word_a": a,
            "word_b": b,
            "found_a": pa["found"],
            "found_b": pb["found"],
            "patterns_a": pa["patterns"],
            "patterns_b": pb["patterns"],
        }

        if not (pa["found"] and pb["found"]):
            result.update(
                verdict="unknown",
                best_distance=None,
                distance=None,
                issues=(
                    [f"'{a}' not found in pronunciation dictionary"]
                    if not pa["found"]
                    else [],
                ) + (
                    [f"'{b}' not found in pronunciation dictionary"]
                    if not pb["found"]
                    else [],
                ),
            )
            return result

        best: tuple[int, str, str] | None = None
        for x in pa["patterns"]:
            for y in pb["patterns"]:
                dist = levenshtein(x.split(), y.split())
                if best is None or dist < best[0]:
                    best = (dist, x, y)

        dist, pat_a, pat_b = best
        if dist == 0:
            verdict = "rhyme"
            issues: list[str] = []
        elif dist == 1:
            verdict = "slant"
            issues = [
                "Slant rhyme: rhyme patterns differ by 1 phoneme "
                f"({pat_a!r} vs {pat_b!r}). Acceptable, but a perfect rhyme would land harder."
            ]
        elif dist == 2:
            verdict = "weak_slant"
            issues = [
                "Weak slant rhyme: patterns differ by 2 phonemes "
                f"({pat_a!r} vs {pat_b!r}). Barely a rhyme; consider replacing a word."
            ]
        else:
            verdict = "no_rhyme"
            issues = [
                "No rhyme: patterns differ by "
                f"{dist} phonemes ({pat_a!r} vs {pat_b!r})."
            ]

        result.update(verdict=verdict, distance=dist, issues=issues)
        return result

    # ------------------------------------------------------ fallback (suffix)

    def suffix_candidates(self, word: str, min_suffix: int = 3, limit: int = 20) -> list[str]:
        """When a word has no known rhymes, fall back to words sharing its
        final suffix (last 3+ characters) as assonance-style candidates."""
        w = word.lower()
        candidates = []
        for suffix_len in range(min_suffix, min(len(w), 10) + 1):
            suffix = w[-suffix_len:]
            matches = [
                x for x in self.dict if x.endswith(suffix)
            ]
            if matches:
                candidates = sorted(set(matches))
                break
        return candidates[:limit]

    # ------------------------------------------------------ suggestions

    def suggestions(self, word: str, limit: int = 15) -> dict:
        """Recommended replacement words for a given end-word."""
        info = self.lookup(word)
        if not info["found"]:
            return {
                "word": word.lower(),
                "found": False,
                "perfect_rhymes": [],
                "slant_rhymes": [],
                "suffix_candidates": self.suffix_candidates(word),
            }
        perfect = self.rhymes(word)[:limit]
        slant = self.slant_rhymes(word, max_distance=2, limit=limit)
        return {
            "word": word.lower(),
            "found": True,
            "patterns": info["patterns"],
            "perfect_rhymes": perfect,
            "slant_rhymes": slant,
            "suffix_candidates": [] if perfect else self.suffix_candidates(word),
        }


_ENGINE: RhymeEngine | None = None


def get_engine() -> RhymeEngine:
    global _ENGINE
    if _ENGINE is None:
        _ENGINE = RhymeEngine()
    return _ENGINE
