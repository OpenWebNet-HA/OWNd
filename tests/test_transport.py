"""Tests for transport lifecycle and serial response demultiplexing."""

import asyncio
from unittest.mock import AsyncMock, patch

import pytest

from OWNd.connection import OWNGateway
from OWNd.message import OWNLightingEvent
from OWNd.transport.serial import AsyncSerialTransport
from OWNd.transport.tcp import AsyncTcpTransport


class FakeWriter:
    def __init__(self) -> None:
        self.written: list[bytes] = []
        self.closed = False

    def write(self, data: bytes) -> None:
        self.written.append(data)

    async def drain(self) -> None:
        return None

    def close(self) -> None:
        self.closed = True

    async def wait_closed(self) -> None:
        return None


@pytest.mark.asyncio
async def test_serial_transport_collects_query_frames_until_ack() -> None:
    transport = AsyncSerialTransport("/dev/ttyUSB0")
    writer = FakeWriter()
    transport._writer = writer
    transport._connected = True

    send_task = asyncio.create_task(transport.send("*#1*12##"))
    await asyncio.sleep(0)
    received = []
    transport.register_listener(received.append)
    transport._process_frame("*#2*21*10*10*50*001*0##")
    transport._process_frame("*#1*12*1*150*0##")
    transport._process_frame("*#*1##")
    result = await send_task

    assert writer.written == [b"*#1*12##"]
    assert isinstance(result, list)
    assert isinstance(result[0], OWNLightingEvent)
    assert len(received) == 1


def test_serial_unsolicited_frame_reaches_listener() -> None:
    transport = AsyncSerialTransport("/dev/ttyUSB0")
    received = []
    transport.register_listener(received.append)

    transport._process_frame("*1*1*12##")

    assert len(received) == 1
    assert isinstance(received[0], OWNLightingEvent)


@pytest.mark.asyncio
async def test_tcp_transport_cleans_event_session_if_command_fails() -> None:
    gateway = OWNGateway(
        {"address": "192.0.2.1", "port": 20000, "modelName": "MH201"}
    )
    event = AsyncMock()
    event.connect.return_value = {"Success": True, "Message": None}
    event.is_connected = True
    command = AsyncMock()
    command.connect.return_value = None
    command.is_connected = False

    with (
        patch("OWNd.transport.tcp.OWNEventSession", return_value=event),
        patch("OWNd.transport.tcp.OWNCommandSession", return_value=command),
    ):
        transport = AsyncTcpTransport(gateway)
        connected = await transport.connect()

    assert not connected
    event.close.assert_awaited_once()
    command.close.assert_awaited_once()
