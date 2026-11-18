"""``send()`` does not log in again right after the gateway refused the password.

Every ``send()`` on a session without streams reconnects, with a 2 s cooldown
after a failure. For a refused login that meant three refused logins in 4.4 s
from a caller that kept sending, and two per ``send_to_gateway()`` call. The
HMAC document: "Every time 3 handshakes procedures fail within 60 seconds, the
authentication service have to be disabled for 60 seconds" (Hmac Specification
1.1, "Simple Authentication Mode (SAM)"). The event session already waits
``RECONNECT_PAUSE_FATAL`` (60 s) before it logs in again.
"""
from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from OWNd.connection import (
    RECONNECT_PAUSE_FATAL,
    SEND_AUTH_COOLDOWN,
    SEND_RECONNECT_COOLDOWN,
    OWNAuthError,
    OWNCommandSession,
    OWNConnectionError,
    OWNGateway,
    OWNProtocolError,
)

MODULE = "OWNd.connection.command_session"


def make_session() -> OWNCommandSession:
    gateway = OWNGateway(
        {"address": "192.0.2.1", "port": 20000, "password": "madeup1", "modelName": "F461"}
    )
    session = OWNCommandSession(gateway=gateway)
    session._logger = MagicMock()
    return session


def refuse_logins(reason: str = "password_error") -> tuple[AsyncMock, AsyncMock]:
    """Patch the socket and the negotiation: TCP opens, the login is refused."""
    writer = MagicMock()
    writer.wait_closed = AsyncMock()
    open_connection = AsyncMock(return_value=(MagicMock(), writer))
    negotiate = AsyncMock(return_value={"Success": False, "Message": reason})
    return open_connection, negotiate


def test_auth_cooldown_is_the_event_session_pause() -> None:
    assert SEND_AUTH_COOLDOWN == RECONNECT_PAUSE_FATAL == 60
    assert SEND_AUTH_COOLDOWN > SEND_RECONNECT_COOLDOWN


@pytest.mark.asyncio
@pytest.mark.parametrize("reason", ["password_error", "password_required"])
async def test_repeated_sends_log_in_once(reason: str) -> None:
    session = make_session()
    open_connection, negotiate = refuse_logins(reason)
    clock = [1000.0]

    with (
        patch("OWNd.connection.session.asyncio.open_connection", new=open_connection),
        patch.object(session, "_negotiate", new=negotiate),
        patch(f"{MODULE}.time.monotonic", side_effect=lambda: clock[0]),
    ):
        for _ in range(6):
            assert await session.send("*#13**15##", is_status_request=True) is None
            # The refused login is what every caller is told, not
            # "connection_unavailable" on every other call.
            assert isinstance(session.last_error, OWNAuthError)
            assert session.last_error.reason == reason
            clock[0] += 1.1
        assert negotiate.await_count == 1

        # Still inside the 60 s: nothing.
        clock[0] = 1000.0 + SEND_AUTH_COOLDOWN - 0.5
        assert await session.send("*#13**15##", is_status_request=True) is None
        assert negotiate.await_count == 1

        # Past it: one new attempt, and the cooldown starts again.
        clock[0] = 1000.0 + SEND_AUTH_COOLDOWN + 0.5
        assert await session.send("*#13**15##", is_status_request=True) is None
        assert negotiate.await_count == 2
        clock[0] += 3.0
        assert await session.send("*#13**15##", is_status_request=True) is None
        assert negotiate.await_count == 2

    held = [
        call
        for call in session._logger.warning.call_args_list
        if call.args[0].startswith("%s Gateway refused the login")
    ]
    assert len(held) == 7
    assert held[0].args[2:4] == (reason, "*#13**15##")


@pytest.mark.asyncio
async def test_cooldown_raises_the_auth_error_when_asked() -> None:
    session = make_session()
    open_connection, negotiate = refuse_logins()

    with (
        patch("OWNd.connection.session.asyncio.open_connection", new=open_connection),
        patch.object(session, "_negotiate", new=negotiate),
    ):
        with pytest.raises(OWNAuthError):
            await session.send("*1*1*11##", raise_on_error=True)
        with pytest.raises(OWNAuthError) as held:
            await session.send("*1*1*11##", raise_on_error=True)
    assert held.value.reason == "password_error"
    assert negotiate.await_count == 1


@pytest.mark.asyncio
async def test_explicit_connect_tries_at_once_and_a_good_login_ends_the_cooldown() -> None:
    session = make_session()
    open_connection, negotiate = refuse_logins()

    with (
        patch("OWNd.connection.session.asyncio.open_connection", new=open_connection),
        patch.object(session, "_negotiate", new=negotiate),
    ):
        assert await session.send("*1*1*11##") is None
        assert negotiate.await_count == 1

        # The caller's own connect() is not held back (a corrected password).
        result = await session.connect()
        assert result == {"Success": False, "Message": "password_error"}
        assert negotiate.await_count == 2

        negotiate.return_value = {"Success": True, "Message": None}
        result = await session.connect()
        assert result == {"Success": True, "Message": None}
        assert session._refused_login is None
        assert session._last_reconnect_failure is None


@pytest.mark.asyncio
async def test_explicit_connect_that_raises_starts_the_cooldown_too() -> None:
    session = make_session()
    open_connection, negotiate = refuse_logins()

    with (
        patch("OWNd.connection.session.asyncio.open_connection", new=open_connection),
        patch.object(session, "_negotiate", new=negotiate),
    ):
        with pytest.raises(OWNAuthError):
            await session.connect(raise_on_error=True)
        assert await session.send("*1*1*11##") is None
    assert negotiate.await_count == 1
    assert isinstance(session.last_error, OWNAuthError)


@pytest.mark.asyncio
async def test_send_to_gateway_logs_in_once() -> None:
    """connect() then send(): the send used to log in a second time."""
    gateway = OWNGateway(
        {"address": "192.0.2.1", "port": 20000, "password": "madeup1", "modelName": "F461"}
    )
    open_connection, negotiate = refuse_logins()

    with (
        patch("OWNd.connection.session.asyncio.open_connection", new=open_connection),
        patch.object(OWNCommandSession, "_negotiate", new=negotiate),
    ):
        assert await OWNCommandSession.send_to_gateway("*#13**15##", gateway) is None

    assert negotiate.await_count == 1
    assert open_connection.await_count == 1


@pytest.mark.asyncio
async def test_failed_hmac_check_is_held_like_a_refused_password() -> None:
    session = make_session()
    open_connection, negotiate = refuse_logins("negotiation_error")

    with (
        patch("OWNd.connection.session.asyncio.open_connection", new=open_connection),
        patch.object(session, "_negotiate", new=negotiate),
    ):
        assert await session.send("*1*1*11##") is None
        assert await session.send("*1*1*11##") is None
    assert negotiate.await_count == 1
    assert isinstance(session.last_error, OWNProtocolError)
    assert session.last_error.reason == "negotiation_error"


@pytest.mark.asyncio
async def test_unreachable_gateway_keeps_the_short_cooldown() -> None:
    """Not a login problem: 2 s, and ``connection_unavailable`` in between, as before."""
    session = make_session()
    clock = [1000.0]

    with (
        patch(
            "OWNd.connection.session.asyncio.open_connection",
            new=AsyncMock(side_effect=ConnectionRefusedError),
        ) as open_connection,
        patch(f"{MODULE}.time.monotonic", side_effect=lambda: clock[0]),
    ):
        assert await session.send("*1*1*11##") is None
        assert session._refused_login is None
        clock[0] += 1.0
        assert await session.send("*1*1*11##") is None
        assert isinstance(session.last_error, OWNConnectionError)
        assert session.last_error.reason == "connection_unavailable"
        assert open_connection.await_count == 1
        clock[0] += SEND_RECONNECT_COOLDOWN
        assert await session.send("*1*1*11##") is None
        assert open_connection.await_count == 2
