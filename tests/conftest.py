"""Shared fixtures: the pristine dataset slice the test suite runs against.

Tests never touch the network or the user's cache. `tests/fixtures/` holds a
pruned slice of both datasets (see tests/fixtures/README.md) covering every
word the assertions mention plus the rhyme families those words belong to.
"""

from pathlib import Path

import pytest

from lyrics_lint.core import RhymeEngine
from lyrics_lint.datasets import load_cmudict, load_frequencies

FIXTURES = Path(__file__).parent / "fixtures"


@pytest.fixture(scope="session")
def dictionary() -> dict[str, list[str]]:
    return load_cmudict(FIXTURES / "cmudict.dict")


@pytest.fixture(scope="session")
def frequency():
    return load_frequencies(FIXTURES / "en_50k.txt")


@pytest.fixture(scope="session")
def engine(dictionary, frequency) -> RhymeEngine:
    return RhymeEngine(overrides=None, dictionary=dictionary, frequency=frequency)


@pytest.fixture(scope="session")
def engine_factory(dictionary, frequency):
    """Build engines from the fixture datasets, overriding only what a test needs."""

    def make(**kwargs):
        kwargs.setdefault("dictionary", dictionary)
        kwargs.setdefault("frequency", frequency)
        return RhymeEngine(**kwargs)

    return make


@pytest.fixture(scope="session", autouse=True)
def _global_engine_uses_fixtures(engine):
    """Point the module-level singleton at the fixture data.

    Without this, anything calling get_engine() would read (or not read) the
    developer's real cache, making the suite depend on machine state.
    """
    from lyrics_lint import core

    previous = core._ENGINE
    core._ENGINE = engine
    yield
    core._ENGINE = previous
