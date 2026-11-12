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
import warnings
from typing import Any
from unittest.mock import AsyncMock, MagicMock

import pytest

from OWNd.connection import OWNCommandSession, OWNGateway


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
