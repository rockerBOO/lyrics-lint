"""Optional datasets: pinned manifest, cache paths, fetching, file parsers.

Nothing here ships data in the wheel. A dataset is a plain file in a cache
directory, fetched on demand by `lyrics data fetch` and verified against a
sha256 pinned in this module. Every function tolerates absence: a missing
dataset is reported, never raised, and the rhyme engine degrades.

Licences of the pinned files:
  - cmudict.dict: CMU Pronouncing Dictionary, BSD-2-Clause (CMU 1993-2015)
  - en_50k.txt:   hermitdave/FrequencyWords (OpenSubtitles 2018 counts), MIT
"""

from __future__ import annotations

import hashlib
import os
import urllib.request
from collections.abc import Callable, Iterable, Sequence
from dataclasses import dataclass
from pathlib import Path

DATA_DIR_ENV = "LYRICS_LINT_DATA"
CACHE_DIRNAME = "lyrics-lint"
CHUNK_SIZE = 64 * 1024


@dataclass(frozen=True)
class Dataset:
    """One fetchable file: where it comes from and what it must hash to."""

    name: str
    filename: str
    url: str
    sha256: str
    licence: str
    description: str


DATASETS: tuple[Dataset, ...] = (
    Dataset(
        name="cmudict",
        filename="cmudict.dict",
        url=(
            "https://raw.githubusercontent.com/cmusphinx/cmudict/"
            "74790861f652b15e4ac49015a90074ad62a27690/cmudict.dict"
        ),
        sha256="81917843c7f44ce2b094ac63873c2c7a4cf802040792c455ba3ca406891c3d22",
        licence="BSD-2-Clause",
        description="CMU Pronouncing Dictionary (word -> ARPAbet pronunciations)",
    ),
    Dataset(
        name="frequencies",
        filename="en_50k.txt",
        url=(
            "https://raw.githubusercontent.com/hermitdave/FrequencyWords/master/"
            "content/2018/en/en_50k.txt"
        ),
        sha256="5351ff405b1126ef555791dd4d9798a48e3e9a501a9fc481a9da957752cfb458",
        licence="MIT",
        description="English word counts from OpenSubtitles 2018 (ranking only)",
    ),
)

DATASETS_BY_NAME: dict[str, Dataset] = {d.name: d for d in DATASETS}


# ------------------------------------------------------------------- locations


def data_dir() -> Path:
    """Where datasets are looked for.

    Explicit override, then XDG cache home, then the classic cache path. The
    directory is not created here: reading must not mutate the filesystem.
    """
    override = os.environ.get(DATA_DIR_ENV)
    if override:
        return Path(override).expanduser()
    cache_home = os.environ.get("XDG_CACHE_HOME")
    if cache_home:
        return Path(cache_home).expanduser() / CACHE_DIRNAME
    return Path.home() / ".cache" / CACHE_DIRNAME


def dataset_path(name: str) -> Path:
    """Path the dataset named `name` occupies, present or not."""
    return data_dir() / DATASETS_BY_NAME[name].filename


def sha256_of(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(CHUNK_SIZE), b""):
            digest.update(chunk)
    return digest.hexdigest()


def status(datasets: Sequence[Dataset] | None = None) -> list[dict]:
    """Report each dataset's presence and whether its bytes still verify."""
    datasets = DATASETS if datasets is None else datasets
    entries = []
    for dataset in datasets:
        path = data_dir() / dataset.filename
        present = path.is_file()
        entries.append(
            {
                "name": dataset.name,
                "path": str(path),
                "present": present,
                "bytes": path.stat().st_size if present else 0,
                "verified": present and sha256_of(path) == dataset.sha256,
                "licence": dataset.licence,
                "description": dataset.description,
            }
        )
    return entries


def verified_path(name: str) -> Path | None:
    """Path to a dataset whose bytes match the pinned hash, else None."""
    path = dataset_path(name)
    if not path.is_file():
        return None
    return path if sha256_of(path) == DATASETS_BY_NAME[name].sha256 else None


def missing_hint() -> str | None:
    """One-line fix-it hint when the pronunciation dictionary is unusable."""
    if verified_path("cmudict") is not None:
        return None
    return "no pronunciation dictionary: run 'lyrics data fetch'"


# ------------------------------------------------------------------- fetching


def fetch(
    names: Iterable[str] | None = None,
    force: bool = False,
    datasets: Sequence[Dataset] | None = None,
) -> list[dict]:
    """Download datasets into the cache, verifying each pinned sha256.

    Writes to `<target>.part` and renames on success, so an interrupted or
    corrupt download never leaves a file that looks usable.
    """
    datasets = DATASETS if datasets is None else datasets
    by_name = {d.name: d for d in datasets}
    wanted = list(by_name) if names is None else list(names)
    unknown = [name for name in wanted if name not in by_name]
    if unknown:
        raise ValueError(
            f"unknown dataset(s): {', '.join(unknown)}; available: {', '.join(by_name)}"
        )

    data_dir().mkdir(parents=True, exist_ok=True)
    results = []
    for name in wanted:
        dataset = by_name[name]
        target = data_dir() / dataset.filename
        if not force and target.is_file() and sha256_of(target) == dataset.sha256:
            results.append(_entry(dataset, target, fetched=False))
            continue

        partial = target.with_suffix(target.suffix + ".part")
        try:
            _download(dataset.url, partial)
            actual = sha256_of(partial)
            if actual != dataset.sha256:
                raise RuntimeError(
                    f"{dataset.name}: sha256 mismatch for {dataset.url} "
                    f"(expected {dataset.sha256}, got {actual})"
                )
            os.replace(partial, target)
        finally:
            partial.unlink(missing_ok=True)
        results.append(_entry(dataset, target, fetched=True))
    return results


def _download(url: str, target: Path) -> None:
    with urllib.request.urlopen(url) as response, target.open("wb") as handle:
        for chunk in iter(lambda: response.read(CHUNK_SIZE), b""):
            handle.write(chunk)


def _entry(dataset: Dataset, path: Path, fetched: bool) -> dict:
    return {
        "name": dataset.name,
        "path": str(path),
        "present": True,
        "bytes": path.stat().st_size,
        "verified": True,
        "fetched": fetched,
        "licence": dataset.licence,
        "description": dataset.description,
    }


# -------------------------------------------------------------------- parsers


def load_cmudict(path: Path) -> dict[str, list[str]]:
    """Parse a CMUdict-format file into `{word: [pronunciation, ...]}`.

    Alt-pronunciation markers (`wind(2)`) are stripped and their readings
    appended, so homographs keep every pronunciation. `;;;` comments and blank
    lines are skipped.
    """
    dictionary: dict[str, list[str]] = {}
    for line in path.read_text(encoding="utf-8", errors="replace").splitlines():
        line = line.strip()
        if not line or line.startswith(";;;"):
            continue
        word, _, phonemes = line.partition(" ")
        phonemes = phonemes.strip()
        if not phonemes:
            continue
        if word.endswith(")") and "(" in word:
            word = word[: word.rindex("(")]
        dictionary.setdefault(word.lower(), []).append(phonemes)
    return dictionary


def load_frequencies(path: Path) -> Callable[[str], float]:
    """Parse `word count` lines into a log10-scaled ranking function."""
    counts: dict[str, int] = {}
    for line in path.read_text(encoding="utf-8", errors="replace").splitlines():
        parts = line.split()
        if len(parts) != 2:
            continue
        word, count = parts
        try:
            counts[word.lower()] = int(count)
        except ValueError:
            continue

    def frequency(word: str) -> float:
        count = counts.get(word.lower(), 0)
        return math_log10(count) if count > 0 else 0.0

    return frequency


def math_log10(value: int) -> float:
    """log10 kept separate so the parser module needs no import at call site."""
    import math

    return math.log10(value)
