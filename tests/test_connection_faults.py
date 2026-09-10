"""Exhaustive tests for connection edge cases, fault recovery, and negotiation branches."""
from __future__ import annotations

import asyncio
import socket
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from OWNd.connection import (
    CONNECT_TIMEOUT,
    MAX_CONNECT_ATTEMPTS,
    NEGOTIATION_MAX_FRAMES,
    OWNCommandSession,
    OWNEventSession,
    OWNGateway,
    OWNSession,
    OWNSignaling,
    RECONNECT_PAUSE,
    RECONNECT_PAUSE_FATAL,
    _FATAL_NEGOTIATION_ERRORS,
)


class FakeWriter:
    def __init__(self) -> None:
        self.written: list[bytes] = []
        self.closed = False
        self._sock: MagicMock | None = MagicMock()

    def write(self, data: bytes) -> None:
        self.written.append(data)

    async def drain(self) -> None:
        return None

    def close(self) -> None:
        self.closed = True

    async def wait_closed(self) -> None:
        return None

    def get_extra_info(self, name: str):
        if name == "socket":
            return self._sock
        return None


def make_fault_session(
    session_type: type[OWNSession] = OWNSession,
    password: str | None = "12345",
    model: str = "Test",
) -> tuple[OWNSession, FakeWriter]:
    gateway = OWNGateway(
        {
            "address": "192.0.2.1",
            "port": 20000,
            "password": password,
            "modelName": model,
        }
    )
    session = session_type(gateway=gateway)
    session._stream_reader = asyncio.StreamReader()
    writer = FakeWriter()
    session._stream_writer = writer  # type: ignore[assignment]
    return session, writer


class TestConnectionFaults:
    """Target all uncovered branches in OWNd.connection."""

    @pytest.mark.asyncio
    async def test_get_first_available_gateway_empty(self) -> None:
        with patch("OWNd.connection.find_gateways", new=AsyncMock(return_value=[])):
            result = await OWNGateway.get_first_available_gateway()
            assert result is None

    def test_on_state_change_exception_swallowed(self) -> None:
        session, _ = make_fault_session()
        logger = MagicMock()
        session._logger = logger
        session._on_state_change = MagicMock(side_effect=RuntimeError("callback crashed"))

        session._set_connected(True)
        assert session._connected is True
        logger.exception.assert_called_once()

    def test_apply_tcp_keepalive_socket_none_and_oserror(self) -> None:
        session, writer = make_fault_session()
        logger = MagicMock()
        session._logger = logger
        session._tcp_keepalive = True

        # 1. Socket is None
        writer._sock = None
        session._apply_tcp_keepalive()

        # 2. setsockopt raises OSError
        writer._sock = MagicMock()
        writer._sock.setsockopt.side_effect = OSError("Keepalive unsupported")
        session._apply_tcp_keepalive()
        logger.warning.assert_called_once()

    @pytest.mark.asyncio
    async def test_read_frame_without_timeout(self) -> None:
        session, _ = make_fault_session()
        assert session._stream_reader is not None
        session._stream_reader.feed_data(b"*#*1##")
        frame = await session._read_frame(timeout=None)
        assert frame == "*#*1##"

    @pytest.mark.asyncio
    async def test_connect_fatal_negotiation_error_aborts(self) -> None:
        session, _ = make_fault_session()
        assert session.gateway is not None

        # Return a fatal negotiation error (password_error)
        with (
            patch("asyncio.open_connection", new=AsyncMock(return_value=(MagicMock(), MagicMock()))),
            patch.object(session, "_negotiate", new=AsyncMock(return_value={"Success": False, "Message": "password_error"})),
            patch.object(session, "close", new=AsyncMock()) as mock_close,
        ):
            result = await session.connect()
            assert result == {"Success": False, "Message": "password_error"}
            assert session.is_connected is False
            mock_close.assert_awaited()

    @pytest.mark.asyncio
    async def test_connect_network_oserror_retry(self) -> None:
        session, _ = make_fault_session()
        assert session.gateway is not None

        with (
            patch("asyncio.open_connection", side_effect=OSError("Network unreachable")),
            patch("asyncio.sleep", new=AsyncMock()),
            patch("OWNd.connection.MAX_CONNECT_ATTEMPTS", 1),
        ):
            result = await session.connect()
            assert result is None
            assert session.is_connected is False

    @pytest.mark.asyncio
    async def test_negotiation_max_frames_exhaustion(self) -> None:
        session, writer = make_fault_session(password="12345")
        # Gateway sends ACK then SHA challenge, but with max_frames=1, second read exceeds limit
        session._read_frame = AsyncMock(side_effect=["*#*1##", "*98*1##"])
        with patch("OWNd.connection.NEGOTIATION_MAX_FRAMES", 1):
            result = await session._negotiate()
            assert result == {"Success": False, "Message": "negotiation_timeout"}

    @pytest.mark.asyncio
    async def test_hmac_sha256_and_unexpected_frames(self) -> None:
        # Test SHA-256 challenge negotiation
        session, writer = make_fault_session(password="12345")
        session._type = "command"

        # 1. Unexpected frame after challenge acceptance (line 731-739)
        session._read_frame = AsyncMock(side_effect=["*#*1##", "*98*2##", "*#*0##"])
        result = await session._negotiate()
        assert result == {"Success": False, "Message": "negotiation_error"}

        # 2. Unexpected frame after sending password (line 721-729)
        session2, _ = make_fault_session(password="12345")
        session2._type = "command"
        session2._read_frame = AsyncMock(side_effect=["*#*1##", "*98*2##", "*#123456789##", "*#*1##"])
        result2 = await session2._negotiate()
        assert result2 == {"Success": False, "Message": "negotiation_error"}

    @pytest.mark.asyncio
    async def test_event_keepalive_edge_cases(self) -> None:
        session, writer = make_fault_session(OWNEventSession, model="F454")
        assert isinstance(session, OWNEventSession)

        # 1. _start_keepalive with None interval
        session._keepalive_interval = None
        session._start_keepalive()
        assert session._keepalive_task is None

        # 2. _keepalive_loop when writer is None
        session._keepalive_interval = 0.01
        session._stream_writer = None
        task = asyncio.create_task(session._keepalive_loop())
        await task
        assert task.done()

        # 3. _keepalive_loop when writer.drain() raises ConnectionError
        session._stream_writer = writer  # type: ignore[assignment]
        writer.drain = AsyncMock(side_effect=ConnectionError("Broken pipe"))
        task2 = asyncio.create_task(session._keepalive_loop())
        await task2
        assert writer.closed

    @pytest.mark.asyncio
    async def test_event_get_next_reconnect_pause_fatal_and_standard(self) -> None:
        session, _ = make_fault_session(OWNEventSession)
        assert isinstance(session, OWNEventSession)
        session._stream_reader = None

        # Fatal pause branch (lines 1049-1053)
        with (
            patch.object(session, "_reconnect", new=AsyncMock(return_value={"Success": False, "Message": "password_error"})),
            patch("asyncio.sleep", new=AsyncMock()) as mock_sleep,
        ):
            res = await session.get_next()
            assert res is None
            mock_sleep.assert_awaited_once_with(RECONNECT_PAUSE_FATAL)

        # Non-fatal pause branch (lines 1052-1053)
        with (
            patch.object(session, "_reconnect", new=AsyncMock(return_value={"Success": False, "Message": "timeout"})),
            patch("asyncio.sleep", new=AsyncMock()) as mock_sleep2,
        ):
            res2 = await session.get_next()
            assert res2 is None
            mock_sleep2.assert_awaited_once_with(RECONNECT_PAUSE)

    @pytest.mark.asyncio
    async def test_event_get_next_no_inactivity_timeout_and_malformed_utf8(self) -> None:
        session, _ = make_fault_session(OWNEventSession)
        assert isinstance(session, OWNEventSession)
        assert session._stream_reader is not None

        # Inactivity timeout None (line 1066)
        session._inactivity_timeout = None
        session._stream_reader.feed_data(b"*1*1*21##")
        msg = await session.get_next()
        assert msg is not None

        # Malformed UTF-8 decoded with errors='replace' (lines 1102-1110)
        session._stream_reader = asyncio.StreamReader()
        session._stream_reader.feed_data(b"*1*\xff\xfe*21##")
        raw = await session.get_next()
        assert raw is not None
        assert isinstance(raw, str)

    @pytest.mark.asyncio
    async def test_command_session_read_response_branches(self) -> None:
        session, _ = make_fault_session(OWNCommandSession)
        assert isinstance(session, OWNCommandSession)

        # 1. Non-terminal signaling ignored, then ACK returned (lines 1228-1233)
        session._read_frame = AsyncMock(side_effect=["*#1234##", "*#*1##"])
        sig, collected = await session._read_command_response()
        assert sig.is_ack()
        assert collected == []

        # 2. _read_signaling_response wrapper (lines 1246-1247)
        session._read_frame = AsyncMock(return_value="*#*1##")
        sig2 = await session._read_signaling_response()
        assert sig2.is_ack()

    @pytest.mark.asyncio
    async def test_command_send_reconnect_failure_and_unexpected_response(self) -> None:
        session, writer = make_fault_session(OWNCommandSession)
        assert isinstance(session, OWNCommandSession)

        # 1. Connect failure in _locked_send (lines 1289-1295)
        session._stream_reader = None
        session._stream_writer = None
        with patch.object(session, "connect", new=AsyncMock(return_value={"Success": False})):
            res = await session.send("*1*1*21##")
            assert res is None

        # 2. Unexpected non-ACK non-NACK response (lines 1339-1345)
        session2, _ = make_fault_session(OWNCommandSession)
        assert isinstance(session2, OWNCommandSession)
        session2._read_command_response = AsyncMock(return_value=(MagicMock(is_ack=MagicMock(return_value=False), is_nack=MagicMock(return_value=False)), []))
        res2 = await session2.send("*1*1*21##")
        assert res2 is None

    @pytest.mark.asyncio
    async def test_command_send_timeout_error(self) -> None:
        session, _ = make_fault_session(OWNCommandSession)
        assert isinstance(session, OWNCommandSession)

        # TimeoutError awaiting response in _locked_send (lines 1372-1379)
        session._read_command_response = AsyncMock(side_effect=TimeoutError("Response timeout"))
        res = await session.send("*1*1*21##")
        assert res is None
        assert session._stream_writer is None
