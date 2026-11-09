"""Tests for the ``python -m OWNd`` command-line entry point."""
from pathlib import Path
import subprocess
import sys

# Runs the real entry point in a fresh interpreter, because the bug only shows in
# a main thread with no event loop set. Gateway discovery is replaced so that no
# network is used; the KeyboardInterrupt follows the same path as Ctrl-C.
_RUN_ENTRY_POINT = """
import runpy
import sys

from OWNd.connection import OWNGateway


async def interrupt(cls, discovery_info):
    raise KeyboardInterrupt


OWNGateway.build_from_discovery_info = classmethod(interrupt)
sys.argv = ["OWNd", "--address", "192.0.2.1"]
runpy.run_module("OWNd", run_name="__main__")
"""


def test_entry_point_starts_and_stops_without_an_existing_event_loop():
    """The CLI must create its own loop: Python 3.14 no longer creates one implicitly."""
    result = subprocess.run(
        [sys.executable, "-c", _RUN_ENTRY_POINT],
        capture_output=True,
        text=True,
        timeout=30,
        cwd=Path(__file__).resolve().parent.parent,
        check=False,
    )

    assert result.returncode == 0, result.stderr
    assert "no current event loop" not in result.stderr
    assert "OWNd stopped." in result.stderr
