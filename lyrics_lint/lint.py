"""Whole-file linting: flag end-words with no rhyme partner in their stanza."""

from __future__ import annotations

from .core import get_engine, levenshtein
from .lines import end_word_span, parse_stanzas

MAX_SLANT_DISTANCE = 2
SUGGESTION_LIMIT = 12


def _distance(engine, word_a: str, word_b: str) -> int:
    pa = engine.lookup(word_a)["patterns"]
    pb = engine.lookup(word_b)["patterns"]
    return min(levenshtein(x.split(), y.split()) for x in pa for y in pb)


def _clusters(engine, words: list[str]) -> list[list[int]]:
    """Group word indices into connected components under "rhymes within
    MAX_SLANT_DISTANCE" — i.e. each stanza's mutually-rhyming groups."""
    n = len(words)
    parent = list(range(n))

    def find(x: int) -> int:
        while parent[x] != x:
            parent[x] = parent[parent[x]]
            x = parent[x]
        return x

    def union(a: int, b: int) -> None:
        ra, rb = find(a), find(b)
        if ra != rb:
            parent[ra] = rb

    for i in range(n):
        for j in range(i + 1, n):
            if _distance(engine, words[i], words[j]) <= MAX_SLANT_DISTANCE:
                union(i, j)

    groups: dict[int, list[int]] = {}
    for i in range(n):
        groups.setdefault(find(i), []).append(i)
    return list(groups.values())


def lint_text(text: str) -> list[dict]:
    """Lint lyric text stanza by stanza.

    For each stanza (a contiguous run of lyric lines), every line's
    end-word is checked against every other end-word in the same stanza:

    - unknown-word: the word isn't in the pronunciation dictionary, so its
      rhyme can't be verified. Suggestions fall back to suffix candidates.
    - no-rhyme-partner: the word isn't within MAX_SLANT_DISTANCE of any
      other end-word in the stanza. Suggestions are replacement words that
      rhyme with the stanza's dominant (largest) rhyme group, since that's
      what the line needs to match.

    Stanzas with fewer than two resolvable end-words are skipped (nothing
    to compare against).
    """
    engine = get_engine()
    diagnostics: list[dict] = []

    for stanza in parse_stanzas(text):
        entries = []
        for lineno, line in stanza:
            span = end_word_span(line)
            if span is None:
                continue
            word, col, end_col = span
            entries.append((lineno, col, end_col, word, engine.lookup(word)))

        for lineno, col, end_col, word, info in entries:
            if not info["found"]:
                diagnostics.append({
                    "line": lineno,
                    "col": col,
                    "end_col": end_col,
                    "severity": "info",
                    "code": "unknown-word",
                    "message": f"'{word}' not in pronunciation dictionary — rhyme unverified",
                    "suggestions": [
                        {"word": w, "distance": None}
                        for w in engine.suffix_candidates(word, limit=SUGGESTION_LIMIT)
                    ],
                })

        found = [(i, e) for i, e in enumerate(entries) if e[4]["found"]]
        if len(found) < 2:
            continue

        found_words = [e[3] for _, e in found]
        clusters = _clusters(engine, found_words)
        # index (within `found`) -> cluster of indices (within `found`)
        cluster_of = {}
        for cluster in clusters:
            for idx in cluster:
                cluster_of[idx] = cluster

        for pos, (_, (lineno, col, end_col, word, info)) in enumerate(found):
            own_cluster = cluster_of[pos]
            if len(own_cluster) > 1:
                continue  # has at least one rhyme partner

            other_clusters = [c for c in clusters if c is not own_cluster]
            target_cluster = max(other_clusters, key=len)
            target_words = [found_words[idx] for idx in target_cluster]
            # Medoid: the cluster member closest (on average) to the rest of
            # the cluster, so a weak-slant outlier doesn't skew suggestions.
            target_word = min(
                target_words,
                key=lambda w: sum(_distance(engine, w, other) for other in target_words),
            )
            best = _distance(engine, word, target_word)

            target = engine.suggestions(target_word, limit=SUGGESTION_LIMIT)
            # Reserve room for slant rhymes so a long perfect-rhyme list
            # doesn't crowd them out entirely.
            perfect_share = max(SUGGESTION_LIMIT - 4, SUGGESTION_LIMIT // 2)
            suggestions = [
                {"word": w, "distance": 0}
                for w in target["perfect_rhymes"][:perfect_share]
            ] + [
                {"word": s["word"], "distance": int(s["distance"])}
                for s in target["slant_rhymes"]
            ]
            suggestions = suggestions[:SUGGESTION_LIMIT]
            diagnostics.append({
                "line": lineno,
                "col": col,
                "end_col": end_col,
                "severity": "warning",
                "code": "no-rhyme-partner",
                "message": (
                    f"'{word}' has no rhyme partner in this stanza "
                    f"(closest pattern distance {best})"
                ),
                "suggestions": suggestions,
            })

    diagnostics.sort(key=lambda d: (d["line"], d["col"]))
    return diagnostics
