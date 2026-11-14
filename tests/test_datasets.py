"""Tests for the optional dataset layer: paths, manifest, fetching, parsers."""

import hashlib

import pytest

from lyrics_lint import datasets


def test_data_dir_honours_explicit_override(tmp_path, monkeypatch):
    monkeypatch.setenv("LYRICS_LINT_DATA", str(tmp_path / "mine"))
    assert datasets.data_dir() == tmp_path / "mine"


def test_data_dir_falls_back_to_xdg_cache(tmp_path, monkeypatch):
    monkeypatch.delenv("LYRICS_LINT_DATA", raising=False)
    monkeypatch.setenv("XDG_CACHE_HOME", str(tmp_path))
    assert datasets.data_dir() == tmp_path / "lyrics-lint"


def test_dataset_path_uses_manifest_filename():
    assert datasets.dataset_path("cmudict").name == "cmudict.dict"


def test_status_reports_absent_dataset(tmp_path, monkeypatch):
    monkeypatch.setenv("LYRICS_LINT_DATA", str(tmp_path / "nothing-here"))
    status = datasets.status()
    entry = next(s for s in status if s["name"] == "cmudict")
    assert entry["present"] is False
    assert entry["verified"] is False


def test_status_verifies_matching_bytes(tmp_path, monkeypatch):
    payload = b"YOU  Y UW1\n"
    dataset = datasets.Dataset(
        "mini",
        "mini.dict",
        "file:///nope",
        hashlib.sha256(payload).hexdigest(),
        "test",
        "mini",
    )
    (tmp_path / "mini.dict").write_bytes(payload)
    monkeypatch.setenv("LYRICS_LINT_DATA", str(tmp_path))

    entry = datasets.status((dataset,))[0]
    assert entry["present"] is True
    assert entry["verified"] is True
    assert entry["bytes"] == len(payload)


def test_status_flags_wrong_bytes_as_unverified(tmp_path, monkeypatch):
    dataset = datasets.Dataset(
        "mini", "mini.dict", "file:///nope", "0" * 64, "test", "mini"
    )
    (tmp_path / "mini.dict").write_bytes(b"tampered")
    monkeypatch.setenv("LYRICS_LINT_DATA", str(tmp_path))

    entry = datasets.status((dataset,))[0]
    assert entry["present"] is True
    assert entry["verified"] is False


# --------------------------------------------------------------- fetching


def _served(tmp_path, payload):
    source = tmp_path / "served.dict"
    source.write_bytes(payload)
    return datasets.Dataset(
        "mini",
        "mini.dict",
        source.as_uri(),
        hashlib.sha256(payload).hexdigest(),
        "test",
        "mini",
    )


def test_fetch_downloads_and_verifies(tmp_path, monkeypatch):
    dataset = _served(tmp_path, b"YOU  Y UW1\n")
    monkeypatch.setenv("LYRICS_LINT_DATA", str(tmp_path / "cache"))

    entry = datasets.fetch(["mini"], datasets=(dataset,))[0]
    assert entry["fetched"] is True
    assert entry["verified"] is True
    assert (tmp_path / "cache" / "mini.dict").read_bytes() == b"YOU  Y UW1\n"


def test_fetch_refuses_hash_mismatch_and_leaves_nothing(tmp_path, monkeypatch):
    dataset = datasets.Dataset(
        "mini", "mini.dict", _served(tmp_path, b"x").url, "0" * 64, "test", "mini"
    )
    monkeypatch.setenv("LYRICS_LINT_DATA", str(tmp_path / "cache"))

    with pytest.raises(RuntimeError, match="mini"):
        datasets.fetch(["mini"], datasets=(dataset,))
    assert not (tmp_path / "cache" / "mini.dict").exists()
    assert not (tmp_path / "cache" / "mini.dict.part").exists()


def test_fetch_skips_present_verified_dataset(tmp_path, monkeypatch):
    dataset = _served(tmp_path, b"YOU  Y UW1\n")
    monkeypatch.setenv("LYRICS_LINT_DATA", str(tmp_path / "cache"))

    datasets.fetch(["mini"], datasets=(dataset,))
    entry = datasets.fetch(["mini"], datasets=(dataset,))[0]
    assert entry["fetched"] is False


def test_fetch_force_redownloads(tmp_path, monkeypatch):
    dataset = _served(tmp_path, b"YOU  Y UW1\n")
    monkeypatch.setenv("LYRICS_LINT_DATA", str(tmp_path / "cache"))

    datasets.fetch(["mini"], datasets=(dataset,))
    entry = datasets.fetch(["mini"], force=True, datasets=(dataset,))[0]
    assert entry["fetched"] is True


def test_fetch_rejects_unknown_dataset(tmp_path, monkeypatch):
    monkeypatch.setenv("LYRICS_LINT_DATA", str(tmp_path))
    with pytest.raises(ValueError, match="nope"):
        datasets.fetch(["nope"], datasets=())


def test_fetch_creates_the_cache_directory(tmp_path, monkeypatch):
    dataset = _served(tmp_path, b"YOU  Y UW1\n")
    cache = tmp_path / "deep" / "cache"
    monkeypatch.setenv("LYRICS_LINT_DATA", str(cache))

    datasets.fetch(["mini"], datasets=(dataset,))
    assert (cache / "mini.dict").is_file()


# ---------------------------------------------------------------- parsers


def test_load_cmudict_skips_comments_and_strips_alt_markers(tmp_path):
    path = tmp_path / "d.dict"
    path.write_text(";;; comment\n\nWIND  W AY1 N D\nWIND(2)  W IH1 N D\n")

    assert datasets.load_cmudict(path) == {"wind": ["W AY1 N D", "W IH1 N D"]}


def test_load_cmudict_tolerates_a_truncated_final_line(tmp_path):
    path = tmp_path / "d.dict"
    path.write_text("YOU  Y UW1\nHALF\n")

    assert datasets.load_cmudict(path) == {"you": ["Y UW1"]}


def test_load_frequencies_returns_log10_counts(tmp_path):
    path = tmp_path / "f.txt"
    path.write_text("you 1000000\ntiny 10\n")

    frequency = datasets.load_frequencies(path)
    assert frequency("you") == pytest.approx(6.0)
    assert frequency("tiny") < frequency("you")
    assert frequency("missing") == 0.0
    assert frequency("YOU") == pytest.approx(6.0)


def test_missing_hint_mentions_fetch_command(tmp_path, monkeypatch):
    monkeypatch.setenv("LYRICS_LINT_DATA", str(tmp_path))

    hint = datasets.missing_hint()
    assert hint is not None
    assert "lyrics data fetch" in hint


def test_verified_path_is_none_when_absent(tmp_path, monkeypatch):
    monkeypatch.setenv("LYRICS_LINT_DATA", str(tmp_path))
    assert datasets.verified_path("cmudict") is None


# ------------------------------------------------ degradation review focus


def test_tampered_cache_file_is_treated_as_absent(tmp_path, monkeypatch):
    """A half-written dictionary must not produce rhymes from garbage."""
    from lyrics_lint.core import RhymeEngine

    payload = b"YOU  Y UW1\n"
    dataset = datasets.Dataset(
        "cmudict",
        "cmudict.dict",
        "file:///nope",
        hashlib.sha256(payload).hexdigest(),
        "BSD-2-Clause",
        "mini dict",
    )
    (tmp_path / "cmudict.dict").write_bytes(b"YOU  Y UW1\nTAMPERED")
    monkeypatch.setenv("LYRICS_LINT_DATA", str(tmp_path))
    monkeypatch.setattr(datasets, "DATASETS", (dataset,))
    monkeypatch.setattr(datasets, "DATASETS_BY_NAME", {dataset.name: dataset})

    assert datasets.verified_path("cmudict") is None
    engine = RhymeEngine(overrides=None, g2p=None, frequency=None)
    assert engine.lookup("you")["found"] is False
