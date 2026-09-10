"""Line handling: extract the end-word from a lyric line."""

from __future__ import annotations

PUNCT = ".,;:!?\"'()-[]{}"


def end_word(line: str) -> str:
    """Return the final word of a lyric line (punctuation stripped)."""
    line = line.strip()
    line = line.strip(PUNCT)
    words = line.split()
    if not words:
        return ""
    return words[-1].strip(PUNCT)
