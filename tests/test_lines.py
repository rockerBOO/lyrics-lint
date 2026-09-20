from lyrics_lint.lines import end_word, end_word_span, is_lyric_line, parse_stanzas


def test_end_word_strips_punctuation():
    assert end_word("and I'm feeling the light.") == "light"


def test_end_word_empty_line():
    assert end_word("   ") == ""


def test_end_word_span_locates_word_and_column():
    line = "paying the cost"
    word, start, end = end_word_span(line)
    assert word == "cost"
    assert line[start - 1 : end - 1] == "cost"


def test_end_word_span_handles_trailing_punctuation():
    line = "and I'm feeling the light."
    word, start, end = end_word_span(line)
    assert word == "light"
    assert line[start - 1 : end - 1] == "light"


def test_end_word_span_empty_line_returns_none():
    assert end_word_span("   ") is None


def test_is_lyric_line_rejects_structural_lines():
    assert not is_lyric_line("")
    assert not is_lyric_line("# Song title")
    assert not is_lyric_line("---")
    assert not is_lyric_line("[Verse 1]")
    assert not is_lyric_line("1. some note")
    assert not is_lyric_line("- a bullet")


def test_is_lyric_line_accepts_lyric_text():
    assert is_lyric_line("i'm in charge")


def test_parse_stanzas_splits_on_blank_and_structural_lines():
    text = """# Song

[Verse 1]
i'm in charge
paying the cost
don't follow me
i'm getting lost

[Chorus]
put me on the spot
all we get is slop
"""
    stanzas = parse_stanzas(text)
    assert len(stanzas) == 2
    assert [line for _, line in stanzas[0]] == [
        "i'm in charge",
        "paying the cost",
        "don't follow me",
        "i'm getting lost",
    ]
    assert [line for _, line in stanzas[1]] == [
        "put me on the spot",
        "all we get is slop",
    ]
    # line numbers are 1-indexed and preserved
    assert stanzas[0][0][0] == 4
