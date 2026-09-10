"""CLI for lyrics-lint."""

from __future__ import annotations

import json
import sys

import click

from .core import get_engine
from .lines import end_word


@click.group()
@click.version_option()
def cli():
    """Lyrics rhyme linter: check pairs, find rhymes, and suggest replacements."""


@cli.command
@click.argument("line_a")
@click.argument("line_b")
@click.option("--word-a", help="Override end-word of line A")
@click.option("--word-b", help="Override end-word of line B")
@click.option("--json", "as_json", is_flag=True, help="Emit machine-readable JSON")
def check(line_a, line_b, word_a, word_b, as_json):
    """Check whether two lyric lines rhyme.

    End-words are extracted automatically; pass --word-a/--word-b to override.
    """
    engine = get_engine()
    a = word_a or end_word(line_a)
    b = word_b or end_word(line_b)
    result = engine.check_pair(a, b)
    # Attach recommendations so the linter can suggest fixes.
    result["recommendations"] = engine.suggestions(b) if result["found_b"] else {
        "word": b, "found": False,
        "perfect_rhymes": [], "slant_rhymes": [],
        "suffix_candidates": engine.suffix_candidates(b),
    }
    result["recommendations_for_a"] = engine.suggestions(a) if result["found_a"] else {
        "word": a, "found": False,
        "perfect_rhymes": [], "slant_rhymes": [],
        "suffix_candidates": engine.suffix_candidates(a),
    }

    if as_json:
        click.echo(json.dumps(result, indent=2))
        return

    verdict = result["verdict"]
    label = {
        "rhyme": "OK — perfect rhyme",
        "slant": "SLANT rhyme",
        "weak_slant": "WEAK slant rhyme",
        "no_rhyme": "NO rhyme",
        "unknown": "UNKNOWN (word(s) not found)",
    }[verdict]
    click.echo(f"{line_a!r} vs {line_b!r}")
    click.echo(f"  end-words: '{a}' / '{b}'")
    if result.get("distance") is not None:
        click.echo(f"  pattern distance: {result['distance']}")
    click.echo(f"  verdict: {label}")
    for issue in result.get("issues", []):
        click.echo(f"  issue: {issue}")

    rec = result["recommendations"]
    if rec["found"] and (rec["perfect_rhymes"] or rec["slant_rhymes"]):
        click.echo(f"  suggestions to replace '{b}':")
        if rec["perfect_rhymes"]:
            click.echo(f"    perfect rhymes: {', '.join(rec['perfect_rhymes'][:10])}")
        if rec["slant_rhymes"]:
            slant_txt = ", ".join(
                f"{s['word']} (d{int(s['distance'])})" for s in rec["slant_rhymes"][:10]
            )
            click.echo(f"    slant rhymes:   {slant_txt}")
    elif not rec["found"] and rec.get("suffix_candidates"):
        click.echo(f"  suffix-based candidates for '{b}':")
        click.echo(f"    {', '.join(rec['suffix_candidates'][:10])}")


@cli.command
@click.argument("word")
@click.option("--limit", default=20, help="Max results")
@click.option("--json", "as_json", is_flag=True)
def rhymes(word, limit, as_json):
    """List perfect rhymes for a word."""
    engine = get_engine()
    info = engine.lookup(word)
    if not info["found"]:
        candidates = engine.suffix_candidates(word)
        out = {"word": word, "found": False, "perfect_rhymes": [], "suffix_candidates": candidates}
    else:
        out = {
            "word": word, "found": True,
            "patterns": info["patterns"],
            "perfect_rhymes": engine.rhymes(word)[:limit],
        }
    if as_json:
        click.echo(json.dumps(out, indent=2))
        return
    if not out["found"]:
        click.echo(f"'{word}' not found in the pronunciation dictionary.")
        if out["suffix_candidates"]:
            click.echo("Suffix-based candidates:")
            for w in out["suffix_candidates"]:
                click.echo(f"  {w}")
        return
    click.echo(f"perfect rhymes of '{word}' (patterns: {', '.join(out['patterns'])}):")
    for w in out["perfect_rhymes"]:
        click.echo(f"  {w}")
    if not out["perfect_rhymes"]:
        click.echo("  (none found)")


@cli.command
@click.argument("word")
@click.option("--max-distance", default=1, type=click.IntRange(min=1, max=2),
              help="1 = slant, 2 = weak slant")
@click.option("--limit", default=20)
@click.option("--json", "as_json", is_flag=True)
def slant(word, max_distance, limit, as_json):
    """List slant rhymes for a word, ranked by pattern distance."""
    engine = get_engine()
    if not engine.lookup(word)["found"]:
        out = {"word": word, "found": False, "slant_rhymes": [],
               "suffix_candidates": engine.suffix_candidates(word)}
    else:
        out = {"word": word, "found": True,
               "slant_rhymes": engine.slant_rhymes(word, max_distance, limit)}
    if as_json:
        click.echo(json.dumps(out, indent=2))
        return
    if not out["found"]:
        click.echo(f"'{word}' not found in the pronunciation dictionary.")
        for w in out["suffix_candidates"]:
            click.echo(f"  {w}")
        return
    rows = out["slant_rhymes"]
    if not rows:
        click.echo(f"no slant rhymes (distance <= {max_distance}) for '{word}'")
        return
    for s in rows:
        click.echo(f"  {s['word']}  (distance {s['distance']})")


@cli.command
@click.argument("word")
@click.option("--limit", default=15)
@click.option("--json", "as_json", is_flag=True)
def suggestions(word, limit, as_json):
    """Recommended replacement words: perfect + slant rhymes, or suffix fallback."""
    engine = get_engine()
    out = engine.suggestions(word, limit)
    if as_json:
        click.echo(json.dumps(out, indent=2))
        return
    if not out["found"]:
        click.echo(f"'{word}' not found; suffix-based candidates:")
        for w in out["suffix_candidates"]:
            click.echo(f"  {w}")
        return
    click.echo(f"for '{word}' (patterns: {', '.join(out['patterns'])}):")
    click.echo("  perfect rhymes:")
    for w in out["perfect_rhymes"]:
        click.echo(f"    {w}")
    for s in out["slant_rhymes"]:
        click.echo(f"    {s['word']}  [slant d{int(s['distance'])}]")


@cli.command
def mcp():
    """Run the MCP server over stdio."""
    from .mcp import mcp

    mcp.run(transport="stdio")


def main():
    cli()


if __name__ == "__main__":
    main()
