"""Line handling: extract end-words and split lyric text into stanzas."""

from __future__ import annotations

import re

PUNCT = ".,;:!?\"'()-[]{}"

SECTION_TAG_RE = re.compile(r"^\[.*\]$")
HR_RE = re.compile(r"^-{3,}$")
LIST_RE = re.compile(r"^\s*(\d+\.|[-*])\s")


def end_word(line: str) -> str:
    """Return the final word of a lyric line (punctuation stripped)."""
    line = line.strip()
    line = line.strip(PUNCT)
    words = line.split()
    if not words:
        return ""
    return words[-1].strip(PUNCT)


def end_word_span(line: str) -> tuple[str, int, int] | None:
    """Locate the end-word within `line`.

    Returns (word, start_col, end_col), 1-indexed with end_col exclusive
    (i.e. line[start_col - 1 : end_col - 1] == word). Returns None if the
    line has no words.
    """
    end = len(line)
    while end > 0 and line[end - 1].isspace():
        end -= 1
    trimmed_end = end
    while trimmed_end > 0 and line[trimmed_end - 1] in PUNCT:
        trimmed_end -= 1
    if trimmed_end == 0:
        return None
    start = trimmed_end
    while start > 0 and not line[start - 1].isspace():
        start -= 1
    while start < trimmed_end and line[start] in PUNCT:
        start += 1
    if start >= trimmed_end:
        return None
    return line[start:trimmed_end], start + 1, trimmed_end + 1


def is_lyric_line(line: str) -> bool:
    """Whether a line should be treated as sung/spoken lyric text rather
    than structural markdown (headings, section tags, rules, lists)."""
    s = line.strip()
    if not s:
        return False
    if s.startswith("#"):
        return False
    if HR_RE.match(s):
        return False
    if SECTION_TAG_RE.match(s):
        return False
    if LIST_RE.match(line):
        return False
    return True


def parse_stanzas(text: str) -> list[list[tuple[int, str]]]:
    """Split lyric text into stanzas: contiguous runs of lyric lines,
    separated by blank lines or structural lines (headings, section tags,
    horizontal rules, lists). Returns 1-indexed (lineno, line) pairs."""
    stanzas: list[list[tuple[int, str]]] = []
    current: list[tuple[int, str]] = []
    for lineno, line in enumerate(text.splitlines(), start=1):
        if is_lyric_line(line):
            current.append((lineno, line))
        elif current:
            stanzas.append(current)
            current = []
    if current:
        stanzas.append(current)
    return stanzas
