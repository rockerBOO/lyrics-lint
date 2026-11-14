"""Tests for the rhyme engine: frequency ranking and pronunciation overrides."""

import pytest
from wordfreq import zipf_frequency

from lyrics_lint.core import (
    FUNCTION_WORDS,
    RhymeEngine,
    final_stress,
    get_engine,
    pattern_cost,
    phoneme_cost,
)


@pytest.fixture(scope="module")
def engine():
    return get_engine()


# --------------------------------------------------- frequency ranking: perfect


def test_rhymes_ranks_common_words_first(engine):
    words = engine.rhymes("you", limit=20)
    # Alphabetical truncation used to return only "abou, abreu, accrue, ...".
    assert "abou" not in words
    assert {"do", "too", "true"} <= set(words)


def test_rhymes_limit_keeps_usable_words(engine):
    words = engine.rhymes("you", limit=20)
    assert {"blue", "through", "new"} <= set(words)


def test_rhymes_without_limit_returns_the_whole_family(engine):
    words = engine.rhymes("you")
    assert len(words) > 300
    assert "zoo" in words


def test_rhymes_frequencies_are_descending(engine):
    freqs = [zipf_frequency(w, "en") for w in engine.rhymes("you", limit=30)]
    assert freqs == sorted(freqs, reverse=True)


# ----------------------------------------------------- frequency ranking: slant


def test_slant_rhymes_rank_common_words_first(engine):
    words = [s["word"] for s in engine.slant_rhymes("you", max_distance=1, limit=10)]
    # Previously: "'cuse", "'kay", "a", "aaliyah", "abaco", ...
    assert "aaliyah" not in words
    assert "abaco" not in words
    assert all(zipf_frequency(w, "en") >= 3.0 for w in words)


def test_slant_rhymes_require_matching_final_stress(engine):
    # A one-phoneme pattern like "UW1" is 1 edit away from almost any bare
    # vowel, so unstressed readings of function words used to be reported as
    # slants. Their pattern ends in stress 0, not 1.
    for row in engine.slant_rhymes("you", max_distance=1, limit=50):
        assert any(final_stress(p) == "1" for p in engine.patterns(row["word"])), row


def test_slant_rhymes_skip_function_words(engine):
    # "the" is in cmudict as both DH AH0 and AH1, so the stress filter doesn't
    # catch it; without this it ranks first as a "slant" of everything.
    words = {s["word"] for s in engine.slant_rhymes("you", max_distance=2, limit=None)}
    assert "the" not in words
    assert not words & FUNCTION_WORDS


# --------------------------------------------------------------- overrides: add


def test_override_adds_word_missing_from_cmudict(tmp_path):
    path = tmp_path / "overrides.txt"
    path.write_text("rizz  R IH1 Z\n")
    eng = RhymeEngine(overrides=path)
    assert eng.lookup("rizz")["found"] is True
    assert eng.patterns("rizz") == ["IH1 Z"]
    # newly added word participates in rhyme lookup
    assert "frizz" in eng.rhymes("rizz")


def test_override_is_visible_from_the_rhyme_index(tmp_path):
    path = tmp_path / "overrides.txt"
    path.write_text("zhoysh  ZH OY1 ZH\n")
    eng = RhymeEngine(overrides=path)
    # pattern_words and unique_patterns must both be updated, otherwise the
    # word is findable by lookup() but invisible to rhyme/slant search.
    assert eng.patterns("zhoysh") == ["OY1 ZH"]
    assert "OY1 ZH" in eng.unique_patterns
    assert any(
        s["word"] == "zhoysh"
        for s in eng.slant_rhymes("boy", max_distance=1, limit=None)
    )


def test_override_appends_instead_of_replacing_pronunciations(tmp_path):
    path = tmp_path / "overrides.txt"
    path.write_text("wind  W IH1 N D\n")
    eng = RhymeEngine(overrides=path)
    # cmudict already has wind = W AY1 N D and W IH1 N D; the override must
    # add to the list, not clobber it.
    assert len(eng.dict["wind"]) == 3


def test_override_ignores_comments_and_blank_lines(tmp_path):
    path = tmp_path / "overrides.txt"
    path.write_text("# brand words\n\nrizz  R IH1 Z   # a z-sound\n\n")
    eng = RhymeEngine(overrides=path)
    assert eng.lookup("rizz")["found"] is True


# ----------------------------------------------------------------------------
# overrides: remove


def test_override_removes_word_with_minus_prefix(tmp_path):
    path = tmp_path / "overrides.txt"
    path.write_text("-blue\n")
    eng = RhymeEngine(overrides=path)
    assert eng.lookup("blue")["found"] is False
    assert "blue" not in eng.rhymes("you")


# ------------------------------------------------------------------- overrides


def test_override_rejects_pronunciation_without_stress_marker(tmp_path):
    path = tmp_path / "overrides.txt"
    path.write_text("zhuzz  ZH UH Z\n")
    with pytest.raises(ValueError, match="zhuzz"):
        RhymeEngine(overrides=path)


def test_missing_override_file_is_not_an_error(tmp_path):
    eng = RhymeEngine(overrides=tmp_path / "nope.txt")
    assert eng.lookup("you")["found"] is True


# -------------------------------------------------------- abbreviation filtering


def test_abbreviations_are_not_suggested(engine):
    # cmudict carries "a.", "i.", "u.", "a.d." — dictionary abbreviations, not
    # words you can sing. They ranked top of every list once frequency-sorted.
    perfect = engine.rhymes("you", limit=40)
    assert "u." not in perfect
    assert not any(w.endswith(".") for w in perfect)

    slants = [s["word"] for s in engine.slant_rhymes("you", max_distance=1, limit=20)]
    assert "a." not in slants
    assert not any("." in w for w in slants)


def test_possessive_apostrophe_artifacts_are_not_suggested(engine):
    # cmudict carries both "this" and "this'" — the bare possessive form is an
    # artifact, not a word you can put at the end of a line.
    words = [s["word"] for s in engine.slant_rhymes("fizz", max_distance=1, limit=50)]
    assert words
    assert not any(w.endswith("'") or w.startswith("'") for w in words)


# --------------------------------------------------- phoneme-aware slant cost


def test_identical_phonemes_have_zero_cost():
    assert phoneme_cost("UW1", "UW1") == 0.0


def test_rounding_difference_costs_less_than_backness_difference():
    # UW is high back rounded; UH is high back unrounded (1 feature apart),
    # IH is high front unrounded (2 features apart).
    assert phoneme_cost("UW1", "UH1") < phoneme_cost("UW1", "IH1")


def test_vowel_height_difference_costs_more_than_voicing():
    # Vowel substitutions dominate rhyme perception, so they cost more than a
    # consonant pair that only differs in voicing (Z vs S).
    assert phoneme_cost("IH1", "EH1") > phoneme_cost("Z", "S")


def test_voicing_only_consonant_pair_is_cheapest_consonant_pair():
    assert phoneme_cost("Z", "S") < phoneme_cost("Z", "M")


def test_pattern_cost_is_symmetric_and_zero_for_identical_patterns():
    assert pattern_cost("IH1 Z", "IH1 Z") == 0.0
    assert pattern_cost("IH1 Z", "EH1 S") == pattern_cost("EH1 S", "IH1 Z")


def test_slant_rhymes_prefer_the_nearer_vowel(engine):
    # Both "duh" (UH1) and "way" (EY1) are distance 1 from "you" (UW1), but UH
    # is one feature from UW while EY differs in height and backness.
    words = [s["word"] for s in engine.slant_rhymes("you", max_distance=1, limit=None)]
    assert words.index("duh") < words.index("way")


def test_slant_rhymes_report_cost_and_sort_by_it(engine):
    rows = engine.slant_rhymes("you", max_distance=2, limit=40)
    assert all("cost" in row for row in rows)
    assert rows == sorted(
        rows,
        key=lambda r: (
            r["distance"],
            r["cost"],
            -zipf_frequency(r["word"], "en"),
            r["word"],
        ),
    )


def test_near_vowel_swap_costs_less_than_added_coda():
    # AO is one feature from UW (height), so swapping it is a milder slant than
    # closing the syllable with an extra consonant, which changes the shape.
    assert pattern_cost("UW1", "AO1") < pattern_cost("UW1", "UW1 L")
