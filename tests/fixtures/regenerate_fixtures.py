"""Regenerate tests/fixtures/ from the real datasets.

The committed fixtures are a pruned slice: every word the tests mention plus
the rhyme-pattern families those words belong to (400 members per family,
most frequent first). That keeps the suite deterministic and fast without
committing 3.6 MB of dictionary.

Usage:

    lyrics data fetch
    uv run python tests/fixtures/regenerate_fixtures.py

Re-run it when tests start asserting on words the fixtures do not have.
"""

from __future__ import annotations

import re
from collections import defaultdict
from pathlib import Path

from lyrics_lint.core import rhyme_pattern
from lyrics_lint.datasets import load_cmudict, verified_path

FIXTURES = Path(__file__).parent
FAMILY_CAP = 400
TEST_GLOB = "*.py"


def fixture_words() -> set[str]:
    """Every lowercase token that appears in the test sources."""
    words: set[str] = set()
    for path in (FIXTURES.parent).glob(TEST_GLOB):
        words |= set(re.findall(r"[a-z]+(?:'[a-z]+)?", path.read_text()))
    return words


def main() -> None:
    dict_path = verified_path("cmudict")
    freq_path = verified_path("frequencies")
    if dict_path is None or freq_path is None:
        raise SystemExit("datasets missing: run `lyrics data fetch` first")

    counts: dict[str, int] = {}
    for line in freq_path.read_text().splitlines():
        parts = line.split()
        if len(parts) == 2:
            counts[parts[0]] = int(parts[1])

    dictionary = load_cmudict(dict_path)
    wanted = {
        rhyme_pattern(pron)
        for word, prons in dictionary.items()
        if word in fixture_words()
        for pron in prons
    }

    families: dict[str, list[tuple[str, str]]] = defaultdict(list)
    for word, prons in dictionary.items():
        for pron in prons:
            if rhyme_pattern(pron) in wanted:
                families[rhyme_pattern(pron)].append((word, pron))

    keep: list[tuple[str, str]] = []
    for members in families.values():
        members.sort(key=lambda wp: -counts.get(wp[0], 0))
        keep.extend(members[:FAMILY_CAP])
    keep.sort()

    seen: dict[str, int] = defaultdict(int)
    lines = []
    for word, pron in keep:
        seen[word] += 1
        marker = "" if seen[word] == 1 else f"({seen[word]})"
        lines.append(f"{word.upper()}{marker}  {pron}")
    (FIXTURES / "cmudict.dict").write_text("\n".join(lines) + "\n")

    kept = sorted({word for word, _ in keep})
    (FIXTURES / "en_50k.txt").write_text(
        "\n".join(f"{word} {counts[word]}" for word in kept if word in counts) + "\n"
    )
    print(f"cmudict.dict: {len(lines)} lines; en_50k.txt: {len(kept)} words")


if __name__ == "__main__":
    main()
