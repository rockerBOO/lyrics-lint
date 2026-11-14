# lyrics-lint

A rhyme and slant-rhyme linter for lyrics, with both a CLI and an MCP server.
Self-contained — no Neo4j required. Rhyme patterns are computed from the
Carnegie Mellon Pronouncing Dictionary, which is **not bundled**: the package
is code only (`click` + `fastmcp`), and the datasets are fetched when you ask
for them.

## Datasets

Two optional files are fetched into a cache directory and verified against a
sha256 pinned in `lyrics_lint/datasets.py`:

| name | file | size | source | licence |
|---|---|---|---|---|
| `cmudict` | `cmudict.dict` | 3.6 MB | [cmusphinx/cmudict](https://github.com/cmusphinx/cmudict) | BSD-2-Clause |
| `frequencies` | `en_50k.txt` | 623 KB | [hermitdave/FrequencyWords](https://github.com/hermitdave/FrequencyWords) (OpenSubtitles 2018) | MIT (code) / CC BY-SA 4.0 (word counts) |

```bash
lyrics data fetch        # download both, verify, write to the cache
lyrics data status       # what is present, whether it still verifies
lyrics data path         # where the cache lives
```

Lookup order: `$LYRICS_LINT_DATA`, then `$XDG_CACHE_HOME/lyrics-lint`, then
`~/.cache/lyrics-lint`. No other code path touches the network, except the
optional `g2p_en` backend, which may download NLTK data on its first guess.

**Without datasets everything still runs, with less functionality:**

| absent | behaviour |
|---|---|
| `cmudict` | `check` answers `unknown`; `rhymes`/`slant`/`suggestions` return empty results; the rhyming and linting commands print a one-line hint to run `lyrics data fetch`, and `--json` payloads plus MCP results carry it as `hint`; `lint` still parses lines but can only report one `unknown-word` per end-word with no suggestions — it cannot judge rhyme at all, because the suffix fallback reads the same dictionary |
| `frequencies` | ranking falls back to alphabetical |

Dataset values are only read, never modified: `status` reports a truncated or
tampered file as `unverified`, and lookups then behave as if it were absent.

## How it works

- Every word's pronunciation is mapped to a **rhyme pattern**: the phoneme
  sequence from the final *stressed* vowel to the end (e.g. `light` → `AY1 T`).
- **Perfect rhyme**: identical rhyme patterns (distance 0).
- **Slant rhyme**: patterns differ by 1 phoneme (Levenshtein distance 1).
- **Weak slant**: distance 2. Beyond that: no rhyme.
- When a word isn't found (or has no rhymes), the linter falls back to the
  **last part of the word**: words sharing its final suffix are returned as
  assonance-style candidates.
- Results are **ranked by word frequency** (log10 of the OpenSubtitles counts)
  rather than alphabetically, so `lyrics rhymes you` opens with `to, do, who,
  too, two, into...` instead of `abou, abreu, accrue`. Slant results sort by
  distance first, then frequency.
- When the query has more than one syllable, perfect rhymes that share its
  pre-rhyme vowel rank first: `rhymes shampoo` opens with `tattoo, bamboo,
  thankyou, taboo` rather than the monosyllables `to, do, who` that dominate the same
  pattern family. Monosyllabic queries are unaffected.
- Slant results carry a phonetic `cost` alongside the plain edit distance, and
  sort by distance first, then cost: substitutions are priced by how far apart
  the phonemes actually are (ARPAbet height/backness/rounding/glide for vowels,
  place/manner/voicing for consonants). `night` → `like, nice, side, died`
  instead of `out, high, try`, and a near vowel swap outranks bolting on an
  extra coda consonant.
- Slant lookup skips candidates whose final stress differs from the query's
  (`the` as `AH0` is not a slant of `you`), plus closed-class words and
  dictionary artifacts (`a.`, `i.`, `this'`) that would otherwise rank high
  once sorted by frequency. Perfect rhymes are never filtered.

## Adding words

CMUdict is from 2015 and has no `rizz`, `gyatt`, `delulu`, `doomscroll` or
`ghosting`. Overrides are small hand-written data, so they ship with the code.
Add pronunciations (or delete bad ones) in
[`lyrics_lint/data/pron_overrides.txt`](lyrics_lint/data/pron_overrides.txt),
which is merged over CMUdict at load time:

```
rizz        R IH1 Z            # add a pronunciation (appended, never replaced)
-gray       G R EY1           # a leading '-' removes a word from the dictionary
```

For words you don't want to hand-write, `--g2p` guesses a pronunciation from
the spelling. This uses `g2p_en` **if you happen to have it installed** — it is
not a dependency and not fetched, so the flag is a no-op otherwise:

```bash
uv run lyrics --g2p check "you looking kinda cruff" "i believe in you"
uv run lyrics --g2p lint songs/eleven.md
```

Guessed words are labelled rather than treated as known: `check` reports the
verdict it computed from the guess, and `lint` emits a `g2p-word` info
diagnostic (`'cruff' — guessed K R AH1 F from spelling`) so a spelling-derived
rhyme never passes silently. Set `LYRICS_LINT_G2P=1` to enable it for the MCP
server.

Each added pronunciation **must** carry a stress digit (`1` or `2`) on a vowel —
without one the rhyme pattern can't be derived and loading fails loudly rather
than silently mis-grouping the word. Homographs keep their existing readings, so
overrides add a pronunciation instead of clobbering the others.

## Setup

Requires [uv](https://uv.dev) (and Python ≥ 3.10).

**Option A — no clone, run straight from git** (recommended for one-off use and MCP clients):

```bash
uvx --from git+https://github.com/rockerBOO/lyrics-lint lyrics --help
```

`uvx` caches the environment, so only the first run takes a few seconds.

Either way, fetch the datasets once before rhyming (see
[Datasets](#datasets)):

```bash
uvx --from git+https://github.com/rockerBOO/lyrics-lint lyrics data fetch
```

**Option B — clone and run locally:**

```bash
git clone https://github.com/rockerBOO/lyrics-lint
cd lyrics-lint
uv sync
```

## CLI usage

With Option B, `uv run` replaces `uvx --from git+...` below:

```bash
# Check a pair of lines (end-words extracted automatically)
uv run lyrics check "the stars are burning bright" "and I'm feeling the light"

# Machine-readable output
uv run lyrics check "the moon is full and silver" "my soul is getting colder" --json

# List perfect rhymes
uv run lyrics rhymes port

# List slant rhymes (distance 1 by default, 2 for weak)
uv run lyrics slant port
uv run lyrics slant port --max-distance 2

# Recommended replacement words (perfect + slant, or suffix fallback)
uv run lyrics suggestions xylophone

# Lint a whole lyrics file: flag end-words with no rhyme partner in their
# stanza, or that aren't in the pronunciation dictionary
uv run lyrics lint songs/eleven.md

# Reads from stdin if FILE is omitted (or passed as '-')
cat songs/eleven.md | uv run lyrics lint --json
```

Run `lyrics data fetch` first, or expect the empty-result behaviour above.

`lint` splits the input into stanzas on blank lines and markdown structure
(`#` headings, `[Section]` tags, `---` rules, lists), then checks each
line's end-word against the others in its stanza. Each diagnostic includes
ranked replacement `suggestions` (perfect + slant rhymes, targeting the
stanza's dominant rhyme group) so you can pick a fix directly.

Every example also works clone-free:

```bash
uvx --from git+https://github.com/rockerBOO/lyrics-lint lyrics check "the stars are burning bright" "and I'm feeling the light"
```

`check` reports the verdict (`rhyme` / `slant` / `weak_slant` / `no_rhyme` /
`unknown`), the pattern distance, the specific issue, and recommendation lists
so you can replace an end-word to fix the rhyme.

## MCP server

Exposes four tools over stdio:

| Tool          | Purpose                                                        |
|---------------|----------------------------------------------------------------|
| `check_pair`  | Check two lines' end-words; verdict + issues + recommendations |
| `rhymes`      | Perfect rhymes for a word (suffix fallback if unknown)         |
| `slant_rhymes`| Slant rhymes ranked by pattern distance, then phonetic cost    |
| `suggestions` | Replacement words: perfect + slant + suffix candidates         |

Run it:

```bash
uv run lyrics mcp
# or clone-free:
uvx --from git+https://github.com/rockerBOO/lyrics-lint lyrics mcp
```

MCP client config (e.g. Claude Desktop / pi / any MCP client) — runs directly
from git, no local clone or path editing needed (requires `uv` and `git`).
Fetch the datasets first: until then every tool returns empty results plus a
`hint`, and the server picks the data up without a restart once it verifies.

```json
{
  "mcpServers": {
    "lyrics-lint": {
      "command": "uvx",
      "args": ["--from", "git+https://github.com/rockerBOO/lyrics-lint", "lyrics", "mcp"]
    }
  }
}
```

## Editor integration

Want to check your lyrics for rhyme issues right in your editor? See
[docs/neovim.md](docs/neovim.md) for Neovim setup.

## Design notes

- The engine builds its pattern index once per process from whatever
  dictionary it was given (~126k words, ~0.5 s).
- `slant_rhymes` compares the word's pattern against all unique patterns on
  demand (≈0.1 s), so no all-pairs DB is needed.
- Ranking by frequency costs ~0.1 s per 5k candidates, which is why `rhymes()`
  accepts a `limit` and callers pass it through instead of slicing afterwards.

## References & credits

- Rhyme quantification scheme: [rhyme_dict](https://github.com/benrussell80/rhyme_dict) — lyrics-lint keeps the same scheme but replaces the Neo4j dependency with an in-memory pattern index.
- Pronunciation data: [Carnegie Mellon Pronouncing Dictionary](https://github.com/cmusphinx/cmudict) (BSD-2-Clause).
- Ranking data: [FrequencyWords](https://github.com/hermitdave/FrequencyWords) © Hermit Dave — code MIT, word lists CC BY-SA 4.0; counts derived from OpenSubtitles 2018. The share-alike applies to the word-count file, including the pruned copy in `tests/fixtures/`, not to the program.
- `tests/fixtures/` holds a pruned slice of both, so the test suite runs offline; see `tests/fixtures/README.md`.
