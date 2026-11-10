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

from OWNd.connection import OWNGateway

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
            client.settimeout(5.0)  # a stalled client must not block the server thread
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


def _interrupt(process: subprocess.Popen[str]) -> None:
    """Stop the CLI the way Ctrl-C does on POSIX.

    ``Popen.send_signal`` on Windows accepts only ``SIGTERM``, ``CTRL_C_EVENT`` and
    ``CTRL_BREAK_EVENT`` and raises ``ValueError`` for ``SIGINT``; the Ctrl-C path
    itself is covered on every platform by
    ``test_entry_point_starts_and_stops_without_an_existing_event_loop``.
    """
    if sys.platform == "win32":
        process.terminate()
    else:
        process.send_signal(signal.SIGINT)


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
            _interrupt(process)
            _, stderr = process.communicate(timeout=15)
        finally:
            if process.poll() is None:
                process.kill()
                process.communicate()

    assert len(accepted) >= 3, stderr
    assert "Now waiting for events" in stderr
    if sys.platform != "win32":
        assert process.returncode == 0, stderr
        assert "OWNd stopped." in stderr


# --- Without --port the entry point probes the network for the gateway
# --- description (SSDP, or the HTTP descriptor of --address). The probe is
# --- replaced in the subprocess so that no network is used.

_RUN_ENTRY_POINT_NO_PROBE_ANSWER = """
import runpy
import sys

import OWNd.connection.gateway as gateway_module
import OWNd.connection.session as session

# The profile's default port (20000 in the library) is redirected to a port the
# test knows to be closed, so the run does not depend on what listens on 20000.
DEFAULT_PORT = int(sys.argv[1])


def closed_default_port_profile(model_name, model_number=None):
    return gateway_module.GatewayProfile(model_name=str(model_name), default_port=DEFAULT_PORT)


async def nothing_found(*args, **kwargs):
    return []


async def no_description(address, session=None):
    return None


gateway_module.get_gateway_profile = closed_default_port_profile
gateway_module.find_gateways = nothing_found
gateway_module.get_gateway = no_description
session.MAX_CONNECT_ATTEMPTS = 2
sys.argv = ["OWNd", *sys.argv[2:]]
runpy.run_module("OWNd", run_name="__main__")
"""


def _closed_port() -> int:
    with socket.socket() as probe:
        probe.bind(("127.0.0.1", 0))
        return int(probe.getsockname()[1])


def test_entry_point_exits_when_no_gateway_is_discovered():
    """``python -m OWNd`` with nothing on SSDP: a connection error, not an AssertionError."""
    result = subprocess.run(
        [sys.executable, "-c", _RUN_ENTRY_POINT_NO_PROBE_ANSWER, str(_closed_port())],
        capture_output=True,
        text=True,
        timeout=30,
        cwd=REPO_ROOT,
        check=False,
    )

    assert result.returncode != 0
    assert "OWNConnectionError" in result.stderr
    assert "No OpenWebNet gateway discovered" in result.stderr
    assert "AssertionError" not in result.stderr
    assert "Starting connection" not in result.stderr
    assert "OWNd stopped." in result.stderr


def test_entry_point_connects_directly_when_the_address_has_no_description():
    """``--address`` without ``--port`` and no description.xml: connect to the address
    on the profile's default port anyway, and give up after the connect attempts."""
    closed_port = _closed_port()
    result = subprocess.run(
        [
            sys.executable,
            "-c",
            _RUN_ENTRY_POINT_NO_PROBE_ANSWER,
            str(closed_port),
            "--address", "127.0.0.1",
            "--password", "12345",
        ],
        capture_output=True,
        text=True,
        timeout=60,
        cwd=REPO_ROOT,
        check=False,
    )

    assert result.returncode != 0
    assert f"connecting to it directly on port {closed_port}" in result.stderr
    assert "OWNConnectionError" in result.stderr
    assert "AssertionError" not in result.stderr
    assert "OWNd stopped." in result.stderr


def test_direct_gateway_from_the_command_line_defaults_to_port_20000():
    """The fallback gateway main() builds without --port uses the documented default."""
    gateway = OWNGateway({"address": "192.0.2.1", "port": None, "password": "12345", "serialNumber": None})
    assert gateway.port == 20000
    assert gateway.password == "12345"


def _ask_password_accept_any(answers: list[bytes]) -> Callable[[socket.socket], None]:
    def handler(client: socket.socket) -> None:
        """Greet, ask for the OPEN password, accept whatever comes back, then drop."""
        client.sendall(b"*#*1##")
        _read_frame(client)  # *99*1##
        client.sendall(b"*#603356072##")
        answers.append(_read_frame(client))
        client.sendall(b"*#*1##")
        time.sleep(0.5)

    return handler


# The HTTP description probe answers (as it does for a reachable gateway), with
# a description that carries no password: the one on the command line must be kept.
_RUN_ENTRY_POINT_DESCRIBED_GATEWAY = """
import runpy
import sys

import OWNd.connection.gateway as gateway_module

PORT = int(sys.argv[1])


async def description(address, session=None):
    return {"address": address, "port": PORT, "modelName": "MyHomeServer1", "serialNumber": "0003500011AA"}


gateway_module.get_gateway = description
sys.argv = ["OWNd", *sys.argv[2:]]
runpy.run_module("OWNd", run_name="__main__")
"""


def test_entry_point_keeps_the_cli_password_when_the_probe_finds_the_gateway():
    """``--address --password`` without ``--port``: the probe builds the gateway from its
    description, which has no password; the command-line password is still used."""
    answers: list[bytes] = []
    with _fake_gateway(_ask_password_accept_any(answers)) as (port, accepted):
        process = subprocess.Popen(
            [
                sys.executable,
                "-c",
                _RUN_ENTRY_POINT_DESCRIBED_GATEWAY,
                str(port),
                "--address", "127.0.0.1",
                "--password", "12345",
            ],
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            cwd=REPO_ROOT,
        )
        try:
            deadline = time.monotonic() + 30
            while len(accepted) < 2 and time.monotonic() < deadline:
                assert process.poll() is None, process.stderr.read() if process.stderr else ""
                time.sleep(0.1)
            _interrupt(process)
            _, stderr = process.communicate(timeout=15)
        finally:
            if process.poll() is None:
                process.kill()
                process.communicate()

    assert answers, stderr
    # The OPEN password answer is *#<digits>##; without a password the session
    # answers the challenge with a NACK (*#*0##) and gives up (password_required).
    assert answers[0].startswith(b"*#") and answers[0] != b"*#*0##", (answers, stderr)
    assert answers[0][2:-2].isdigit(), (answers, stderr)
    assert "password_required" not in stderr
    assert "Now waiting for events" in stderr
