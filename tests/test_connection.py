"""Regression tests for session negotiation and command responses."""

import asyncio
from unittest.mock import AsyncMock, patch

import pytest

from OWNd.connection import OWNCommandSession, OWNEventSession, OWNGateway, OWNSession
from OWNd.message import OWNLightingEvent


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

    def get_extra_info(self, name: str):
        del name
        return None


def make_session(
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
    session._stream_writer = writer
    return session, writer


@pytest.mark.asyncio
async def test_legacy_authentication_fails_closed_on_unexpected_frame() -> None:
    session, _ = make_session()
    session._read_frame = AsyncMock(
        side_effect=["*#*1##", "*#123456789##", "*99*0##"]
    )

    result = await session._negotiate()

    assert result == {"Success": False, "Message": "negotiation_error"}


@pytest.mark.asyncio
async def test_invalid_password_is_rejected_before_writing() -> None:
    session, writer = make_session(password="not-a-number")

    result = await session._negotiate()

    assert result == {"Success": False, "Message": "password_error"}
    assert writer.written == []


@pytest.mark.asyncio
async def test_command_negotiation_uses_alternate_session_after_nack() -> None:
    session, writer = make_session(OWNCommandSession)
    session._read_frame = AsyncMock(
        side_effect=["*#*0##", "*#*1##", "*#123456789##", "*#*1##"]
    )

    result = await session._negotiate()

    assert result == {"Success": True, "Message": None}
    assert writer.written[:2] == [b"*99*0##", b"*99*9##"]


@pytest.mark.asyncio
async def test_negotiation_has_an_absolute_deadline() -> None:
    session, _ = make_session()

    async def stalled_exchange() -> dict:
        await asyncio.sleep(1)
        return {"Success": True, "Message": None}

    session._negotiate_exchange = stalled_exchange
    with patch("OWNd.connection.NEGOTIATION_TOTAL_TIMEOUT", 0.01):
        result = await session._negotiate()

    assert result == {"Success": False, "Message": "negotiation_timeout"}


@pytest.mark.asyncio
async def test_temporary_test_session_always_closes() -> None:
    session, writer = make_session()
    session._negotiate = AsyncMock(
        side_effect=asyncio.IncompleteReadError(partial=b"", expected=1)
    )

    with patch(
        "OWNd.connection.asyncio.open_connection",
        new=AsyncMock(return_value=(asyncio.StreamReader(), writer)),
    ):
        result = await session.test_connection()

    assert result == {"Success": False, "Message": "connection_error"}
    assert writer.closed
    assert session._stream_writer is None


@pytest.mark.asyncio
async def test_command_returns_frames_preceding_ack() -> None:
    session, _ = make_session(OWNCommandSession)
    assert isinstance(session, OWNCommandSession)
    session._read_frame = AsyncMock(side_effect=["*1*1*12##", "*#*1##"])

    result = await session.send("*#1*12##", is_status_request=True)

    assert isinstance(result, list)
    assert len(result) == 1
    assert isinstance(result[0], OWNLightingEvent)


@pytest.mark.asyncio
async def test_command_response_frame_count_is_bounded() -> None:
    session, _ = make_session(OWNCommandSession)
    assert isinstance(session, OWNCommandSession)
    session._read_frame = AsyncMock(return_value="*1*1*12##")

    with (
        patch("OWNd.connection.COMMAND_RESPONSE_MAX_FRAMES", 3),
        pytest.raises(TimeoutError),
    ):
        await session._read_command_response()

    assert session._read_frame.await_count == 3


@pytest.mark.asyncio
async def test_event_keepalive_is_profile_controlled() -> None:
    enabled, _ = make_session(OWNEventSession, model="F454")
    disabled, _ = make_session(OWNEventSession, model="MH201")
    assert isinstance(enabled, OWNEventSession)
    assert isinstance(disabled, OWNEventSession)

    assert enabled._keepalive_interval == 90
    assert disabled._keepalive_interval is None


def test_gateway_uses_profile_default_port() -> None:
    gateway = OWNGateway({"address": "192.0.2.1", "modelName": "MH201"})

    assert gateway.port == 20000
