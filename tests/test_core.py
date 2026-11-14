"""Tests for the rhyme engine: frequency ranking and pronunciation overrides."""

import pathlib

import pytest

from lyrics_lint.core import (
    FUNCTION_WORDS,
    RhymeEngine,
    final_stress,
    pattern_cost,
    phoneme_cost,
    pre_rhyme_vowel,
)

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


def test_rhymes_frequencies_are_descending(engine, frequency):
    freqs = [frequency(w) for w in engine.rhymes("you", limit=30)]
    assert freqs == sorted(freqs, reverse=True)


# ----------------------------------------------------- frequency ranking: slant


def test_slant_rhymes_rank_common_words_first(engine, frequency):
    words = [s["word"] for s in engine.slant_rhymes("you", max_distance=1, limit=10)]
    # Previously: "'cuse", "'kay", "a", "aaliyah", "abaco", ...
    assert "aaliyah" not in words
    assert "abaco" not in words
    assert all(frequency(w) >= 3.0 for w in words)


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


def test_override_adds_word_missing_from_cmudict(tmp_path, engine_factory):
    path = tmp_path / "overrides.txt"
    path.write_text("rizz  R IH1 Z\n")
    eng = engine_factory(overrides=path)
    assert eng.lookup("rizz")["found"] is True
    assert eng.patterns("rizz") == ["IH1 Z"]
    # newly added word participates in rhyme lookup
    assert "frizz" in eng.rhymes("rizz")


def test_override_is_visible_from_the_rhyme_index(tmp_path, engine_factory):
    path = tmp_path / "overrides.txt"
    path.write_text("zhoysh  ZH OY1 ZH\n")
    eng = engine_factory(overrides=path)
    # pattern_words and unique_patterns must both be updated, otherwise the
    # word is findable by lookup() but invisible to rhyme/slant search.
    assert eng.patterns("zhoysh") == ["OY1 ZH"]
    assert "OY1 ZH" in eng.unique_patterns
    assert any(
        s["word"] == "zhoysh"
        for s in eng.slant_rhymes("boy", max_distance=1, limit=None)
    )


def test_override_appends_instead_of_replacing_pronunciations(tmp_path, engine_factory):
    path = tmp_path / "overrides.txt"
    path.write_text("wind  W IH1 N D\n")
    eng = engine_factory(overrides=path)
    # cmudict already has wind = W AY1 N D and W IH1 N D; the override must
    # add to the list, not clobber it.
    assert len(eng.dict["wind"]) == 3


def test_override_ignores_comments_and_blank_lines(tmp_path, engine_factory):
    path = tmp_path / "overrides.txt"
    path.write_text("# brand words\n\nrizz  R IH1 Z   # a z-sound\n\n")
    eng = engine_factory(overrides=path)
    assert eng.lookup("rizz")["found"] is True


# ----------------------------------------------------------------------------
# overrides: remove


def test_override_removes_word_with_minus_prefix(tmp_path, engine_factory):
    path = tmp_path / "overrides.txt"
    path.write_text("-blue\n")
    eng = engine_factory(overrides=path)
    assert eng.lookup("blue")["found"] is False
    assert "blue" not in eng.rhymes("you")


# ------------------------------------------------------------------- overrides


def test_override_rejects_pronunciation_without_stress_marker(tmp_path, engine_factory):
    path = tmp_path / "overrides.txt"
    path.write_text("zhuzz  ZH UH Z\n")
    with pytest.raises(ValueError, match="zhuzz"):
        RhymeEngine(overrides=path)


def test_missing_override_file_is_not_an_error(tmp_path, engine_factory):
    eng = engine_factory(overrides=tmp_path / "nope.txt")
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


def test_slant_rhymes_report_cost_and_sort_by_it(engine, frequency):
    rows = engine.slant_rhymes("you", max_distance=2, limit=40)
    assert all("cost" in row for row in rows)
    assert rows == sorted(
        rows,
        key=lambda r: (
            r["distance"],
            r["cost"],
            -frequency(r["word"]),
            r["word"],
        ),
    )


def test_near_vowel_swap_costs_less_than_added_coda():
    # AO is one feature from UW (height), so swapping it is a milder slant than
    # closing the syllable with an extra consonant, which changes the shape.
    assert pattern_cost("UW1", "AO1") < pattern_cost("UW1", "UW1 L")


# --------------------------------------------- rich (multi-syllable) rhyme ranking


def test_pre_rhyme_vowel_of_multisyllable_word():
    assert pre_rhyme_vowel("SH AE0 M P UW1") == "AE"
    assert pre_rhyme_vowel("B AE0 M B UW1") == "AE"


def test_pre_rhyme_vowel_of_monosyllable_word_is_empty():
    assert pre_rhyme_vowel("Y UW1") == ""
    assert pre_rhyme_vowel("T UW1") == ""


def test_multisyllable_query_ranks_richer_rhymes_first(engine):
    # shampoo/bamboo/tattoo share a vowel in the syllable before the rhyme, so
    # they are smoother rhymes than the monosyllables (to/do/who) that used to
    # fill this list.
    words = engine.rhymes("shampoo", limit=5)
    assert words
    for word in words:
        prons = engine.lookup(word)["pronunciations"]
        assert all(pre_rhyme_vowel(p) == "AE" for p in prons)


def test_monosyllable_query_keeps_frequency_order(engine):
    # No pre-rhyme syllable exists, so nothing is reordered.
    assert engine.rhymes("you", limit=3) == ["to", "do", "who"]


# ------------------------------------------------- grapheme-to-phoneme fallback


@pytest.fixture
def fake_g2p():
    """Deterministic stand-in for the real G2P backend: only 'cruff' resolves."""
    calls = []

    def g2p(word):
        calls.append(word)
        return ["K", "R", "AH1", "F"] if word == "cruff" else None

    g2p.calls = calls
    return g2p


def test_g2p_resolves_word_missing_from_cmudict(fake_g2p, engine_factory):
    eng = engine_factory(g2p=fake_g2p)
    info = eng.lookup("cruff")
    assert info["found"] is True
    assert info["source"] == "g2p"
    assert info["patterns"] == ["AH1 F"]
    assert "stuff" in eng.rhymes("cruff")


def test_g2p_result_is_cached(fake_g2p, engine_factory):
    eng = engine_factory(g2p=fake_g2p)
    eng.lookup("cruff")
    eng.lookup("cruff")
    assert fake_g2p.calls == ["cruff"]


def test_g2p_disabled_leaves_word_unknown(engine_factory):
    eng = engine_factory(g2p=None)
    assert eng.lookup("cruff")["found"] is False
    assert eng.lookup("cruff")["source"] is None


def test_g2p_returning_none_leaves_word_unknown(engine_factory):
    eng = engine_factory(g2p=lambda _word: None)
    assert eng.lookup("cruff")["found"] is False


def test_dataset_word_reports_dataset_source(engine):
    assert engine.lookup("you")["source"] == "dataset"


def test_override_word_reports_override_source(tmp_path, engine_factory):
    path = tmp_path / "overrides.txt"
    path.write_text("rizz  R IH1 Z\n")
    eng = engine_factory(overrides=path)
    assert eng.lookup("rizz")["source"] == "override"


def test_g2p_word_participates_in_rhyme_lookup_once_resolved(fake_g2p, engine_factory):
    # Resolution is lazy: a g2p word joins the pattern index when it is first
    # looked up, so it can be a rhyme partner from then on.
    eng = engine_factory(g2p=fake_g2p)
    assert "stuff" in eng.rhymes("cruff")
    assert "cruff" in eng.rhymes("stuff")


# -------------------------------------------------- injected engine datasets


def test_engine_indexes_injected_dictionary():
    engine = RhymeEngine(
        dictionary={"foo": ["F UW1"], "goo": ["G UW1"]}, frequency=None
    )
    assert engine.lookup("foo")["found"] is True
    assert engine.rhymes("foo") == ["goo"]


def test_engine_without_dictionary_is_empty_but_usable():
    engine = RhymeEngine(overrides=None, dictionary={}, frequency=None)
    assert engine.lookup("you")["found"] is False
    assert engine.rhymes("you") == []
    assert engine.slant_rhymes("you") == []
    assert engine.suggestions("you")["perfect_rhymes"] == []


# --------------------------------------------------- packaging: no dataset deps


def test_engine_module_imports_no_dataset_at_module_level():
    """Importing lyrics_lint must not need cmudict/wordfreq/g2p_en.

    A guarded import inside a function body is fine; an import at module level
    would make the dataset a hard requirement again.
    """
    import ast

    tree = ast.parse(pathlib.Path("lyrics_lint/core.py").read_text())
    module_level = set()
    for node in tree.body:
        if isinstance(node, ast.Import):
            module_level.update(alias.name.split(".")[0] for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module:
            module_level.add(node.module.split(".")[0])

    assert module_level.isdisjoint({"cmudict", "wordfreq", "g2p_en"})


def test_declared_dependencies_are_code_only():
    import tomllib

    project = tomllib.loads(pathlib.Path("pyproject.toml").read_text())
    declared = " ".join(project["project"]["dependencies"]).lower()
    for dataset_package in ("cmudict", "wordfreq", "g2p-en"):
        assert dataset_package not in declared


def test_frequency_table_entry_without_a_pronunciation_does_not_crash(
    engine_factory,
):
    """A word can be in the frequency list and not in the dictionary: ranking
    must return 0.0 for it, never a KeyError, and never invent a result."""
    engine = engine_factory(dictionary={"you": ["Y UW1"]})

    assert engine.rhymes("you") == []
    assert engine.frequency("definitely-not-a-word") == 0.0
    assert all(s["word"] in engine.dict for s in engine.slant_rhymes("you", 2, 5))


# ------------------------------------------------------- suffix fallback fixes


def _suffix_engine():
    """A tiny dictionary where the target has no rhymes but shares a suffix.

    The real fixture is pruned to rhyme families, so no word in it exercises
    the fallback; this one is built to.
    """
    return RhymeEngine(
        overrides=None,
        dictionary={
            "purple": ["P ER1 P AH0 L"],
            "people": ["P IY1 P AH0 L"],
            "simple": ["S IH1 M P AH0 L"],
            "trample": ["T R AE1 M P AH0 L"],
        },
        frequency=lambda w: {"people": 5.0, "simple": 9.0, "trample": 1.0}.get(w, 0.0),
    )


def test_suffix_candidates_never_suggest_the_word_itself():
    # Before the fix this returned ['purple'] for 'purple'.
    assert "purple" not in _suffix_engine().suffix_candidates("purple", limit=10)


def test_suffix_candidates_are_ordered_by_frequency():
    # Alphabetical would be people, simple, trample.
    assert _suffix_engine().suffix_candidates("purple", limit=3) == [
        "simple",
        "people",
        "trample",
    ]
