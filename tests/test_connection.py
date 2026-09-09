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
async def test_large_status_sweep_is_drained_before_ack() -> None:
    session, writer = make_session(OWNCommandSession)
    assert isinstance(session, OWNCommandSession)
    assert session._stream_reader is not None
    for index in range(100):
        session._stream_reader.feed_data(f"*1*0*{index + 11}##".encode())
    session._stream_reader.feed_data(b"*#*1##")

    result = await session.send("*#1*0##", is_status_request=True)

    assert isinstance(result, list)
    assert len(result) == 100
    assert writer.written == [b"*#1*0##"]


@pytest.mark.asyncio
async def test_written_command_is_not_replayed_after_lost_ack() -> None:
    session, writer = make_session(OWNCommandSession)
    assert isinstance(session, OWNCommandSession)
    assert session._stream_reader is not None
    session._stream_reader.feed_eof()

    with patch.object(session, "connect", new_callable=AsyncMock) as connect:
        result = await session.send("*1*1*11##")

    assert result is None
    assert writer.written == [b"*1*1*11##"]
    connect.assert_not_awaited()


@pytest.mark.asyncio
async def test_disconnected_status_request_retries_once() -> None:
    session, original_writer = make_session(OWNCommandSession)
    assert isinstance(session, OWNCommandSession)
    assert session._stream_reader is not None
    session._stream_reader.feed_eof()

    retry_writer = FakeWriter()

    async def reconnect() -> dict:
        session._stream_reader = asyncio.StreamReader()
        session._stream_reader.feed_eof()
        session._stream_writer = retry_writer  # type: ignore[assignment]
        return {"Success": True, "Message": None}

    with patch.object(session, "connect", side_effect=reconnect) as connect:
        result = await session.send("*#1*0##", is_status_request=True)

    assert result is None
    connect.assert_awaited_once()
    assert original_writer.written == [b"*#1*0##"]
    assert retry_writer.written == [b"*#1*0##"]


@pytest.mark.asyncio
async def test_cancelled_command_closes_stream() -> None:
    session, writer = make_session(OWNCommandSession)
    assert isinstance(session, OWNCommandSession)

    pending = asyncio.create_task(
        session.send("*#1*0##", is_status_request=True)
    )
    await asyncio.sleep(0)
    pending.cancel()

    with pytest.raises(asyncio.CancelledError):
        await pending

    assert writer.closed
    assert session._stream_reader is None
    assert session._stream_writer is None


@pytest.mark.asyncio
async def test_partial_response_followed_by_nack_is_not_retried() -> None:
    session, writer = make_session(OWNCommandSession)
    assert isinstance(session, OWNCommandSession)
    assert session._stream_reader is not None
    session._stream_reader.feed_data(b"*1*0*11##*#*0##")

    result = await session.send("*#1*0##", is_status_request=True)

    assert result is None
    assert writer.written == [b"*#1*0##"]


@pytest.mark.asyncio
async def test_probe_gateway_uses_read_only_model_request() -> None:
    gateway = OWNGateway({"address": "192.0.2.1", "port": 20000})

    with (
        patch.object(
            OWNCommandSession,
            "connect",
            new=AsyncMock(return_value={"Success": True, "Message": None}),
        ),
        patch.object(
            OWNCommandSession,
            "send",
            new=AsyncMock(return_value=True),
        ) as send,
        patch.object(OWNCommandSession, "close", new=AsyncMock()) as close,
    ):
        result = await OWNCommandSession.probe_gateway(gateway)

    assert result is True
    send.assert_awaited_once_with("*#13**15##", is_status_request=True)
    close.assert_awaited_once()


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
