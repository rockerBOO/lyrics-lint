"""CLI tests for the `lyrics data` group and missing-dataset behaviour."""

import pathlib

from click.testing import CliRunner

from lyrics_lint.cli import cli
from lyrics_lint.core import RhymeEngine


def test_data_status_marks_absent_datasets(tmp_path, monkeypatch):
    monkeypatch.setenv("LYRICS_LINT_DATA", str(tmp_path))

    result = CliRunner().invoke(cli, ["data", "status"])

    assert result.exit_code == 0
    assert "cmudict" in result.output
    assert "missing" in result.output


def test_data_status_reports_verified_dataset(tmp_path, monkeypatch):
    import hashlib

    from lyrics_lint import datasets

    payload = b"YOU  Y UW1\n"
    dataset = datasets.Dataset(
        "cmudict",
        "cmudict.dict",
        "file:///nope",
        hashlib.sha256(payload).hexdigest(),
        "BSD-2-Clause",
        "mini dict",
    )
    (tmp_path / "cmudict.dict").write_bytes(payload)
    monkeypatch.setenv("LYRICS_LINT_DATA", str(tmp_path))
    monkeypatch.setattr(datasets, "DATASETS", (dataset,))
    monkeypatch.setattr(datasets, "DATASETS_BY_NAME", {dataset.name: dataset})

    result = CliRunner().invoke(cli, ["data", "status", "--json"])

    assert result.exit_code == 0
    assert '"verified": true' in result.output


def test_data_path_prints_cache_location(tmp_path, monkeypatch):
    monkeypatch.setenv("LYRICS_LINT_DATA", str(tmp_path))

    result = CliRunner().invoke(cli, ["data", "path"])

    assert result.exit_code == 0
    assert str(tmp_path) in result.output


def test_data_fetch_rejects_unknown_name(tmp_path, monkeypatch):
    monkeypatch.setenv("LYRICS_LINT_DATA", str(tmp_path))

    result = CliRunner().invoke(cli, ["data", "fetch", "nope"])

    assert result.exit_code != 0
    assert "nope" in result.output


def test_rhymes_without_dictionary_prints_fetch_hint(tmp_path, monkeypatch):
    monkeypatch.setenv("LYRICS_LINT_DATA", str(tmp_path))
    monkeypatch.setattr(
        "lyrics_lint.cli.get_engine",
        lambda: RhymeEngine(overrides=None, dictionary={}, frequency=lambda _w: 0.0),
    )

    result = CliRunner().invoke(cli, ["rhymes", "you"])

    assert result.exit_code == 0
    assert "lyrics data fetch" in result.output


def test_lint_without_dictionary_still_reports(tmp_path, monkeypatch):
    monkeypatch.setenv("LYRICS_LINT_DATA", str(tmp_path))
    empty = lambda: RhymeEngine(  # noqa: E731
        overrides=None, dictionary={}, frequency=lambda _w: 0.0
    )
    monkeypatch.setattr("lyrics_lint.cli.get_engine", empty)
    monkeypatch.setattr("lyrics_lint.lint.get_engine", empty)
    lyrics = tmp_path / "s.md"
    lyrics.write_text("paying the cost\ni love the color purple\n")

    result = CliRunner().invoke(cli, ["lint", str(lyrics)])

    assert result.exit_code == 0
    assert "lyrics data fetch" in result.output
    assert "unknown-word" in result.output


def test_data_fetch_reports_network_failure_without_a_traceback(tmp_path, monkeypatch):
    import urllib.error

    from lyrics_lint import datasets

    monkeypatch.setenv("LYRICS_LINT_DATA", str(tmp_path))
    monkeypatch.setattr(
        datasets.urllib.request,
        "urlopen",
        lambda *_a, **_k: (_ for _ in ()).throw(urllib.error.URLError("no route")),
    )

    result = CliRunner().invoke(cli, ["data", "fetch", "cmudict"])

    assert result.exit_code != 0
    assert "Error:" in result.output
    assert "cmudict" in result.output
    assert "Traceback" not in result.output


def _verified_dict_on_disk(tmp_path, monkeypatch):
    """Put a verifying cmudict in the cache while the engine stays empty."""
    import hashlib

    from lyrics_lint import datasets

    payload = pathlib.Path("tests/fixtures/cmudict.dict").read_bytes()
    dataset = datasets.Dataset(
        "cmudict",
        "cmudict.dict",
        "file:///x",
        hashlib.sha256(payload).hexdigest(),
        "BSD-2-Clause",
        "mini",
    )
    (tmp_path / "cmudict.dict").write_bytes(payload)
    monkeypatch.setenv("LYRICS_LINT_DATA", str(tmp_path))
    monkeypatch.setattr(datasets, "DATASETS", (dataset,))
    monkeypatch.setattr(datasets, "DATASETS_BY_NAME", {"cmudict": dataset})
    monkeypatch.setattr(
        "lyrics_lint.cli.get_engine",
        lambda: RhymeEngine(overrides=None, dictionary={}, frequency=lambda _w: 0.0),
    )


def test_hint_follows_the_engine_not_the_filesystem(tmp_path, monkeypatch):
    # Regression: the hint used to disappear as soon as the file verified, even
    # though this engine had been built before the fetch and stayed empty.
    _verified_dict_on_disk(tmp_path, monkeypatch)

    result = CliRunner().invoke(cli, ["rhymes", "you"])

    assert result.exit_code == 0
    assert "lyrics data fetch" in result.output


def test_json_payload_carries_the_hint_when_data_is_missing(tmp_path, monkeypatch):
    monkeypatch.setenv("LYRICS_LINT_DATA", str(tmp_path))
    monkeypatch.setattr(
        "lyrics_lint.cli.get_engine",
        lambda: RhymeEngine(overrides=None, dictionary={}, frequency=lambda _w: 0.0),
    )

    result = CliRunner().invoke(cli, ["rhymes", "you", "--json"])

    assert '"hint"' in result.output
    assert "lyrics data fetch" in result.output
