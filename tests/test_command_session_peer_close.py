"""A command session whose socket the gateway already closed is reopened before the write.

A live F461 2.0.11 closes a command session it finds idle for about 30 s
(plant run 2026-11-11, ``*#18*51*#1200#1*0##`` sent 33 s after the previous
command: the write "succeeded", the read failed within 1 ms, and the frame was
neither received nor replayed). The FIN or RST is delivered to the streams while
the session sits idle, so ``send()`` can see it before writing.

Only asyncio's own streams are inspected. Streams installed by hand (MagicMock,
AsyncMock, fakes) are left alone, so suites that model a lost acknowledgement
by feeding EOF before the write (MyHOME's ``test_gateway_regressions.py``)
keep the previous behaviour.
"""
from __future__ import annotations

import asyncio
import inspect
import socket
import warnings
from collections.abc import AsyncIterator, Callable
from contextlib import asynccontextmanager
from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from OWNd.connection import OWNCommandSession, OWNGateway, OWNNackError


class _FakeTransport(asyncio.WriteTransport):
    def __init__(self, closing: bool) -> None:
        super().__init__()
        self.closing = closing

    def is_closing(self) -> bool:
        return self.closing

    def close(self) -> None:
        self.closing = True


class FakeWriter(asyncio.StreamWriter):
    """An ``asyncio.StreamWriter`` (so ``_peer_closed()`` inspects it) that records writes."""

    def __init__(self, closing: bool = False) -> None:
        super().__init__(
            _FakeTransport(closing), asyncio.Protocol(), None, asyncio.get_running_loop()
        )
        self.written: list[bytes] = []
        self.closed = False

    def write(self, data: bytes | bytearray | memoryview) -> None:
        self.written.append(bytes(data))

    async def drain(self) -> None:
        return None

    def close(self) -> None:
        self.closed = True
        self._transport.close()

    async def wait_closed(self) -> None:
        return None

    def is_closing(self) -> bool:
        return self._transport.is_closing()

    def get_extra_info(self, name: str, default: Any = None) -> Any:  # pragma: no cover - not used here
        return default


def make_session() -> OWNCommandSession:
    gateway = OWNGateway(
        {"address": "192.0.2.1", "port": 20000, "password": "12345", "modelName": "F461"}
    )
    return OWNCommandSession(gateway=gateway)


def arm_reconnect(session: OWNCommandSession, reply: bytes = b"*#*1##") -> tuple[AsyncMock, FakeWriter]:
    """Make ``connect()`` install fresh streams whose first read is ``reply``."""
    new_writer = FakeWriter()

    async def _connect(*args, **kwargs):
        reader = asyncio.StreamReader()
        reader.feed_data(reply)
        session._stream_reader = reader
        session._stream_writer = new_writer  # type: ignore[assignment]
        return {"Success": True, "Message": None}

    connect = AsyncMock(side_effect=_connect)
    session.connect = connect  # type: ignore[method-assign]
    return connect, new_writer


class TestPeerClosedCommandSession:
    @pytest.mark.asyncio
    async def test_peer_closed_detection(self) -> None:
        session = make_session()
        # No streams: send() reopens anyway, nothing to report here.
        assert session._peer_closed() is False

        reader = asyncio.StreamReader()
        writer = FakeWriter()
        session._stream_reader = reader
        session._stream_writer = writer  # type: ignore[assignment]
        assert session._peer_closed() is False

        reader.feed_eof()  # FIN delivered while idle
        assert session._peer_closed() is True

        reader = asyncio.StreamReader()
        reader.set_exception(ConnectionResetError("peer reset"))  # RST delivered while idle
        session._stream_reader = reader
        assert session._peer_closed() is True

        session._stream_reader = asyncio.StreamReader()
        session._stream_writer = FakeWriter(closing=True)  # type: ignore[assignment]
        assert session._peer_closed() is True

        # Streams installed by hand are not inspected. MyHOME's regression
        # suite models a lost acknowledgement with a real reader at EOF and a
        # MagicMock writer: that is the previous behaviour, not a reopen.
        dead_reader = asyncio.StreamReader()
        dead_reader.feed_eof()
        session._stream_reader = dead_reader
        session._stream_writer = MagicMock()
        assert session._peer_closed() is False

        # An AsyncMock reader must not be poked (its methods return coroutines).
        session._stream_reader = AsyncMock()
        with warnings.catch_warnings():
            warnings.simplefilter("error")
            assert session._peer_closed() is False

        session._stream_reader = MagicMock()
        session._stream_writer = FakeWriter()  # type: ignore[assignment]
        assert session._peer_closed() is False

    @pytest.mark.asyncio
    async def test_send_reopens_a_peer_closed_session_before_writing(self) -> None:
        session = make_session()
        dead_reader = asyncio.StreamReader()
        dead_reader.feed_eof()
        dead_writer = FakeWriter()
        session._stream_reader = dead_reader
        session._stream_writer = dead_writer  # type: ignore[assignment]
        connect, new_writer = arm_reconnect(session)

        result = await session.send("*#18*51*#1200#1*0##")

        assert result is True
        connect.assert_awaited_once()
        assert dead_writer.written == []  # nothing went into the dead socket
        assert dead_writer.closed is True
        assert new_writer.written == [b"*#18*51*#1200#1*0##"]
        assert session.is_open is True

    @pytest.mark.asyncio
    async def test_send_on_a_live_session_does_not_reconnect(self) -> None:
        session = make_session()
        reader = asyncio.StreamReader()
        reader.feed_data(b"*#*1##")
        writer = FakeWriter()
        session._stream_reader = reader
        session._stream_writer = writer  # type: ignore[assignment]
        connect, _ = arm_reconnect(session)

        result = await session.send("*#18*51*#1200#1*0##")

        assert result is True
        connect.assert_not_awaited()
        assert writer.written == [b"*#18*51*#1200#1*0##"]

    @pytest.mark.asyncio
    async def test_send_reports_the_loss_when_the_reopen_fails(self) -> None:
        session = make_session()
        dead_reader = asyncio.StreamReader()
        dead_reader.set_exception(ConnectionResetError("peer reset"))
        session._stream_reader = dead_reader
        session._stream_writer = FakeWriter()  # type: ignore[assignment]
        session.connect = AsyncMock(return_value={"Success": False, "Message": "refused"})  # type: ignore[method-assign]

        result = await session.send("*#18*51*#1200#1*0##")

        assert result is None
        assert session.is_open is False
        assert session.last_error is not None


class TestCloseBehindUnreadBytes:
    """The gateway sent something, then closed: ``at_eof()`` is False while bytes wait.

    A live F461 2.0.11 closes a command session that has sent nothing since
    its handshake after 30 s with ``*#*0##`` followed 1 ms later by the FIN
    (plant capture 2026-11-17: ``recv b'*#*0##' at 30.108s``, ``recv b'' at
    30.109s``); a session which carried a frame is closed with the FIN alone.
    An F455 1.0.76 sends the FIN alone.
    """

    @staticmethod
    def _install(session: OWNCommandSession, data: bytes, *, eof: bool) -> tuple[asyncio.StreamReader, FakeWriter]:
        reader = asyncio.StreamReader()
        if data:
            reader.feed_data(data)
        if eof:
            reader.feed_eof()
        writer = FakeWriter()
        session._stream_reader = reader
        session._stream_writer = writer  # type: ignore[assignment]
        return reader, writer

    @pytest.mark.asyncio
    async def test_nack_then_fin_is_a_closed_session(self) -> None:
        session = make_session()
        reader, _ = self._install(session, b"*#*0##", eof=True)

        # What OWNd#167 looks at: nothing, the buffered frame hides the EOF.
        assert reader.at_eof() is False

        assert session._peer_closed() is True

    @pytest.mark.asyncio
    async def test_an_idle_live_session_is_left_alone(self) -> None:
        session = make_session()
        reader, _ = self._install(session, b"", eof=False)

        assert session._peer_closed() is False
        assert reader.at_eof() is False

    @pytest.mark.asyncio
    async def test_bytes_of_a_session_that_is_still_open_stay_in_the_reader(self) -> None:
        session = make_session()
        reader, _ = self._install(session, b"*#*1##*1*1*11##", eof=False)

        assert session._peer_closed() is False
        # Nothing was consumed: the session reads what it would have read before.
        assert await reader.readuntil(b"##") == b"*#*1##"
        assert await reader.readuntil(b"##") == b"*1*1*11##"

    @pytest.mark.asyncio
    async def test_streams_installed_by_hand_are_not_read(self) -> None:
        session = make_session()
        reader = asyncio.StreamReader()
        reader.feed_data(b"*#*0##")
        reader.feed_eof()
        session._stream_reader = reader
        session._stream_writer = MagicMock()
        assert session._peer_closed() is False
        assert await reader.readuntil(b"##") == b"*#*0##"

        session._stream_reader = AsyncMock()
        session._stream_writer = FakeWriter()  # type: ignore[assignment]
        with warnings.catch_warnings():
            warnings.simplefilter("error")
            assert session._peer_closed() is False

        session._stream_reader = None
        session._stream_writer = None
        assert session._peer_closed() is False

    @pytest.mark.asyncio
    @pytest.mark.parametrize(
        ("frame", "is_status_request"),
        [
            ("*#13**15##", True),  # was: None + OWNNackError, the gateway never got it
            ("*1*0*0011##", False),  # was: ERROR "Could not send message", then a retry
        ],
    )
    async def test_send_reopens_instead_of_reading_the_stale_nack(
        self, frame: str, is_status_request: bool
    ) -> None:
        session = make_session()
        session._logger = MagicMock()
        _, dead_writer = self._install(session, b"*#*0##", eof=True)
        if is_status_request:
            connect, new_writer = arm_reconnect(session, reply=b"*#13**15*200##" + b"*#*1##")
        else:
            connect, new_writer = arm_reconnect(session)

        result = await session.send(frame, is_status_request=is_status_request)

        if is_status_request:
            assert isinstance(result, list)
            assert [str(m) for m in result] == ["*#13**15*200##"]
        else:
            assert result is True
        assert session.last_error is None
        connect.assert_awaited_once()
        assert dead_writer.written == []  # nothing went into the dead socket
        assert dead_writer.closed is True
        assert new_writer.written == [frame.encode()]
        session._logger.error.assert_not_called()

    @pytest.mark.asyncio
    async def test_send_on_a_live_session_with_a_waiting_reply_is_unchanged(self) -> None:
        session = make_session()
        _, writer = self._install(session, b"*1*1*11##*#*1##", eof=False)
        connect, _ = arm_reconnect(session)

        result = await session.send("*#1*11##", is_status_request=True)

        assert isinstance(result, list) and [str(m) for m in result] == ["*1*1*11##"]
        connect.assert_not_awaited()
        assert writer.written == [b"*#1*11##"]


# --- The same check on real sockets (review of OWNd#186) ---
#
# Bytes a stand-in peer writes on a socket pair, not a gateway capture; the
# model request and its reply are those of ``tests/test_f461_live_plant.py``.

Streams = tuple[asyncio.StreamReader, asyncio.StreamWriter, socket.socket]


@asynccontextmanager
async def stream_pair() -> AsyncIterator[Streams]:
    """asyncio streams on one end of a socket pair; the test writes the gateway's side."""
    local, peer = socket.socketpair()
    with peer:
        try:
            reader, writer = await asyncio.open_connection(sock=local)
        except BaseException:
            local.close()
            raise
        try:
            yield reader, writer, peer
        finally:
            writer.close()
            await writer.wait_closed()


def received(peer: socket.socket) -> bytes:
    """What the stand-in peer has received so far, without waiting."""
    peer.setblocking(False)
    try:
        return peer.recv(1024)
    except BlockingIOError:
        return b""


async def until(condition: Callable[[], bool], deadline: float = 2.0) -> None:
    """Wait, with a deadline, until the event loop has delivered what the test is about."""
    async with asyncio.timeout(deadline):
        while not condition():
            await asyncio.sleep(0.005)


def unread(reader: asyncio.StreamReader) -> bytes:
    return bytes(reader._buffer)  # type: ignore[attr-defined]


class TestCloseBehindUnreadBytesOnRealSockets:
    @pytest.mark.asyncio
    async def test_frame_and_fin_delivered_reopens_before_the_write(self) -> None:
        session = make_session()
        async with stream_pair() as (reader, writer, old_peer), stream_pair() as (reader2, writer2, new_peer):
            session._stream_reader, session._stream_writer = reader, writer
            old_peer.sendall(b"*#*0##")
            old_peer.shutdown(socket.SHUT_WR)
            # The frame AND the end of stream have reached the reader.
            await until(lambda: reader._eof)  # type: ignore[attr-defined]
            assert unread(reader) == b"*#*0##"
            assert reader.at_eof() is False
            assert session._peer_closed() is True

            new_peer.sendall(b"*#13**15*200##" + b"*#*1##")

            async def reopen(*args: Any, **kwargs: Any) -> dict[str, Any]:
                session._stream_reader, session._stream_writer = reader2, writer2
                return {"Success": True, "Message": None}

            with patch.object(session, "connect", side_effect=reopen) as connect:
                result = await session.send("*#13**15##", is_status_request=True)

            connect.assert_awaited_once()
            assert isinstance(result, list)
            assert [str(message) for message in result] == ["*#13**15*200##"]
            assert received(old_peer) == b""  # nothing went into the dead socket
            assert received(new_peer) == b"*#13**15##"

    @pytest.mark.asyncio
    async def test_fin_still_on_the_socket_raises_nothing(self) -> None:
        """Between the gateway's frame and its FIN (1 ms on the F461) ``send()`` behaves as before."""
        session = make_session()
        async with stream_pair() as (reader, writer, peer):
            session._stream_reader, session._stream_writer = reader, writer
            failed_connect = AsyncMock(return_value={"Success": False, "Message": "connection_error"})
            with patch.object(session, "connect", failed_connect):
                peer.sendall(b"*#*0##")
                await until(lambda: unread(reader) == b"*#*0##")
                peer.shutdown(socket.SHUT_WR)
                # No loop turn between the shutdown and the send: the FIN is not processed yet.
                assert await session.send("*#13**15##", is_status_request=True) is None
                assert isinstance(session.last_error, OWNNackError)

    @pytest.mark.asyncio
    async def test_a_frame_arriving_in_two_parts_keeps_its_byte_order(self) -> None:
        session = make_session()
        async with stream_pair() as (reader, writer, peer):
            session._stream_reader, session._stream_writer = reader, writer
            peer.sendall(b"*1*1*")
            await until(lambda: unread(reader) == b"*1*1*")
            peer.sendall(b"11##")
            assert session._peer_closed() is False
            assert await asyncio.wait_for(reader.readuntil(b"##"), 1) == b"*1*1*11##"

    @pytest.mark.asyncio
    async def test_send_reads_a_reply_arriving_in_two_parts_in_order(self) -> None:
        session = make_session()
        async with stream_pair() as (reader, writer, peer):
            session._stream_reader, session._stream_writer = reader, writer
            peer.sendall(b"*#13*")
            await until(lambda: unread(reader) == b"*#13*")
            peer.sendall(b"*15*200##" + b"*#*1##")
            with patch.object(session, "connect", side_effect=AssertionError("unexpected reconnect")):
                result = await session.send("*#13**15##", is_status_request=True)
            assert isinstance(result, list)
            assert [str(message) for message in result] == ["*#13**15*200##"]

    @pytest.mark.asyncio
    async def test_cancel_on_the_first_suspension_closes_the_session(self) -> None:
        session = make_session()
        async with stream_pair() as (reader, writer, peer):
            session._stream_reader, session._stream_writer = reader, writer
            with patch.object(session, "connect", side_effect=AssertionError("unexpected reconnect")):
                task = asyncio.ensure_future(session.send("*#13**15##", is_status_request=True))
                await asyncio.sleep(0)
                task.cancel()
                with pytest.raises(asyncio.CancelledError):
                    await task
            assert session.is_open is False
            assert writer.is_closing() is True
            # No suspension before the write: the peer already has the request.
            assert received(peer) == b"*#13**15##"

    @pytest.mark.asyncio
    async def test_the_check_is_synchronous(self) -> None:
        session = make_session()
        async with stream_pair() as (reader, writer, _peer):
            session._stream_reader, session._stream_writer = reader, writer
            assert session._peer_closed() is False
            assert inspect.iscoroutinefunction(OWNCommandSession._peer_closed) is False
            assert not hasattr(OWNCommandSession, "_closed_behind_unread_bytes")
