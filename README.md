# lyrics-lint

A rhyme and slant-rhyme linter for lyrics, with both a CLI and an MCP server.
Self-contained — no Neo4j required. Rhyme patterns are computed directly from
the Carnegie Mellon Pronouncing Dictionary (`cmudict`).

## How it works

- Every word's pronunciation is mapped to a **rhyme pattern**: the phoneme
  sequence from the final *stressed* vowel to the end (e.g. `light` → `AY1 T`).
- **Perfect rhyme**: identical rhyme patterns (distance 0).
- **Slant rhyme**: patterns differ by 1 phoneme (Levenshtein distance 1).
- **Weak slant**: distance 2. Beyond that: no rhyme.
- When a word isn't found (or has no rhymes), the linter falls back to the
  **last part of the word**: words sharing its final suffix are returned as
  assonance-style candidates.

## Setup

Requires [uv](https://uv.dev) (and Python ≥ 3.10).

**Option A — no clone, run straight from git** (recommended for one-off use and MCP clients):

```bash
uvx --from git+https://github.com/rockerBOO/lyrics-lint lyrics --help
```

`uvx` caches the environment, so only the first run takes a few seconds.

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
```

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
| `slant_rhymes`| Slant rhymes ranked by pattern distance                        |
| `suggestions` | Replacement words: perfect + slant + suffix candidates         |

Run it:

```bash
uv run lyrics mcp
# or clone-free:
uvx --from git+https://github.com/rockerBOO/lyrics-lint lyrics mcp
```

MCP client config (e.g. Claude Desktop / pi / any MCP client) — runs directly
from git, no local clone or path editing needed (requires `uv` and `git`):

```json
{
  "mcpServers": {
    "lyrics-lint": {
      "command": ["uvx", "--from", "git+https://github.com/rockerBOO/lyrics-lint", "lyrics", "mcp"]
    }
  }
}
```

## Design notes

- The engine loads cmudict (~30k words) once per process and builds a
  pattern → words index in memory (~1 s).
- `slant_rhymes` compares the word's pattern against all unique patterns on
  demand (≈0.1 s), so no all-pairs DB is needed.

## References & credits

- Rhyme quantification scheme: [rhyme_dict](https://github.com/benrussell80/rhyme_dict) — lyrics-lint keeps the same scheme but replaces the Neo4j dependency with an in-memory pattern index.
- Pronunciation data: [Carnegie Mellon Pronouncing Dictionary](http://www.speech.cs.cmu.edu/cgi-bin/cmudict).
