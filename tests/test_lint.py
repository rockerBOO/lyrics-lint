from lyrics_lint.lint import lint_text


def test_flags_end_word_with_no_rhyme_partner_in_stanza():
    text = """paying the cost
i love the color purple
don't follow me
i'm getting lost
"""
    diagnostics = lint_text(text)
    codes_by_line = {d["line"]: d["code"] for d in diagnostics}
    # "purple" (line 2) has no rhyme partner among cost/lost
    assert codes_by_line[2] == "no-rhyme-partner"
    # "cost" (line 1) and "lost" (line 4) are perfect rhymes -> no diagnostic
    assert 1 not in codes_by_line
    assert 4 not in codes_by_line


def test_flags_unknown_word():
    text = """you looking kinda cruff
i believe in you
"""
    diagnostics = lint_text(text)
    unknown = [d for d in diagnostics if d["code"] == "unknown-word"]
    assert len(unknown) == 1
    assert unknown[0]["line"] == 1
    assert "cruff" in unknown[0]["message"]


def test_all_lines_rhyming_produces_no_diagnostics():
    text = """put me on the spot
all we get is slop
you think i'll stop
better call a cop
"""
    diagnostics = lint_text(text)
    assert diagnostics == []


def test_single_line_stanza_produces_no_diagnostics():
    text = "[Verse 1]\njust one line\n"
    diagnostics = lint_text(text)
    assert diagnostics == []


def test_diagnostic_column_points_at_end_word():
    text = "paying the cost\ni love the color purple\ndon't follow me\ni'm getting lost\n"
    diagnostics = lint_text(text)
    d = next(d for d in diagnostics if d["line"] == 2)
    line = "i love the color purple"
    assert line[d["col"] - 1 : d["end_col"] - 1] == "purple"


def test_no_rhyme_partner_includes_suggestions_that_rhyme_with_the_stanza():
    text = "i'm in charge\npaying the cost\ndon't follow me\ni'm getting lost\n"
    diagnostics = lint_text(text)
    d = next(d for d in diagnostics if d["line"] == 3)
    assert d["code"] == "no-rhyme-partner"
    words = [s["word"] for s in d["suggestions"]]
    # suggestions should rhyme with the stanza's dominant pattern (cost/lost),
    # not be rhymes of "me" itself
    assert "frost" in words or "crossed" in words
    # perfect rhymes (distance 0) come before slant rhymes
    distances = [s["distance"] for s in d["suggestions"]]
    assert distances == sorted(distances)


def test_no_rhyme_partner_suggestions_include_slant_rhymes_too():
    text = "i'm in charge\npaying the cost\ndon't follow me\ni'm getting lost\n"
    diagnostics = lint_text(text)
    d = next(d for d in diagnostics if d["line"] == 3)
    assert any(s["distance"] and s["distance"] > 0 for s in d["suggestions"])


def test_unknown_word_includes_suffix_candidates_as_suggestions():
    text = "you looking kinda cruff\ni believe in you\n"
    diagnostics = lint_text(text)
    d = next(d for d in diagnostics if d["code"] == "unknown-word")
    assert d["suggestions"]
    assert all(s["distance"] is None for s in d["suggestions"])
