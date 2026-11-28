"""Command queue pacing, synchronized send, and request/reply tracking."""

from __future__ import annotations

import asyncio
import contextlib
import contextvars
import logging
import time
from collections.abc import Callable, Mapping
from typing import Any

from .gateway import OWNGateway
from .session import (
    COMMAND_RESPONSE_MAX_FRAMES,
    COMMAND_TIMEOUT,
    KEEPALIVE_FRAME,
    KEEPALIVE_INTERVAL,
    OWNSession,
    RECONNECT_PAUSE_FATAL,
    _CONNECT_MAX_ATTEMPTS,
    _FATAL_NEGOTIATION_ERRORS,
    _negotiation_error_to_exception,
)
from ..exceptions import (
    OWNAuthError,
    OWNConnectionError,
    OWNError,
    OWNNackError,
    OWNProtocolError,
    OWNTimeoutError,
)
from ..message import (
    OWNMessage,
    OWNSignaling,
    is_who18_dimension_52_crash_form,
    is_who22_bare_power_frame,
    is_who4_dimension_22_crash_form,
)

# Why every send path refuses a WHO 4 dimension 22 frame without an actuator
# token (see ``OWNd.message.is_who4_dimension_22_crash_form``): the gateway
# never gets the frame.
DESTRUCTIVE_FRAME_REASON = (
    "WHO 4 dimension 22 without an actuator token in WHERE crashes the "
    "thermoregulation daemon (bt_termo) on Linux IP gateways"
)
# Same treatment for a WHO 18 dimension 52 frame outside the tested forms
# (``OWNd.message.is_who18_dimension_52_crash_form``): a four-digit year such
# as ``52#2026#10`` crashed the F460 020012, F461 020011 and 3488 030205 in the
# firmware oracle (``ownd-audit-frames``, emulated firmware).
DESTRUCTIVE_DIM52_REASON = (
    "WHO 18 dimension 52 outside its tested forms (a four-digit year such as "
    "52#2026#10) crashes the F460, F461 and 3488 gateways after the telegram "
    "went out (own-firmware-oracle ownd-audit-frames)"
)


# Same treatment for the bare WHO 22 power frame
# (``OWNd.message.is_who22_bare_power_frame``).
DESTRUCTIVE_WHO22_REASON = (
    "the bare WHO 22 power frame (WHAT 0 / 1 without #mmtype#area, not a published "
    "form) crashes the sound daemon on eight of the twelve pinned emulated gateways; use "
    "turn_on_with_source / "
    "route_source / turn_off_atomic"
)


def destructive_frame_reason(frame: str) -> str | None:
    """The refusal reason when ``frame`` is one every send path refuses, else ``None``.

    The one classifier behind ``OWNCommandSession.send``, ``send_to_gateway``
    and ``AsyncSerialTransport.send`` (``AsyncTcpTransport.send`` goes through
    the session), so the paths cannot drift: the WHO 4 dimension 22 crash
    forms, the WHO 18 dimension 52 crash forms and the bare WHO 22 power frame.
    """
    if is_who4_dimension_22_crash_form(frame):
        return DESTRUCTIVE_FRAME_REASON
    if is_who18_dimension_52_crash_form(frame):
        return DESTRUCTIVE_DIM52_REASON
    if is_who22_bare_power_frame(frame):
        return DESTRUCTIVE_WHO22_REASON
    return None


def destructive_frame_error(
    frame: str, reason: str = DESTRUCTIVE_FRAME_REASON
) -> OWNProtocolError:
    """The error every send path raises or records for a frame known to crash a gateway."""
    return OWNProtocolError(
        f"Refusing to send `{frame}`: {reason}",
        frame=frame,
        reason="destructive_frame",
    )


# Cooldown window (seconds) after an in-send() reconnect attempt fails, so
# concurrent callers queued behind _send_lock fail fast instead of each
# repeating a socket connect attempt while the gateway is unreachable.
SEND_RECONNECT_COOLDOWN = 2.0
# The cooldown after a login the gateway refused for good (wrong, missing or
# unusable password, failed HMAC check): the event session already waits
# RECONNECT_PAUSE_FATAL before it logs in again, and so does every implicit
# reconnect of ``send()``. A caller that kept sending used to log in again
# every SEND_RECONNECT_COOLDOWN seconds (three refused logins in 4.4 s), while
# the HMAC document says: "Every time 3 handshakes procedures fail within 60
# seconds, the authentication service have to be disabled for 60 seconds"
# (Hmac Specification 1.1, "Simple Authentication Mode (SAM)"). An explicit
# ``connect()`` still tries at once, and so does a ``send()`` after the
# gateway's address, port or password changed.
SEND_AUTH_COOLDOWN = float(RECONNECT_PAUSE_FATAL)

# Per-task active ``OWNCommandSession.connect()`` call ``(session, seq)`` so
# ``_on_fatal_negotiation_error`` attributes a refusal strictly to the ``connect()``
# running in the current task (never to an overlapping ``connect()`` or a
# concurrent ``test_connection()``).
_ACTIVE_CONNECT: contextvars.ContextVar[tuple[OWNCommandSession, int] | None] = (
    contextvars.ContextVar("_ACTIVE_CONNECT", default=None)
)


class OWNCommandSession(OWNSession):
    def __init__(
        self,
        gateway: OWNGateway | None = None,
        logger: logging.Logger | None = None,
        on_state_change: Callable[[bool], None] | None = None,
        on_auth_error: Callable[[OWNAuthError], Any] | None = None,
    ):
        super().__init__(
            gateway=gateway,
            connection_type="command",
            logger=logger,
            on_state_change=on_state_change,
            on_auth_error=on_auth_error,
        )
        # Serializes concurrent senders sharing this session (e.g. the
        # keepalive loop and a regular command): interleaved write/read pairs
        # on the same stream would steal each other's acknowledgements.
        self._send_lock = asyncio.Lock()
        self._last_reconnect_failure: float | None = None
        # The reason of the last connect() the gateway refused for good and
        # the address, port and password the gateway object held when the
        # refusal became known; ``send()``
        # reports it without logging in again until SEND_AUTH_COOLDOWN has
        # passed, connect() succeeds, or one of the three changes.
        self._refused_login_reason: str | None = None
        self._refused_login_target: tuple[object, object, object] | None = None
        # Number of the latest connect() started on this session.
        self._connect_seq: int = 0
        # The connect() whose refusal the hold records.
        self._refused_login_seq: int | None = None

    def _clear_refused_login(self) -> None:
        """Clear any recorded login-refusal hold."""
        self._last_reconnect_failure = None
        self._refused_login_reason = None
        self._refused_login_target = None
        self._refused_login_seq = None

    async def connect(
        self, *, raise_on_error: bool = False
    ) -> dict[str, Any] | None:
        self._connect_seq += 1
        seq = self._connect_seq
        if (
            self._refused_login_reason is not None
            and self._refused_login_target != self._login_target()
        ):
            self._clear_refused_login()
        token = _ACTIVE_CONNECT.set((self, seq))
        try:
            result = await super().connect(raise_on_error=raise_on_error)
        except OWNError as error:
            self._hold_refused_login(error.reason, seq)
            raise
        finally:
            _ACTIVE_CONNECT.reset(token)
        if isinstance(result, Mapping) and result.get("Success", False):
            if seq == self._connect_seq:
                self._clear_refused_login()
        elif isinstance(result, Mapping):
            self._hold_refused_login(result.get("Message"), seq)
        return result

    def _on_fatal_negotiation_error(self, reason: str, error: OWNError) -> None:
        """Record the hold before user callbacks run and before ``connect()`` yields to close streams.

        Applies to every fatal negotiation error (including ``negotiation_error``,
        which raises ``OWNProtocolError`` rather than ``OWNAuthError``).
        """
        active = _ACTIVE_CONNECT.get()
        if active is not None and active[0] is self:
            self._hold_refused_login(reason, active[1])

    def _notify_auth_error(self, error: OWNAuthError) -> None:
        """Clear ``_ACTIVE_CONNECT`` across auth callbacks so spawned tasks do not inherit it.

        Hold-arming during ``connect()`` happens in
        ``_on_fatal_negotiation_error()`` right before this hook runs, so
        ``test_connection()`` (which invokes ``_notify_auth_error()`` directly)
        can never arm ``SEND_AUTH_COOLDOWN``.
        """
        token = _ACTIVE_CONNECT.set(None)
        try:
            super()._notify_auth_error(error)
        finally:
            _ACTIVE_CONNECT.reset(token)

    def _set_connected(self, value: bool) -> None:
        """Clear ``_ACTIVE_CONNECT`` across state callbacks so spawned tasks do not inherit it."""
        token = _ACTIVE_CONNECT.set(None)
        try:
            super()._set_connected(value)
        finally:
            _ACTIVE_CONNECT.reset(token)

    def _login_target(self) -> tuple[object, object, object] | None:
        """The address, port and password a login is refused for."""
        if self._gateway is None:
            return None
        return (self._gateway.address, self._gateway.port, self._gateway.password)

    def _hold_refused_login(self, reason: object, seq: int) -> None:
        """Start the SEND_AUTH_COOLDOWN hold when ``reason`` is a login refused for good, once, and only for the latest ``connect()`` (``seq``).

        The hold records the address, port and password the gateway object holds when the refusal becomes known.
        """
        if seq != self._connect_seq or self._refused_login_seq == seq:
            return
        if isinstance(reason, str) and reason in _FATAL_NEGOTIATION_ERRORS:
            self._last_reconnect_failure = time.monotonic()
            self._refused_login_reason = reason
            self._refused_login_target = self._login_target()
            self._refused_login_seq = seq

    @classmethod
    async def send_to_gateway(
        cls,
        message: str | OWNMessage,
        gateway: OWNGateway,
        *,
        raise_on_error: bool = False,
    ) -> list[OWNMessage | str] | bool | None:
        connection = cls(gateway)
        # Refused before connect(): no socket, no handshake, no command slot
        # on a single-session gateway (MH200N, F453AV...) and no 5-attempt
        # backoff on an unreachable host for a frame that is never written.
        frame = str(message)
        reason = destructive_frame_reason(frame)
        if reason is not None:
            connection._refuse_destructive_frame(
                frame, message, raise_on_error=raise_on_error, reason=reason
            )
            return None
        try:
            if raise_on_error:
                await connection.connect(raise_on_error=True)
                return await connection.send(message, raise_on_error=True)
            result = await connection.connect()
            if not isinstance(result, Mapping) or not result.get("Success", False):
                return None
            return await connection.send(message)
        finally:
            with contextlib.suppress(Exception):
                await connection.close()

    @classmethod
    async def connect_to_gateway(
        cls, gateway: OWNGateway, *, raise_on_error: bool = False
    ) -> dict[str, Any] | None:
        connection = cls(gateway)
        try:
            return await connection.connect(raise_on_error=raise_on_error)
        finally:
            with contextlib.suppress(Exception):
                await connection.close()

    @classmethod
    async def probe_gateway(
        cls, gateway: OWNGateway, logger: logging.Logger | None = None
    ) -> bool:
        """Probe gateway responsiveness with a read-only model request."""
        connection = cls(gateway=gateway, logger=logger)
        try:
            result = await connection.connect()
            if not isinstance(result, Mapping) or not result.get("Success", False):
                return False
            response = await connection.send(
                "*#13**15##", is_status_request=True
            )
            return response is not None
        except Exception:  # noqa: BLE001 - watchdog probes must be fail-safe
            return False
        finally:
            with contextlib.suppress(Exception):
                await connection.close()

    async def keepalive(self) -> bool:
        """Send one harmless keepalive (gateway time request) on this command
        session. Returns True if the gateway acknowledged, False otherwise.

        ``send()`` already reconnects on a broken socket, so a False here means
        the gateway is genuinely unresponsive even after a reconnect attempt.
        """
        try:
            result = await self.send(KEEPALIVE_FRAME, is_status_request=True)
            return result is not None
        except Exception:  # pylint: disable=broad-except
            self._logger.exception("%s Keepalive failed.", self._log_id)
            return False

    async def run_keepalive(
        self, stop_event: asyncio.Event, interval: float = KEEPALIVE_INTERVAL
    ) -> None:
        """Background loop: ping the gateway every ``interval`` seconds until
        ``stop_event`` is set. Meant to be launched as an asyncio task."""
        self._logger.info(
            "%s Keepalive started (every %ss).", self._log_id, interval
        )
        while not stop_event.is_set():
            try:
                await asyncio.wait_for(stop_event.wait(), timeout=interval)
            except TimeoutError:
                ok = await self.keepalive()
                self._logger.debug(
                    "%s Keepalive %s.",
                    self._log_id,
                    "ok" if ok else "FAILED",
                )

    def _peer_closed(self) -> bool:
        """True when the open socket was already closed by the gateway.

        After the peer's FIN the stream reader is at EOF; after an RST it
        carries the exception and the transport is closing. Both are visible
        before any read, since the event loop delivered them while the session
        sat idle. Only asyncio's own streams are inspected: ``False`` when they
        are missing (``send()`` reopens them anyway) and for streams installed
        by hand (test doubles, which may model a lost acknowledgement by
        feeding EOF before the write), so those keep the previous behaviour.

        ``StreamReader.at_eof()`` stays false until the buffer is empty, so an
        end of stream behind unread bytes is read from the reader's private
        ``_eof`` flag, only on asyncio's own ``StreamReader`` class (a subclass
        keeps the previous behaviour). A live F461 2.0.11 closes an idle
        command session that sent nothing since its handshake that way:
        ``*#*0##`` at 30.108 s, the FIN at 30.109 s (plant capture
        2026-11-17); an F455 1.0.76 sends the FIN alone. ``send()`` then wrote
        into the dead socket and took the stale ``*#*0##`` for the answer to
        its own frame. Nothing is read from or fed to the reader here.
        """
        reader, writer = self._stream_reader, self._stream_writer
        if not isinstance(reader, asyncio.StreamReader) or not isinstance(
            writer, asyncio.StreamWriter
        ):
            return False
        if (
            reader.at_eof()
            or reader.exception() is not None
            or writer.is_closing()
        ):
            return True
        if type(reader) is asyncio.StreamReader and getattr(reader, "_eof", False):
            self._logger.debug(
                "%s Gateway sent %r and closed the idle command session.",
                self._log_id,
                bytes(getattr(reader, "_buffer", b"")),
            )
            return True
        return False

    async def _read_command_response(
        self,
    ) -> tuple[OWNSignaling, list[OWNMessage | str]]:
        """Read a bounded command response through its final ACK or NACK.

        Status and dimension frames preceding the signaling terminator are
        returned to the caller instead of being discarded.
        """
        collected: list[OWNMessage | str] = []
        async with asyncio.timeout(COMMAND_TIMEOUT):
            for _ in range(COMMAND_RESPONSE_MAX_FRAMES):
                raw_response = await self._read_frame(COMMAND_TIMEOUT)
                try:
                    resulting_message = OWNMessage.parse(
                        raw_response, gateway=self._gateway
                    )
                except (ValueError, IndexError, TypeError) as error:
                    self._logger.warning(
                        "%s Malformed command response %r: %s",
                        self._log_id,
                        raw_response,
                        error,
                    )
                    resulting_message = None
                if isinstance(resulting_message, OWNSignaling):
                    if resulting_message.is_ack() or resulting_message.is_nack():
                        return resulting_message, collected
                    self._logger.debug(
                        "%s Ignoring non-terminal signaling response `%s`.",
                        self._log_id,
                        resulting_message,
                    )
                    continue
                collected.append(resulting_message or raw_response)
                self._logger.debug(
                    "%s Collected command response `%s`.",
                    self._log_id,
                    collected[-1],
                )
        raise TimeoutError(
            f"no signaling response within {COMMAND_RESPONSE_MAX_FRAMES} frames"
        )

    async def _read_signaling_response(self) -> OWNSignaling:
        """Read only the final signaling frame for backward compatibility."""
        signaling, _ = await self._read_command_response()
        return signaling

    async def send(
        self,
        message: str | OWNMessage,
        is_status_request: bool = False,
        *,
        raise_on_error: bool = False,
    ) -> list[OWNMessage | str] | bool | None:
        """Send the attached message on an existing 'command' connection,
        actively reconnecting it if it had been reset.

        ``message`` is a raw frame (``"*1*1*11##"``) or any ``OWNMessage`` -
        typically a command built by ``OWNLightingCommand.switch_on("11")``
        or parsed by ``OWNCommand.parse()``; it goes on the wire as
        ``str(message)``.

        Concurrency-safe: an internal lock serializes callers sharing this
        session (e.g. ``run_keepalive`` alongside regular commands), so the
        write/read-acknowledgement pairs can never interleave.

        Retries (both on NACK and on connection reset/timeout) are bounded and
        iterative, never recursive, so a flapping connection can neither grow
        the call stack nor loop forever.
        """
        async with self._send_lock:
            return await self._locked_send(
                message, is_status_request, raise_on_error=raise_on_error
            )

    def _refuse_destructive_frame(
        self,
        frame: str,
        message: str | OWNMessage,
        *,
        raise_on_error: bool,
        reason: str = DESTRUCTIVE_FRAME_REASON,
    ) -> None:
        """Record and log the refusal of a frame known to crash a gateway, never written.

        ``frame`` is the serialised string the error carries; ``message`` is
        the caller's object, passed to the logger like every other send log
        line (formatted lazily, and what downstream tests assert on).
        """
        err = destructive_frame_error(frame, reason)
        self._last_error = err
        self._logger.error(
            "%s Refusing to send `%s`: %s.",
            self._log_id,
            message,
            reason,
        )
        if raise_on_error:
            raise err

    async def _locked_send(
        self,
        message: str | OWNMessage,
        is_status_request: bool = False,
        *,
        raise_on_error: bool = False,
    ) -> list[OWNMessage | str] | bool | None:
        self._last_error = None
        # Serialised once: the frame checked is the frame parsed, raised and
        # written. Log lines keep the caller's object (formatted lazily).
        frame = str(message)
        reason = destructive_frame_reason(frame)
        if reason is not None:
            self._refuse_destructive_frame(frame, message, raise_on_error=raise_on_error, reason=reason)
            return None
        msg_obj = (
            message
            if isinstance(message, OWNMessage)
            else OWNMessage.parse(frame, gateway=self._gateway)
        )
        is_valid_frame = (
            msg_obj is not None
            and msg_obj.is_valid
            and not isinstance(msg_obj, OWNSignaling)
        )
        if not is_valid_frame:
            err: OWNError = OWNProtocolError(
                f"Invalid OpenWebNet frame `{frame}`",
                frame=frame,
                reason="invalid_frame",
            )
            self._last_error = err
            self._logger.error(
                "%s Refusing to send invalid OpenWebNet frame `%s`.",
                self._log_id,
                message,
            )
            if raise_on_error:
                raise err
            return None

        # One retry is enough for a command NACK or for a connection that was
        # already unavailable.  A NACKed status request is not retried: the
        # gateway has answered (the device or subsystem is absent), and on an
        # MH200N every NACK costs ~2 s of a shared queue (MyHOME#425).  More
        # importantly, never replay a command after it was written: the
        # gateway may have executed it even if its acknowledgement was lost.
        # Status requests are idempotent and can be retried safely after a
        # transport reset.
        is_idempotent_query = is_status_request and (
            getattr(msg_obj, "_message_type", None)
            in ("STATUS_REQUEST", "DIMENSION_REQUEST")
        )
        max_attempts = 2

        for attempt in range(1, max_attempts + 1):
            # After an outage the previous connect()/reconnect may have given up
            # and left the writer at None; rebuild the session here with a
            # single fast connect attempt (and a short cooldown on failure) so
            # queued callers behind _send_lock never stall for a full 5-attempt
            # exponential backoff loop.
            #
            # Note on single-slot gateways (e.g. MH201, which accepts TCP and
            # closes during negotiation when its session slot is exhausted; see
            # OpenWebNet-HA/OWNd#132 and OpenWebNet-HA/MyHOME#758): callers that
            # recycle idle command sockets (such as MyHOME's
            # CommandWorkerPool.sending_loop() after COMMAND_SESSION_IDLE_TIMEOUT)
            # invoke `await session.connect()` directly when `not session.is_open`
            # before calling `send()`, preserving the full MAX_CONNECT_ATTEMPTS=5
            # (~13.3 s) retry window on session open. This single-attempt path
            # only runs when `send()` is called directly on a closed session or
            # on attempt 2 after a mid-flight transport drop.
            # A gateway closes a command session it finds idle (a live F461
            # 2.0.11 after about 30 s, 2026-11-11 plant run). Its FIN or RST
            # has already reached the reader or the transport before the next
            # write, so the write would succeed locally and the read would fail
            # at once, with the frame never received and, written, never
            # replayed. Nothing has been written yet here, so dropping the dead
            # socket and reopening below is not a replay. The same holds when
            # the gateway sent something before closing (an F461 2.0.11 sends
            # ``*#*0##`` 1 ms before its FIN).
            if self._peer_closed():
                self._logger.debug(
                    "%s Command session was closed by the gateway while idle; "
                    "reopening it before `%s`.",
                    self._log_id,
                    message,
                )
                await self._close_streams()

            if self._stream_reader is None or self._stream_writer is None:
                now = time.monotonic()
                refused_reason = self._refused_login_reason
                if (
                    refused_reason is not None
                    and self._refused_login_target != self._login_target()
                ):
                    # The address, port or password changed since the refusal:
                    # log in again at once.
                    self._clear_refused_login()
                elif (
                    refused_reason is not None
                    and self._last_reconnect_failure is not None
                    and (now - self._last_reconnect_failure) < SEND_AUTH_COOLDOWN
                ):
                    # No new login: the answer cannot change until the
                    # password does. Each caller gets its own exception.
                    err = _negotiation_error_to_exception(refused_reason)
                    self._last_error = err
                    self._logger.warning(
                        "%s Authentication handshake failed (%s); message `%s` "
                        "not sent, next login attempt in %.0fs.",
                        self._log_id,
                        refused_reason,
                        message,
                        SEND_AUTH_COOLDOWN - (now - self._last_reconnect_failure),
                    )
                    if raise_on_error:
                        raise err
                    return None
                elif refused_reason is not None:
                    # The hold has run out and this send() logs in again. The
                    # old refusal goes first: connect() keeps a hold for the
                    # same address, port and password, and an attempt that
                    # then fails without a login (gateway unreachable) would
                    # restart the 60 s under the old reason.
                    self._clear_refused_login()
                if (
                    self._last_reconnect_failure is not None
                    and (now - self._last_reconnect_failure)
                    < SEND_RECONNECT_COOLDOWN
                ):
                    err = OWNConnectionError(
                        f"Command session unavailable; message `{frame}` not sent",
                        reason="connection_unavailable",
                    )
                    self._last_error = err
                    self._logger.warning(
                        "%s Command session unavailable; message `%s` not sent.",
                        self._log_id,
                        message,
                    )
                    if raise_on_error:
                        raise err
                    return None

                seq_before = self._connect_seq
                attempts_token = _CONNECT_MAX_ATTEMPTS.set(1)
                try:
                    result = await self.connect()
                finally:
                    _CONNECT_MAX_ATTEMPTS.reset(attempts_token)

                if (
                    not isinstance(result, Mapping)
                    or not result.get("Success", False)
                    or self._stream_reader is None
                    or self._stream_writer is None
                ):
                    msg = result.get("Message") if isinstance(result, Mapping) else None
                    if isinstance(msg, str) and msg in _FATAL_NEGOTIATION_ERRORS:
                        err = _negotiation_error_to_exception(msg)
                    else:
                        err = self._last_error or OWNConnectionError(
                            f"Command session unavailable; message `{frame}` not sent",
                            reason="connection_unavailable",
                        )
                    # Do not re-arm cooldown or close a newer concurrent connect()'s live socket.
                    if self._connect_seq <= seq_before + 1:
                        self._last_reconnect_failure = time.monotonic()
                        await self.close()
                        self._last_error = err
                    self._logger.warning(
                        "%s Command session unavailable; message `%s` not sent.",
                        self._log_id,
                        message,
                    )
                    if raise_on_error:
                        raise err
                    return None
                if self._connect_seq <= seq_before + 1:
                    self._last_reconnect_failure = None

            written = False
            try:
                self._stream_writer.write(frame.encode())
                written = True
                await self._stream_writer.drain()

                resulting_message, collected = await self._read_command_response()

                if resulting_message.is_ack():
                    self._logger.debug(
                        "%s Message `%s` was successfully sent.",
                        self._log_id,
                        message,
                    )
                    return collected or True

                if resulting_message.is_nack():
                    # A NACK after response data terminates that transaction;
                    # replaying it would duplicate the already returned sweep.
                    if collected or is_status_request or attempt == max_attempts:
                        if is_status_request:
                            self._logger.debug(
                                "%s Gateway rejected status request %s (NACK, %s response(s)). Subsystem or device may not be present.",
                                self._log_id,
                                message,
                                len(collected),
                            )
                        else:
                            self._logger.error(
                                "%s Could not send message `%s`. No more retries.",
                                self._log_id,
                                message,
                            )
                        err = OWNNackError(
                            f"Gateway rejected message `{frame}` with NACK",
                            frame=frame,
                            responses=list(collected),
                        )
                        self._last_error = err
                        if raise_on_error:
                            raise err
                        return None
                    self._logger.error(
                        "%s Could not send message `%s`. Retrying (%d)...",
                        self._log_id,
                        message,
                        attempt,
                    )
                    continue

                self._logger.warning(
                    "%s Unexpected response `%s` to message `%s`.",
                    self._log_id,
                    resulting_message,
                    message,
                )
                err = OWNProtocolError(
                    f"Unexpected response `{resulting_message}` to message `{frame}`",
                    frame=str(resulting_message),
                    reason="unexpected_response",
                )
                self._last_error = err
                if raise_on_error:
                    raise err
                return None

            except asyncio.CancelledError:
                await self.close()
                raise
            except OWNError:
                raise
            except TimeoutError as error:
                await self.close()
                err = OWNTimeoutError(
                    f"Timed out awaiting the complete response for `{frame}`",
                    reason="command_timeout",
                )
                self._last_error = err
                self._logger.warning(
                    "%s Timed out awaiting the complete response for `%s`; "
                    "command session closed.",
                    self._log_id,
                    message,
                )
                if raise_on_error:
                    raise err from error
                return None
            except (
                ConnectionResetError,
                asyncio.IncompleteReadError,
                asyncio.LimitOverrunError,
                OSError,
            ) as error:
                # Release the broken socket without deciding the connected
                # state yet: a retry that succeeds is an internal recycle and
                # must not flap the consumer (offline, then online again).
                await self._close_streams()
                if attempt < max_attempts and (is_idempotent_query or not written):
                    self._logger.debug(
                        "%s Command session connection lost (%s), retrying once...",
                        self._log_id,
                        error,
                    )
                    continue
                # No retry: this is a definitive loss, and the consumer hears it.
                self._set_connected(False)
                err = OWNConnectionError(
                    f"Connection lost before acknowledgement of `{frame}` ({error})",
                    reason="connection_lost",
                )
                self._last_error = err
                self._logger.warning(
                    "%s Connection lost before acknowledgement of `%s`; "
                    "message will not be replayed.",
                    self._log_id,
                    message,
                )
                if raise_on_error:
                    raise err from error
                return None
            except Exception as error:  # pylint: disable=broad-except
                await self.close()
                err = OWNConnectionError(
                    f"Command session crashed ({error})",
                    reason="session_crash",
                )
                self._last_error = err
                self._logger.exception(
                    "%s Command session crashed.", self._log_id
                )
                if raise_on_error:
                    raise err from error
                return None

        return None  # pragma: no cover
