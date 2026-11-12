"""WHO 18 DIMENSION 52 frames outside the tested forms are refused by every send path.

``*#18*51*52#2026#10##`` and ``*#18*51*52#2026#10*100##`` crash the F460 020012,
F461 020011 and 3488 030205 after the telegram went out (OpenWebNet-HA/
own-firmware-oracle, suite ``ownd-audit-frames``, ``findings/audit-crash-frames.md``;
emulated firmware, not yet replayed on physical hardware); the documented
two-digit form ``*#18*51*52#26#9##`` went out without a crash. The firmware reads
the year with ``atoi()`` into one byte, so the guard allows only the tested
spellings (``*52``, ``*52*Wh``, ``52#YY#M``, ``52#YY#M*Wh``) and refuses the rest,
the way ``is_who4_dimension_22_crash_form`` does (tests/test_who4_dimension22_guard.py,
whose layout this module follows: detector, command session, one-shot helper,
TCP and serial transports, single serialisation).
"""

from __future__ import annotations

import asyncio
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from OWNd.connection import OWNCommandSession, OWNGateway
from OWNd.connection.command_session import (
    DESTRUCTIVE_DIM52_REASON,
    DESTRUCTIVE_FRAME_REASON,
    destructive_frame_reason,
)
from OWNd.exceptions import OWNProtocolError
from OWNd.message import (
    OWNCommand,
    OWNEnergyCommand,
    OWNMessage,
    is_who18_dimension_52,
    is_who18_dimension_52_crash_form,
    is_who18_dimension_52_four_digit_year,
)
from OWNd.transport.serial import AsyncSerialTransport
from OWNd.transport.tcp import AsyncTcpTransport

CRASH_ROWS = ["*#18*51*52#2026#10##", "*#18*51*52#2026#10*100##"]  # the oracle's crash rows
SAFE_FORMS = ["*#18*51*52#26#9##", "*#18*51*52#26#9*100##", "*#18*51*52##", "*#18*51*52*100##"]
REFUSED_FORMS = CRASH_ROWS + [
    "*#18*71#0*52#2026#1##",  # actuator WHERE, single-digit month
    "*#18*5255*52#2026#12##",
    "*#18*51*52#02026#10##",  # atoi("02026") == 2026: the same one-byte overflow
    "*#18*51*52#256#10##",  # three digits, >= 256
    "*#18*51*52#999#10##",
    "*#018*51*52#2026#10##",  # leading zeros on WHO / DIMENSION (atoi reads 18 / 52)
    "*#18*51*052#2026#10##",
    "*#18*51*52#2026#010##",  # three-digit month
    "*#18*51*52#26#13##",  # month outside 1..12
    "*#18*51*52#26#0##",
    "*#18*51*52#2026#10*100*0##",  # more than one value field (a reply shape)
    "*#18*51*#52#2026#10*100##",  # dimension write
    "*#18*51*52#2026#10#1##",  # extra # parameter
    "*#18**52#2026#10##",  # empty WHERE
    "*#18*51*52#２０２６#10##",  # fullwidth digits
    "*#18*51*52#26#9*1００##",
    "*#18* 51*52#26#9##",  # whitespace
    "*#18*51*+52#26#9##",
    "*#18*51*52#2026#10##\n",  # trailing newline (``$`` would match before it; ``\Z`` does not)
]
UNRELATED = [
    "*#18*51*51#2026##",  # other dimension
    "*#18*51*511#10#2##",  # dimension 511, not 52
    "*#18*51*52*##",  # empty value: not a DIMENSION 52 request shape the regex admits? it is; see test below
    "*#4*2*22##",  # other WHO (its own guard)
    "*18*26*51##",  # a WHO 18 command, not a dimension request
    "*#1*14*#18*52##",  # mid-frame *#18* is a DIMENSION 18 write, not WHO 18
    "",
]


# ------------------------------------------------------------------ detector


@pytest.mark.parametrize("frame", REFUSED_FORMS)
def test_detector_flags_every_refused_form(frame: str) -> None:
    assert is_who18_dimension_52(frame) is True
    assert is_who18_dimension_52_crash_form(frame) is True
    assert is_who18_dimension_52_four_digit_year(frame) is True  # the alias


@pytest.mark.parametrize("frame", SAFE_FORMS + ["*#18*71#0*52#26#1##", "*#18*51*52#0#12*5##", "*#18*51*52#9#9##"])
def test_detector_recognises_safe_forms_but_does_not_refuse_them(frame: str) -> None:
    assert is_who18_dimension_52(frame) is True
    assert is_who18_dimension_52_crash_form(frame) is False


@pytest.mark.parametrize("frame", [f for f in UNRELATED if f != "*#18*51*52*##"])
def test_detector_leaves_other_frames_alone(frame: str) -> None:
    assert is_who18_dimension_52(frame) is False
    assert is_who18_dimension_52_crash_form(frame) is False


def test_an_empty_value_field_is_not_a_tested_form() -> None:
    assert is_who18_dimension_52("*#18*51*52*##") is True
    assert is_who18_dimension_52_crash_form("*#18*51*52*##") is True


@pytest.mark.parametrize("frame", CRASH_ROWS)
def test_refused_forms_still_parse(frame: str) -> None:
    """The parser stays permissive: refusing is the send layer's job."""
    parsed = OWNCommand.parse(frame)
    assert parsed is not None and parsed.is_valid is True
    assert is_who18_dimension_52_crash_form(parsed) is True


@pytest.mark.parametrize(
    "frame",
    [
        b"*#18*51*52#2026#10##",
        bytearray(b"*#18*51*52#2026#10##"),
        memoryview(b"*#18*51*52#2026#10##"),
        "*1*1*11##*#18*51*52#2026#10##",  # one chunk among others
        "*#18*51*52#26#9##*#18*51*52#2026#10##",  # a safe chunk does not excuse the crash chunk
    ],
)
def test_detector_decodes_buffers_and_inspects_every_chunk(frame: object) -> None:
    assert is_who18_dimension_52_crash_form(frame) is True


def test_builders_emit_only_safe_forms() -> None:
    for command in (
        OWNEnergyCommand.report_current_month_energy("51", 100, 2026, 9),
        OWNEnergyCommand.report_current_month_energy("51", 100),
    ):
        assert is_who18_dimension_52(command) is True
        assert is_who18_dimension_52_crash_form(command) is False


def test_shared_classifier_names_the_reason() -> None:
    assert destructive_frame_reason("*#18*51*52#2026#10##") == DESTRUCTIVE_DIM52_REASON
    assert destructive_frame_reason("*#4*2*22##") == DESTRUCTIVE_FRAME_REASON
    assert destructive_frame_reason("*#18*51*52#26#9##") is None
    assert destructive_frame_reason("*1*1*11##") is None
    assert "3488" in DESTRUCTIVE_DIM52_REASON and "four-digit year" in DESTRUCTIVE_DIM52_REASON


# ------------------------------------------------------------------ command session


class _Writer:
    def __init__(self) -> None:
        self.written: list[bytes] = []

    def write(self, data: bytes) -> None:
        self.written.append(data)

    async def drain(self) -> None:
        return None

    def close(self) -> None:
        return None

    async def wait_closed(self) -> None:
        return None


def _gateway() -> OWNGateway:
    return OWNGateway(
        {"address": "192.0.2.10", "port": 20000, "password": "12345", "modelName": "F461", "serialNumber": "x", "UDN": "x"}
    )


def _command_session() -> tuple[OWNCommandSession, _Writer]:
    session = OWNCommandSession(gateway=_gateway())
    session._stream_reader = asyncio.StreamReader()
    writer = _Writer()
    session._stream_writer = writer  # type: ignore[assignment]
    session._read_frame = AsyncMock(return_value="*#*1##")  # type: ignore[method-assign]
    return session, writer


@pytest.mark.asyncio
@pytest.mark.parametrize("frame", SAFE_FORMS)
async def test_command_session_sends_safe_forms(frame: str) -> None:
    session, writer = _command_session()
    assert await session.send(frame) is True
    assert session.last_error is None
    assert writer.written == [frame.encode()]


@pytest.mark.asyncio
@pytest.mark.parametrize("frame", REFUSED_FORMS)
async def test_command_session_refuses_raw_string(frame: str) -> None:
    session, writer = _command_session()
    assert await session.send(frame) is None
    assert isinstance(session.last_error, OWNProtocolError)
    assert session.last_error.reason == "destructive_frame"
    assert "four-digit year" in str(session.last_error)
    assert writer.written == []
    with pytest.raises(OWNProtocolError) as excinfo:
        await session.send(frame, raise_on_error=True)
    assert excinfo.value.reason == "destructive_frame"
    assert writer.written == []


@pytest.mark.asyncio
async def test_command_session_refuses_parsed_message() -> None:
    session, writer = _command_session()
    message = OWNMessage.parse("*#18*51*52#2026#10##")
    assert message is not None
    assert await session.send(message) is None
    assert isinstance(session.last_error, OWNProtocolError)
    assert writer.written == []


class _CountingCommand(OWNEnergyCommand):
    """Counts serialisations: the string checked must be the one parsed, raised and written."""

    def __init__(self, raw: str) -> None:
        super().__init__(raw)
        self.str_calls = 0

    def __str__(self) -> str:
        self.str_calls += 1
        return super().__str__()


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("raw", "expected", "writes"),
    [("*#18*51*52#26#9##", True, 1), ("*#18*51*52#2026#10##", None, 0)],
    ids=["safe", "refused"],
)
async def test_command_session_serialises_once(raw: str, expected: bool | None, writes: int) -> None:
    session, writer = _command_session()
    session._logger = MagicMock()
    message = _CountingCommand(raw)
    assert await session.send(message) is expected
    assert message.str_calls == 1
    assert writer.written == [raw.encode()] * writes
    if expected is None:
        assert isinstance(session.last_error, OWNProtocolError)
        assert session.last_error.frame == raw


@pytest.mark.asyncio
@pytest.mark.parametrize("frame", CRASH_ROWS)
async def test_command_session_refuses_before_connecting(frame: str) -> None:
    """Refused in the send layer: no socket is opened for a frame that is never written."""
    session = OWNCommandSession(gateway=_gateway())
    with patch.object(session, "connect", new=AsyncMock()) as connect:
        assert await session.send(frame) is None
        connect.assert_not_awaited()
    assert isinstance(session._last_error, OWNProtocolError)
    assert session._last_error.reason == "destructive_frame"


@pytest.mark.asyncio
@pytest.mark.parametrize("message", ["*#18*51*52#2026#10##", OWNCommand.parse("*#18*51*52#2026#10*100##")])
async def test_send_to_gateway_refuses_without_connecting(message: str | OWNMessage) -> None:
    gateway = _gateway()
    with patch.object(OWNCommandSession, "connect", new=AsyncMock()) as connect:
        with pytest.raises(OWNProtocolError) as excinfo:
            await OWNCommandSession.send_to_gateway(message, gateway, raise_on_error=True)
        assert excinfo.value.reason == "destructive_frame"
        assert await OWNCommandSession.send_to_gateway(message, gateway) is None
        connect.assert_not_awaited()


@pytest.mark.asyncio
async def test_send_to_gateway_still_connects_for_safe_forms() -> None:
    gateway = _gateway()
    with (
        patch.object(OWNCommandSession, "connect", new=AsyncMock()) as connect,
        patch.object(OWNCommandSession, "send", new=AsyncMock(return_value=True)) as send,
    ):
        assert await OWNCommandSession.send_to_gateway("*#18*51*52#26#9##", gateway) is True
        connect.assert_awaited_once()
        send.assert_awaited_once()


# ------------------------------------------------------------------ transports


def _serial_transport() -> tuple[AsyncSerialTransport, _Writer]:
    transport = AsyncSerialTransport(port="/dev/null")
    writer = _Writer()
    transport._writer = writer  # type: ignore[assignment]
    transport._connected = True
    return transport, writer


@pytest.mark.asyncio
@pytest.mark.parametrize("frame", CRASH_ROWS)
async def test_tcp_transport_refuses_through_its_command_session(frame: str) -> None:
    transport = AsyncTcpTransport(gateway=_gateway())
    session, writer = _command_session()
    transport._command_session = session
    assert await transport.send(frame) is None
    assert isinstance(session.last_error, OWNProtocolError)
    assert session.last_error.reason == "destructive_frame"
    assert writer.written == []
    with pytest.raises(OWNProtocolError):
        await transport.send(frame, raise_on_error=True)
    assert writer.written == []


@pytest.mark.asyncio
async def test_tcp_transport_sends_safe_form() -> None:
    transport = AsyncTcpTransport(gateway=_gateway())
    session, writer = _command_session()
    transport._command_session = session
    assert await transport.send("*#18*51*52#26#9##") is True
    assert writer.written == [b"*#18*51*52#26#9##"]


@pytest.mark.asyncio
@pytest.mark.parametrize("frame", CRASH_ROWS + ["*#18*51*52#2026#10", "*#18*51*52#02026#10"])
async def test_serial_transport_refuses(frame: str) -> None:
    """With and without the ``##`` the transport appends before checking; on d88eed3 both were written."""
    transport, writer = _serial_transport()
    transport._logger = MagicMock()
    assert await transport.send(frame) is None
    assert isinstance(transport._last_error, OWNProtocolError)
    assert transport._last_error.reason == "destructive_frame"
    assert "four-digit year" in str(transport._last_error)
    assert writer.written == []
    with pytest.raises(OWNProtocolError) as excinfo:
        await transport.send(frame, raise_on_error=True)
    assert excinfo.value.reason == "destructive_frame"
    assert writer.written == []


@pytest.mark.asyncio
async def test_serial_transport_refuses_built_message() -> None:
    transport, writer = _serial_transport()
    transport._logger = MagicMock()
    message = OWNCommand.parse("*#18*51*52#2026#10*100##")
    assert message is not None
    assert await transport.send(message) is None
    assert writer.written == []


@pytest.mark.asyncio
@pytest.mark.parametrize("frame", SAFE_FORMS)
async def test_serial_transport_sends_safe_forms(frame: str) -> None:
    transport, writer = _serial_transport()

    async def ack() -> None:
        await asyncio.sleep(0)
        assert transport._pending_future is not None
        transport._pending_future.set_result(True)

    task = asyncio.create_task(ack())
    assert await transport.send(frame, raise_on_error=True) is True
    await task
    assert transport.last_error is None
    assert writer.written == [frame.encode()]
