"""The consumer typing contract in tests/typing/ holds under mypy --strict.

The same check runs in CI's ``quality`` job (``mypy OWNd tests/typing``);
this test makes ``pytest`` alone sufficient to notice a signature that
would reject a consumer, and skips where mypy is not installed.
"""
from __future__ import annotations

import pathlib

import pytest

mypy_api = pytest.importorskip("mypy.api")

CONSUMER_DIR = pathlib.Path(__file__).parent / "typing"


def test_consumer_calls_type_check_under_strict() -> None:
    stdout, stderr, status = mypy_api.run(["--strict", str(CONSUMER_DIR)])
    assert status == 0, f"consumer typing contract broken:\n{stdout}{stderr}"
