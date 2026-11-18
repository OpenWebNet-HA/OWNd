"""Extended tests for core transport abstraction (base, tcp, serial)."""
from __future__ import annotations

import asyncio
import errno
import os
import sys
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from serialx import SerialException

from OWNd.connection import OWNGateway
from OWNd.exceptions import OWNNackError, OWNProtocolError, OWNTimeoutError
from OWNd.message import OWNEvent, OWNGatewayCommand, OWNGatewayEvent, OWNMessage
from OWNd.profiles import Legrand3578Profile
from OWNd.transport.base import OWNTransport
from OWNd.transport.serial import AsyncSerialTransport
from OWNd.transport.tcp import AsyncTcpTransport


# ── 1. Base Transport ────────────────────────────────────────────────────────

class DummyTransport(OWNTransport):
    """Concrete subclass for testing OWNTransport base methods."""

    def __init__(self):
        super().__init__(log_id="[Dummy]")
        self._connected = False

    @property
    def is_connected(self) -> bool:
        return self._connected

    @property
    def transport_type(self) -> str:
        return "dummy"

    async def connect(self) -> bool:
        self._connected = True
        return True

    async def disconnect(self) -> None:
        self._connected = False

    async def send(
        self,
        message: str | OWNMessage,
        is_status_request: bool = False,
        *,
        raise_on_error: bool = False,
        timeout: float | None = None,
    ) -> list[OWNMessage | str] | bool | None:
        return True


def test_base_transport_listeners():
    """Test listener registration, notification, and unsubscription."""
    transport = DummyTransport()
    assert transport.transport_type == "dummy"
    assert transport.is_connected is False

    received_1 = []
    received_2 = []

    def sub1(msg):
        received_1.append(msg)

    def sub2(msg):
        if msg == "error":
            raise ValueError("Listener exploded")
        received_2.append(msg)

    unsub1 = transport.register_listener(sub1)
    unsub2 = transport.register_listener(sub2)

    # Broadcast message
    transport.notify_listeners("hello")
    assert received_1 == ["hello"]
    assert received_2 == ["hello"]

    # Broadcast causing an exception in one listener: should not crash transport
    transport.notify_listeners("error")
    assert received_1 == ["hello", "error"]
    assert received_2 == ["hello"]  # Errored, not appended

    # Unsubscribe sub1
    unsub1()
    transport.notify_listeners("after_unsub")
    assert received_1 == ["hello", "error"]  # Unsubscribed
    assert received_2 == ["hello", "after_unsub"]

    unsub2()


# ── 2. TCP Transport ─────────────────────────────────────────────────────────

@pytest.fixture
def dummy_gateway():
    return OWNGateway({"address": "127.0.0.1", "port": 20000, "password": "1234"})


@pytest.mark.asyncio
async def test_tcp_transport_connect_event_session_failure(dummy_gateway):
    """Test connect fails when Event session fails."""
    transport = AsyncTcpTransport(gateway=dummy_gateway)
    assert transport.transport_type == "tcp"

    with patch("OWNd.transport.tcp.OWNEventSession") as mock_event_cls:
        mock_event_sess = MagicMock()
        mock_event_sess.connect = AsyncMock(return_value={"Success": False, "Message": "auth_failed"})
        mock_event_sess.close = AsyncMock()
        mock_event_cls.return_value = mock_event_sess

        success = await transport.connect()
        assert success is False
        assert transport.is_connected is False


@pytest.mark.asyncio
async def test_tcp_transport_connect_command_session_failure(dummy_gateway):
    """Test connect closes event session and fails when Command session fails."""
    transport = AsyncTcpTransport(gateway=dummy_gateway)

    with (
        patch("OWNd.transport.tcp.OWNEventSession") as mock_event_cls,
        patch("OWNd.transport.tcp.OWNCommandSession") as mock_cmd_cls,
    ):
        mock_event_sess = MagicMock()
        mock_event_sess.connect = AsyncMock(return_value={"Success": True})
        mock_event_sess.close = AsyncMock()
        mock_event_cls.return_value = mock_event_sess

        mock_cmd_sess = MagicMock()
        mock_cmd_sess.connect = AsyncMock(return_value={"Success": False, "Message": "refused"})
        mock_cmd_sess.close = AsyncMock()
        mock_cmd_cls.return_value = mock_cmd_sess

        success = await transport.connect()
        assert success is False
        assert transport.is_connected is False
        mock_event_sess.close.assert_called_once()


@pytest.mark.asyncio
async def test_tcp_transport_full_lifecycle_and_listen_loop(dummy_gateway):
    """Test successful connect, message reading in listen loop, send, and disconnect."""
    transport = AsyncTcpTransport(gateway=dummy_gateway)

    with (
        patch("OWNd.transport.tcp.OWNEventSession") as mock_event_cls,
        patch("OWNd.transport.tcp.OWNCommandSession") as mock_cmd_cls,
    ):
        mock_event_sess = MagicMock()
        mock_event_sess.connect = AsyncMock(return_value={"Success": True})
        mock_event_sess.close = AsyncMock()
        mock_event_sess.is_connected = True

        event_queue = asyncio.Queue()
        await event_queue.put(OWNEvent.parse("*1*1*12##"))

        async def fake_get_next():
            return await event_queue.get()

        mock_event_sess.get_next = AsyncMock(side_effect=fake_get_next)
        mock_event_cls.return_value = mock_event_sess

        mock_cmd_sess = MagicMock()
        mock_cmd_sess.connect = AsyncMock(return_value={"Success": True})
        mock_cmd_sess.close = AsyncMock()
        mock_cmd_sess.is_connected = True
        mock_cmd_sess.send = AsyncMock(return_value=True)
        mock_cmd_cls.return_value = mock_cmd_sess

        received = []
        transport.register_listener(lambda msg: received.append(msg))

        success = await transport.connect()
        assert success is True
        assert transport.is_connected is True

        for _ in range(20):
            if len(received) == 1:
                break
            await asyncio.sleep(0.01)

        assert len(received) == 1
        assert str(received[0]) == "*1*1*12##"

        # Send command
        res = await transport.send("*1*1*12##", is_status_request=False)
        assert res is True
        mock_cmd_sess.send.assert_called_once_with(
            "*1*1*12##", False, raise_on_error=False
        )

        # Disconnect
        await transport.disconnect()
        assert transport.is_connected is False
        mock_event_sess.close.assert_called_once()
        mock_cmd_sess.close.assert_called_once()


@pytest.mark.asyncio
async def test_tcp_transport_listen_loop_cancelled(dummy_gateway):
    """Test _listen_loop breaks cleanly when CancelledError occurs."""
    transport = AsyncTcpTransport(gateway=dummy_gateway)
    mock_event_sess = MagicMock()
    mock_event_sess.get_next = AsyncMock(side_effect=asyncio.CancelledError())
    transport._event_session = mock_event_sess
    transport._stopping = False

    with pytest.raises(asyncio.CancelledError):
        await transport._listen_loop()


@pytest.mark.asyncio
async def test_tcp_transport_send_not_connected(dummy_gateway):
    """Test send raises RuntimeError when command session is not connected."""
    transport = AsyncTcpTransport(gateway=dummy_gateway)
    with pytest.raises(RuntimeError, match="TCP transport is not connected"):
        await transport.send("*1*1*12##")


@pytest.mark.asyncio
async def test_tcp_transport_send_with_timeout(dummy_gateway):
    """Test AsyncTcpTransport.send enforces explicit timeout."""
    transport = AsyncTcpTransport(gateway=dummy_gateway)
    mock_cmd = MagicMock()

    async def slow_send(*args, **kwargs):
        await asyncio.sleep(0.2)
        return True

    mock_cmd.send = AsyncMock(side_effect=slow_send)
    transport._command_session = mock_cmd

    assert await transport.send("*1*1*12##", timeout=0.5) is True
    assert await transport.send("*1*1*12##", timeout=0.01, raise_on_error=False) is None
    with pytest.raises(OWNTimeoutError, match="Timed out"):
        await transport.send("*1*1*12##", timeout=0.01, raise_on_error=True)


# ── 3. Serial Transport ───────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_serial_transport_connect_port_errors():
    """Test connect classifies SerialException, EBUSY, and generic OSError."""
    transport = AsyncSerialTransport(port="COM99", baudrate=19200, handshake=False)
    assert transport.transport_type == "serial"

    with patch(
        "OWNd.transport.serial.open_serial_connection",
        new=AsyncMock(side_effect=SerialException("Port vanished")),
    ):
        assert await transport.connect() is False
        assert transport.is_connected is False
        assert transport.last_error is not None
        assert transport.last_error.reason == "cannot_connect"

    with patch(
        "OWNd.transport.serial.open_serial_connection",
        new=AsyncMock(side_effect=OSError(errno.EBUSY, "Busy")),
    ):
        assert await transport.connect() is False
        assert transport.last_error is not None
        assert transport.last_error.reason == "port_busy"
        with pytest.raises(Exception) as exc_info:
            await transport.connect(raise_on_error=True)
        assert getattr(exc_info.value, "reason", None) == "port_busy"


@pytest.mark.asyncio
async def test_serial_transport_connect_with_mock_serialx():
    """Test connect opens serialx connection successfully without handshake."""
    mock_reader = AsyncMock()
    mock_writer = MagicMock()
    mock_writer.drain = AsyncMock()
    mock_writer.wait_closed = AsyncMock()
    mock_reader.readuntil.side_effect = asyncio.CancelledError()

    with patch(
        "OWNd.transport.serial.open_serial_connection",
        new=AsyncMock(return_value=(mock_reader, mock_writer)),
    ) as mock_open:
        transport = AsyncSerialTransport(port="COM5", baudrate=19200, handshake=False)
        success = await transport.connect()
        assert success is True
        assert transport.is_connected is True
        mock_open.assert_awaited_once_with(
            url="COM5", baudrate=19200, exclusive=True
        )
        await transport.disconnect()
        assert transport.is_connected is False


@pytest.mark.asyncio
async def test_serial_transport_connect_port_open_error():
    """Test connect handles generic OSError when opening serial port."""
    with patch(
        "OWNd.transport.serial.open_serial_connection",
        new=AsyncMock(side_effect=OSError("Port not found")),
    ):
        transport = AsyncSerialTransport(port="COM99", handshake=False)
        success = await transport.connect()
        assert success is False
        assert transport.is_connected is False
        assert transport.last_error is not None
        assert transport.last_error.reason == "cannot_connect"


@pytest.mark.asyncio
async def test_serial_transport_send_not_connected():
    """Test send raises RuntimeError when not connected."""
    transport = AsyncSerialTransport(port="COM1")
    with pytest.raises(RuntimeError, match="Serial transport is not connected"):
        await transport.send("*1*1*12##")


@pytest.mark.asyncio
async def test_serial_transport_demux_logic():
    """Test in-band serial demultiplexing: unsolicited vs query responses vs ACK/NACK."""
    transport = AsyncSerialTransport(port="COM1")
    transport._connected = True
    loop = asyncio.get_running_loop()

    received_unsolicited = []
    transport.register_listener(lambda msg: received_unsolicited.append(msg))

    # 1. Unsolicited frame (*1*1*12##) -> dispatched to listener
    transport._process_frame("*1*1*12##")
    assert len(received_unsolicited) == 1
    assert str(received_unsolicited[0]) == "*1*1*12##"

    # 2. Query response with no pending future -> dispatched to listener
    transport._process_frame("*#1*12##")
    assert len(received_unsolicited) == 2

    # 3. Query response with pending command future (intermediate frames then ACK)
    transport._pending_future = loop.create_future()
    transport._pending_frames = []

    # Intermediate frame
    transport._process_frame("*#1*12*1##")
    assert len(transport._pending_frames) == 1
    assert not transport._pending_future.done()

    # Signaling ACK
    transport._process_frame("*#*1##")
    assert transport._pending_future.done()
    assert transport._pending_future.result() == transport._pending_frames

    # 4. Query response with pending command future ending in NACK
    transport._pending_future = loop.create_future()
    transport._pending_frames = []
    transport._process_frame("*#*0##")
    assert transport._pending_future.done()
    assert transport._pending_future.result() is None

    # 5. Signaling ACK with no intermediate collected frames -> returns True
    transport._pending_future = loop.create_future()
    transport._pending_frames = []
    transport._process_frame("*#*1##")
    assert transport._pending_future.result() is True


@pytest.mark.asyncio
async def test_serial_transport_send_success_and_timeout():
    """Test send command writes frame and resolves future or times out."""
    transport = AsyncSerialTransport(port="COM1")
    mock_reader = AsyncMock()
    mock_writer = MagicMock()
    mock_writer.drain = AsyncMock()
    mock_writer.wait_closed = AsyncMock()

    transport._reader = mock_reader
    transport._writer = mock_writer
    transport._connected = True

    # Successful send: resolve future in background
    async def resolve_future():
        await asyncio.sleep(0.01)
        if transport._pending_future:
            transport._pending_future.set_result(True)

    asyncio.create_task(resolve_future())
    with patch("OWNd.transport.serial.COMMAND_TIMEOUT", 1.0):
        res = await transport.send("*1*1*12##")
        assert res is True
        mock_writer.write.assert_called_with(b"*1*1*12##")

    # Send without ##: should append ##
    async def resolve_future_again():
        await asyncio.sleep(0.01)
        if transport._pending_future:
            transport._pending_future.set_result(True)

    asyncio.create_task(resolve_future_again())
    with patch("OWNd.transport.serial.COMMAND_TIMEOUT", 1.0):
        res2 = await transport.send("*1*1*12")
        assert res2 is True
        mock_writer.write.assert_called_with(b"*1*1*12##")

    # Timeout send
    with patch("OWNd.transport.serial.COMMAND_TIMEOUT", 0.02):
        res_timeout = await transport.send("*1*1*12##")
        assert res_timeout is None


@pytest.mark.asyncio
async def test_serial_transport_read_loop_exceptions():
    """Test _read_loop handles blank frames, delimiter-only, exceptions, and clean cancellation."""
    transport = AsyncSerialTransport(port="COM1")
    mock_reader = AsyncMock()
    mock_reader.readuntil.side_effect = [
        b"  ##",
        b"##",
        b"*1*1*12##",
        OSError("Corrupt frame"),
    ]
    transport._reader = mock_reader
    transport._connected = True

    received = []
    transport.register_listener(lambda msg: received.append(msg))

    await transport._read_loop()
    assert len(received) == 1
    assert str(received[0]) == "*1*1*12##"
    assert transport.is_connected is False


@pytest.mark.asyncio
async def test_serial_transport_disconnect_with_writer_exception():
    """Test disconnect cleanly handles writer exceptions and clears state."""
    transport = AsyncSerialTransport(port="COM1")
    mock_writer = MagicMock()
    mock_writer.close = MagicMock()
    mock_writer.wait_closed = AsyncMock(side_effect=OSError("Socket error"))

    async def dummy_loop():
        try:
            await asyncio.sleep(100)
        except asyncio.CancelledError:
            pass

    task = asyncio.create_task(dummy_loop())
    transport._writer = mock_writer
    transport._reader = AsyncMock()
    transport._reader_task = task
    transport._connected = True

    await transport.disconnect()
    assert transport.is_connected is False
    assert transport._reader is None
    assert transport._writer is None


class _FakeAsyncSerialPair:
    """In-memory bidirectional stream helper for mock serialx handshake/reconnect tests."""

    def __init__(self, responder) -> None:
        self._queue: asyncio.Queue[bytes] = asyncio.Queue()
        self._responder = responder
        self.written: list[bytes] = []
        self.closed = False

    def push_rx(self, data: bytes) -> None:
        self._queue.put_nowait(data)

    async def readuntil(self, sep: bytes = b"##") -> bytes:
        del sep
        item = await self._queue.get()
        if isinstance(item, BaseException):
            raise item
        return item

    def write(self, data: bytes) -> None:
        self.written.append(data)
        for reply in self._responder(data.decode()):
            self.push_rx(reply.encode())

    async def drain(self) -> None:
        return None

    def close(self) -> None:
        self.closed = True

    async def wait_closed(self) -> None:
        return None


@pytest.mark.asyncio
async def test_serial_transport_zigbee_handshake_and_missing_60_ack():
    """Verify full 60 -> 16 -> 66 -> 12 handshake and failure when *13*60*## fails."""
    tapped: list[tuple[str, str]] = []
    states: list[bool] = []

    def respond_ok(tx: str) -> list[str]:
        if tx == "*13*60*##":
            return ["*#*1##"]
        if tx == "*#13**16##":
            return ["*#13**16*1*2*4##", "*#*1##"]
        if tx == "*13*66*##":
            return ["*#*1##"]
        if tx == "*#13**12##":
            return ["*#13**12*0*3*80*0*0*1*2*3##", "*#*1##"]
        return ["*#*0##"]

    pair = _FakeAsyncSerialPair(respond_ok)
    transport = AsyncSerialTransport(
        port="/dev/ttyUSB0",
        gateway=Legrand3578Profile(),
        on_state_change=states.append,
        raw_frame_callback=lambda d, r: tapped.append((d, r)),
    )
    assert transport.raw_frame_callback is not None

    with patch(
        "OWNd.transport.serial.open_serial_connection",
        new=AsyncMock(return_value=(pair, pair)),
    ):
        assert await transport.connect() is True

    assert transport.is_connected is True
    assert transport.firmware_version == "1.2.4"
    assert transport.firmware_version_tuple == (1, 2, 4)
    assert transport.ieee_address == "00:03:50:00:00:01:02:03"
    assert states == [True]
    assert ("tx", "*13*60*##") in tapped
    assert ("rx", "*#13**12*0*3*80*0*0*1*2*3##") in tapped
    await transport.disconnect()
    assert states == [True, False]

    # Missing *13*60*## ACK -> no_zigbee_interface (and state stays False)
    states_fail: list[bool] = []
    pair_fail = _FakeAsyncSerialPair(lambda tx: ["*#*0##"])
    transport_fail = AsyncSerialTransport(
        port="/dev/ttyUSB1",
        on_state_change=states_fail.append,
    )
    with patch(
        "OWNd.transport.serial.open_serial_connection",
        new=AsyncMock(return_value=(pair_fail, pair_fail)),
    ):
        assert await transport_fail.connect() is False
    assert transport_fail.last_error is not None
    assert transport_fail.last_error.reason == "no_zigbee_interface"
    assert states_fail == []

    # Same with raise_on_error=True
    pair_fail2 = _FakeAsyncSerialPair(lambda tx: ["*#*0##"])
    with patch(
        "OWNd.transport.serial.open_serial_connection",
        new=AsyncMock(return_value=(pair_fail2, pair_fail2)),
    ):
        with pytest.raises(OWNProtocolError) as exc_info:
            await transport_fail.connect(raise_on_error=True)
        assert exc_info.value.reason == "no_zigbee_interface"


@pytest.mark.asyncio
async def test_serial_transport_dim66_dim73_and_pending_matching():
    """Verify strict DIM 66 / DIM 73 / WHO 1 DIM 4 / command demux rules."""
    transport = AsyncSerialTransport(port="/dev/ttyUSB0", gateway=Legrand3578Profile())
    listener_msgs: list[object] = []
    transport.register_listener(listener_msgs.append)
    transport._connected = True

    def respond_dim66(tx: str) -> list[str]:
        if tx == "*#13**66*0##":
            return [
                "*#13*99999901#9*66*1*256##",  # wrong index -> listener
                "*#13*702053501#9*66*0*256##",  # matching index 0
                "*#*1##",
            ]
        if tx == "*#13**66#2##":
            return ["*#13*702053502#9*66#2*512##", "*#*1##"]
        if tx == "*#13**66*3##":
            return ["*#13**66*0##", "*#*1##"]
        if tx == "*#13*702053500#9*66##":
            return [
                "*#13*99999901#9*66*0*256##",  # different node -> listener
                "*#13*702053501#9*66*0*256##",  # same node unit 01 -> collected
                "*#*1##",
            ]
        if tx == "*#13**66##":
            return ["*#13**66*0##", "*#*1##"]
        if tx == "*#13**73#1##":
            return [
                "*#13**73#2*99##",  # wrong index -> listener
                "*#13**16*1*2*4##",  # wrong dim -> listener
                "*#13**73#1*42##",
                "*#*1##",
            ]
        if tx == "*#13**73##":
            return ["*#13**73*42##", "*#*1##"]
        if tx == "*#1*702053501#9*1##":
            return ["*#1*702053501#9*4*150*2##", "*#*1##"]
        if tx == "*#1*702053501#9*5##":
            return [
                "*#1*702053501#9*6*100##",  # wrong dimension -> listener
                "*#1*702053501#9*5*2##",
                "*#*1##",
            ]
        if tx == "*1*1*702053501#9##":
            return [
                "*#1*702053501#9*1*200*5##",  # concurrent dim during command -> listener
                "*#*1##",
            ]
        return ["*#*1##"]

    pair = _FakeAsyncSerialPair(respond_dim66)
    transport._reader = pair  # type: ignore[assignment]
    transport._writer = pair  # type: ignore[assignment]
    task = asyncio.create_task(transport._read_loop())

    try:
        res0 = await transport.send(OWNGatewayCommand.get_product_info(0), is_status_request=True)
        assert isinstance(res0, list) and len(res0) == 1
        assert isinstance(res0[0], OWNGatewayEvent)
        assert res0[0].zigbee_product_index == 0
        assert res0[0].zigbee_device_type == "On/Off Switch"

        res2 = await transport.send("*#13**66#2##", is_status_request=True)
        assert isinstance(res2, list) and len(res2) == 1
        assert isinstance(res2[0], OWNGatewayEvent)
        assert res2[0].zigbee_product_index == 2
        assert res2[0].zigbee_device_type == "Shutter Control"

        res3 = await transport.send(OWNGatewayCommand.get_product_info(3), is_status_request=True)
        assert isinstance(res3, list) and len(res3) == 1
        assert isinstance(res3[0], OWNGatewayEvent)
        assert res3[0].is_zigbee_product_unreachable is True

        res_u0 = await transport.send("*#13*702053500#9*66##", is_status_request=True)
        assert isinstance(res_u0, list) and len(res_u0) == 1
        assert res_u0[0].zigbee_device_id == "7020535"  # type: ignore[union-attr]

        res_bare66 = await transport.send("*#13**66##", is_status_request=True)
        assert isinstance(res_bare66, list) and len(res_bare66) == 1

        res_73p = await transport.send("*#13**73#1##", is_status_request=True)
        assert isinstance(res_73p, list) and len(res_73p) == 1

        res_73 = await transport.send("*#13**73##", is_status_request=True)
        assert isinstance(res_73, list) and len(res_73) == 1

        res_dim4 = await transport.send("*#1*702053501#9*1##", is_status_request=True)
        assert isinstance(res_dim4, list) and res_dim4[0].dimension == 4  # type: ignore[union-attr]

        res_dim5 = await transport.send("*#1*702053501#9*5##", is_status_request=True)
        assert isinstance(res_dim5, list) and res_dim5[0].dimension == 5  # type: ignore[union-attr]

        res_cmd = await transport.send("*1*1*702053501#9##")
        assert res_cmd is True

        assert len(listener_msgs) == 6
    finally:
        transport._stopping = True
        task.cancel()
        with pytest.raises(asyncio.CancelledError):
            await task


@pytest.mark.asyncio
async def test_serial_transport_busy_nack_and_retry():
    """Verify *#*6## + *#*0## BUSY NACK handling with busy_retry=False and True."""
    # 1. Default busy_retry=False -> records OWNNackError(reason='busy_nack', busy=True)
    pair = _FakeAsyncSerialPair(lambda tx: ["*#*6##", "*#*0##"])
    t_no_retry = AsyncSerialTransport("/dev/ttyUSB0", busy_retry=False)
    t_no_retry._connected = True
    t_no_retry._reader = pair  # type: ignore[assignment]
    t_no_retry._writer = pair  # type: ignore[assignment]
    reader_task = asyncio.create_task(t_no_retry._read_loop())
    try:
        assert await t_no_retry.send("*1*1*702053501#9##") is None
        assert isinstance(t_no_retry.last_error, OWNNackError)
        assert t_no_retry.last_error.busy is True
        assert t_no_retry.last_error.reason == "busy_nack"

        with pytest.raises(OWNNackError) as exc_info:
            await t_no_retry.send("*1*1*702053501#9##", raise_on_error=True)
        assert exc_info.value.busy is True
        assert exc_info.value.reason == "busy_nack"
    finally:
        t_no_retry._stopping = True
        reader_task.cancel()
        with pytest.raises(asyncio.CancelledError):
            await reader_task

    # 2. busy_retry=True -> recovers on 2nd attempt
    attempts = 0

    def busy_once(tx: str) -> list[str]:
        nonlocal attempts
        attempts += 1
        if attempts == 1:
            return ["*#*6##", "*#*0##"]
        return ["*#*1##"]

    pair2 = _FakeAsyncSerialPair(busy_once)
    t_retry = AsyncSerialTransport("/dev/ttyUSB0", busy_retry=True)
    t_retry._connected = True
    t_retry._reader = pair2  # type: ignore[assignment]
    t_retry._writer = pair2  # type: ignore[assignment]
    reader_task2 = asyncio.create_task(t_retry._read_loop())
    try:
        with patch("OWNd.transport.serial.BUSY_RETRY_DELAY", 0.001):
            assert await t_retry.send("*1*1*702053501#9##") is True
            assert attempts == 2
            assert t_retry.last_error is None
    finally:
        t_retry._stopping = True
        reader_task2.cancel()
        with pytest.raises(asyncio.CancelledError):
            await reader_task2

    # 3. busy_retry=True exhausting 3 attempts -> raises OWNNackError(busy=True)
    pair3 = _FakeAsyncSerialPair(lambda tx: ["*#*6##", "*#*0##"])
    t_exhaust = AsyncSerialTransport("/dev/ttyUSB0", busy_retry=True)
    t_exhaust._connected = True
    t_exhaust._reader = pair3  # type: ignore[assignment]
    t_exhaust._writer = pair3  # type: ignore[assignment]
    reader_task3 = asyncio.create_task(t_exhaust._read_loop())
    try:
        with patch("OWNd.transport.serial.BUSY_RETRY_DELAY", 0.001):
            with pytest.raises(OWNNackError) as exc_info3:
                await t_exhaust.send("*1*1*702053501#9##", raise_on_error=True)
            assert exc_info3.value.busy is True
            assert len(pair3.written) == 3
    finally:
        t_exhaust._stopping = True
        reader_task3.cancel()
        with pytest.raises(asyncio.CancelledError):
            await reader_task3

    # 4. Plain NACK does not retry even when busy_retry=True
    pair4 = _FakeAsyncSerialPair(lambda tx: ["*#*0##"])
    t_plain = AsyncSerialTransport("/dev/ttyUSB0", busy_retry=True)
    t_plain._connected = True
    t_plain._reader = pair4  # type: ignore[assignment]
    t_plain._writer = pair4  # type: ignore[assignment]
    reader_task4 = asyncio.create_task(t_plain._read_loop())
    try:
        assert await t_plain.send("*1*1*702053501#9##") is None
        assert isinstance(t_plain.last_error, OWNNackError)
        assert t_plain.last_error.busy is False
        assert t_plain.last_error.reason == "nack"
        assert len(pair4.written) == 1
        with pytest.raises(OWNNackError) as exc_info4:
            await t_plain.send("*1*1*702053501#9##", raise_on_error=True)
        assert exc_info4.value.busy is False
    finally:
        t_plain._stopping = True
        reader_task4.cancel()
        with pytest.raises(asyncio.CancelledError):
            await reader_task4


@pytest.mark.asyncio
async def test_serial_transport_firmware_quirks_and_supervisor_restore():
    """Verify fw <= 1.2.3 synthesized ACK, fw <= 1.2.0 RX-only WHO 2 swap, and DIM 67 restore."""
    tapped: list[tuple[str, str]] = []
    received: list[OWNMessage | str] = []

    transport = AsyncSerialTransport(
        "/dev/ttyUSB0",
        gateway=Legrand3578Profile(),
        raw_frame_callback=lambda d, r: tapped.append((d, r)),
    )
    transport.register_listener(received.append)
    transport._connected = True
    transport._firmware_tuple = (1, 2, 0)

    def respond_quirks(tx: str) -> list[str]:
        if tx == "*#2*702053501#9##":
            # fw <= 1.2.0 swaps 1 <-> 2 on RX, and fw <= 1.2.3 synthesizes missing ACK!
            return ["*2*1*702053501#9##"]
        if tx == "*2*1*702053501#9##":
            # TX is NOT swapped; RX 2 becomes 1
            return ["*2*2*702053501#9##", "*#*1##"]
        if tx == "*13*65*##":
            return ["*#*1##"]
        return ["*#*1##"]

    pair = _FakeAsyncSerialPair(respond_quirks)
    transport._reader = pair  # type: ignore[assignment]
    transport._writer = pair  # type: ignore[assignment]
    reader_task = asyncio.create_task(transport._read_loop())
    try:
        # 1. fw <= 1.2.3 synthesized ACK + fw <= 1.2.0 RX swap (1 -> 2)
        res = await transport.send("*#2*702053501#9##", is_status_request=True)
        assert res is True
        assert len(received) == 1
        assert str(received[0]) == "*2*2*702053501#9##"
        assert ("rx", "*2*1*702053501#9##") in tapped  # pre-rewrite raw wire token

        # 2. TX *2*1*... is sent verbatim (not swapped); RX *2*2*... swaps to *2*1*...
        assert await transport.send("*2*1*702053501#9##") is True
        assert b"*2*1*702053501#9##" in pair.written
        assert str(received[-1]) == "*2*1*702053501#9##"

        # 3. Scan network -> unsolicited DIM 67 restores supervisor idempotently
        assert await transport.send(OWNGatewayCommand.scan_network()) is True
        pair.push_rx(b"*#13**67*3##")
        await asyncio.sleep(0.05)
        assert b"*13*66*##" in pair.written
        sup_count = pair.written.count(b"*13*66*##")
        pair.push_rx(b"*#13**67*3##")
        await asyncio.sleep(0.05)
        assert pair.written.count(b"*13*66*##") == sup_count
    finally:
        transport._stopping = True
        reader_task.cancel()
        with pytest.raises(asyncio.CancelledError):
            await reader_task


@pytest.mark.asyncio
async def test_serial_transport_boot_noise_callbacks_errors_and_reconnect():
    """Verify boot noise stripping, callback safety, send errors, and reconnect loop."""
    states: list[bool] = []
    tapped: list[tuple[str, str]] = []

    def bad_state_cb(val: bool) -> None:
        states.append(val)
        raise RuntimeError("boom state")

    def bad_raw_cb(direction: str, raw: str) -> None:
        tapped.append((direction, raw))
        raise RuntimeError("boom raw")

    transport = AsyncSerialTransport(
        "/dev/ttyUSB0",
        handshake=False,
        reconnect=True,
        on_state_change=bad_state_cb,
        raw_frame_callback=bad_raw_cb,
    )
    transport.raw_frame_callback = bad_raw_cb

    pair1 = _FakeAsyncSerialPair(lambda tx: ["*#*1##"])
    pair2 = _FakeAsyncSerialPair(lambda tx: ["*#*1##"])

    with (
        patch(
            "OWNd.transport.serial.open_serial_connection",
            new=AsyncMock(side_effect=[(pair1, pair1), OSError("wait"), (pair2, pair2)]),
        ),
        patch("OWNd.transport.serial.RECONNECT_BACKOFF_STEPS", (0.005,)),
    ):
        assert await transport.connect() is True
        assert await transport.connect() is True  # already connected short-circuit
        assert states == [True]

        # Boot noise before '*' in _read_loop
        pair1.push_rx(b"BOOT_BANNER\r\n*1*1*702053501#9##")
        await asyncio.sleep(0.02)
        assert ("rx", "BOOT_BANNER") in tapped
        assert ("rx", "*1*1*702053501#9##") in tapped

        # Unexpected EOF triggers disconnect callback and reconnect loop
        pair1.push_rx(OSError("USB unplugged"))  # type: ignore[arg-type]
        for _ in range(50):
            if states == [True, False, True]:
                break
            await asyncio.sleep(0.01)
        assert states == [True, False, True]
        await transport.disconnect()
        assert states == [True, False, True, False]

    # Error paths on send(): destructive, invalid, timeout, drain failure, unexpected signaling, connection lost
    mock_writer = MagicMock()
    mock_writer.write = MagicMock()
    mock_writer.drain = AsyncMock()
    mock_writer.close = MagicMock()
    mock_writer.wait_closed = AsyncMock()
    transport._writer = mock_writer
    transport._connected = True
    transport._stopping = False

    # Destructive frame
    assert await transport.send("*#4*1*22##") is None
    assert transport.last_error is not None and transport.last_error.reason == "destructive_frame"
    with pytest.raises(OWNProtocolError):
        await transport.send("*#4*1*22##", raise_on_error=True)

    # Invalid frame
    assert await transport.send("not_valid") is None
    assert transport.last_error is not None and transport.last_error.reason == "invalid_frame"
    with pytest.raises(OWNProtocolError):
        await transport.send("not_valid", raise_on_error=True)

    # Timeout with raise_on_error=True
    with pytest.raises(OWNTimeoutError):
        await transport.send("*1*1*12##", timeout=0.01, raise_on_error=True)

    # Drain raises SerialException
    mock_writer.drain = AsyncMock(side_effect=SerialException("write failed"))
    assert await transport.send("*1*1*12##") is None
    assert transport.last_error is not None and transport.last_error.reason == "connection_lost"
    with pytest.raises(Exception) as exc_w:
        await transport.send("*1*1*12##", raise_on_error=True)
    assert getattr(exc_w.value, "reason", None) == "connection_lost"

    # Unexpected signaling response (e.g. *#1234##) while connected
    mock_writer.drain = AsyncMock()

    async def send_weird_signaling():
        await asyncio.sleep(0.01)
        transport._process_frame("*#1234##")

    asyncio.create_task(send_weird_signaling())
    with pytest.raises(OWNProtocolError):
        await transport.send("*1*1*12##", raise_on_error=True)

    # Connection dropped mid-send
    async def drop_mid_send():
        await asyncio.sleep(0.01)
        transport._connected = False
        if transport._pending_future and not transport._pending_future.done():
            transport._pending_future.set_result(None)

    asyncio.create_task(drop_mid_send())
    assert await transport.send("*1*1*12##") is None
    assert transport.last_error is not None and transport.last_error.reason == "connection_lost"

    # Malformed WHO 13 clock frame on wire handled safely
    assert transport._parse_frame("*#13**1*99*99*99*2026##") is None
    # Pending lost connection before lock acquisition branch
    transport._connected = True
    transport._writer = mock_writer
    orig_acquire = transport._command_lock.acquire

    async def drop_on_acquire():
        await orig_acquire()
        transport._connected = False
        return True

    with patch.object(transport._command_lock, "acquire", side_effect=drop_on_acquire):
        assert await transport.send("*1*1*12##", raise_on_error=False) is None
        assert transport.last_error is not None and transport.last_error.reason == "connection_lost"
        transport._connected = True
        with pytest.raises(Exception) as exc_lost:
            await transport.send("*1*1*12##", raise_on_error=True)
        assert getattr(exc_lost.value, "reason", None) == "connection_lost"

    # Handshake succeeding even when FW / IEEE queries return empty or non-matching replies
    pair_minimal = _FakeAsyncSerialPair(
        lambda tx: ["*#13**15*4##", "*#*1##"] if tx in ("*#13**16##", "*#13**12##") else ["*#*1##"]
    )
    t_minimal = AsyncSerialTransport("/dev/ttyUSB4", reconnect=False)
    with patch(
        "OWNd.transport.serial.open_serial_connection",
        new=AsyncMock(return_value=(pair_minimal, pair_minimal)),
    ):
        assert await t_minimal.connect() is True
    assert t_minimal.firmware_version is None
    assert t_minimal.ieee_address is None
    await t_minimal.disconnect()

    # _reconnect_loop cancelled via disconnect() while sleeping
    t_rec_cancel = AsyncSerialTransport("/dev/ttyUSB5", handshake=False, reconnect=True)
    t_rec_cancel._stopping = False
    t_rec_cancel._auto_reconnect_enabled = True
    with patch("OWNd.transport.serial.RECONNECT_BACKOFF_STEPS", (5.0,)):
        t_rec_cancel._reconnect_task = asyncio.create_task(t_rec_cancel._reconnect_loop())
        await asyncio.sleep(0.01)
        await t_rec_cancel.disconnect()

    # _restore_supervisor when disconnected is a no-op
    t_rec_cancel._connected = False
    await t_rec_cancel._restore_supervisor()

    # _matches_pending_request bare *#13**66## against non-empty where reply (line 409)
    assert t_rec_cancel._matches_pending_request(
        OWNMessage.parse("*#13**66##"), OWNMessage.parse("*#13*702053501#9*66*256##")
    ) is False

    # Disconnect cancels active reconnect_task and restore_task
    transport._reconnect_task = asyncio.create_task(asyncio.sleep(10))
    transport._supervisor_restore_task = asyncio.create_task(asyncio.sleep(10))
    await transport.disconnect()

    # _reconnect_loop exits cleanly if stopped after sleep
    transport._stopping = False
    transport._auto_reconnect_enabled = True

    async def stop_during_sleep(_delay: float) -> None:
        transport._stopping = True

    with (
        patch("OWNd.transport.serial.RECONNECT_BACKOFF_STEPS", (0.001,)),
        patch("asyncio.sleep", side_effect=stop_during_sleep),
    ):
        await transport._reconnect_loop()

    # Handshake cancellation and _restore_supervisor exception safety
    pair_cancel = _FakeAsyncSerialPair(lambda tx: [])
    t_cancel = AsyncSerialTransport("/dev/ttyUSB2", handshake=True)
    with patch(
        "OWNd.transport.serial.open_serial_connection",
        new=AsyncMock(return_value=(pair_cancel, pair_cancel)),
    ):
        connect_task = asyncio.create_task(t_cancel.connect())
        await asyncio.sleep(0.01)
        connect_task.cancel()
        with pytest.raises(asyncio.CancelledError):
            await connect_task

    t_cancel._connected = True
    with patch.object(t_cancel, "send", side_effect=RuntimeError("restore err")):
        await t_cancel._restore_supervisor()

    # Connect cancels stale reconnect_task; _matches_status_reply_quirk & _matches_pending_request edges
    t_edge = AsyncSerialTransport("/dev/ttyUSB3", handshake=False)
    t_edge._reconnect_task = asyncio.create_task(asyncio.sleep(10))
    with patch(
        "OWNd.transport.serial.open_serial_connection",
        new=AsyncMock(side_effect=OSError("no device")),
    ):
        assert await t_edge.connect() is False
    assert t_edge._matches_status_reply_quirk(None, None) is False
    assert t_edge._matches_status_reply_quirk(
        OWNMessage.parse("*#13**16##"), OWNMessage.parse("*1*1*12##")
    ) is False
    req66 = OWNGatewayCommand.get_product_info(0)
    assert t_edge._matches_pending_request(req66, OWNMessage.parse("*#13**16*1*2*3##")) is False
    assert t_edge._matches_pending_request(
        OWNMessage.parse("*#13**73##"), OWNMessage.parse("*#13**16*1*2*3##")
    ) is False
    assert t_edge._matches_pending_request(
        OWNMessage.parse("*#1*12*1##"), OWNMessage.parse("*#1*99*1*150*0##")
    ) is False
    # Stray signaling while no pending request
    t_edge._process_frame("*#*1##")


@pytest.mark.skipif(sys.platform == "win32", reason="POSIX pty required")
@pytest.mark.asyncio
async def test_serial_transport_real_serialx_pty_handshake_and_ebusy():
    """Exercise real serialx over POSIX pty: full handshake, DIM 66 discovery, and EBUSY."""
    import pty
    import tty

    master_fd, slave_fd = pty.openpty()
    tty.setraw(master_fd)
    tty.setraw(slave_fd)
    slave_path = os.ttyname(slave_fd)

    loop = asyncio.get_running_loop()
    stop_event = asyncio.Event()

    async def pty_emulator() -> None:
        buf = bytearray()
        while not stop_event.is_set():
            try:
                chunk = await loop.run_in_executor(None, os.read, master_fd, 256)
            except OSError:
                break
            if not chunk:
                break
            buf.extend(chunk)
            while b"##" in buf:
                idx = buf.index(b"##")
                frame = bytes(buf[: idx + 2]).decode()
                del buf[: idx + 2]
                if frame == "*13*60*##":
                    os.write(master_fd, b"*#*1##")
                elif frame == "*#13**16##":
                    os.write(master_fd, b"*#13**16*1*2*4##*#*1##")
                elif frame == "*13*66*##":
                    os.write(master_fd, b"*#*1##")
                elif frame == "*#13**12##":
                    os.write(master_fd, b"*#13**12*0*3*80*0*0*1*2*3##*#*1##")
                elif frame == "*#13**66*0##":
                    os.write(master_fd, b"*#13*702053501#9*66*0*256##*#*1##")
                elif frame == "*1*1*702053501#9##":
                    os.write(master_fd, b"*#*1##")

    emu_task = asyncio.create_task(pty_emulator())
    transport = AsyncSerialTransport(slave_path, baudrate=19200, reconnect=False)
    contender = AsyncSerialTransport(slave_path, baudrate=19200, reconnect=False)
    try:
        assert await transport.connect(raise_on_error=True) is True
        assert transport.ieee_address == "00:03:50:00:00:01:02:03"
        assert transport.firmware_version_tuple == (1, 2, 4)

        # Exclusive lock check via second serialx connection -> EBUSY (port_busy)
        assert await contender.connect() is False
        assert contender.last_error is not None
        assert contender.last_error.reason == "port_busy"

        # Real DIM 66 discovery + lighting command over pty
        prod = await transport.send(
            OWNGatewayCommand.get_product_info(0), is_status_request=True
        )
        assert isinstance(prod, list) and len(prod) == 1
        assert isinstance(prod[0], OWNGatewayEvent)
        assert prod[0].zigbee_device_type == "On/Off Switch"
        assert await transport.send("*1*1*702053501#9##") is True
    finally:
        stop_event.set()
        await transport.disconnect()
        await contender.disconnect()
        for fd in (master_fd, slave_fd):
            try:
                os.close(fd)
            except OSError:
                pass
        emu_task.cancel()
        with pytest.raises(asyncio.CancelledError):
            await emu_task


@pytest.mark.skipif(sys.platform == "win32", reason="POSIX runtime serialx test")
@pytest.mark.asyncio
async def test_serial_transport_real_serialx_socket_uri():
    """Exercise real serialx over socket://127.0.0.1:<port>."""

    async def handle_client(
        reader: asyncio.StreamReader, writer: asyncio.StreamWriter
    ) -> None:
        try:
            while True:
                data = await reader.readuntil(b"##")
                frame = data.decode()
                if frame == "*13*60*##":
                    writer.write(b"*#*1##")
                elif frame == "*#13**16##":
                    writer.write(b"*#13**16*1*2*4##*#*1##")
                elif frame == "*13*66*##":
                    writer.write(b"*#*1##")
                elif frame == "*#13**12##":
                    writer.write(b"*#13**12*0*3*80*0*0*1*2*3##*#*1##")
                elif frame == "*1*1*702053501#9##":
                    writer.write(b"*#*1##")
                await writer.drain()
        except (asyncio.IncompleteReadError, ConnectionError):
            pass
        finally:
            writer.close()

    server = await asyncio.start_server(handle_client, "127.0.0.1", 0)
    port = server.sockets[0].getsockname()[1]
    transport = AsyncSerialTransport(
        f"socket://127.0.0.1:{port}", baudrate=19200, reconnect=False
    )
    try:
        assert await transport.connect() is True
        assert transport.ieee_address == "00:03:50:00:00:01:02:03"
        assert await transport.send("*1*1*702053501#9##") is True
    finally:
        await transport.disconnect()
        server.close()
        await server.wait_closed()
