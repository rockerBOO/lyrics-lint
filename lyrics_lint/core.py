"""Core rhyme engine.

Rhymes are quantified the same way as the original rhyme_dict project:
a word's "rhyme pattern" is the sequence of ARPAbet phonemes from the
final stressed vowel to the end of the word. Two words are perfect
rhymes if they share an identical rhyme pattern (including stress).
Slant rhymes are words whose patterns differ by a small Levenshtein
distance (1 = slant, 2 = weak slant).
"""

from __future__ import annotations

import os
import re
from collections import defaultdict
from collections.abc import Callable, Mapping, Sequence
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


def _zero_frequency(_word: str) -> float:
    """Ranking fallback when no frequency dataset is available."""
    return 0.0


def dataset_dictionary() -> dict[str, list[str]]:
    """Pronunciation data from the cache, or an empty mapping.

    Absence is normal: the engine then has nothing to rhyme with, which is a
    degraded but working state, not an error.
    """
    from .datasets import load_cmudict, verified_path

    path = verified_path("cmudict")
    return load_cmudict(path) if path is not None else {}


def dataset_frequency() -> Callable[[str], float]:
    """Frequency ranking from the cache, or a zero function."""
    from .datasets import load_frequencies, verified_path

    path = verified_path("frequencies")
    return load_frequencies(path) if path is not None else _zero_frequency


_G2P = None


def _valid_phoneme(token: str) -> bool:
    return _base(token) in VOWEL_FEATURES or _base(token) in CONSONANT_FEATURES


def default_g2p(word: str) -> list[str] | None:
    """Guess ARPAbet phonemes for a word cmudict does not know.

    Backed by `g2p_en` (a pure-Python neural grapheme-to-phoneme model), which
    downloads its NLTK data on first use, so it is only initialised when an
    unknown word is actually looked up. Returns None when the backend is not
    installed. `RhymeEngine(g2p=None)` skips this entirely.
    """
    global _G2P
    if _G2P is None:
        try:
            from g2p_en import G2p
        except ImportError:  # pragma: no cover - optional dependency
            _G2P = False
        else:
            _G2P = G2p()
    if _G2P is False:
        return None
    tokens = [t for t in _G2P(word) if _valid_phoneme(t)]
    if not tokens:
        return None
    return tokens


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
            cur.append(
                min(
                    prev[j] + 1,  # deletion
                    cur[j - 1] + 1,  # insertion
                    prev[j - 1] + (0 if ta == tb else 1),
                )
            )  # substitution
        prev = cur
    return prev[len(b)]


def final_stress(pattern: str) -> str:
    """Stress digit of a rhyme pattern's stressed vowel ('1' or '2')."""
    head = pattern.split(maxsplit=1)[0]
    return head[-1] if STRESS_TOKEN_RE.match(head) else ""


# ARPAbet features, used to weight substitutions. Binary Levenshtein treats
# "UW1 -> UH1" (rounding only) exactly like "UW1 -> AA1" (height and backness),
# which is wrong: the nearer vowel is the better slant.
#
#                            height  backness  round  diphthong  glide
VOWEL_FEATURES: dict[str, tuple[int, int, int, int, int]] = {
    "IY": (1, 1, 0, 0, 0),
    "IH": (1, 1, 0, 0, 0),
    "UH": (1, 3, 0, 0, 0),
    "UW": (1, 3, 1, 0, 0),
    "EH": (2, 1, 0, 0, 0),
    "AH": (2, 2, 0, 0, 0),
    "ER": (2, 2, 1, 0, 0),
    "AO": (2, 3, 1, 0, 0),
    "EY": (2, 1, 0, 1, 1),
    "OW": (2, 3, 1, 1, 2),
    "OY": (2, 3, 1, 1, 1),
    "AE": (3, 1, 0, 0, 0),
    "AA": (3, 3, 0, 0, 0),
    "AY": (3, 2, 0, 1, 1),
    "AW": (3, 2, 0, 1, 2),
}

#                            place  manner  voiced
CONSONANT_FEATURES: dict[str, tuple[int, int, int]] = {
    "P": (1, 1, 0),
    "B": (1, 1, 1),
    "M": (1, 4, 1),
    "F": (2, 3, 0),
    "V": (2, 3, 1),
    "TH": (3, 3, 0),
    "DH": (3, 3, 1),
    "T": (4, 1, 0),
    "D": (4, 1, 1),
    "S": (4, 3, 0),
    "Z": (4, 3, 1),
    "N": (4, 4, 1),
    "L": (4, 5, 1),
    "R": (4, 5, 1),
    "SH": (5, 3, 0),
    "ZH": (5, 3, 1),
    "CH": (5, 2, 0),
    "JH": (5, 2, 1),
    "Y": (6, 6, 1),
    "K": (7, 1, 0),
    "G": (7, 1, 1),
    "NG": (7, 4, 1),
    "HH": (8, 3, 0),
    "W": (9, 6, 1),
}

# Vowels carry the rhyme, so a vowel substitution costs more than a consonant
# one. Adding a coda phoneme (1.15) prices above a near-vowel swap (~1.12) and
# below a distant one, so "you"/"duh" outranks "you"/"school".
VOWEL_WEIGHT = 0.6
CONSONANT_WEIGHT = 0.3
INDEL_COST = 1.15
UNRELATED_COST = 1.5


def _base(phoneme: str) -> str:
    """Phoneme without its stress digit."""
    return phoneme.rstrip("012")


def phoneme_cost(a: str, b: str) -> float:
    """Substitution cost between two ARPAbet phonemes (0.0 = identical)."""
    if a == b:
        return 0.0
    base_a, base_b = _base(a), _base(b)
    features_a = VOWEL_FEATURES.get(base_a)
    features_b = VOWEL_FEATURES.get(base_b)
    if features_a is not None and features_b is not None:
        differing = sum(x != y for x, y in zip(features_a, features_b, strict=True))
        return round(1.0 + VOWEL_WEIGHT * differing / len(features_a), 4)
    features_a = CONSONANT_FEATURES.get(base_a)
    features_b = CONSONANT_FEATURES.get(base_b)
    if features_a is not None and features_b is not None:
        differing = sum(x != y for x, y in zip(features_a, features_b, strict=True))
        return round(1.0 + CONSONANT_WEIGHT * differing / len(features_a), 4)
    return UNRELATED_COST


def pattern_cost(pattern_a: str, pattern_b: str) -> float:
    """Feature-weighted edit cost between two rhyme patterns.

    Same DP as `levenshtein`, but substitutions are priced by phonetic
    distance, so a nearer vowel ranks above a distant one at equal distance.
    """
    a = pattern_a.split()
    b = pattern_b.split()
    previous = [i * INDEL_COST for i in range(len(b) + 1)]
    for i, token_a in enumerate(a, 1):
        current = [i * INDEL_COST]
        for j, token_b in enumerate(b, 1):
            current.append(
                min(
                    previous[j] + INDEL_COST,
                    current[j - 1] + INDEL_COST,
                    previous[j - 1] + phoneme_cost(token_a, token_b),
                )
            )
        previous = current
    return round(previous[len(b)], 4)


def is_word_token(word: str) -> bool:
    """Whether `word` is a plain word rather than a dictionary abbreviation."""
    return WORD_TOKEN_RE.fullmatch(word) is not None


def pre_rhyme_vowel(pronunciation: str) -> str:
    """Stress-free vowel of the syllable just before the rhyme ("" if none).

    shampoo/bamboo/tattoo all rhyme on `UW1` and all share an AE in the
    preceding syllable, which makes them smoother rhymes for each other than
    the bare monosyllables (to, do, who) in the same family.
    """
    tokens = pronunciation.split()
    stressed = [i for i, t in enumerate(tokens) if STRESS_TOKEN_RE.match(t)]
    if not stressed:
        return ""
    for i in range(stressed[-1] - 1, -1, -1):
        base = _base(tokens[i])
        if base in VOWEL_FEATURES:
            return base
    return ""


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

    def __init__(
        self,
        overrides: str | Path | None = DEFAULT_OVERRIDES,
        g2p: Callable[[str], list[str] | None] | None = None,
        dictionary: Mapping[str, Sequence[str]] | None = None,
        frequency: Callable[[str], float] | None = None,
    ) -> None:
        self.dict: dict[str, list[str]] = {}
        self.pattern_words: dict[str, set[str]] = defaultdict(set)
        # Where each pronunciation came from: dataset / override / g2p.
        self.sources: dict[str, str] = {}
        self.unique_patterns: list[str] = []
        self.g2p = g2p
        self.frequency = dataset_frequency() if frequency is None else frequency

        if dictionary is None:
            dictionary = dataset_dictionary()
        for word, pronunciations in dictionary.items():
            w = word.lower()
            self.dict[w] = list(pronunciations)
            self.sources[w] = "dataset"
            for pron in self.dict[w]:
                self.pattern_words[rhyme_pattern(pron)].add(w)

        self._load_overrides(overrides)
        self.unique_patterns = list(self.pattern_words.keys())

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
            self.sources[word] = "override"
            pattern = rhyme_pattern(phonemes)
            self.pattern_words[pattern].add(word)
            if pattern not in self.unique_patterns:
                self.unique_patterns.append(pattern)

    def _remove(self, word: str) -> None:
        self.sources.pop(word, None)
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

    def _resolve(self, word: str) -> list[str]:
        """Pronunciations for `word`, asking the G2P backend if needed."""
        pronunciations = self.dict.get(word)
        if pronunciations is not None or self.g2p is None:
            return pronunciations or []
        tokens = self.g2p(word)
        if not tokens:
            return []
        pronunciation = " ".join(tokens)
        self.dict[word] = [pronunciation]
        self.sources[word] = "g2p"
        pattern = rhyme_pattern(pronunciation)
        self.pattern_words[pattern].add(word)
        if pattern not in self.unique_patterns:
            self.unique_patterns.append(pattern)
        return [pronunciation]

    def lookup(self, word: str) -> dict:
        """Full info for a word: pronunciations, rhyme patterns, provenance."""
        w = word.lower()
        pronunciations = self._resolve(w)
        patterns = [rhyme_pattern(p) for p in pronunciations]
        return {
            "word": w,
            "found": bool(pronunciations),
            "source": self.sources.get(w) if pronunciations else None,
            "pronunciations": pronunciations,
            "patterns": patterns,
        }

    # --------------------------------------------------------------- rhymes

    def rhymes(self, word: str, limit: int | None = None) -> list[str]:
        """Perfect rhymes (identical rhyme pattern), richest and common first.

        Ranked by frequency so `limit` doesn't truncate to the first N words
        alphabetically ("abou, abreu, accrue, ..." instead of "do, too, true"),
        with multi-syllable words whose pre-rhyme syllable matches the query's
        lifted ahead of monosyllables in the same family.
        """
        info = self.lookup(word)
        if not info["found"]:
            return []
        out: set[str] = set()
        for pat in info["patterns"]:
            out.update(self.pattern_words.get(pat, set()))
        out.discard(word.lower())
        out = {w for w in out if is_word_token(w)}

        shapes = {pre_rhyme_vowel(p) for p in info["pronunciations"]} - {""}

        def rank(candidate: str) -> tuple[int, float, str]:
            rich = 0
            if shapes:
                prons = self.dict.get(candidate, [])
                if any(pre_rhyme_vowel(p) in shapes for p in prons):
                    rich = -1
            return (rich, -self.frequency(candidate), candidate)

        ranked = sorted(out, key=rank)
        return ranked[:limit] if limit else ranked

    def slant_rhymes(
        self, word: str, max_distance: int = 1, limit: int | None = None
    ) -> list[dict]:
        """Slant rhymes ranked by pattern distance, then phonetic cost.

        `distance` is the plain Levenshtein distance (what the verdict
        taxonomy is built on); `cost` is the feature-weighted price of those
        edits, so the nearest vowel ranks first within a distance.
        """
        info = self.lookup(word)
        if not info["found"]:
            return []
        stress = {final_stress(p) for p in info["patterns"]}
        out: dict[str, tuple[int, float]] = {}
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
                if dist > max_distance:
                    continue
                cost = pattern_cost(pat, other)
                for w in self.pattern_words.get(other, set()):
                    if w == word.lower() or w in FUNCTION_WORDS or not is_word_token(w):
                        continue
                    previous = out.get(w)
                    out[w] = (
                        (dist, cost)
                        if previous is None
                        else min(previous, (dist, cost))
                    )
        ranked = sorted(
            out.items(),
            key=lambda kv: (kv[1][0], kv[1][1], -self.frequency(kv[0]), kv[0]),
        )
        if limit:
            ranked = ranked[:limit]
        return [
            {"word": w, "distance": dist, "cost": cost} for w, (dist, cost) in ranked
        ]

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
            issues = []
            if not pa["found"]:
                issues.append(f"'{a}' not found in pronunciation dictionary")
            if not pb["found"]:
                issues.append(f"'{b}' not found in pronunciation dictionary")
            result.update(
                verdict="unknown",
                best_distance=None,
                distance=None,
                issues=issues,
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
                (
                    "Slant rhyme: rhyme patterns differ by 1 phoneme "
                    f"({pat_a!r} vs {pat_b!r}). "
                    "Acceptable, but a perfect rhyme would land harder."
                )
            ]
        elif dist == 2:
            verdict = "weak_slant"
            issues = [
                (
                    "Weak slant rhyme: patterns differ by 2 phonemes "
                    f"({pat_a!r} vs {pat_b!r}). "
                    "Barely a rhyme; consider replacing a word."
                )
            ]
        else:
            verdict = "no_rhyme"
            issues = [
                (
                    "No rhyme: patterns differ by "
                    f"{dist} phonemes ({pat_a!r} vs {pat_b!r})."
                )
            ]

        result.update(verdict=verdict, distance=dist, issues=issues)
        return result

    # ------------------------------------------------------ fallback (suffix)

    def suffix_candidates(
        self, word: str, min_suffix: int = 3, limit: int = 20
    ) -> list[str]:
        """When a word has no known rhymes, fall back to words sharing its
        final suffix (last 3+ characters) as assonance-style candidates.

        Ranked by frequency like every other suggestion path, and never
        includes the word itself.
        """
        w = word.lower()
        candidates: list[str] = []
        for suffix_len in range(min_suffix, min(len(w), 10) + 1):
            suffix = w[-suffix_len:]
            matches = {x for x in self.dict if x != w and x.endswith(suffix)}
            if matches:
                candidates = sorted(matches, key=lambda x: (-self.frequency(x), x))
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

G2P_ENV_VAR = "LYRICS_LINT_G2P"


def g2p_enabled() -> bool:
    """Whether guessed pronunciations are enabled via the environment.

    Off by default: the G2P backend imports a neural model (and, on first use,
    downloads NLTK data), so it is opt-in rather than a startup cost.
    """
    return os.environ.get(G2P_ENV_VAR, "").strip().lower() in {"1", "true", "yes"}


def get_engine() -> RhymeEngine:
    global _ENGINE
    if _ENGINE is None:
        _ENGINE = RhymeEngine(g2p=default_g2p if g2p_enabled() else None)
    return _ENGINE
