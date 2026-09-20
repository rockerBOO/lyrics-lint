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

# Lint a whole lyrics file: flag end-words with no rhyme partner in their
# stanza, or that aren't in the pronunciation dictionary
uv run lyrics lint song.md

# Reads from stdin if FILE is omitted (or passed as '-')
cat song.md | uv run lyrics lint --json
```

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

## Editor integration (nvim-lint)

`lyrics lint --json` is built for editor integration: it reads text on
stdin and emits a JSON array of diagnostics, each shaped as:

```json
{
  "line": 3,
  "col": 14,
  "end_col": 16,
  "severity": "warning",
  "code": "no-rhyme-partner",
  "message": "'me' has no rhyme partner in this stanza (closest pattern distance 3)",
  "suggestions": [
    { "word": "crossed", "distance": 0 },
    { "word": "abort", "distance": 1 }
  ]
}
```

`distance: 0` = perfect rhyme, `1`/`2` = slant/weak-slant, `null` = an
unverified suffix-based fallback (used when the flagged word itself isn't
in the pronunciation dictionary). `line`/`col`/`end_col` are 1-indexed,
`end_col` exclusive.

Example [nvim-lint](https://github.com/mfussenegger/nvim-lint) linter
definition (adjust `cmd` to your install path, or use `uvx --from
git+https://github.com/rockerBOO/lyrics-lint lyrics` instead of a local
venv binary):

```lua
require("lint").linters.lyrics = {
  cmd = "/path/to/lyrics-lint/.venv/bin/lyrics",
  args = { "lint", "-", "--json" },
  stdin = true,
  stream = "stdout",
  ignore_exitcode = true,
  parser = function(output)
    local ok, decoded = pcall(vim.json.decode, output)
    if not ok or type(decoded) ~= "table" then
      return {}
    end
    local severities = { info = vim.diagnostic.severity.INFO, warning = vim.diagnostic.severity.WARN }
    local diagnostics = {}
    for _, d in ipairs(decoded) do
      table.insert(diagnostics, {
        lnum = d.line - 1,
        col = d.col - 1,
        end_lnum = d.line - 1,
        end_col = d.end_col - 1,
        message = d.message,
        code = d.code,
        severity = severities[d.severity] or vim.diagnostic.severity.WARN,
        source = "lyrics-lint",
      })
    end
    return diagnostics
  end,
}
```

It isn't tied to any filetype by default — run it on demand, e.g.
`require("lint").try_lint("lyrics")` bound to a keymap, since it's
async (~1 s: cmudict loads fresh per invocation) and would be noisy if
run on every markdown save.

## Design notes

- The engine loads cmudict (~30k words) once per process and builds a
  pattern → words index in memory (~1 s).
- `slant_rhymes` compares the word's pattern against all unique patterns on
  demand (≈0.1 s), so no all-pairs DB is needed.

## References & credits

- Rhyme quantification scheme: [rhyme_dict](https://github.com/benrussell80/rhyme_dict) — lyrics-lint keeps the same scheme but replaces the Neo4j dependency with an in-memory pattern index.
- Pronunciation data: [Carnegie Mellon Pronouncing Dictionary](http://www.speech.cs.cmu.edu/cgi-bin/cmudict).
