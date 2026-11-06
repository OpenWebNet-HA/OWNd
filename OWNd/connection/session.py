"""Base TCP session management, frame buffering, and connection state machine."""

from __future__ import annotations

import asyncio
import contextlib
import hmac
import logging
import secrets
import socket
import string
import time
from collections.abc import Callable, Mapping
from typing import Any
from urllib.parse import urlparse

from .auth import (
    calculate_open_password,
    decode_hmac_response,
    encode_hmac_password,
    hex_string_to_int_string,
    int_string_to_hex_string,
)
from .gateway import OWNGateway, _first_scalar
from ..discovery import get_port
from ..exceptions import (
    OWNAuthError,
    OWNConnectionError,
    OWNError,
    OWNNackError,
    OWNProtocolError,
    OWNTimeoutError,
)
from ..message import OWNMessage, OWNSignaling
from ..profiles import GatewayProfile, get_gateway_profile

NEGOTIATION_TIMEOUT = 10
# The complete handshake may span several frames, but must still have one
# absolute deadline and a hard frame budget.
NEGOTIATION_TOTAL_TIMEOUT = 30
NEGOTIATION_MAX_FRAMES = 5
COMMAND_TIMEOUT = 10
# Status sweeps can legitimately return one frame per configured device.  Keep
# a hard budget, but leave enough headroom for large installations (the V2
# regression suite covers a 100-frame lighting sweep).
COMMAND_RESPONSE_MAX_FRAMES = 256
# Bound the TCP connect itself, so a black-holed host (SYN accepted, never
# completed) cannot hang the event loop for the OS-default TCP timeout.
CONNECT_TIMEOUT = 10
MAX_CONNECT_ATTEMPTS = 5
# Active keepalive: a harmless "gateway time" request that the MH201 answers.
# Sent periodically on the COMMAND session; a failure forces a reconnect.
KEEPALIVE_FRAME = "*#13**0##"
KEEPALIVE_INTERVAL = 900  # 15 minutes
EVENT_KEEPALIVE_FRAME = b"*#*1##"
# Passive watchdog on the EVENT session: if no frame arrives for this long the
# connection is presumed dead and re-established. Must be set ABOVE the gateway's
# own session lifetime (observed ~58 min on MH201) so it never false-positives
# during normal operation; it only catches a truly silent death (power loss,
# cable pulled) when no clean FIN/RST is received.
EVENT_INACTIVITY_TIMEOUT = 3900  # 65 minutes
# OS-level TCP keepalive for the EVENT session socket. The kernel sends empty
# probes on the *existing* connection (no new sessions, no gateway-side app
# load) and surfaces a dead link as a socket error, which the read loop turns
# into a reconnect. This actively detects a silent death (power loss, cable
# pulled, blackholed route) in ~TCP_KEEPALIVE_IDLE + TCP_KEEPALIVE_CNT *
# TCP_KEEPALIVE_INTVL seconds, instead of waiting for the passive watchdog.
TCP_KEEPALIVE_IDLE = 30  # start probing after 30s of silence
TCP_KEEPALIVE_INTVL = 10  # probe every 10s
TCP_KEEPALIVE_CNT = 3  # declare dead after 3 missed probes (~60s total)
# Authentication negotiation failures (missing/wrong/unsupported password).
_AUTH_NEGOTIATION_ERRORS = frozenset({"password_required", "password_error"})
# Negotiation failures that will never succeed on a retry: don't loop on them.
_FATAL_NEGOTIATION_ERRORS = frozenset(
    {"password_required", "password_error", "negotiation_error"}
)
# Pause before the next reconnection cycle when connect() returned without an
# open stream (gave up after MAX_CONNECT_ATTEMPTS, or hit a fatal negotiation
# error). Without this pause the event read loop would spin at full speed,
# hammering the gateway with connection attempts (observed ~100/s on an MH201
# whose session slots were exhausted after an outage: the flood prevented it
# from ever expiring its stale sessions and recovering on its own).
RECONNECT_PAUSE = 10
# Longer pause when the failure was fatal (e.g. a genuinely wrong password):
# retrying fast cannot help, and every attempt costs the gateway a session.
RECONNECT_PAUSE_FATAL = 60
# Routine event-session drops (e.g. the MH200/MH201 hourly session recycle)
# recover transparently and are logged at DEBUG. Only a *burst* of drops is
# worth a WARNING: DROP_BURST_COUNT drops within DROP_BURST_WINDOW seconds,
# repeated at most once every DROP_WARNING_INTERVAL seconds so a flapping
# link does not turn into a log flood.
DROP_BURST_COUNT = 3
DROP_BURST_WINDOW = 600  # 10 minutes
DROP_WARNING_INTERVAL = 3600  # 1 hour


def _negotiation_error_to_exception(reason: str | None) -> OWNError:
    """Map a negotiation error code to a typed OWNError subclass."""
    if reason in _AUTH_NEGOTIATION_ERRORS:
        return OWNAuthError(
            f"Gateway authentication failed ({reason})", reason=reason
        )
    if reason == "negotiation_timeout":
        return OWNTimeoutError(
            "Timed out negotiating OpenWebNet session", reason=reason
        )
    if reason == "negotiation_refused":
        return OWNNackError(
            "Gateway refused session negotiation with NACK", reason=reason
        )
    if reason in ("negotiation_error", "negotiation_failed"):
        return OWNProtocolError(
            f"OpenWebNet negotiation protocol error ({reason})", reason=reason
        )
    return OWNConnectionError(
        f"Gateway connection failed ({reason or 'unknown'})", reason=reason
    )


class OWNSession:
    """Connection to OpenWebNet gateway"""

    SEPARATOR = b"##"

    def __init__(
        self,
        gateway: OWNGateway | None = None,
        connection_type: str = "test",
        logger: logging.Logger | None = None,
        on_state_change: Callable[[bool], None] | None = None,
        on_auth_error: Callable[[OWNAuthError], Any] | None = None,
    ):
        """Initialize the class
        Arguments:
        gateway: OpenWebNet gateway instance
        connection_type: used when logging to identify this session
        logger: instance of logging
        on_state_change: optional callback invoked with True/False whenever the
            connection comes up / goes down. Lets a consumer (e.g. the Home
            Assistant integration) flip entity availability instantly instead of
            waiting for the next keepalive.
        on_auth_error: optional callback invoked with an ``OWNAuthError`` when
            session authentication fails (e.g. password changed on the gateway
            at runtime so Home Assistant can trigger a reauthentication flow).
        """

        self._gateway = gateway
        self._type = connection_type.lower()
        # A session must always be able to log: fall back to the module
        # logger when the caller provides none (e.g. the classmethod helpers),
        # instead of crashing on `None.warning(...)` and masking the real error.
        self._logger = logger if logger is not None else logging.getLogger(__name__)
        self._on_state_change = on_state_change
        self._on_auth_error = on_auth_error
        self._last_error: OWNError | None = None
        self._connect_max_attempts_override: int | None = None
        self._connected = False
        # Enable OS-level TCP keepalive on the socket (event session only).
        self._tcp_keepalive = False

        # Stream reader/writer, initialised on connect():
        self._stream_reader: asyncio.StreamReader | None = None
        self._stream_writer: asyncio.StreamWriter | None = None

    @property
    def last_error(self) -> OWNError | None:
        """The typed ``OWNError`` from the most recent failed operation, or ``None``."""
        return self._last_error

    @property
    def on_auth_error(self) -> Callable[[OWNAuthError], Any] | None:
        """Optional callback invoked when gateway authentication is rejected."""
        return self._on_auth_error

    @on_auth_error.setter
    def on_auth_error(
        self, callback: Callable[[OWNAuthError], Any] | None
    ) -> None:
        self._on_auth_error = callback

    def _notify_auth_error(self, error: OWNAuthError) -> None:
        """Invoke the consumer's auth-failure callback without letting it crash the session."""
        if self._on_auth_error is not None:
            try:
                self._on_auth_error(error)
            except Exception:  # noqa: BLE001
                if self._logger is not None:
                    self._logger.exception(
                        "%s on_auth_error callback raised.", self._log_id
                    )

    @property
    def is_connected(self) -> bool:
        """True once a session has been negotiated and not since lost."""
        return self._connected

    @property
    def is_open(self) -> bool:
        """True while the session holds an open socket (both streams set).

        This is the transport view, distinct from ``is_connected``, which is
        the consumer-facing negotiated state and deliberately does not flap
        while an internal reconnect recycles the socket. So ``is_connected``
        may read ``True`` with ``is_open`` ``False`` mid-reconnect, and the
        other way round during negotiation. The streams are what ``send()``
        checks before deciding to reopen the session.
        """
        return self._stream_reader is not None and self._stream_writer is not None

    @property
    def _log_id(self) -> str:
        """Log prefix; safe also on a session created without a gateway."""
        # NB: must go through the *gateway*'s log_id — returning self._log_id
        # here would recurse into this very property.
        return self._gateway.log_id if self._gateway is not None else "[no gateway]"

    def _set_connected(self, value: bool) -> None:
        """Update connection state and notify the consumer on transitions only."""
        if value == self._connected:
            return
        self._connected = value
        if self._on_state_change is not None:
            try:
                self._on_state_change(value)
            except Exception:  # noqa: BLE001 - consumer callback must not break us
                if self._logger is not None:
                    self._logger.exception(
                        "%s on_state_change callback raised.", self._log_id
                    )

    def _apply_tcp_keepalive(self) -> None:
        """Enable OS-level TCP keepalive on the current socket (best-effort).

        Any failure (option unsupported, platform without the fine-grained
        Linux knobs, no socket) is logged and ignored: the connection keeps
        working exactly as before, so this can never break the link.
        """
        if not self._tcp_keepalive or self._stream_writer is None:
            return
        try:
            sock = self._stream_writer.get_extra_info("socket")
            if sock is None:
                return
            sock.setsockopt(socket.SOL_SOCKET, socket.SO_KEEPALIVE, 1)
            # Linux-specific fine tuning; absent on some platforms -> ignored.
            if hasattr(socket, "TCP_KEEPIDLE"):
                sock.setsockopt(
                    socket.IPPROTO_TCP, socket.TCP_KEEPIDLE, TCP_KEEPALIVE_IDLE
                )
            if hasattr(socket, "TCP_KEEPINTVL"):
                sock.setsockopt(
                    socket.IPPROTO_TCP, socket.TCP_KEEPINTVL, TCP_KEEPALIVE_INTVL
                )
            if hasattr(socket, "TCP_KEEPCNT"):
                sock.setsockopt(
                    socket.IPPROTO_TCP, socket.TCP_KEEPCNT, TCP_KEEPALIVE_CNT
                )
            self._logger.debug(
                "%s TCP keepalive enabled on event socket "
                "(idle=%ss, intvl=%ss, cnt=%s).",
                self._log_id,
                TCP_KEEPALIVE_IDLE,
                TCP_KEEPALIVE_INTVL,
                TCP_KEEPALIVE_CNT,
            )
        except OSError as err:
            self._logger.warning(
                "%s Could not enable TCP keepalive (%s); continuing without it.",
                self._log_id,
                err,
            )

    async def _read_frame(self, timeout: float | None = None) -> str:  # noqa: ASYNC109
        """Read one OWN frame (terminated by SEPARATOR) and return it decoded.

        When ``timeout`` is provided, an ``asyncio.TimeoutError`` is raised if the
        gateway stays silent for longer than that, so negotiation and command
        acknowledgements can never block the event loop indefinitely. The event
        listener passes ``None`` on purpose, as bus silence is expected there.
        """
        # Programming-error guard (and mypy narrowing): callers must have an
        # open connection before reading frames.
        assert self._stream_reader is not None
        reader = self._stream_reader.readuntil(OWNSession.SEPARATOR)
        if timeout is not None:
            raw_response = await asyncio.wait_for(reader, timeout=timeout)
        else:
            raw_response = await reader
        # A BTicino F524 (firmware 1.3.95) sends its OPEN nonce as ``\x00*#<digits>##``: NUL
        # bytes before the frame are padding, never part of OpenWebNet, and would otherwise make
        # the nonce unrecognisable and fail every negotiation (MyHOME#466, 2026-11-06).
        return raw_response.lstrip(b"\x00").decode()

    @property
    def gateway(self) -> OWNGateway | None:
        return self._gateway

    @gateway.setter
    def gateway(self, gateway: OWNGateway | None) -> None:
        self._gateway = gateway

    @property
    def logger(self) -> logging.Logger:
        return self._logger

    @logger.setter
    def logger(self, logger: logging.Logger) -> None:
        self._logger = logger

    @property
    def connection_type(self) -> str:
        return self._type

    @connection_type.setter
    def connection_type(self, connection_type: str) -> None:
        self._type = connection_type.lower()

    @classmethod
    async def test_gateway(
        cls, gateway: OWNGateway, *, raise_on_error: bool = False
    ) -> dict[str, Any]:
        connection = cls(gateway)
        return await connection.test_connection(raise_on_error=raise_on_error)

    async def test_connection(
        self, *, raise_on_error: bool = False
    ) -> dict[str, Any]:
        assert self._gateway is not None
        self._last_error = None
        retry_count = 0
        retry_timer = 1

        while True:
            try:
                if retry_count > 2:
                    self._logger.error(
                        "%s Test session connection still refused after 3 attempts.",
                        self._log_id,
                    )
                    err: OWNError = OWNConnectionError(
                        "Test session connection still refused after 3 attempts",
                        reason="connection_error",
                    )
                    self._last_error = err
                    if raise_on_error:
                        raise err
                    return {"Success": False, "Message": "connection_error"}
                (
                    self._stream_reader,
                    self._stream_writer,
                ) = await asyncio.wait_for(
                    asyncio.open_connection(
                        self._gateway.address, self._gateway.port
                    ),
                    timeout=CONNECT_TIMEOUT,
                )
                break
            except (ConnectionRefusedError, TimeoutError, OSError) as error:
                self._logger.warning(
                    "%s Test session connection failed (%s), retrying in %ss.",
                    self._log_id,
                    error,
                    retry_timer,
                )
                await asyncio.sleep(retry_timer)
                retry_count += 1
                retry_timer *= 2

        try:
            try:
                result = await self._negotiate()
                if not result.get("Success"):
                    err = _negotiation_error_to_exception(result.get("Message"))
                    self._last_error = err
                    if isinstance(err, OWNAuthError):
                        self._notify_auth_error(err)
                    if raise_on_error:
                        raise err
                return result
            except ConnectionResetError:
                self._logger.error(
                    "%s Negotiation reset while opening %s session. Wait 60 seconds before retrying.",
                    self._log_id,
                    self._type,
                )
                err = OWNConnectionError(
                    "Negotiation reset while opening session",
                    reason="password_retry",
                )
                self._last_error = err
                if raise_on_error:
                    raise err from None
                return {"Success": False, "Message": "password_retry"}
            except (
                asyncio.IncompleteReadError,
                EOFError,
                TimeoutError,
                OSError,
            ) as error:
                # The gateway accepted the TCP connection but closed it (or timed
                # out) during negotiation: typical right after a reboot/power-cycle
                # when it is not ready yet. Report a clean transient failure instead
                # of letting the exception propagate and crash the caller's setup.
                self._logger.warning(
                    "%s Negotiation failed while opening %s session (%s).",
                    self._log_id,
                    self._type,
                    error,
                )
                err = (
                    OWNTimeoutError(
                        f"Negotiation timed out ({error})",
                        reason="connection_error",
                    )
                    if isinstance(error, TimeoutError)
                    else OWNConnectionError(
                        f"Negotiation failed ({error})",
                        reason="connection_error",
                    )
                )
                self._last_error = err
                if raise_on_error:
                    raise err from error
                return {"Success": False, "Message": "connection_error"}
        finally:
            # Test sessions are always temporary. Release the descriptor on
            # success, protocol rejection, transport failure and cancellation.
            with contextlib.suppress(Exception):
                await self.close()

    async def connect(
        self, *, raise_on_error: bool = False
    ) -> dict[str, Any] | None:
        assert self._gateway is not None
        self._logger.debug("%s Opening %s session.", self._log_id, self._type)
        self._last_error = None

        max_attempts = self._connect_max_attempts_override or MAX_CONNECT_ATTEMPTS
        retry_count = 0
        last_attempt_error: OWNError = OWNConnectionError(
            "Session could not be established", reason="connection_error"
        )

        while True:
            try:
                # Bound the connect: open_connection has no timeout of its own.
                (
                    self._stream_reader,
                    self._stream_writer,
                ) = await asyncio.wait_for(
                    asyncio.open_connection(self._gateway.address, self._gateway.port),
                    timeout=CONNECT_TIMEOUT,
                )
                self._apply_tcp_keepalive()
                result = await self._negotiate()
                if result.get("Success"):
                    self._last_error = None
                    self._set_connected(True)
                    return result
                # Negotiation completed but was rejected.
                msg = result.get("Message")
                last_attempt_error = _negotiation_error_to_exception(msg)
                if msg in _FATAL_NEGOTIATION_ERRORS:
                    self._logger.error(
                        "%s %s session negotiation failed (%s); giving up.",
                        self._log_id,
                        self._type.capitalize(),
                        msg,
                    )
                    self._last_error = last_attempt_error
                    if isinstance(last_attempt_error, OWNAuthError):
                        self._notify_auth_error(last_attempt_error)
                    self._set_connected(False)
                    # The TCP connection survived the rejected negotiation:
                    # release it, it will not be used.
                    with contextlib.suppress(Exception):
                        await self._close_streams()
                    if raise_on_error:
                        raise last_attempt_error
                    return result
                reason = f"negotiation failed ({msg})"
                wait = max(1, retry_count * 2)
            except ConnectionResetError:
                reason, wait = "connection reset", 60
                last_attempt_error = OWNConnectionError(
                    "Connection reset by peer", reason="connection_reset"
                )
            except (ConnectionRefusedError, asyncio.IncompleteReadError):
                reason, wait = "connection refused", max(1, retry_count * 2)
                last_attempt_error = OWNConnectionError(
                    "Connection refused", reason="connection_refused"
                )
            except TimeoutError:
                reason, wait = (
                    f"connect timed out ({CONNECT_TIMEOUT}s)",
                    max(1, retry_count * 2),
                )
                last_attempt_error = OWNTimeoutError(
                    f"Connect timed out ({CONNECT_TIMEOUT}s)",
                    reason="connect_timeout",
                )
            except OSError as error:
                # Host unreachable, no route, DNS failure, etc.
                reason, wait = f"network error ({error})", max(1, retry_count * 2)
                last_attempt_error = OWNConnectionError(
                    f"Network error ({error})", reason="network_error"
                )

            retry_count += 1
            # A failed attempt can leave a half-open socket behind (e.g. TCP
            # connected but negotiation failed or was reset): release it before
            # retrying or giving up, so retries never accumulate leaked
            # descriptors. Only the streams: the connected flag is decided
            # below, so a retry that succeeds never flaps the consumer.
            with contextlib.suppress(Exception):
                await self._close_streams()
            if retry_count >= max_attempts:
                self._last_error = last_attempt_error
                if max_attempts > 1:
                    self._logger.warning(
                        "%s %s session could not be established after %d attempts; "
                        "will retry.",
                        self._log_id,
                        self._type.capitalize(),
                        max_attempts,
                    )
                self._set_connected(False)
                if raise_on_error:
                    raise last_attempt_error
                return None
            self._logger.warning(
                "%s %s session: %s. Retrying in %ss (attempt %d/%d).",
                self._log_id,
                self._type.capitalize(),
                reason,
                wait,
                retry_count,
                max_attempts,
            )
            await asyncio.sleep(wait)

    async def _reconnect(self) -> dict[str, Any] | None:
        """Tear down a (likely broken) connection and open a fresh one.

        Connection state is intentionally NOT flipped to False here: a routine
        reconnect (the gateway recycles the session ~hourly) recovers in well
        under a second and must not flap entity availability. State only goes
        False when connect() definitively gives up (see below), which is why
        this recycles the streams instead of calling close().
        """
        # Closing a broken socket may itself fail; we don't care here.
        with contextlib.suppress(Exception):
            await self._close_streams()
        return await self.connect()

    async def close(self) -> None:
        """Closes the connection to the OpenWebNet gateway.

        This is the explicit teardown: the socket is released and the session
        is no longer connected, so ``is_connected`` goes ``False`` and the
        ``on_state_change`` consumer is notified. Internal recycling
        (``_reconnect()``, the retry loop in ``connect()``) deliberately uses
        ``_close_streams()`` instead so a transient reconnect does not flap
        the consumer-facing state.
        """
        await self._close_streams()
        self._set_connected(False)

    async def _close_streams(self) -> None:
        """Release the socket without touching the connected flag."""

        # May be invoked on an empty instance, or on an already-broken socket:
        # be robust against Nones and against wait_closed() re-raising.
        writer = self._stream_writer
        self._stream_reader = None
        self._stream_writer = None
        if writer is not None:
            writer.close()
            # The peer may already be gone; we only need it marked closed.
            with contextlib.suppress(OSError, asyncio.IncompleteReadError):
                await writer.wait_closed()
        if self._gateway is not None:
            self._logger.debug(
                "%s %s session closed.", self._log_id, self._type.capitalize()
            )

    async def _negotiate(self) -> dict[str, Any]:
        """Negotiate one session within an absolute deadline."""
        try:
            async with asyncio.timeout(NEGOTIATION_TOTAL_TIMEOUT):
                return await self._negotiate_exchange()
        except TimeoutError:
            self._logger.error(
                "%s Timed out negotiating %s session after %ss.",
                self._log_id,
                self._type,
                NEGOTIATION_TOTAL_TIMEOUT,
            )
            return {"Success": False, "Message": "negotiation_timeout"}

    async def _negotiate_exchange(self) -> dict[str, Any]:
        """Perform the bounded frame exchange for session negotiation."""
        # Programming-error guards (and mypy narrowing): negotiation is only
        # ever entered right after a successful open_connection() on a
        # session bound to a gateway.
        assert self._gateway is not None
        assert self._stream_reader is not None and self._stream_writer is not None

        if self._gateway.password is not None and not (
            isinstance(self._gateway.password, str)
            and self._gateway.password.isascii()
        ):
            self._logger.error(
                "%s Invalid OpenWebNet password: expected ASCII characters only.",
                self._log_id,
            )
            return {"Success": False, "Message": "password_error"}

        type_id = 0 if self._type == "command" else 1
        error = False
        error_message = None

        self._logger.debug(
            "%s Negotiating %s session.", self._log_id, self._type
        )

        frames_read = 0

        async def read_signaling() -> OWNSignaling:
            nonlocal frames_read
            if frames_read >= NEGOTIATION_MAX_FRAMES:
                raise TimeoutError(
                    f"negotiation exceeded {NEGOTIATION_MAX_FRAMES} frames"
                )
            frames_read += 1
            return OWNSignaling(await self._read_frame(NEGOTIATION_TIMEOUT))

        try:
            self._stream_writer.write(f"*99*{type_id}##".encode())
            await self._stream_writer.drain()

            resulting_message = await read_signaling()

            if resulting_message.is_nack() and self._type == "command":
                self._logger.debug(
                    "%s Standard command session refused; trying alternate session.",
                    self._log_id,
                )
                self._stream_writer.write(b"*99*9##")
                await self._stream_writer.drain()
                resulting_message = await read_signaling()

            if resulting_message.is_nack():
                self._logger.error(
                    "%s Error while opening %s session.",
                    self._log_id,
                    self._type,
                )
                return {"Success": False, "Message": "connection_refused"}

            resulting_message = await read_signaling()
            if resulting_message.is_nack():
                error = True
                error_message = "negotiation_refused"
                self._logger.debug(
                    "%s Reply: `%s`", self._log_id, resulting_message
                )
                self._logger.error(
                    "%s Error while opening %s session.",
                    self._log_id,
                    self._type,
                )
            elif resulting_message.is_sha():
                self._logger.debug(
                    "%s Received SHA challenge: `%s`",
                    self._log_id,
                    resulting_message,
                )
                if self._gateway.password is None:
                    error = True
                    error_message = "password_required"
                    self._logger.warning(
                        "%s Connection requires a password but none was provided.",
                        self._log_id,
                    )
                    self._stream_writer.write(b"*#*0##")
                    await self._stream_writer.drain()
                else:
                    method = "sha"
                    if resulting_message.is_sha_1():
                        method = "sha1"
                    elif resulting_message.is_sha_256():
                        method = "sha256"
                    self._logger.debug(
                        "%s Accepting %s challenge, initiating handshake.",
                        self._log_id,
                        method,
                    )
                    self._stream_writer.write(b"*#*1##")
                    await self._stream_writer.drain()
                    resulting_message = await read_signaling()
                    if (
                        resulting_message.is_nonce()
                        and resulting_message.nonce is not None
                    ):
                        server_random_string_ra = resulting_message.nonce
                        # Rb must be unpredictable: use a CSPRNG (not `random`).
                        key = "".join(secrets.choice(string.digits) for _ in range(56))
                        client_random_string_rb = self._hex_string_to_int_string(
                            hmac.new(key=key.encode(), digestmod=method).hexdigest()
                        )
                        hashed_password = f"*#{client_random_string_rb}*{self._encode_hmac_password(method=method, password=self._gateway.password, nonce_a=server_random_string_ra, nonce_b=client_random_string_rb)}##"  # pylint: disable=line-too-long
                        self._logger.debug(
                            "%s Sending %s session password.",
                            self._log_id,
                            self._type,
                        )
                        self._stream_writer.write(hashed_password.encode())
                        await self._stream_writer.drain()
                        resulting_message = await read_signaling()
                        if resulting_message.is_nack():
                            error = True
                            error_message = "password_error"
                            self._logger.error(
                                "%s Password error while opening %s session.",
                                self._log_id,
                                self._type,
                            )
                        elif resulting_message.is_nonce():
                            hmac_response = resulting_message.nonce
                            expected_response = self._decode_hmac_response(
                                method=method,
                                password=self._gateway.password,
                                nonce_a=server_random_string_ra,
                                nonce_b=client_random_string_rb,
                            )
                            # Constant-time comparison: never leak through
                            # timing how much of the digest matched.
                            if (
                                expected_response is not None
                                and hmac_response is not None
                                and hmac.compare_digest(
                                    hmac_response, expected_response
                                )
                            ):
                                self._stream_writer.write(b"*#*1##")
                                await self._stream_writer.drain()
                                self._logger.debug(
                                    "%s Session established successfully.",
                                    self._log_id,
                                )
                            else:
                                self._logger.error(
                                    "%s Server identity could not be confirmed.",
                                    self._log_id,
                                )
                                self._stream_writer.write(b"*#*0##")
                                await self._stream_writer.drain()
                                error = True
                                error_message = "negotiation_error"
                                self._logger.error(
                                    "%s Error while opening %s session: HMAC authentication failed.",
                                    self._log_id,
                                    self._type,
                                )
                        else:
                            error = True
                            error_message = "negotiation_error"
                            self._logger.error(
                                "%s Unexpected response `%s` after sending the HMAC password; "
                                "closing %s session.",
                                self._log_id,
                                resulting_message,
                                self._type,
                            )
                    else:
                        error = True
                        error_message = "negotiation_error"
                        self._logger.error(
                            "%s Unexpected response `%s` after accepting the HMAC challenge; "
                            "closing %s session.",
                            self._log_id,
                            resulting_message,
                            self._type,
                        )
            elif (
                resulting_message.is_nonce()
                and resulting_message.nonce is not None
            ):
                self._logger.debug(
                    "%s Received nonce: `%s`", self._log_id, resulting_message
                )
                nonce = resulting_message.nonce
                if self._gateway.password is not None:
                    if not self._gateway.password.isdecimal():
                        error = True
                        error_message = "password_error"
                        self._logger.error(
                            "%s Gateway requested legacy numeric authentication, but provided password is not decimal digits only.",
                            self._log_id,
                        )
                    else:
                        hashed_password = f"*#{self._get_own_password(self._gateway.password, nonce)}##"  # pylint: disable=line-too-long
                        self._logger.debug(
                            "%s Sending %s session password.",
                            self._log_id,
                            self._type,
                        )
                        self._stream_writer.write(hashed_password.encode())
                        await self._stream_writer.drain()
                        resulting_message = await read_signaling()
                        if resulting_message.is_nack():
                            error = True
                            error_message = "password_error"
                            self._logger.error(
                                "%s Password error while opening %s session.",
                                self._log_id,
                                self._type,
                            )
                        elif resulting_message.is_ack():
                            self._logger.debug(
                                "%s %s session established successfully.",
                                self._log_id,
                                self._type.capitalize(),
                            )
                        else:
                            error = True
                            error_message = "negotiation_error"
                            self._logger.error(
                                "%s Unexpected response `%s` after sending the legacy password; "
                                "closing %s session.",
                                self._log_id,
                                resulting_message,
                                self._type,
                            )
                else:
                    error = True
                    error_message = "password_required"
                    self._logger.warning(
                        "%s Connection requires a password but none was provided for %s session.",
                        self._log_id,
                        self._type,
                    )
            elif resulting_message.is_ack():
                self._logger.debug(
                    "%s %s session established successfully.",
                    self._log_id,
                    self._type.capitalize(),
                )
            else:
                error = True
                error_message = "negotiation_failed"
                self._logger.debug(
                    "%s Unexpected message during negotiation: %s",
                    self._log_id,
                    resulting_message,
                )
        except TimeoutError:
            error = True
            error_message = "negotiation_timeout"
            self._logger.error(
                "%s Timed out negotiating %s session.",
                self._log_id,
                self._type,
            )
        except asyncio.IncompleteReadError:
            # The gateway closed the connection mid-negotiation. This is NOT
            # a password problem: it happens when the gateway is busy or out
            # of session slots (e.g. an MH201 still holding stale sessions
            # right after an outage). It must be treated as transient — never
            # as a fatal error — so connect() retries it with back-off.
            error = True
            error_message = "connection_closed"
            self._logger.warning(
                "%s Connection closed by the gateway while negotiating %s "
                "session (busy or out of session slots?); will retry.",
                self._log_id,
                self._type,
            )

        return {"Success": not error, "Message": error_message}


    def _get_own_password(
        self, password: str | int, nonce: str, test: bool = False
    ) -> int:
        return calculate_open_password(password, nonce, test=test)

    def _encode_hmac_password(
        self, method: str, password: str, nonce_a: str, nonce_b: str
    ) -> str | None:
        return encode_hmac_password(method, password, nonce_a, nonce_b)

    def _decode_hmac_response(
        self, method: str, password: str, nonce_a: str, nonce_b: str
    ) -> str | None:
        return decode_hmac_response(method, password, nonce_a, nonce_b)

    def _int_string_to_hex_string(self, int_string: str) -> str:
        return int_string_to_hex_string(int_string)

    def _hex_string_to_int_string(self, hex_string: str) -> str:
        return hex_string_to_int_string(hex_string)
