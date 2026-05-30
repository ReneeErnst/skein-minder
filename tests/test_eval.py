"""Tests for the eval module."""

from __future__ import annotations

from skeinminder.eval import EvalExample, load_examples


def test_load_examples_returns_nonempty_list() -> None:
    examples = load_examples()
    assert len(examples) >= 1
    assert all(isinstance(e, EvalExample) for e in examples)
    assert all(e.id != "" for e in examples)
