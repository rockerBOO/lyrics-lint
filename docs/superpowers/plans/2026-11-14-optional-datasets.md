# Optional datasets Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Move every dataset out of the wheel and out of the dependency list, fetched on demand into a cache directory, with the linter degrading instead of failing when a dataset is absent.

**Architecture:** `lyrics_lint/datasets.py` owns the pinned manifest, the cache-directory probe order, the fetch/verify routine, and the two file parsers. `RhymeEngine` takes a `dictionary` mapping and a `frequency` callable (both defaulting to whatever the dataset layer finds, empty when absent), so core has no import-time dataset dependency. The CLI gains a `data` command group and a hint on stderr when the dictionary is missing; MCP results carry a `hint` key instead.

**Tech Stack:** Python 3.10+, click, fastmcp, pytest, ruff. Standard library only for fetching (`urllib.request`, `hashlib`, `pathlib`).

**Spec:** `docs/superpowers/specs/2026-11-14-optional-datasets.md`

## Global Constraints

- Runtime dependencies after this work: `click>=8.1`, `fastmcp>=2.0`. Nothing else.
- `cmudict`, `wordfreq`, `g2p-en` must not appear in `pyproject.toml`, and no module may import them at import time. `g2p_en` may only be imported inside a function, guarded by `ImportError`.
- Cache probe order, exactly: `LYRICS_LINT_DATA` → `$XDG_CACHE_HOME/lyrics-lint` → `~/.cache/lyrics-lint` → absent.
- Pinned hashes are copied verbatim from the spec; a mismatch must raise, never warn.
- Nothing may raise when a dataset is missing. Absent ⇒ empty results + hint.
- Every test runs offline with no cache. Fixtures live in `tests/fixtures/`.
- `uv run pytest` and `uv run ruff check .` must pass before every commit.

## Review Focus

- `LYRICS_LINT_DATA` pointing at a directory that does not exist: expect "absent", not a crash.
- A truncated or half-downloaded cache file: expect `status` to report unverified, and lookups to behave as if absent rather than returning garbage.
- `data fetch` interrupted mid-download: expect no partial file left in place, and the old file (if any) preserved.
- Word with an alt-pron marker (`word(2)`) in the dictionary: expect both pronunciations indexed, word keyed without the marker.
- A word in the frequency file that is missing from the dictionary: expect it not to appear in rhyme results, and no KeyError from ranking.

---

### Task 1: Dataset paths, manifest, and status

**Files:**
- Create: `lyrics_lint/datasets.py`
- Test: `tests/test_datasets.py`

**Interfaces:**
- Produces: `Dataset(name, filename, url, sha256, licence, description)` frozen dataclass; `DATASETS: tuple[Dataset, ...]`; `data_dir() -> Path`; `dataset_path(name: str) -> Path`; `sha256_of(path: Path) -> str`; `status(datasets=DATASETS) -> list[dict]` where each dict has `name`, `path`, `present`, `bytes`, `verified`, `licence`.

- [ ] **Step 1: Write the failing test** — `tests/test_datasets.py`

```python
def test_data_dir_honours_explicit_override(tmp_path, monkeypatch):
    monkeypatch.setenv("LYRICS_LINT_DATA", str(tmp_path / "mine"))
    assert datasets.data_dir() == tmp_path / "mine"


def test_data_dir_falls_back_to_xdg_cache(tmp_path, monkeypatch):
    monkeypatch.delenv("LYRICS_LINT_DATA", raising=False)
    monkeypatch.setenv("XDG_CACHE_HOME", str(tmp_path))
    assert datasets.data_dir() == tmp_path / "lyrics-lint"


def test_dataset_path_uses_manifest_filename():
    assert datasets.dataset_path("cmudict").name == "cmudict.dict"


def test_status_reports_absent_dataset(tmp_path):
    status = datasets.status()
    entry = next(s for s in status if s["name"] == "cmudict")
    assert entry["present"] is False and entry["verified"] is False


def test_status_verifies_matching_bytes(tmp_path):
    payload = b"YOU  Y UW1\n"
    ds = datasets.Dataset(
        "mini",
        "mini.dict",
        "file:///nope",
        hashlib.sha256(payload).hexdigest(),
        "test",
        "mini",
    )
    (tmp_path / "mini.dict").write_bytes(payload)
    monkeypatch.setenv("LYRICS_LINT_DATA", str(tmp_path))
    entry = datasets.status((ds,))[0]
    assert (
        entry["present"] is True
        and entry["verified"] is True
        and entry["bytes"] == len(payload)
    )


def test_status_flags_wrong_bytes_as_unverified(tmp_path, monkeypatch):
    ds = datasets.Dataset("mini", "mini.dict", "file:///nope", "0" * 64, "test", "mini")
    (tmp_path / "mini.dict").write_bytes(b"tampered")
    monkeypatch.setenv("LYRICS_LINT_DATA", str(tmp_path))
    entry = datasets.status((ds,))[0]
    assert entry["present"] is True and entry["verified"] is False
```

- [ ] **Step 2: Run to verify failure** — `uv run pytest tests/test_datasets.py -v` → `ModuleNotFoundError`/`AttributeError`
- [ ] **Step 3: Implement** `lyrics_lint/datasets.py` with the manifest exactly as specified (`cmudict`, `frequencies`, pinned URLs and sha256 values copied from the spec). `data_dir()` uses `LYRICS_LINT_DATA` if set (an absent directory is still returned, not created), else `$XDG_CACHE_HOME/lyrics-lint`, else `Path.home()/".cache"/"lyrics-lint"`. `status()` never creates or modifies anything.
- [ ] **Step 4: Run to verify pass** — `uv run pytest tests/test_datasets.py -v`
- [ ] **Step 5: Commit** — `git commit -m "data: add pinned dataset manifest and cache paths"`

---

### Task 2: Fetch with hash verification

**Files:**
- Modify: `lyrics_lint/datasets.py`
- Test: `tests/test_datasets.py`

**Interfaces:**
- Produces: `fetch(names: Iterable[str] | None = None, force: bool = False, datasets=DATASETS) -> list[dict]`. Returns one `status`-shaped dict per dataset, with an added `"fetched": bool`. Raises `ValueError` for an unknown name and `RuntimeError` on hash mismatch (naming the dataset and both hashes).

- [ ] **Step 1: Write the failing test**

```python
def _serve(tmp_path, payload):
    path = tmp_path / "served.dict"
    path.write_bytes(payload)
    return datasets.Dataset(
        "mini",
        "mini.dict",
        path.as_uri(),
        hashlib.sha256(payload).hexdigest(),
        "test",
        "mini",
    )


def test_fetch_downloads_and_verifies(tmp_path, monkeypatch):
    source = _serve(tmp_path, b"YOU  Y UW1\n")
    monkeypatch.setenv("LYRICS_LINT_DATA", str(tmp_path / "cache"))
    entry = datasets.fetch(["mini"], datasets=(source,))[0]
    assert entry["fetched"] is True and entry["verified"] is True
    assert (tmp_path / "cache" / "mini.dict").read_bytes() == b"YOU  Y UW1\n"


def test_fetch_refuses_hash_mismatch_and_leaves_nothing(tmp_path, monkeypatch):
    source = datasets.Dataset(
        "mini", "mini.dict", _serve(tmp_path, b"x").url, "0" * 64, "test", "mini"
    )
    monkeypatch.setenv("LYRICS_LINT_DATA", str(tmp_path / "cache"))
    with pytest.raises(RuntimeError, match="mini"):
        datasets.fetch(["mini"], datasets=(source,))
    assert not (tmp_path / "cache" / "mini.dict").exists()
    assert not (tmp_path / "cache" / "mini.dict.part").exists()


def test_fetch_skips_present_verified_dataset(tmp_path, monkeypatch):
    source = _serve(tmp_path, b"YOU  Y UW1\n")
    monkeypatch.setenv("LYRICS_LINT_DATA", str(tmp_path / "cache"))
    datasets.fetch(["mini"], datasets=(source,))
    entry = datasets.fetch(["mini"], datasets=(source,))[0]
    assert entry["fetched"] is False


def test_fetch_rejects_unknown_dataset(tmp_path, monkeypatch):
    monkeypatch.setenv("LYRICS_LINT_DATA", str(tmp_path))
    with pytest.raises(ValueError, match="nope"):
        datasets.fetch(["nope"], datasets=())
```

- [ ] **Step 2: Run to verify failure** — `uv run pytest tests/test_datasets.py -k fetch -v`
- [ ] **Step 3: Implement** `fetch()`: stream the URL in 64 KiB chunks into `<target>.part` while feeding `hashlib.sha256`, then compare, then `os.replace`. On mismatch or any exception, remove the `.part` file in a `finally` before re-raising. `force=True` bypasses the "already verified" skip. `data_dir().mkdir(parents=True, exist_ok=True)` happens inside `fetch` only.
- [ ] **Step 4: Run to verify pass** — `uv run pytest tests/test_datasets.py -v`
- [ ] **Step 5: Commit** — `git commit -m "data: fetch datasets with sha256 verification and atomic writes"`

---

### Task 3: Dictionary and frequency file parsers

**Files:**
- Modify: `lyrics_lint/datasets.py`
- Test: `tests/test_datasets.py`

**Interfaces:**
- Produces: `load_cmudict(path: Path) -> dict[str, list[str]]` (pronunciations are space-joined uppercase ARPAbet strings, keys lowercased, `word(2)` alt-pron markers stripped and appended, `;;;` comments and blank lines skipped); `load_frequencies(path: Path) -> Callable[[str], float]` returning `log10(count)` for a known word and `0.0` otherwise; `lyrics_lint.datasets.missing_hint() -> str | None` returning `"no pronunciation dictionary: run 'lyrics data fetch'"` when the cmudict file is absent or unverified, else `None`.

- [ ] **Step 1: Write the failing test**

```python
def test_load_cmudict_skips_comments_and_strips_alt_markers(tmp_path):
    path = tmp_path / "d.dict"
    path.write_text(";;; comment\n\nWIND  W AY1 N D\nWIND(2)  W IH1 N D\n")
    assert datasets.load_cmudict(path) == {"wind": ["W AY1 N D", "W IH1 N D"]}


def test_load_frequencies_returns_log10_counts(tmp_path):
    path = tmp_path / "f.txt"
    path.write_text("you 1000000\ntiny 10\n")
    freq = datasets.load_frequencies(path)
    assert freq("you") == pytest.approx(6.0)
    assert freq("tiny") < freq("you")
    assert freq("missing") == 0.0


def test_missing_hint_mentions_fetch_command(tmp_path, monkeypatch):
    monkeypatch.setenv("LYRICS_LINT_DATA", str(tmp_path))
    assert "lyrics data fetch" in datasets.missing_hint()
```

- [ ] **Step 2: Run to verify failure** — `uv run pytest tests/test_datasets.py -k "load or hint" -v`
- [ ] **Step 3: Implement** the three functions. The frequency callable closes over a `dict[str, int]` and does the `log10` conversion per call (cheap, and keeps the table reusable).
- [ ] **Step 4: Run to verify pass** — `uv run pytest tests/test_datasets.py -v`
- [ ] **Step 5: Commit** — `git commit -m "data: parse cmudict.dict and frequency list formats"`

---

### Task 4: Engine takes an injected dictionary

**Files:**
- Modify: `lyrics_lint/core.py` (`__init__`, `_load_overrides`, remove the `import cmudict` block)
- Create: `tests/conftest.py`, `tests/fixtures/cmudict.dict`, `tests/fixtures/en_50k.txt`
- Test: `tests/test_core.py`

**Interfaces:**
- Consumes: `datasets.dataset_path`, `datasets.load_cmudict`, `datasets.load_frequencies`.
- Produces: `RhymeEngine(overrides=..., g2p=None, dictionary: Mapping[str, list[str]] | None = None, frequency: Callable[[str], float] | None = None)`. `None` means "use the dataset layer, empty when absent". `engine.dict` is the merged mapping (dictionary + overrides + g2p results); `engine.frequency(word) -> float`.

- [ ] **Step 1: Build the fixtures.** Prune the real files to the words the tests assert on plus their whole rhyme-pattern families:

```bash
uv run python - <<'PY'
import re, pathlib
src = pathlib.Path("/tmp/ds-probe/cmudict.dict").read_text().splitlines()
words = set(re.findall(r"[a-z']+", "".join(p.read_text() for p in pathlib.Path("tests").glob("*.py"))))
base = {w.split("(")[0]: w for w in (l.split("  ")[0] for l in src if "  " in l)}
PATTERN = re.compile(r"([A-Z]{2}[12][A-Z0-9 ]*)$")
keep = set()
for line in src:
    m = re.match(r"(\S+)\s\s+(\S.*)", line)
    if not m: continue
    word, pron = m.group(1).split("(")[0].lower(), m.group(2)
    if word in words:
        pat = re.search(r"[A-Z]{2}[12][^A-Z]*$", pron).group(0)
        for l2 in src:
            m2 = re.match(r"(\S+)\s\s+(\S.*)", l2)
            if m2 and m2.group(2).endswith(pat): keep.add(l2)
pathlib.Path("tests/fixtures").mkdir(exist_ok=True)
pathlib.Path("tests/fixtures/cmudict.dict").write_text("\n".join(sorted(keep)) + "\n")
counts = dict(l.split() for l in pathlib.Path("/tmp/ds-probe/en_50k.txt").read_text().splitlines())
names = {l.split("(")[0].lower() for l in keep}
pathlib.Path("tests/fixtures/en_50k.txt").write_text(
    "".join(f"{n} {counts[n]}\n" for n in sorted(names) if n in counts))
PY
```

  Verify the fixtures are plausible before continuing: `wc -l tests/fixtures/*`, and check that `grep -c "^you " tests/fixtures/cmudict.dict` is 1.

- [ ] **Step 2: Write the failing test** — append to `tests/test_core.py`

```python
def test_engine_indexes_injected_dictionary():
    engine = RhymeEngine(
        dictionary={"foo": ["F UW1"], "bar": ["B AA1 R"]}, frequency=None
    )
    assert engine.lookup("foo")["found"] is True
    assert engine.rhymes("foo") == ["foo"] or engine.rhymes("foo") == []


def test_engine_without_dictionary_is_empty_but_usable():
    engine = RhymeEngine(overrides=None, dictionary={}, frequency=None)
    assert engine.lookup("you")["found"] is False
    assert engine.rhymes("you") == []
    assert engine.slant_rhymes("you") == []
```

- [ ] **Step 3: Run to verify failure** — `uv run pytest tests/test_core.py -k "injected or without_dictionary" -v`
- [ ] **Step 4: Implement** the constructor changes, replacing the `cmudict` import with `dictionary or load from datasets`. Add `tests/conftest.py` with session fixtures `dictionary`/`frequency` built from `tests/fixtures/`, and a module-scoped `engine` fixture (`RhymeEngine(overrides=None, dictionary=dictionary, frequency=frequency)`), then delete the local `engine` fixture in `tests/test_core.py` so it comes from conftest.
- [ ] **Step 5: Run the whole suite and make every test pass** — `uv run pytest` (expect failures from whichever fixture words are missing; add those words to the fixture generation list and re-run the Task 4 step 1 script until green)
- [ ] **Step 6: Commit** — `git commit -m "core: take the pronunciation dictionary by injection, defaulting to datasets"`

---

### Task 5: Engine takes an injected frequency table

**Files:**
- Modify: `lyrics_lint/core.py` (delete `frequency()`, `_FREQUENCY`, `_no_frequency`; sort keys use `self.frequency`)
- Test: `tests/test_core.py`

**Interfaces:**
- Produces: `engine.frequency(word: str) -> float`; `RhymeEngine(frequency=...)` where `None` means "load the `frequencies` dataset, else 0.0".

- [ ] **Step 1: Write the failing test**

```python
def test_injected_frequency_controls_ranking():
    dictionary = {"you": ["Y UW1"], "do": ["D UW1"], "zebu": ["Z IY1 B UW0"]}
    common = RhymeEngine(
        dictionary=dictionary, frequency=lambda w: 9.0 if w == "do" else 1.0
    )
    assert common.rhymes("you", limit=1) == ["do"]
    reversed_order = RhymeEngine(
        dictionary=dictionary, frequency=lambda w: 9.0 if w == "zebu" else 1.0
    )
    assert reversed_order.rhymes("you", limit=1) == ["zebu"]


def test_missing_frequency_table_degrades_to_alphabetical():
    engine = RhymeEngine(
        dictionary={"z": ["Z UW1"], "a": ["AH0"]}, frequency=lambda _w: 0.0
    )
    assert engine.rhymes("z") == ["z"]
```

- [ ] **Step 2: Run to verify failure** — `uv run pytest tests/test_core.py -k frequency -v`
- [ ] **Step 3: Implement** `self.frequency` in `__init__` (`frequency or dataset_frequencies() or zero`), replace every module-level `frequency(...)` call in `rhymes()`/`slant_rhymes()`/`suggestions()` with `self.frequency(...)`, and rewrite the `zipf_frequency` assertions in `tests/test_core.py` to use the conftest `frequency` fixture instead.
- [ ] **Step 4: Run to verify pass** — `uv run pytest`
- [ ] **Step 5: Commit** — `git commit -m "core: take the frequency table by injection, defaulting to datasets"`

---

### Task 6: `lyrics data` commands and missing-data hints

**Files:**
- Modify: `lyrics_lint/cli.py`, `lyrics_lint/mcp.py`, `lyrics_lint/lint.py`
- Test: `tests/test_cli.py`

**Interfaces:**
- Produces: `lyrics data status [--json]`, `lyrics data fetch [NAME ...] [--force]`, `lyrics data path [NAME]`. `check`, `rhymes`, `slant`, `suggestions` print `datasets.missing_hint()` to stderr when the dictionary is absent, before their normal output. MCP tools add `"hint"` to their returned dict when `missing_hint()` is not `None`.

- [ ] **Step 1: Write the failing test** — `tests/test_cli.py`

```python
def test_data_status_marks_absent(tmp_path, monkeypatch):
    monkeypatch.setenv("LYRICS_LINT_DATA", str(tmp_path))
    result = CliRunner().invoke(cli, ["data", "status"])
    assert result.exit_code == 0
    assert "cmudict" in result.output and "missing" in result.output


def test_rhymes_without_dictionary_prints_hint(tmp_path, monkeypatch):
    monkeypatch.setenv("LYRICS_LINT_DATA", str(tmp_path))
    monkeypatch.setattr(
        "lyrics_lint.cli.get_engine",
        lambda: RhymeEngine(overrides=None, dictionary={}, frequency=None),
    )
    result = CliRunner().invoke(cli, ["rhymes", "you"])
    assert result.exit_code == 0
    assert "lyrics data fetch" in result.output


def test_data_fetch_rejects_unknown_name(tmp_path, monkeypatch):
    monkeypatch.setenv("LYRICS_LINT_DATA", str(tmp_path))
    result = CliRunner().invoke(cli, ["data", "fetch", "nope"])
    assert result.exit_code != 0
    assert "nope" in result.output
```

- [ ] **Step 2: Run to verify failure** — `uv run pytest tests/test_cli.py -v`
- [ ] **Step 3: Implement** the command group (`@cli.group("data")` with three subcommands) and the stderr hint. `status` prints a fixed-width table: name, present/missing, verified, size, licence, path.
- [ ] **Step 4: Run to verify pass** — `uv run pytest`
- [ ] **Step 5: Commit** — `git commit -m "cli: add 'lyrics data' commands and missing-dataset hints"`

---

### Task 7: Drop the dataset dependencies and document

**Files:**
- Modify: `pyproject.toml`, `README.md`, `lyrics_lint/core.py` (guard `g2p_en` import), `tests/fixtures/README.md`
- Test: `tests/test_core.py` (import guard test)

**Interfaces:**
- Produces: no import of `cmudict`, `wordfreq`, or `g2p_en` outside `try/except ImportError` inside function bodies. `lyrics_lint/__init__.py` still imports.

- [ ] **Step 1: Write the failing test**

```python
def test_no_heavy_dataset_imports_at_module_level():
    source = pathlib.Path("lyrics_lint/core.py").read_text()
    for name in ("import cmudict", "from cmudict", "import wordfreq", "from wordfreq"):
        assert name not in source
```

- [ ] **Step 2: Run to verify failure** — `uv run pytest tests/test_core.py -k heavy -v`
- [ ] **Step 3: Implement** — `uv remove cmudict wordfreq g2p-en`; move the `g2p_en` import inside `default_g2p` under `try/except ImportError` (already there, confirm); update README: new "Datasets" section (fetch/status/path, cache location, licences and attribution for the pruned fixtures), remove the old dependency claims; add `tests/fixtures/README.md` with both licences and the pruning note.
- [ ] **Step 4: Run to verify pass** — `uv run pytest`, `uv run ruff check .`, `uv build --wheel` and confirm with `unzip -l dist/*.whl | grep -E "cmudict|en_50k"` that no dataset is bundled.
- [ ] **Step 5: Commit** — `git commit -m "build: drop dataset dependencies; document fetching"`

---

## Self-Review

- Spec coverage: manifest/paths (Task 1), fetch+verify (Task 2), parsers (Task 3), dictionary injection (Task 4), frequency injection (Task 5), CLI/MCP surface (Task 6), dependency removal + docs (Task 7). Degradation contract is covered by tests in Tasks 4, 5, and 6. Licence/attribution is Task 7.
- Type consistency: `Dataset` field order is fixed in Task 1 and used positionally in Tasks 1–2 tests; `status()`/`fetch()` shapes are shared; `load_cmudict`/`load_frequencies` names are used verbatim in Task 4.
- Review Focus items are pinned: absent directory (Task 1), truncated file (Task 1 unverified), interrupted fetch (Task 2), alt-pron marker (Task 3), frequency-only word (Task 5 ranking test).
