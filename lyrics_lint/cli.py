"""CLI for lyrics-lint."""

from __future__ import annotations

import json
import os

import click

from . import datasets
from .core import G2P_ENV_VAR, get_engine
from .lines import end_word
from .lint import lint_text


@click.group()
@click.version_option()
@click.option(
    "--g2p",
    "use_g2p",
    is_flag=True,
    help="Guess pronunciations for words missing from the dictionary (slower first run).",
)
def cli(use_g2p):
    """Lyrics rhyme linter: check pairs, find rhymes, and suggest replacements."""
    if use_g2p:
        os.environ[G2P_ENV_VAR] = "1"


def _warn_missing_data(engine) -> str | None:
    """Point at `lyrics data fetch` when this engine has nothing to rhyme with.

    Asks the engine rather than the filesystem: an engine built before a fetch
    is still empty, so the advice has to keep showing until it is rebuilt.
    """
    hint = engine.missing_hint()
    if hint is not None:
        click.echo(f"warning: {hint}", err=True)
    return hint


@cli.group("data")
def data():
    """Manage the optional speech datasets (nothing ships in the package)."""


@data.command("status")
@click.option("--json", "as_json", is_flag=True, help="Emit machine-readable JSON")
def data_status(as_json):
    """Show which datasets are present and whether they still verify."""
    entries = datasets.status()
    if as_json:
        click.echo(json.dumps(entries, indent=2))
        return
    for entry in entries:
        if entry["verified"]:
            state = "ok"
        elif entry["present"]:
            state = "unverified"
        else:
            state = "missing"
        click.echo(
            f"{entry['name']:<12} {state:<11} {entry['bytes']:>9} bytes  "
            f"{entry['licence']:<14} {entry['path']}"
        )


@data.command("fetch")
@click.argument("names", nargs=-1)
@click.option("--force", is_flag=True, help="Re-download even if the file verifies")
def data_fetch(names, force):
    """Download datasets into the cache and verify their sha256."""
    try:
        results = datasets.fetch(names or None, force=force)
    except (ValueError, RuntimeError) as exc:
        raise click.ClickException(str(exc)) from exc
    for entry in results:
        action = "fetched" if entry["fetched"] else "already present"
        click.echo(
            f"{entry['name']:<12} {action:<16} {entry['bytes']:>9} bytes  {entry['path']}"
        )


@data.command("path")
@click.argument("name", required=False)
def data_path(name):
    """Print the cache directory, or the path of one dataset."""
    if name is None:
        click.echo(datasets.data_dir())
        return
    try:
        click.echo(datasets.dataset_path(name))
    except KeyError as exc:
        raise click.ClickException(f"unknown dataset: {name}") from exc


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
    hint = _warn_missing_data(engine)
    a = word_a or end_word(line_a)
    b = word_b or end_word(line_b)
    result = engine.check_pair(a, b)
    # Attach recommendations so the linter can suggest fixes.
    result["recommendations"] = (
        engine.suggestions(b)
        if result["found_b"]
        else {
            "word": b,
            "found": False,
            "perfect_rhymes": [],
            "slant_rhymes": [],
            "suffix_candidates": engine.suffix_candidates(b),
        }
    )
    result["recommendations_for_a"] = (
        engine.suggestions(a)
        if result["found_a"]
        else {
            "word": a,
            "found": False,
            "perfect_rhymes": [],
            "slant_rhymes": [],
            "suffix_candidates": engine.suffix_candidates(a),
        }
    )

    if as_json:
        click.echo(json.dumps({**result, "hint": hint} if hint else result, indent=2))
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
    hint = _warn_missing_data(engine)
    info = engine.lookup(word)
    if not info["found"]:
        candidates = engine.suffix_candidates(word)
        out = {
            "word": word,
            "found": False,
            "perfect_rhymes": [],
            "suffix_candidates": candidates,
        }
    else:
        out = {
            "word": word,
            "found": True,
            "patterns": info["patterns"],
            "perfect_rhymes": engine.rhymes(word, limit=limit),
        }
    if as_json:
        click.echo(json.dumps({**out, "hint": hint} if hint else out, indent=2))
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
@click.option(
    "--max-distance",
    default=1,
    type=click.IntRange(min=1, max=2),
    help="1 = slant, 2 = weak slant",
)
@click.option("--limit", default=20)
@click.option("--json", "as_json", is_flag=True)
def slant(word, max_distance, limit, as_json):
    """List slant rhymes for a word, ranked by pattern distance."""
    engine = get_engine()
    hint = _warn_missing_data(engine)
    if not engine.lookup(word)["found"]:
        out = {
            "word": word,
            "found": False,
            "slant_rhymes": [],
            "suffix_candidates": engine.suffix_candidates(word),
        }
    else:
        out = {
            "word": word,
            "found": True,
            "slant_rhymes": engine.slant_rhymes(word, max_distance, limit),
        }
    if as_json:
        click.echo(json.dumps({**out, "hint": hint} if hint else out, indent=2))
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
    hint = _warn_missing_data(engine)
    out = engine.suggestions(word, limit)
    if as_json:
        click.echo(json.dumps({**out, "hint": hint} if hint else out, indent=2))
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
@click.argument("file", type=click.File("r"), default="-")
@click.option(
    "--json", "as_json", is_flag=True, help="Emit machine-readable JSON diagnostics"
)
def lint(file, as_json):
    """Lint a lyrics file: flag end-words with no rhyme partner in their stanza.

    Reads from FILE, or stdin if omitted (use '-' explicitly for stdin too).
    Splits the text into stanzas on blank lines and structural markdown
    (headings, '[Section]' tags, horizontal rules, lists), then checks each
    line's end-word against the others in its stanza.
    """
    _warn_missing_data(get_engine())
    diagnostics = lint_text(file.read())

    if as_json:
        click.echo(json.dumps(diagnostics, indent=2))
        return

    if not diagnostics:
        click.echo("no issues found")
        return

    for d in diagnostics:
        click.echo(
            f"{d['line']}:{d['col']}: {d['severity']}: {d['message']} [{d['code']}]"
        )
        if d.get("suggestions"):
            labels = []
            for s in d["suggestions"][:10]:
                if s["distance"] is None or s["distance"] == 0:
                    labels.append(s["word"])
                else:
                    labels.append(f"{s['word']} (slant d{s['distance']})")
            click.echo(f"    try: {', '.join(labels)}")


@cli.command
def mcp():
    """Run the MCP server over stdio."""
    from .mcp import mcp

    mcp.run(transport="stdio")


def main():
    cli()


if __name__ == "__main__":
    main()
