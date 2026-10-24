"""WHO 4 DIMENSION 22 never leaves OWNd.

``*#4*ZONE*22##`` kills the gateway's thermoregulation daemon (bt_termo) and
reboots an F461 about 3 minutes later (firmware oracle crash_frames; live F461
2.0.11). The frames below are test inputs only: every send path must refuse
them before anything is written.
"""

from __future__ import annotations

import asyncio
import logging
from collections.abc import Callable
from unittest.mock import AsyncMock, patch

import pytest

from OWNd.connection import OWNCommandSession, OWNGateway
from OWNd.exceptions import OWNProtocolError
from OWNd.message import (
    OWNAutomationCommand,
    OWNCommand,
    OWNHeatingCommand,
    OWNLightingCommand,
    OWNMessage,
    OWNSoundCommand,
    OWNSoundDiffusionCommand,
    is_who4_dimension_22,
)
from OWNd.transport.serial import AsyncSerialTransport
from OWNd.transport.tcp import AsyncTcpTransport

DIMENSION_22_FRAMES = (
    "*#4*2*22##",
    "*#4*#0*22##",
    "*#4*#1*22##",
    "*#4*2#1*22##",
    "*#4**22##",
    "*#4*2*22#1##",
    "*#4*2*#22*1##",
    "*#4*2*22*1##",
    "*#04*2*022##",
    "*1*1*11##*#4*2*22##",
    # Published split-unit forms (WHO 4 specification, pp. 66-68).
    "*#4*3#2#1*22##",
    "*#4*3#2#1*#22*0***##",
    "*#4*45#1*#22*3**1*1##",
    # Tokens the gateway's atoi() still reads as 4 / 22: whitespace, sign,
    # missing terminator (the serial transport appends ``##``).
    "*#4*2*22 ",
    "*#4*2*22 ##",
    "*#4*2* 22##",
    "*#4*2*+22##",
    "*# 4*2*22##",
    "*#+4*2*22##",
    "*#4*2*22",
)

# Zone 22, other dimensions, dimension 22 of other WHOs, and mid-frame
# ``*#4*`` tokens (WHERE ``#4`` or DIMENSION ``#4``) stay sendable.
SAFE_FRAMES = (
    "*#4*22##",
    "*#4*22*0##",
    "*#4*#22*14##",
    "*#4*2*20##",
    "*#4*2*220##",
    "*#4*2*0*0220##",
    "*#4*2*2 2##",
    "*#4*2*-22##",
    "*#44*2*22##",
    "*#13**22##",
    "*#1*22*1##",
    "*4*303*22##",
    # WHERE ``#4`` (group 4 / central-unit zone 4) with a value of 22.
    "*#2*#4*#11#001*22##",
    "*#1*#4*#2*22*0*0##",
    "*#1*#4*#12*22*100*50##",
    "*#16*#4*#1*22##",
    "*#22*#4*#1*22##",
    "*#22*#4*#19*22##",
    "*#4*#4*#30*22*10*2026##",
    "*#4*#4*#31*22*30##",
    "*#4*#4*#32*22*00##",
    # DIMENSION ``#4`` write whose second value is 22.
    "*#1*14*#4*1*22##",
    # Other subsystems carrying a 22.
    "*#1004*2*22##",
    "*#22*3#1#1*1##",
    # Single-``#`` concatenation: one chunk starting with ``*1*``; the frame
    # validation of every send path refuses it as invalid instead.
    "*1*1*11#*#4*2*22##",
)

# Builders whose WHERE is group / central-unit zone ``#4`` and whose first
# value is 22: the unanchored detector used to refuse all of them.
WHERE_HASH_4_BUILDERS = (
    (lambda: OWNAutomationCommand.set_shutter_level("#4", 22), "*#2*#4*#11#001*22##"),
    (lambda: OWNLightingCommand.set_variable_timer("#4", 22, 0, 0), "*#1*#4*#2*22*0*0##"),
    (
        lambda: OWNLightingCommand.set_hsv_color("#4", 22, 100, 50),
        "*#1*#4*#12*22*100*50##",
    ),
    (lambda: OWNSoundCommand.set_volume("#4", 22), "*#16*#4*#1*22##"),
    (lambda: OWNSoundDiffusionCommand.set_volume("#4", 22), "*#22*#4*#1*22##"),
    (lambda: OWNSoundDiffusionCommand.set_preset("#4", 22), "*#22*#4*#6*22##"),
    (
        lambda: OWNHeatingCommand.set_holiday_end_date("#4", 22, 10, 2026),
        "*#4*#4*#30*22*10*2026##",
    ),
    (lambda: OWNHeatingCommand.set_holiday_end_time("#4", 22, 30), "*#4*#4*#31*22*30##"),
    (
        lambda: OWNHeatingCommand.set_timed_manual_end_time("#4", 22, 0),
        "*#4*#4*#32*22*00##",
    ),
)


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


def _command_session() -> tuple[OWNCommandSession, _Writer]:
    gateway = OWNGateway({"address": "192.0.2.1", "port": 20000, "password": "12345"})
    session = OWNCommandSession(gateway=gateway)
    session._stream_reader = asyncio.StreamReader()
    writer = _Writer()
    session._stream_writer = writer  # type: ignore[assignment]
    session._read_frame = AsyncMock(return_value="*#*1##")  # type: ignore[method-assign]
    return session, writer


@pytest.mark.parametrize("frame", DIMENSION_22_FRAMES)
def test_detector_flags_every_dimension_22_form(frame: str) -> None:
    assert is_who4_dimension_22(frame) is True


@pytest.mark.parametrize("frame", SAFE_FRAMES)
def test_detector_leaves_other_frames_alone(frame: str) -> None:
    assert is_who4_dimension_22(frame) is False


@pytest.mark.parametrize(
    "frame",
    [b"*#4*2*22##", bytearray(b"*#4*2*22##"), memoryview(b"*#4*2*22##")],
    ids=["bytes", "bytearray", "memoryview"],
)
def test_detector_decodes_buffers(frame: object) -> None:
    assert is_who4_dimension_22(frame) is True
    assert is_who4_dimension_22(b"*#4*#4*#30*22*10*2026##") is False


@pytest.mark.parametrize(
    "build, expected",
    WHERE_HASH_4_BUILDERS,
    ids=[expected for _, expected in WHERE_HASH_4_BUILDERS],
)
def test_detector_leaves_where_hash_4_builders_alone(
    build: Callable[[], OWNCommand], expected: str
) -> None:
    command = build()
    assert str(command) == expected
    assert command.is_valid
    assert is_who4_dimension_22(command) is False
    assert is_who4_dimension_22(str(command)) is False


@pytest.mark.parametrize(
    "build, expected",
    WHERE_HASH_4_BUILDERS,
    ids=[expected for _, expected in WHERE_HASH_4_BUILDERS],
)
@pytest.mark.asyncio
async def test_command_session_still_sends_where_hash_4_builders(
    build: Callable[[], OWNCommand], expected: str
) -> None:
    session, writer = _command_session()

    assert await session.send(build()) is True
    assert writer.written == [expected.encode()]


@pytest.mark.parametrize("frame", DIMENSION_22_FRAMES)
@pytest.mark.asyncio
async def test_command_session_refuses_raw_string(frame: str) -> None:
    session, writer = _command_session()

    assert await session.send(frame) is None
    assert writer.written == []
    assert isinstance(session._last_error, OWNProtocolError)
    assert session._last_error.reason == "destructive_frame"

    with pytest.raises(OWNProtocolError) as excinfo:
        await session.send(frame, is_status_request=True, raise_on_error=True)
    assert excinfo.value.reason == "destructive_frame"
    assert writer.written == []


@pytest.mark.parametrize(
    "message",
    [
        OWNCommand.parse("*#4*2*22##"),
        OWNMessage.parse("*#4*#0*22##"),
        OWNHeatingCommand("*#4*2#1*22##"),
    ],
    ids=["OWNCommand.parse", "OWNMessage.parse", "OWNHeatingCommand"],
)
@pytest.mark.asyncio
async def test_command_session_refuses_parsed_and_built_messages(message: OWNMessage) -> None:
    # The parser still reads the frame (it may appear on the bus); only sending is refused.
    assert isinstance(message, OWNHeatingCommand)
    assert message.is_valid
    session, writer = _command_session()

    with pytest.raises(OWNProtocolError, match="dimension 22"):
        await session.send(message, raise_on_error=True)
    assert writer.written == []


class _CountingCommand(OWNHeatingCommand):
    """Counts serialisations: the string checked must be the one written and logged."""

    def __init__(self, raw: str) -> None:
        super().__init__(raw)
        self.str_calls = 0

    def __str__(self) -> str:
        self.str_calls += 1
        return super().__str__()


@pytest.mark.parametrize(
    "raw, reply, expected, writes",
    [
        ("*#4*22##", "*#*1##", True, 1),
        ("*#4*22##", "*#*0##", None, 2),  # a NACKed command is retried once
        ("*#4*2*22##", "*#*1##", None, 0),
    ],
    ids=["ack", "nack", "destructive"],
)
@pytest.mark.asyncio
async def test_command_session_serialises_once(
    raw: str,
    reply: str,
    expected: bool | None,
    writes: int,
    caplog: pytest.LogCaptureFixture,
) -> None:
    session, writer = _command_session()
    session._read_frame = AsyncMock(return_value=reply)  # type: ignore[method-assign]
    message = _CountingCommand(raw)

    with caplog.at_level(logging.DEBUG):
        assert await session.send(message) is expected
    assert message.str_calls == 1
    assert writer.written == [raw.encode()] * writes
    assert raw in caplog.text


@pytest.mark.asyncio
async def test_command_session_refuses_before_reconnecting() -> None:
    session, _ = _command_session()
    session._stream_writer = None
    session._stream_reader = None
    with patch.object(session, "connect", new_callable=AsyncMock) as connect:
        assert await session.send("*#4*2*22##") is None
    connect.assert_not_called()


@pytest.mark.parametrize(
    "message",
    ["*#4*2*22##", OWNHeatingCommand("*#4*3#2#1*22##")],
    ids=["str", "OWNHeatingCommand"],
)
@pytest.mark.asyncio
async def test_send_to_gateway_refuses_without_connecting(
    message: str | OWNMessage, caplog: pytest.LogCaptureFixture
) -> None:
    # Fail fast: no socket, no handshake, no gateway command slot, no
    # 5-attempt backoff on an unreachable host.
    gateway = OWNGateway({"address": "192.0.2.1", "port": 20000, "password": "12345"})

    with (
        patch.object(OWNCommandSession, "connect", new_callable=AsyncMock) as connect,
        patch.object(OWNCommandSession, "_locked_send", new_callable=AsyncMock) as send,
        caplog.at_level(logging.ERROR),
    ):
        with pytest.raises(OWNProtocolError) as excinfo:
            await OWNCommandSession.send_to_gateway(message, gateway, raise_on_error=True)
        assert excinfo.value.reason == "destructive_frame"
        assert excinfo.value.frame == str(message)
        assert await OWNCommandSession.send_to_gateway(message, gateway) is None
    connect.assert_not_called()
    send.assert_not_called()
    assert caplog.text.count("bt_termo") == 2


@pytest.mark.asyncio
async def test_send_to_gateway_still_connects_for_other_frames() -> None:
    gateway = OWNGateway({"address": "192.0.2.1", "port": 20000, "password": "12345"})

    with (
        patch.object(
            OWNCommandSession,
            "connect",
            new_callable=AsyncMock,
            return_value={"Success": True},
        ) as connect,
        patch.object(
            OWNCommandSession, "_locked_send", new_callable=AsyncMock, return_value=True
        ) as send,
    ):
        assert await OWNCommandSession.send_to_gateway("*#4*22##", gateway) is True
    connect.assert_awaited_once()
    send.assert_awaited_once_with("*#4*22##", False, raise_on_error=False)


@pytest.mark.parametrize("frame", SAFE_FRAMES[:3])
@pytest.mark.asyncio
async def test_command_session_still_sends_zone_22(frame: str) -> None:
    session, writer = _command_session()

    assert await session.send(frame, is_status_request=True) is True
    assert writer.written == [frame.encode()]


def _serial_transport() -> tuple[AsyncSerialTransport, _Writer]:
    transport = AsyncSerialTransport(port="/dev/null")
    writer = _Writer()
    transport._writer = writer  # type: ignore[assignment]
    transport._connected = True
    return transport, writer


@pytest.mark.asyncio
async def test_tcp_transport_refuses_through_its_command_session(
    caplog: pytest.LogCaptureFixture,
) -> None:
    gateway = OWNGateway({"address": "192.0.2.1", "port": 20000, "password": "12345"})
    transport = AsyncTcpTransport(gateway=gateway)
    assert transport.last_error is None
    session, writer = _command_session()
    transport._command_session = session

    with caplog.at_level(logging.ERROR):
        assert await transport.send("*#4*2*22##") is None
    assert writer.written == []
    assert transport.last_error is session.last_error
    assert isinstance(transport.last_error, OWNProtocolError)
    assert transport.last_error.reason == "destructive_frame"
    assert "bt_termo" in caplog.text

    # The keyword reaches the command session: same contract on both transports.
    with pytest.raises(OWNProtocolError) as excinfo:
        await transport.send("*#4*2*22##", raise_on_error=True)
    assert excinfo.value.reason == "destructive_frame"
    assert writer.written == []


@pytest.mark.parametrize("frame", DIMENSION_22_FRAMES)
@pytest.mark.asyncio
async def test_serial_transport_refuses(
    frame: str, caplog: pytest.LogCaptureFixture
) -> None:
    transport, writer = _serial_transport()

    # Default: like AsyncTcpTransport, log at ERROR, keep the error, return None.
    with caplog.at_level(logging.ERROR):
        assert await transport.send(frame) is None
    assert writer.written == []
    assert transport._pending_future is None
    assert isinstance(transport.last_error, OWNProtocolError)
    assert transport.last_error.reason == "destructive_frame"
    assert transport.last_error.frame.endswith("##")
    assert "bt_termo" in caplog.text

    with pytest.raises(OWNProtocolError) as excinfo:
        await transport.send(frame, raise_on_error=True)
    assert excinfo.value.reason == "destructive_frame"
    assert excinfo.value.frame == transport.last_error.frame
    assert writer.written == []
    assert transport._pending_future is None


@pytest.mark.asyncio
async def test_serial_transport_refuses_built_message() -> None:
    transport, writer = _serial_transport()

    with pytest.raises(OWNProtocolError, match="dimension 22"):
        await transport.send(OWNHeatingCommand("*#4*2#1*22##"), raise_on_error=True)
    assert writer.written == []


@pytest.mark.parametrize(
    "frame",
    ["*1*1*11#*#4*2*22##", "*#*1##", "not a frame", ""],
    ids=["single-hash-concatenation", "signaling", "text", "empty"],
)
@pytest.mark.asyncio
async def test_serial_transport_refuses_invalid_frames(
    frame: str, caplog: pytest.LogCaptureFixture
) -> None:
    # Like OWNCommandSession._locked_send: only a valid, non-signaling frame is written.
    transport, writer = _serial_transport()

    with caplog.at_level(logging.ERROR):
        assert await transport.send(frame) is None
    assert writer.written == []
    assert transport._pending_future is None
    assert isinstance(transport.last_error, OWNProtocolError)
    assert transport.last_error.reason == "invalid_frame"
    assert "invalid OpenWebNet frame" in caplog.text

    with pytest.raises(OWNProtocolError) as excinfo:
        await transport.send(frame, raise_on_error=True)
    assert excinfo.value.reason == "invalid_frame"
    assert writer.written == []


@pytest.mark.asyncio
async def test_serial_transport_not_connected_comes_first() -> None:
    # Same ordering as AsyncTcpTransport: an unconnected transport is a
    # RuntimeError whatever the frame; the frame checks run on a connected one.
    transport = AsyncSerialTransport(port="/dev/null")
    with pytest.raises(RuntimeError, match="not connected"):
        await transport.send("*#4*2*22##", raise_on_error=True)
    assert transport.last_error is None


@pytest.mark.asyncio
async def test_serial_transport_still_sends_safe_frames() -> None:
    transport, writer = _serial_transport()
    assert transport.last_error is None

    # The third frame has no terminator: the serial transport appends it.
    for frame in ("*#4*22##", "*#1*#4*#2*22*0*0##", "*#4*#4*#30*22*10*2026"):

        async def ack() -> None:
            await asyncio.sleep(0)
            assert transport._pending_future is not None
            transport._pending_future.set_result(True)

        task = asyncio.create_task(ack())
        assert await transport.send(frame, raise_on_error=True) is True
        await task
        assert transport.last_error is None
    assert writer.written == [b"*#4*22##", b"*#1*#4*#2*22*0*0##", b"*#4*#4*#30*22*10*2026##"]
