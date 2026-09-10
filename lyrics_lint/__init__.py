"""lyrics-lint: rhyme and slant-rhyme linting for lyrics."""

from .core import RhymeEngine, get_engine, rhyme_pattern
from .lines import end_word

__all__ = ["RhymeEngine", "get_engine", "rhyme_pattern", "end_word"]
