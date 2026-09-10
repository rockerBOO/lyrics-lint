"""MCP server exposing the rhyme linter as tools.

Run with: uv run lyrics mcp   (stdio transport)
"""

from __future__ import annotations

from typing import Annotated

from fastmcp import FastMCP
from pydantic import Field

from .core import get_engine
from .lines import end_word

mcp = FastMCP("lyrics-lint")


@mcp.tool()
def check_pair(
    line_a: Annotated[str, Field(description="First lyric line")],
    line_b: Annotated[str, Field(description="Second lyric line")],
    word_a: Annotated[str, Field(description="Optional: override end-word of line A")] = None,
    word_b: Annotated[str, Field(description="Optional: override end-word of line B")] = None,
) -> dict:
    """Check whether two lyric lines rhyme.

    Extracts the end-word of each line, computes their rhyme patterns, and
    returns a verdict (rhyme / slant / weak_slant / no_rhyme / unknown) plus
    issues and recommended replacement words for both end-words.
    """
    engine = get_engine()
    a = word_a or end_word(line_a)
    b = word_b or end_word(line_b)
    result = engine.check_pair(a, b)
    result["recommendations"] = (
        engine.suggestions(b) if result["found_b"]
        else {"word": b, "found": False, "perfect_rhymes": [],
              "slant_rhymes": [], "suffix_candidates": engine.suffix_candidates(b)}
    )
    result["recommendations_for_a"] = (
        engine.suggestions(a) if result["found_a"]
        else {"word": a, "found": False, "perfect_rhymes": [],
              "slant_rhymes": [], "suffix_candidates": engine.suffix_candidates(a)}
    )
    return result


@mcp.tool()
def rhymes(
    word: Annotated[str, Field(description="Word to find perfect rhymes for")],
    limit: Annotated[int, Field(description="Max results", default=20)] = 20,
) -> dict:
    """List perfect rhymes (identical rhyme pattern) for a word.

    Falls back to suffix-based candidates if the word is not found.
    """
    engine = get_engine()
    info = engine.lookup(word)
    if not info["found"]:
        return {"word": word, "found": False, "perfect_rhymes": [],
                "suffix_candidates": engine.suffix_candidates(word)}
    return {"word": word, "found": True, "patterns": info["patterns"],
            "perfect_rhymes": engine.rhymes(word)[:limit]}


@mcp.tool()
def slant_rhymes(
    word: Annotated[str, Field(description="Word to find slant rhymes for")],
    max_distance: Annotated[int, Field(description="1 = slant, 2 = weak slant", default=1)] = 1,
    limit: Annotated[int, Field(description="Max results", default=20)] = 20,
) -> dict:
    """List slant rhymes for a word, ranked by pattern distance."""
    engine = get_engine()
    if not engine.lookup(word)["found"]:
        return {"word": word, "found": False, "slant_rhymes": [],
                "suffix_candidates": engine.suffix_candidates(word)}
    return {"word": word, "found": True,
            "slant_rhymes": engine.slant_rhymes(word, max_distance, limit)}


@mcp.tool()
def suggestions(
    word: Annotated[str, Field(description="End-word to get replacement suggestions for")],
    limit: Annotated[int, Field(description="Max results per category", default=15)] = 15,
) -> dict:
    """Get recommended replacement words for an end-word.

    Returns perfect rhymes, slant rhymes (with distances), and — when the word
    is unknown or has no rhymes — suffix-based candidates drawn from the last
    part of the word.
    """
    return get_engine().suggestions(word, limit)
