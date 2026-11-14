"""MCP surface: the hint key and the shapes the tools return."""

import pytest

from lyrics_lint import mcp as mcp_module
from lyrics_lint.core import RhymeEngine


@pytest.fixture
def empty_engine_installed(monkeypatch):
    """Make the MCP tools see an engine with no dataset dictionary."""
    engine = RhymeEngine(overrides=None, dictionary={}, frequency=lambda _w: 0.0)
    monkeypatch.setattr(mcp_module, "get_engine", lambda: engine)
    return engine


def test_check_pair_carries_the_hint_when_data_is_missing(empty_engine_installed):
    result = mcp_module.check_pair("i love you", "and me too")

    assert result["verdict"] == "unknown"
    assert "lyrics data fetch" in result["hint"]


def test_rhymes_carries_the_hint_when_data_is_missing(empty_engine_installed):
    result = mcp_module.rhymes("you", 5)

    assert result["found"] is False
    assert result["perfect_rhymes"] == []
    assert "lyrics data fetch" in result["hint"]


def test_slant_rhymes_carries_the_hint_when_data_is_missing(empty_engine_installed):
    result = mcp_module.slant_rhymes("you", 1, 5)

    assert result["found"] is False
    assert "lyrics data fetch" in result["hint"]


def test_suggestions_carries_the_hint_when_data_is_missing(empty_engine_installed):
    result = mcp_module.suggestions("you", 5)

    assert result["found"] is False
    assert "lyrics data fetch" in result["hint"]


def test_no_hint_when_the_engine_has_dataset_data():
    # The session engine comes from tests/fixtures, so it is dataset-sourced.
    result = mcp_module.rhymes("you", 3)

    assert result["found"] is True
    assert result["perfect_rhymes"]
    assert "hint" not in result
