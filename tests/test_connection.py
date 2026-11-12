"""Regression tests for session negotiation and command responses."""

import asyncio
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from OWNd.connection import (
    DROP_BURST_COUNT,
    DROP_BURST_WINDOW,
    DROP_WARNING_INTERVAL,
    OWNCommandSession,
    OWNEventSession,
    OWNGateway,
    OWNSession,
)
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


class LostOnReadReader(asyncio.StreamReader):
    """A reader that looks live before the write and loses the socket on the read.

    ``feed_eof()`` before ``send()`` would model a gateway that closed the
    socket while the session sat idle, which ``send()`` now detects and reopens
    before writing. The tests below model the other case: the connection drops
    after the frame went out, while the acknowledgement is awaited.
    """

    def at_eof(self) -> bool:
        return False

    def exception(self) -> BaseException | None:
        return None

    async def readuntil(self, separator: bytes = b"\n") -> bytes:
        raise asyncio.IncompleteReadError(b"", None)


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


def test_gateway_normalizes_firmware_sequences() -> None:
    gateway = OWNGateway(
        {"address": "192.0.2.1", "modelNumber": ["2", 1, "0"]}
    )

    assert gateway.firmware == "2.1.0"

    gateway.firmware = ("3", 4)
    assert gateway.firmware == "3.4"

    gateway.firmware = []
    assert gateway.firmware is None


@pytest.mark.asyncio
async def test_legacy_authentication_fails_closed_on_unexpected_frame() -> None:
    session, _ = make_session()
    session._read_frame = AsyncMock(
        side_effect=["*#*1##", "*#123456789##", "*99*0##"]
    )

    result = await session._negotiate()

    assert result == {"Success": False, "Message": "negotiation_error"}


@pytest.mark.asyncio
async def test_non_ascii_password_is_rejected_before_writing() -> None:
    session, writer = make_session(password="not_ascii_\u1234_pw")

    result = await session._negotiate()

    assert result == {"Success": False, "Message": "password_error"}
    assert writer.written == []


@pytest.mark.asyncio
@pytest.mark.parametrize("session_cls,expected_init_frame", [
    (OWNCommandSession, b"*99*0##"),
    (OWNEventSession, b"*99*1##"),
])
async def test_alphanumeric_password_succeeds_hmac_sha1(session_cls, expected_init_frame) -> None:
    """Verify modern gateways (e.g. F454) accept alphanumeric passwords under HMAC-SHA1."""
    pw = "F454_alpha_Pass_123!"
    session, writer = make_session(session_type=session_cls, password=pw, model="F454")
    nonce_a = "1234567890123456789012345678901234567890"

    async def read_frame_side_effect(timeout: float = 0.0) -> str:
        call_count = session._read_frame.await_count
        if call_count == 1:
            return "*#*1##"
        elif call_count == 2:
            return "*98*1##"  # SHA-1 challenge
        elif call_count == 3:
            return f"*#{nonce_a}##"
        else:
            last_written = writer.written[-1].decode()
            parts = last_written.strip("*#").split("*")
            rb = parts[0]
            server_hmac = session._decode_hmac_response("sha1", pw, nonce_a, rb)
            return f"*#{server_hmac}##"

    session._read_frame = AsyncMock(side_effect=read_frame_side_effect)

    result = await session._negotiate()

    assert result == {"Success": True, "Message": None}
    assert writer.written[0] == expected_init_frame
    assert writer.written[1] == b"*#*1##"
    assert writer.written[-1] == b"*#*1##"


@pytest.mark.asyncio
@pytest.mark.parametrize("session_cls,expected_init_frame", [
    (OWNCommandSession, b"*99*0##"),
    (OWNEventSession, b"*99*1##"),
])
async def test_alphanumeric_password_succeeds_hmac_sha256(session_cls, expected_init_frame) -> None:
    """Verify modern gateways accept complex alphanumeric passwords under HMAC-SHA256."""
    pw = "MyHomeServer1_ComplexPass#2026"
    session, writer = make_session(session_type=session_cls, password=pw, model="MyHomeServer1")
    nonce_a = "9876543210987654321098765432109876543210"

    async def read_frame_side_effect(timeout: float = 0.0) -> str:
        call_count = session._read_frame.await_count
        if call_count == 1:
            return "*#*1##"
        elif call_count == 2:
            return "*98*2##"  # SHA-256 challenge
        elif call_count == 3:
            return f"*#{nonce_a}##"
        else:
            last_written = writer.written[-1].decode()
            parts = last_written.strip("*#").split("*")
            rb = parts[0]
            server_hmac = session._decode_hmac_response("sha256", pw, nonce_a, rb)
            return f"*#{server_hmac}##"

    session._read_frame = AsyncMock(side_effect=read_frame_side_effect)

    result = await session._negotiate()

    assert result == {"Success": True, "Message": None}
    assert writer.written[0] == expected_init_frame
    assert writer.written[1] == b"*#*1##"
    assert writer.written[-1] == b"*#*1##"


@pytest.mark.asyncio
async def test_alphanumeric_password_rejected_on_legacy_nonce() -> None:
    """Verify legacy numeric gateways reject alphanumeric passwords gracefully with password_error."""
    session, writer = make_session(session_type=OWNCommandSession, password="not-a-number", model="MH200N")
    session._read_frame = AsyncMock(
        side_effect=["*#*1##", "*#123456789##"]
    )

    result = await session._negotiate()

    assert result == {"Success": False, "Message": "password_error"}
    # Sent initial command session request, but stopped before sending malformed legacy password
    assert writer.written == [b"*99*0##"]


def test_gateway_password_normalization() -> None:
    """Verify OWNGateway normalizes passwords across integer, string, empty, and None inputs."""
    gw1 = OWNGateway({"address": "10.0.0.1", "password": 12345})
    assert gw1.password == "12345"

    gw2 = OWNGateway({"address": "10.0.0.1", "password": "F454Password"})
    assert gw2.password == "F454Password"

    gw3 = OWNGateway({"address": "10.0.0.1", "password": ""})
    assert gw3.password is None

    gw4 = OWNGateway({"address": "10.0.0.1", "password": None})
    assert gw4.password is None

    gw4.password = 99999
    assert gw4.password == "99999"
    gw4.password = "alpha_key"
    assert gw4.password == "alpha_key"
    gw4.password = ""
    assert gw4.password is None
    gw4.password = None
    assert gw4.password is None


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
    with patch("OWNd.connection.session.NEGOTIATION_TOTAL_TIMEOUT", 0.01):
        result = await session._negotiate()

    assert result == {"Success": False, "Message": "negotiation_timeout"}


@pytest.mark.asyncio
async def test_temporary_test_session_always_closes() -> None:
    session, writer = make_session()
    session._negotiate = AsyncMock(
        side_effect=asyncio.IncompleteReadError(partial=b"", expected=1)
    )

    with patch(
        "OWNd.connection.session.asyncio.open_connection",
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
        patch("OWNd.connection.command_session.COMMAND_RESPONSE_MAX_FRAMES", 3),
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
    session._stream_reader = LostOnReadReader()

    with patch.object(session, "connect", new_callable=AsyncMock) as connect:
        result = await session.send("*1*1*11##")

    assert result is None
    assert writer.written == [b"*1*1*11##"]
    connect.assert_not_awaited()


@pytest.mark.asyncio
async def test_disconnected_status_request_retries_once() -> None:
    session, original_writer = make_session(OWNCommandSession)
    assert isinstance(session, OWNCommandSession)
    session._stream_reader = LostOnReadReader()

    retry_writer = FakeWriter()

    async def reconnect() -> dict:
        session._stream_reader = LostOnReadReader()
        session._stream_writer = retry_writer  # type: ignore[assignment]
        return {"Success": True, "Message": None}

    with patch.object(session, "connect", side_effect=reconnect) as connect:
        result = await session.send("*#1*0##", is_status_request=True)

    assert result is None
    connect.assert_awaited_once()
    assert original_writer.written == [b"*#1*0##"]
    assert retry_writer.written == [b"*#1*0##"]


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "frame",
    [
        "*1*1*11##",
        "*#4*000*0*0215##",
        "*#4*000*#0*0215##",
    ],
)
async def test_written_non_query_with_status_request_flag_is_not_replayed_after_lost_ack(
    frame: str,
) -> None:
    session, writer = make_session(OWNCommandSession)
    assert isinstance(session, OWNCommandSession)
    session._stream_reader = LostOnReadReader()

    with patch.object(session, "connect", new_callable=AsyncMock) as connect:
        result = await session.send(frame, is_status_request=True)

    assert result is None
    assert writer.written == [frame.encode()]
    connect.assert_not_awaited()


@pytest.mark.asyncio
async def test_disconnected_dimension_request_retries_once() -> None:
    session, original_writer = make_session(OWNCommandSession)
    assert isinstance(session, OWNCommandSession)
    session._stream_reader = LostOnReadReader()

    retry_writer = FakeWriter()

    async def reconnect() -> dict[str, object]:
        session._stream_reader = LostOnReadReader()
        session._stream_writer = retry_writer  # type: ignore[assignment]
        return {"Success": True, "Message": None}

    with patch.object(session, "connect", side_effect=reconnect) as connect:
        result = await session.send("*#4*000*0##", is_status_request=True)

    assert result is None
    connect.assert_awaited_once()
    assert original_writer.written == [b"*#4*000*0##"]
    assert retry_writer.written == [b"*#4*000*0##"]


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
async def test_rejected_status_request_is_not_retried() -> None:
    # A NACK is the gateway's answer, not a transport failure: sending the
    # request again only repeats it (~2 s each on an MH200N, MyHOME#425).
    session, writer = make_session(OWNCommandSession)
    assert isinstance(session, OWNCommandSession)
    logger = MagicMock()
    session._logger = logger
    session._read_frame = AsyncMock(side_effect=["*#*0##", "*#*0##"])

    result = await session.send("*#16*0##", is_status_request=True)

    assert result is None
    assert writer.written == [b"*#16*0##"]
    logger.error.assert_not_called()
    logger.debug.assert_any_call(
        "%s Gateway rejected status request %s (NACK, %s response(s)). Subsystem or device may not be present.",
        session._log_id,
        "*#16*0##",
        0,
    )


@pytest.mark.asyncio
async def test_nacked_command_is_still_retried_once() -> None:
    session, writer = make_session(OWNCommandSession)
    assert isinstance(session, OWNCommandSession)
    session._read_frame = AsyncMock(side_effect=["*#*0##", "*#*1##"])

    result = await session.send("*1*1*11##")

    assert result is True
    assert writer.written == [b"*1*1*11##", b"*1*1*11##"]


@pytest.mark.asyncio
async def test_event_connection_loss_is_logged_at_debug() -> None:
    """Routine event session drops are logged at DEBUG to avoid HA log spam."""
    session, _ = make_session(OWNEventSession)
    assert isinstance(session, OWNEventSession)
    logger = MagicMock()
    session._logger = logger
    session._stream_reader = AsyncMock()
    session._stream_reader.readuntil = AsyncMock(
        side_effect=asyncio.IncompleteReadError(b"", 0)
    )
    session._reconnect = AsyncMock(return_value={"Success": True})

    result = await session.get_next()

    assert result is None
    session._reconnect.assert_awaited_once()
    logger.warning.assert_not_called()
    logger.debug.assert_any_call(
        "%s Event connection lost, reconnecting...", session._log_id
    )


@pytest.mark.asyncio
async def test_event_connection_loss_oversized_frame_is_warning() -> None:
    """An over-long frame is a protocol signal, not a session recycle."""
    session, _ = make_session(OWNEventSession)
    logger = MagicMock()
    session._logger = logger
    session._stream_reader = AsyncMock()
    session._stream_reader.readuntil = AsyncMock(
        side_effect=asyncio.LimitOverrunError("overrun", 0)
    )
    session._reconnect = AsyncMock(return_value={"Success": True})

    result = await session.get_next()

    assert result is None
    session._reconnect.assert_awaited_once()
    logger.warning.assert_any_call(
        "%s Received oversized or garbage frame, dropping connection and reconnecting...",
        session._log_id,
    )


def _fake_clock(*times: float):
    """Patch only the module's ``time`` so asyncio's own loop clock is untouched."""
    it = iter(times)
    return patch(
        "OWNd.connection.event_session.time",
        SimpleNamespace(monotonic=lambda: next(it)),
    )


def _dropping_event_session() -> tuple[OWNEventSession, MagicMock]:
    session, _ = make_session(OWNEventSession)
    assert isinstance(session, OWNEventSession)
    logger = MagicMock()
    session._logger = logger
    session._stream_reader = AsyncMock()
    session._stream_reader.readuntil = AsyncMock(
        side_effect=asyncio.IncompleteReadError(b"", 0)
    )
    session._reconnect = AsyncMock(return_value={"Success": True})
    return session, logger


BURST_WARNING = "%s Event connection dropped %d times in %.0fs; network may be unstable. Reconnecting..."


@pytest.mark.asyncio
async def test_event_connection_drop_burst_is_warning_on_fresh_host() -> None:
    """A burst warns even when monotonic() is small (host up < 1 h)."""
    session, logger = _dropping_event_session()
    # Fresh boot: monotonic() well below DROP_WARNING_INTERVAL. A 0.0 sentinel
    # for "never warned" would silently suppress the warning here.
    with _fake_clock(100.0, 100.5, 101.0, 101.5):
        for _ in range(DROP_BURST_COUNT - 1):
            await session.get_next()
            logger.warning.assert_not_called()
            logger.debug.assert_any_call(
                "%s Event connection lost, reconnecting...", session._log_id
            )
            logger.debug.reset_mock()

        await session.get_next()
        # Drops at 100.0 / 100.5 / 101.0: the reported span is the real 1.0s,
        # not the 600s window they were measured in.
        logger.warning.assert_called_once_with(
            BURST_WARNING, session._log_id, DROP_BURST_COUNT, 1.0
        )
        logger.warning.reset_mock()

        # Another drop right after the warning stays quiet (hourly rate limit).
        await session.get_next()
        logger.warning.assert_not_called()
        logger.debug.assert_any_call(
            "%s Event connection lost, reconnecting...", session._log_id
        )

    assert session._reconnect.await_count == DROP_BURST_COUNT + 1


@pytest.mark.asyncio
async def test_event_connection_drop_burst_reports_real_span() -> None:
    """A slow burst reports its own span, distinguishing it from a fast one."""
    session, logger = _dropping_event_session()
    t0 = 5000.0
    spread = 200.0
    # Spread over most of DROP_BURST_WINDOW, but still inside it.
    assert spread * (DROP_BURST_COUNT - 1) < DROP_BURST_WINDOW
    with _fake_clock(*(t0 + i * spread for i in range(DROP_BURST_COUNT))):
        for _ in range(DROP_BURST_COUNT):
            await session.get_next()

    logger.warning.assert_called_once_with(
        BURST_WARNING,
        session._log_id,
        DROP_BURST_COUNT,
        spread * (DROP_BURST_COUNT - 1),
    )


@pytest.mark.asyncio
async def test_event_connection_drops_outside_window_stay_debug() -> None:
    """Hourly session recycling never accumulates into a burst."""
    session, logger = _dropping_event_session()
    with _fake_clock(*(float(i * 3460) for i in range(10))):
        for _ in range(10):
            await session.get_next()

    logger.warning.assert_not_called()
    assert logger.debug.call_count == 10
    assert len(session._recent_drops) == 1


@pytest.mark.asyncio
async def test_event_connection_drop_burst_warns_again_after_interval() -> None:
    """A persistent flap is re-reported once per DROP_WARNING_INTERVAL."""
    session, logger = _dropping_event_session()
    t0 = 5000.0
    # Burst one at t0, burst two well after the warning interval has elapsed.
    times = [t0, t0 + 1, t0 + 2]
    t1 = t0 + DROP_WARNING_INTERVAL + 5
    times += [t1, t1 + 1, t1 + 2]
    with _fake_clock(*times):
        for _ in times:
            await session.get_next()

    assert logger.warning.call_count == 2
    assert session._last_drop_warning == t1 + 2


@pytest.mark.asyncio
async def test_event_connection_drop_tracker_survives_reconnect() -> None:
    """_reconnect() goes through connect(); that must not wipe the burst tracker."""
    session, logger = _dropping_event_session()
    session._reconnect = AsyncMock(side_effect=session.connect)

    with (
        patch.object(OWNSession, "connect", AsyncMock(return_value=None)),
        _fake_clock(100.0, 100.5, 101.0),
    ):
        for _ in range(DROP_BURST_COUNT):
            await session.get_next()

    logger.warning.assert_called_once_with(
        BURST_WARNING, session._log_id, DROP_BURST_COUNT, 1.0
    )


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


@pytest.mark.asyncio
async def test_command_session_rejects_invalid_or_empty_message() -> None:
    from OWNd.message import OWNMessage, OWNSignaling

    session, _ = make_session(OWNCommandSession)
    assert isinstance(session, OWNCommandSession)
    logger = MagicMock()
    session._logger = logger

    assert await session.send(OWNMessage("not-a-frame")) is None
    assert await session.send("not-a-frame") is None
    assert await session.send("   ") is None
    assert await session.send(OWNSignaling("*#*1##")) is None
    assert await session.send("*#*1##") is None
    assert await session.send("*#123456789##") is None
    assert logger.error.call_count == 6


@pytest.mark.asyncio
async def test_typed_exceptions_and_last_error() -> None:
    from OWNd import (
        OWNAuthError,
        OWNConnectionError,
        OWNError,
        OWNNackError,
        OWNProtocolError,
        OWNTimeoutError,
    )

    session, _ = make_session(OWNCommandSession)
    assert isinstance(session, OWNCommandSession)

    # 1. Invalid frame -> OWNProtocolError
    with pytest.raises(OWNProtocolError) as exc_info:
        await session.send("not-a-frame", raise_on_error=True)
    assert isinstance(session.last_error, OWNProtocolError)
    assert exc_info.value.frame == "not-a-frame"

    # 2. NACK response -> OWNNackError
    assert session._stream_reader is not None
    session._stream_reader.feed_data(b"*#*0##")
    with pytest.raises(OWNNackError) as nack_exc:
        await session.send("*#1*11##", is_status_request=True, raise_on_error=True)
    assert isinstance(session.last_error, OWNNackError)
    assert nack_exc.value.frame == "*#1*11##"

    # 3. Timeout response -> OWNTimeoutError (subclass of OWNConnectionError and OWNError)
    session2, _ = make_session(OWNCommandSession)
    assert isinstance(session2, OWNCommandSession)
    session2._read_command_response = AsyncMock(side_effect=TimeoutError("Timed out"))  # type: ignore[method-assign]
    with pytest.raises(OWNTimeoutError):
        await session2.send("*1*1*11##", raise_on_error=True)
    assert isinstance(session2.last_error, OWNTimeoutError)
    assert isinstance(session2.last_error, OWNConnectionError)
    assert isinstance(session2.last_error, OWNError)

    # 4. Auth failure on connect(raise_on_error=True) -> OWNAuthError
    auth_seen: list[OWNAuthError] = []
    session3, _ = make_session(OWNCommandSession)
    session3.on_auth_error = auth_seen.append
    with (
        patch(
            "OWNd.connection.session.asyncio.open_connection",
            new=AsyncMock(return_value=(MagicMock(), MagicMock())),
        ),
        patch.object(
            session3,
            "_negotiate",
            new=AsyncMock(
                return_value={"Success": False, "Message": "password_error"}
            ),
        ),
    ):
        with pytest.raises(OWNAuthError):
            await session3.connect(raise_on_error=True)
    assert len(auth_seen) == 1
    assert auth_seen[0].reason == "password_error"
    assert isinstance(session3.last_error, OWNAuthError)


@pytest.mark.asyncio
async def test_event_session_raise_on_auth_error() -> None:
    from OWNd import OWNAuthError

    auth_seen: list[OWNAuthError] = []
    session, _ = make_session(OWNEventSession)
    assert isinstance(session, OWNEventSession)
    session.on_auth_error = auth_seen.append
    session._stream_reader = None
    session._stream_writer = None

    with (
        patch(
            "OWNd.connection.session.asyncio.open_connection",
            new=AsyncMock(return_value=(MagicMock(), MagicMock())),
        ),
        patch.object(
            session,
            "_negotiate",
            new=AsyncMock(
                return_value={"Success": False, "Message": "password_required"}
            ),
        ),
    ):
        with pytest.raises(OWNAuthError) as exc_info:
            await session.get_next(raise_on_auth_error=True)

    assert exc_info.value.reason == "password_required"
    assert len(auth_seen) == 1


@pytest.mark.asyncio
async def test_send_when_disconnected_uses_single_connect_attempt_and_cooldown() -> None:
    session, _ = make_session(OWNCommandSession)
    assert isinstance(session, OWNCommandSession)
    session._stream_reader = None
    session._stream_writer = None

    open_conn = AsyncMock(side_effect=ConnectionRefusedError)
    with patch("OWNd.connection.session.asyncio.open_connection", new=open_conn):
        # First send() attempts only 1 TCP connect (not 5 with backoff)
        assert await session.send("*1*1*11##") is None
        assert open_conn.await_count == 1

        # Second send() within cooldown window fails fast without calling open_connection again
        assert await session.send("*1*1*12##") is None
        assert open_conn.await_count == 1


def test_gateway_clock_builders_accept_tzinfo() -> None:
    import datetime as dt
    from OWNd.message import OWNGatewayCommand

    tz = dt.timezone(dt.timedelta(hours=2))
    cmd_dt = OWNGatewayCommand.set_datetime_to_now(tz)
    cmd_d = OWNGatewayCommand.set_date_to_today(tz)
    cmd_t = OWNGatewayCommand.set_time_to_now(tz)
    assert str(cmd_dt).startswith("*#13**#22*")
    assert "*002*" in str(cmd_dt)
    assert str(cmd_d).startswith("*#13**#1*0")
    assert str(cmd_t).startswith("*#13**#0*")
    assert str(cmd_t).endswith("*002##")
    with pytest.raises(ValueError, match="time_zone must be a datetime.tzinfo"):
        OWNGatewayCommand.set_datetime_to_now(123)  # type: ignore[arg-type]


@pytest.mark.asyncio
async def test_session_and_command_error_paths_with_raise_on_error() -> None:
    from OWNd import (
        OWNAuthError,
        OWNConnectionError,
        OWNNackError,
        OWNProtocolError,
        OWNTimeoutError,
    )
    from OWNd.connection.session import _negotiation_error_to_exception
    from OWNd.message import OWNSignaling

    # _negotiation_error_to_exception branches
    assert isinstance(_negotiation_error_to_exception("negotiation_timeout"), OWNTimeoutError)
    assert isinstance(_negotiation_error_to_exception("negotiation_refused"), OWNNackError)
    assert isinstance(_negotiation_error_to_exception("negotiation_error"), OWNProtocolError)
    assert isinstance(_negotiation_error_to_exception(None), OWNConnectionError)

    # on_auth_error getter & exception resilience in _notify_auth_error
    session, _ = make_session(OWNCommandSession)
    assert session.on_auth_error is None

    def broken_cb(err: OWNAuthError) -> None:
        raise RuntimeError("callback boom")

    session.on_auth_error = broken_cb
    assert session.on_auth_error is broken_cb
    session._notify_auth_error(OWNAuthError("bad pw", reason="password_error"))
    saved_logger = session._logger
    session._logger = None  # type: ignore[assignment]
    session._notify_auth_error(OWNAuthError("bad pw", reason="password_error"))
    session._logger = saved_logger

    # test_connection(raise_on_error=True) refused after 3 attempts
    with (
        patch(
            "OWNd.connection.session.asyncio.open_connection",
            new=AsyncMock(side_effect=ConnectionRefusedError),
        ),
        patch("OWNd.connection.session.asyncio.sleep", new=AsyncMock()),
    ):
        with pytest.raises(OWNConnectionError):
            await session.test_connection(raise_on_error=True)

    # test_connection(raise_on_error=True) negotiation failure (auth & non-auth)
    auth_called: list[OWNAuthError] = []
    session.on_auth_error = auth_called.append
    with (
        patch(
            "OWNd.connection.session.asyncio.open_connection",
            new=AsyncMock(return_value=(MagicMock(), MagicMock())),
        ),
        patch.object(
            session,
            "_negotiate",
            new=AsyncMock(return_value={"Success": False, "Message": "password_error"}),
        ),
    ):
        with pytest.raises(OWNAuthError):
            await session.test_connection(raise_on_error=True)
        res_no_raise = await session.test_connection(raise_on_error=False)
        assert res_no_raise == {"Success": False, "Message": "password_error"}
    assert len(auth_called) == 2

    with (
        patch(
            "OWNd.connection.session.asyncio.open_connection",
            new=AsyncMock(return_value=(MagicMock(), MagicMock())),
        ),
        patch.object(
            session,
            "_negotiate",
            new=AsyncMock(return_value={"Success": False, "Message": "negotiation_refused"}),
        ),
    ):
        with pytest.raises(OWNNackError):
            await session.test_connection(raise_on_error=True)

    # connect(raise_on_error=True) with fatal non-auth negotiation error
    with (
        patch(
            "OWNd.connection.session.asyncio.open_connection",
            new=AsyncMock(return_value=(MagicMock(), MagicMock())),
        ),
        patch.object(
            session,
            "_negotiate",
            new=AsyncMock(return_value={"Success": False, "Message": "negotiation_error"}),
        ),
    ):
        with pytest.raises(OWNProtocolError):
            await session.connect(raise_on_error=True)

    # test_connection(raise_on_error=True) ConnectionResetError and TimeoutError during _negotiate
    with (
        patch(
            "OWNd.connection.session.asyncio.open_connection",
            new=AsyncMock(return_value=(MagicMock(), MagicMock())),
        ),
        patch.object(session, "_negotiate", new=AsyncMock(side_effect=ConnectionResetError)),
    ):
        with pytest.raises(OWNConnectionError) as rst_exc:
            await session.test_connection(raise_on_error=True)
        assert rst_exc.value.reason == "password_retry"

    with (
        patch(
            "OWNd.connection.session.asyncio.open_connection",
            new=AsyncMock(return_value=(MagicMock(), MagicMock())),
        ),
        patch.object(session, "_negotiate", new=AsyncMock(side_effect=TimeoutError("slow"))),
    ):
        with pytest.raises(OWNTimeoutError):
            await session.test_connection(raise_on_error=True)

    # connect(raise_on_error=True) exhausting max_attempts, and send() reconnect + cooldown raising
    cmd_sess, _ = make_session(OWNCommandSession)
    assert isinstance(cmd_sess, OWNCommandSession)
    cmd_sess._stream_reader = None
    cmd_sess._stream_writer = None
    with patch(
        "OWNd.connection.session.asyncio.open_connection",
        new=AsyncMock(side_effect=ConnectionRefusedError),
    ):
        cmd_sess._connect_max_attempts_override = 1
        with pytest.raises(OWNConnectionError):
            await cmd_sess.connect(raise_on_error=True)
        cmd_sess._connect_max_attempts_override = None
        with pytest.raises(OWNConnectionError):
            await cmd_sess.send("*1*1*11##", raise_on_error=True)
        # Second call hits SEND_RECONNECT_COOLDOWN with raise_on_error=True
        with pytest.raises(OWNConnectionError):
            await cmd_sess.send("*1*1*12##", raise_on_error=True)

    # send_to_gateway(raise_on_error=True)
    gw_obj = OWNGateway({"address": "127.0.0.1", "port": 20000})
    with (
        patch.object(OWNCommandSession, "connect", new=AsyncMock(return_value={"Success": True})) as m_conn,
        patch.object(OWNCommandSession, "send", new=AsyncMock(return_value=True)) as m_send,
    ):
        assert await OWNCommandSession.send_to_gateway("*1*1*11##", gw_obj, raise_on_error=True) is True
        m_conn.assert_awaited_once_with(raise_on_error=True)
        m_send.assert_awaited_once_with("*1*1*11##", raise_on_error=True)

    # send(raise_on_error=True) on unexpected signaling, connection lost, and generic crash
    s_proto, _ = make_session(OWNCommandSession)
    assert isinstance(s_proto, OWNCommandSession)
    s_proto._read_command_response = AsyncMock(return_value=(OWNSignaling("*#*2##"), []))  # type: ignore[method-assign]
    with pytest.raises(OWNProtocolError):
        await s_proto.send("*1*1*11##", raise_on_error=True)

    s_lost, _ = make_session(OWNCommandSession)
    assert isinstance(s_lost, OWNCommandSession)
    s_lost._stream_reader = LostOnReadReader()
    with pytest.raises(OWNConnectionError) as lost_exc:
        await s_lost.send("*1*1*11##", raise_on_error=True)
    assert lost_exc.value.reason == "connection_lost"

    s_crash, _ = make_session(OWNCommandSession)
    assert isinstance(s_crash, OWNCommandSession)
    s_crash._read_command_response = AsyncMock(side_effect=RuntimeError("boom"))  # type: ignore[method-assign]
    with pytest.raises(OWNConnectionError) as crash_exc:
        await s_crash.send("*1*1*11##", raise_on_error=True)
    assert crash_exc.value.reason == "session_crash"

    # Event session _maybe_raise_auth_error when _reconnect returns dict without setting _last_error
    ev_sess, _ = make_session(OWNEventSession)
    assert isinstance(ev_sess, OWNEventSession)
    ev_sess._stream_reader = None
    ev_sess._stream_writer = None
    with patch.object(
        ev_sess,
        "_reconnect",
        new=AsyncMock(return_value={"Success": False, "Message": "connection_error"}),
    ):
        assert await ev_sess.get_next(raise_on_auth_error=True) is None
    with patch.object(
        ev_sess,
        "_reconnect",
        new=AsyncMock(return_value={"Success": False, "Message": "password_error"}),
    ):
        with pytest.raises(OWNAuthError):
            await ev_sess.get_next(raise_on_auth_error=True)


