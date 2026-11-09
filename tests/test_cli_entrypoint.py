"""Tests for the ``python -m OWNd`` command-line entry point."""
from collections.abc import Callable, Iterator
from contextlib import contextmanager
from pathlib import Path
import signal
import socket
import subprocess
import sys
import threading
import time

REPO_ROOT = Path(__file__).resolve().parent.parent

# Runs the real entry point in a fresh interpreter: the entry point owns its event
# loop, and the Python 3.14 bug only showed in a main thread with no loop set.
# Gateway discovery is replaced so that no network is used; the KeyboardInterrupt
# follows the same path as Ctrl-C.
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
        cwd=REPO_ROOT,
        check=False,
    )

    assert result.returncode == 0, result.stderr
    assert "no current event loop" not in result.stderr
    assert "OWNd stopped." in result.stderr


_RUN_ENTRY_POINT_FAILURE = """
import runpy
import sys

from OWNd.connection import OWNGateway


async def fail(cls, discovery_info):
    raise ConnectionRefusedError("Gateway unreachable")


OWNGateway.build_from_discovery_info = classmethod(fail)
sys.argv = ["OWNd", "--address", "192.0.2.1"]
runpy.run_module("OWNd", run_name="__main__")
"""


def test_entry_point_exits_on_runtime_error():
    """The CLI must not hang if gateway initialization or connection raises an error."""
    result = subprocess.run(
        [sys.executable, "-c", _RUN_ENTRY_POINT_FAILURE],
        capture_output=True,
        text=True,
        timeout=10,
        cwd=REPO_ROOT,
        check=False,
    )

    assert result.returncode != 0
    assert "ConnectionRefusedError" in result.stderr
    assert "OWNd stopped." in result.stderr


# --- The first connection: a gateway that cannot be reached, or that rejects the
# --- password, ends the command; a drop after a good connection does not.


def _read_frame(client: socket.socket) -> bytes:
    data = b""
    while not data.endswith(b"##"):
        chunk = client.recv(1)
        if not chunk:
            break
        data += chunk
    return data


def _reject_password(client: socket.socket) -> None:
    """Greet, ask for the OPEN password, and refuse whatever comes back."""
    client.sendall(b"*#*1##")
    _read_frame(client)  # *99*1##
    client.sendall(b"*#603356072##")
    _read_frame(client)  # the password answer
    client.sendall(b"*#*0##")
    time.sleep(0.2)


def _accept_then_drop(client: socket.socket) -> None:
    """Accept the event session without a password, then drop the connection."""
    client.sendall(b"*#*1##")
    _read_frame(client)  # *99*1##
    client.sendall(b"*#*1##")
    time.sleep(0.5)


@contextmanager
def _fake_gateway(handler: Callable[[socket.socket], None]) -> Iterator[tuple[int, list[float]]]:
    """A local TCP server that plays one side of the OpenWebNet handshake."""
    server = socket.socket()
    server.bind(("127.0.0.1", 0))
    server.listen(5)
    accepted: list[float] = []

    def serve() -> None:
        while True:
            try:
                client, _ = server.accept()
            except OSError:
                return
            accepted.append(time.monotonic())
            try:
                handler(client)
            except OSError:
                pass
            finally:
                client.close()

    threading.Thread(target=serve, daemon=True).start()
    try:
        yield server.getsockname()[1], accepted
    finally:
        server.close()


def _cli(port: int) -> list[str]:
    return [
        "--address", "127.0.0.1",
        "--port", str(port),
        "--password", "12345",
        "--mac", "00:03:50:00:00:01",
    ]


# MAX_CONNECT_ATTEMPTS is lowered only to keep the test short (one 1 s back-off
# instead of 13 s); the entry point and the session code run unchanged.
_RUN_ENTRY_POINT_FEW_ATTEMPTS = """
import runpy
import sys

import OWNd.connection.session as session

session.MAX_CONNECT_ATTEMPTS = 2
sys.argv = ["OWNd", *sys.argv[1:]]
runpy.run_module("OWNd", run_name="__main__")
"""


def test_entry_point_exits_when_the_gateway_refuses_the_connection():
    """Nothing listening on the port: give up after the connect attempts, do not retry forever."""
    with socket.socket() as probe:
        probe.bind(("127.0.0.1", 0))
        closed_port = probe.getsockname()[1]

    result = subprocess.run(
        [sys.executable, "-c", _RUN_ENTRY_POINT_FEW_ATTEMPTS, *_cli(closed_port)],
        capture_output=True,
        text=True,
        timeout=30,
        cwd=REPO_ROOT,
        check=False,
    )

    assert result.returncode != 0
    assert "OWNConnectionError" in result.stderr
    assert "OWNd stopped." in result.stderr


def test_entry_point_exits_when_the_gateway_rejects_the_password():
    """A rejected password ends the command at once with the authentication error."""
    with _fake_gateway(_reject_password) as (port, accepted):
        result = subprocess.run(
            [sys.executable, "-m", "OWNd", *_cli(port)],
            capture_output=True,
            text=True,
            timeout=30,
            cwd=REPO_ROOT,
            check=False,
        )

    assert result.returncode != 0
    assert "OWNAuthError" in result.stderr
    assert "OWNd stopped." in result.stderr
    assert len(accepted) == 1


def test_entry_point_keeps_reconnecting_after_a_drop_once_connected():
    """Only the first connection is fatal: a later drop still reconnects, as a monitor should."""
    with _fake_gateway(_accept_then_drop) as (port, accepted):
        process = subprocess.Popen(
            [sys.executable, "-m", "OWNd", *_cli(port)],
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            cwd=REPO_ROOT,
        )
        try:
            deadline = time.monotonic() + 30
            while len(accepted) < 3 and time.monotonic() < deadline:
                assert process.poll() is None, process.stderr.read() if process.stderr else ""
                time.sleep(0.1)
            process.send_signal(signal.SIGINT)
            _, stderr = process.communicate(timeout=15)
        finally:
            if process.poll() is None:
                process.kill()
                process.communicate()

    assert len(accepted) >= 3
    assert process.returncode == 0, stderr
    assert "Now waiting for events" in stderr
    assert "OWNd stopped." in stderr
