"""Exhaustive unit tests for profiles, discovery, TCP and serial transports."""
from __future__ import annotations

import asyncio
from unittest.mock import AsyncMock, MagicMock, patch

import aiohttp
import pytest

from OWNd.discovery import (
    SimpleServiceDiscoveryProtocol,
    _client_session,
    get_gateway,
)
from OWNd.profiles import (
    GenericGatewayProfile,
    MH200NProfile,
    get_gateway_profile,
)
from OWNd.transport.serial import AsyncSerialTransport
from OWNd.transport.tcp import AsyncTcpTransport
from OWNd.connection import OWNGateway


# ── Profiles ────────────────────────────────────────────────────────────────

class TestProfilesExhaustive:
    def test_generic_fallback_and_properties(self) -> None:
        # None and empty string return _GENERIC profile
        prof_none = get_gateway_profile(None)
        assert isinstance(prof_none, GenericGatewayProfile)
        assert prof_none.model_name == "Generic"

        prof_empty = get_gateway_profile("")
        assert isinstance(prof_empty, GenericGatewayProfile)

        # max_command_workers property
        profile = MH200NProfile()
        assert profile.max_command_workers == profile.max_command_sessions

        # display_name property
        assert profile.display_name == "MH200N Gateway"


# ── Discovery ───────────────────────────────────────────────────────────────

class TestDiscoveryExhaustive:
    def test_datagram_received_error_handling(self) -> None:
        recvq: asyncio.Queue = asyncio.Queue()
        excq: asyncio.Queue = asyncio.Queue()
        proto = SimpleServiceDiscoveryProtocol(recvq=recvq, excq=excq)

        addr = ("192.168.1.50", 1900)

        # 1. UnicodeDecodeError
        proto.datagram_received(b"\xff\xfe\x00\x00\xff", addr)
        assert recvq.empty()

        # 2. Non-HTTP packet
        proto.datagram_received(b"SOME_OTHER_PACKET", addr)
        assert recvq.empty()

        # 3. Malformed HTTP status line
        proto.datagram_received(b"HTTP/1.1\r\n\r\n", addr)
        assert recvq.empty()

        # 4. Missing LOCATION or ST header
        proto.datagram_received(
            b"HTTP/1.1 200 OK\r\nUSN: uuid:1234\r\n\r\n", addr
        )
        assert recvq.empty()

    @pytest.mark.asyncio
    async def test_client_session_with_caller_session(self) -> None:
        # Caller-provided session yields itself and does not close
        mock_session = MagicMock(spec=aiohttp.ClientSession)
        async with _client_session(mock_session) as sess:
            assert sess is mock_session
        assert not mock_session.close.called

    @pytest.mark.asyncio
    async def test_get_gateway_fallback_when_serial_number_missing(self) -> None:
        # details missing serialNumber causes get_gateway to fall back to find_gateways
        with (
            patch(
                "OWNd.discovery._get_scpd_details",
                new=AsyncMock(return_value={"friendlyName": "UnknownGW"}),
            ),
            patch(
                "OWNd.discovery.find_gateways",
                new=AsyncMock(return_value=[{"address": "192.168.1.100", "port": 20000}]),
            ),
        ):
            gw = await get_gateway("192.168.1.100")
            assert gw is not None
            assert gw["address"] == "192.168.1.100"


# ── TCP Transport ───────────────────────────────────────────────────────────

class TestTCPTransportExhaustive:
    @pytest.mark.asyncio
    async def test_connect_disconnects_existing_sessions(self) -> None:
        gateway = OWNGateway({"address": "127.0.0.1", "port": 20000})
        transport = AsyncTcpTransport(gateway=gateway)

        # Set fake sessions
        fake_ev = MagicMock()
        fake_ev.close = AsyncMock()
        fake_cmd = MagicMock()
        fake_cmd.close = AsyncMock()
        transport._event_session = fake_ev
        transport._command_session = fake_cmd

        with (
            patch("OWNd.transport.tcp.OWNEventSession") as mock_ev_cls,
            patch("OWNd.transport.tcp.OWNCommandSession") as mock_cmd_cls,
        ):
            mock_ev_instance = MagicMock()
            mock_ev_instance.connect = AsyncMock(return_value={"Success": True})
            mock_ev_instance.close = AsyncMock()
            mock_ev_cls.return_value = mock_ev_instance

            mock_cmd_instance = MagicMock()
            mock_cmd_instance.connect = AsyncMock(return_value={"Success": True})
            mock_cmd_instance.close = AsyncMock()
            mock_cmd_cls.return_value = mock_cmd_instance

            success = await transport.connect()
            assert success is True
            # Previous sessions were closed
            fake_ev.close.assert_awaited_once()
            fake_cmd.close.assert_awaited_once()

        await transport.disconnect()

    @pytest.mark.asyncio
    async def test_listen_loop_generic_exception_logging(self) -> None:
        gateway = OWNGateway({"address": "127.0.0.1", "port": 20000})
        transport = AsyncTcpTransport(gateway=gateway)
        logger = MagicMock()
        transport._logger = logger

        fake_ev = MagicMock()
        fake_ev.get_next = AsyncMock(side_effect=RuntimeError("unexpected crash"))
        transport._event_session = fake_ev

        await transport._listen_loop()
        logger.exception.assert_called_once()

    @pytest.mark.asyncio
    async def test_disconnect_with_none_sessions(self) -> None:
        gateway = OWNGateway({"address": "127.0.0.1", "port": 20000})
        transport = AsyncTcpTransport(gateway=gateway)
        transport._event_session = None
        transport._command_session = None
        await transport.disconnect()
        assert transport._stopping is True


# ── Serial Transport ────────────────────────────────────────────────────────

class TestSerialTransportExhaustive:
    @pytest.mark.asyncio
    async def test_connect_already_connected(self) -> None:
        transport = AsyncSerialTransport(port="COM1")
        transport._connected = True
        assert await transport.connect() is True

    @pytest.mark.asyncio
    async def test_connect_reconnects_when_stale_reader_writer(self) -> None:
        transport = AsyncSerialTransport(port="COM1")
        mock_writer = MagicMock()
        mock_writer.wait_closed = AsyncMock()
        transport._writer = mock_writer
        transport._connected = False

        mock_module = MagicMock()
        mock_module.open_serial_connection = AsyncMock(side_effect=OSError("Port busy"))
        with patch.dict("sys.modules", {"serial_asyncio": mock_module}):
            result = await transport.connect()
            assert result is False
            mock_writer.close.assert_called_once()

    @pytest.mark.asyncio
    async def test_process_frame_unsolicited_and_other_signaling(self) -> None:
        transport = AsyncSerialTransport(port="COM1")
        listener = MagicMock()
        transport.register_listener(listener)

        # 1. Unsolicited frame dispatched directly
        transport._process_frame("*1*1*21##")
        listener.assert_called_once()

        # 2. Non-ACK, non-NACK signaling completes pending future with None
        loop = asyncio.get_running_loop()
        future = loop.create_future()
        transport._pending_future = future
        transport._process_frame("*#1234##")
        assert future.done()
        assert future.result() is None

    @pytest.mark.asyncio
    async def test_process_frame_max_frames_exceeded(self) -> None:
        from OWNd.connection import COMMAND_RESPONSE_MAX_FRAMES

        transport = AsyncSerialTransport(port="COM1")
        loop = asyncio.get_running_loop()
        future = loop.create_future()
        transport._pending_future = future
        transport._pending_request = MagicMock(who=1, where="21")
        # Fill pending frames to max
        transport._pending_frames = [MagicMock()] * COMMAND_RESPONSE_MAX_FRAMES

        transport._process_frame("*#1*21*1*100##")

        assert future.done()
        with pytest.raises(TimeoutError, match="command response exceeded"):
            future.result()

    @pytest.mark.asyncio
    async def test_listen_loop_none_message_and_stopping(self) -> None:
        gateway = OWNGateway({"address": "127.0.0.1", "port": 20000})
        transport = AsyncTcpTransport(gateway=gateway)
        fake_ev = MagicMock()

        async def get_next_side_effect():
            transport._stopping = True
            return None

        fake_ev.get_next = AsyncMock(side_effect=get_next_side_effect)
        transport._event_session = fake_ev

        await transport._listen_loop()
        assert fake_ev.get_next.call_count == 1

    @pytest.mark.asyncio
    async def test_disconnect_cancels_pending_future(self) -> None:
        transport = AsyncSerialTransport(port="COM1")
        loop = asyncio.get_running_loop()
        future = loop.create_future()
        transport._pending_future = future
        await transport.disconnect()
        assert future.done()
        assert future.result() is None

    @pytest.mark.asyncio
    async def test_serial_read_loop_cancellation_and_finally_cleanup(self) -> None:
        transport = AsyncSerialTransport(port="COM1")
        mock_reader = MagicMock()
        mock_reader.readuntil = AsyncMock(side_effect=asyncio.CancelledError)
        transport._reader = mock_reader

        mock_writer = MagicMock()
        transport._writer = mock_writer

        loop = asyncio.get_running_loop()
        future = loop.create_future()
        transport._pending_future = future
        transport._connected = True

        with pytest.raises(asyncio.CancelledError):
            await transport._read_loop()

        assert transport._connected is False
        mock_writer.close.assert_called_once()
        assert future.done()
        assert future.result() is None

    @pytest.mark.asyncio
    async def test_serial_read_loop_stopping_normal_exit(self) -> None:
        transport = AsyncSerialTransport(port="COM1")
        mock_reader = MagicMock()
        transport._reader = mock_reader
        transport._stopping = True

        await transport._read_loop()
        assert transport._connected is False

    @pytest.mark.asyncio
    async def test_serial_read_loop_stopping_on_oserror(self) -> None:
        transport = AsyncSerialTransport(port="COM1")
        mock_reader = MagicMock()

        async def read_side_effect(sep: bytes) -> bytes:
            transport._stopping = True
            raise OSError("Device removed")

        mock_reader.readuntil = AsyncMock(side_effect=read_side_effect)
        transport._reader = mock_reader
        transport._stopping = False

        await transport._read_loop()
        assert transport._connected is False
