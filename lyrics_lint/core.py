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
from pathlib import Path

STRESS_TOKEN_RE = re.compile(r"^[A-Z]{2}[12]$")

# cmudict carries abbreviations like "a.", "i.", "u.", "a.d." and bare
# possessives like "this'". They are not singable words, and once results are
# frequency-sorted they rank near the top.
WORD_TOKEN_RE = re.compile(r"[a-z]+(?:[-'][a-z]+)*")

# Closed-class words are never useful replacement end-words, and because their
# patterns are bare vowels ("the" -> AH1) they sit one edit from almost any
# open syllable. Frequency-sorted, they would otherwise top every slant list.
# Perfect rhymes are NOT filtered by this.
FUNCTION_WORDS = frozenset(
    """
    a an the and or but nor yet so for of to in on at by with from into onto
    upon about above below over under through between among against during
    before after since until as than that this these those there here when
    where why how what which who whom whose i me my mine we us our ours you
    your yours he him his she her hers it its they them their theirs oneself
    be am is are was were been being have has had having do does did doing
    will would shall should can could may might must not no yes if then else
    all any some each every both few more most other such own same very
    just only also even still ever never always oh ah uh um
    """.split()
)

# Optional pronunciation overrides, merged over CMUdict at load time.
DEFAULT_OVERRIDES = Path(__file__).resolve().parent / "data" / "pron_overrides.txt"

_FREQUENCY = None


def frequency(word: str) -> float:
    """Zipf frequency of `word` in English (0.0 = unknown/very rare).

    Used only for ranking results, so a missing `wordfreq` install degrades
    to insertion order rather than failing.
    """
    global _FREQUENCY
    if _FREQUENCY is None:
        try:
            from wordfreq import zipf_frequency
        except ImportError:  # pragma: no cover - wordfreq is a hard dependency
            _FREQUENCY = lambda _w: 0.0
        else:
            _FREQUENCY = lambda w: zipf_frequency(w, "en")
    return _FREQUENCY(word)


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


def final_stress(pattern: str) -> str:
    """Stress digit of a rhyme pattern's stressed vowel ('1' or '2')."""
    head = pattern.split(maxsplit=1)[0]
    return head[-1] if STRESS_TOKEN_RE.match(head) else ""


def is_word_token(word: str) -> bool:
    """Whether `word` is a plain word rather than a dictionary abbreviation."""
    return WORD_TOKEN_RE.fullmatch(word) is not None


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

    def __init__(self, overrides: str | Path | None = DEFAULT_OVERRIDES) -> None:
        import cmudict

        self.dict: dict[str, list[str]] = {}
        self.pattern_words: dict[str, set[str]] = defaultdict(set)

        for word, pron_list in cmudict.dict().items():
            w = word.lower()
            pronunciations = [" ".join(p) for p in pron_list]
            self.dict[w] = pronunciations
            for pron in pronunciations:
                self.pattern_words[rhyme_pattern(pron)].add(w)

        self._load_overrides(overrides)
        self.unique_patterns: list[str] = list(self.pattern_words.keys())

    def _load_overrides(self, path: str | Path | None) -> None:
        """Merge a CMUdict-format override file into the index.

        One entry per line: `<word> <PHONEMES>`. `#` starts a comment. A line
        starting with `-` drops that word (e.g. `-blue`). Pronunciations are
        appended, never replaced, so homographs keep their existing readings.
        """
        if path is None:
            return
        try:
            text = Path(path).read_text()
        except FileNotFoundError:
            return

        for raw in text.splitlines():
            line = raw.split("#", 1)[0].strip()
            if not line:
                continue
            parts = line.split()
            word = parts[0].lower()
            phonemes = " ".join(parts[1:])

            if word.startswith("-"):
                self._remove(word[1:])
                continue

            if not phonemes:
                raise ValueError(f"{word}: override entry has no pronunciation")
            if not any(STRESS_TOKEN_RE.match(t) for t in phonemes.split()):
                raise ValueError(
                    f"{word}: pronunciation {phonemes!r} has no stress-marked "
                    "vowel; expected e.g. 'R IH1 Z'"
                )

            self.dict.setdefault(word, []).append(phonemes)
            self.pattern_words[rhyme_pattern(phonemes)].add(word)

    def _remove(self, word: str) -> None:
        for pron in self.dict.pop(word, []):
            pattern = rhyme_pattern(pron)
            words = self.pattern_words.get(pattern)
            if words is not None:
                words.discard(word)
                if not words:
                    del self.pattern_words[pattern]

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

    def rhymes(self, word: str, limit: int | None = None) -> list[str]:
        """Perfect rhymes (identical rhyme pattern), most common first.

        Ranked by frequency so `limit` doesn't truncate to the first N words
        alphabetically ("abou, abreu, accrue, ..." instead of "do, too, true").
        """
        info = self.lookup(word)
        if not info["found"]:
            return []
        out: set[str] = set()
        for pat in info["patterns"]:
            out.update(self.pattern_words.get(pat, set()))
        out.discard(word.lower())
        out = {w for w in out if is_word_token(w)}
        ranked = sorted(out, key=lambda w: (-frequency(w), w))
        return ranked[:limit] if limit else ranked

    def slant_rhymes(
        self, word: str, max_distance: int = 1, limit: int | None = None
    ) -> list[dict]:
        """Slant rhymes ranked by pattern distance (1 = slant, 2 = weak)."""
        info = self.lookup(word)
        if not info["found"]:
            return []
        stress = {final_stress(p) for p in info["patterns"]}
        out: dict[str, int] = {}
        for pat in info["patterns"]:
            for other in self.unique_patterns:
                if other == pat:
                    continue
                # A short pattern is 1 edit from any bare vowel, so without
                # this every unstressed function word ("the", "a") counts as
                # a slant of a stressed syllable like "you".
                if final_stress(other) not in stress:
                    continue
                dist = levenshtein(pat.split(), other.split())
                if dist <= max_distance:
                    for w in self.pattern_words.get(other, set()):
                        if (
                            w == word.lower()
                            or w in FUNCTION_WORDS
                            or not is_word_token(w)
                        ):
                            continue
                        out[w] = min(out.get(w, 99), dist)
        ranked = sorted(
            out.items(), key=lambda kv: (kv[1], -frequency(kv[0]), kv[0])
        )
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
        perfect = self.rhymes(word, limit=limit)
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
