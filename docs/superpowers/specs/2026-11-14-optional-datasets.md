# Optional datasets — spec

**Date:** 2026-11-14
**Status:** approved (approach C: runtime fetch)

## Problem

`lyrics-lint` currently pulls three data-heavy or copyleft packages:

| dependency | installed size | licence | why it is a problem |
|---|---|---|---|
| `cmudict` (PyPI wrapper) | 3.7 MB | **GPL-3.0-or-later** | the wheel we publish inherits copyleft; the *data* inside is CMU's BSD-2 |
| `wordfreq` | 60.3 MB | Apache-2.0 (data from many corpora) | 58 MB of it is non-English data we never use |
| `g2p-en` | 3.4 MB + ~20 MB NLTK download at first use | Apache-2.0 | network access on a lookup, for a guess |

None of that is code. It is data, and none of it needs to ship in the wheel.

## What we build

A dataset layer that fetches data at runtime into a cache directory, and a
rhyme engine that works — with less functionality — when a dataset is absent.

**Two datasets, pinned in code (`lyrics_lint/datasets.py`):**

| name | filename | size | source | licence | sha256 |
|---|---|---|---|---|---|
| `cmudict` | `cmudict.dict` | 3.6 MB | `cmusphinx/cmudict` @ `74790861f652b15e4ac49015a90074ad62a27690` | BSD-2 (CMU 1993-2015) | `81917843c7f44ce2b094ac63873c2c7a4cf802040792c455ba3ca406891c3d22` |
| `frequencies` | `en_50k.txt` | 623 KB | `hermitdave/FrequencyWords` `content/2018/en/en_50k.txt` (OpenSubtitles 2018) | MIT | `5351ff405b1126ef555791dd4d9798a48e3e9a501a9fc481a9da957752cfb458` |

**Probe order:** `LYRICS_LINT_DATA` → `$XDG_CACHE_HOME/lyrics-lint` →
`~/.cache/lyrics-lint` → nothing. Presence is decided by the file existing;
`status` reports whether the bytes still match the pinned sha256.

**Commands:** `lyrics data status`, `lyrics data fetch [--force] [name ...]`,
`lyrics data path`. Fetch verifies the sha256 and writes atomically
(`.part` then rename); a mismatch is an error and leaves nothing behind.
No other code path touches the network.

## Degradation contract

Absence is normal, never an error:

| absent | behaviour |
|---|---|
| `cmudict` | `check` → verdict `unknown`; `rhymes`/`slant`/`suggestions` → empty results; every result carries a `hint` telling the user to run `lyrics data fetch`. `lint` still parses lines and reports `unknown-word` entries with suffix-based advice (pure string matching, no dictionary). |
| `frequencies` | ranking falls back to alphabetical (`frequency()` returns 0.0 for every word). |
| both | everything above; nothing raises. |
| `g2p_en` not installed | `--g2p` is a no-op; `RhymeEngine(g2p=...)` still accepts an injected callable. |

## Dependencies after this work

`click`, `fastmcp`. Nothing else. `g2p_en` becomes an optional, undeclared
import used only when it happens to be installed.

## Out of scope

- Bundling data in the wheel (rejected: that is approach A).
- A separate `lyrics-lint-data` distribution (rejected: approach B).
- Changing the project licence. With the GPL wrapper gone, no change is needed.
- Auto-fetching on first run. Fetching is always an explicit command.

## Tests

- The suite runs with **no cache, no network**: `tests/fixtures/` holds a
  pruned `cmudict.dict` (BSD) and `en_50k.txt` (MIT) covering every word the
  tests assert on. Fixtures are attributed in the README.
- Fetching is tested against `file://` URLs, including hash mismatch.
- One opt-in module exercises the real cache (`pytest -m dataset`).
