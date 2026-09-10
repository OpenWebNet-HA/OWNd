"""Extended tests for core transport abstraction (base, tcp, serial)."""
import asyncio
from unittest.mock import AsyncMock, MagicMock, patch
import pytest

from OWNd.connection import OWNGateway
from OWNd.message import OWNEvent
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

    async def send(self, message: str, is_status_request: bool = False):
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
        mock_cmd_sess.send.assert_called_once_with("*1*1*12##", False)

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


# ── 3. Serial Transport ───────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_serial_transport_connect_import_or_port_error():
    """Test connect fails gracefully when serial port cannot be opened."""
    transport = AsyncSerialTransport(port="COM99", baudrate=19200)
    assert transport.transport_type == "serial"

    with patch.dict("sys.modules", {"serial_asyncio": None}):
        success = await transport.connect()
        assert success is False
        assert transport.is_connected is False


@pytest.mark.asyncio
async def test_serial_transport_connect_with_mock_serial_asyncio():
    """Test connect opens serial_asyncio connection successfully."""
    mock_serial_mod = MagicMock()
    mock_reader = AsyncMock()
    mock_writer = MagicMock()
    mock_writer.drain = AsyncMock()
    mock_writer.wait_closed = AsyncMock()
    mock_serial_mod.open_serial_connection = AsyncMock(return_value=(mock_reader, mock_writer))

    with patch.dict("sys.modules", {"serial_asyncio": mock_serial_mod}):
        transport = AsyncSerialTransport(port="COM5", baudrate=19200)
        mock_reader.readuntil.side_effect = asyncio.CancelledError()
        success = await transport.connect()
        assert success is True
        assert transport.is_connected is True
        await transport.disconnect()
        assert transport.is_connected is False


@pytest.mark.asyncio
async def test_serial_transport_connect_port_open_error():
    """Test connect handles OSError when opening serial port."""
    mock_serial_mod = MagicMock()
    mock_serial_mod.open_serial_connection = AsyncMock(side_effect=OSError("Port not found"))

    with patch.dict("sys.modules", {"serial_asyncio": mock_serial_mod}):
        transport = AsyncSerialTransport(port="COM99")
        success = await transport.connect()
        assert success is False
        assert transport.is_connected is False


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
