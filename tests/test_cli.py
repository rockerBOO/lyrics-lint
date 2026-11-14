"""CLI tests for the `lyrics data` group and missing-dataset behaviour."""

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
