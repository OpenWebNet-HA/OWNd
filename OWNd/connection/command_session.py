"""Command queue pacing, synchronized send, and request/reply tracking."""

from __future__ import annotations

import asyncio
import contextlib
import logging
import time
from collections.abc import Callable
from typing import Any

from .gateway import OWNGateway
from .session import (
    COMMAND_RESPONSE_MAX_FRAMES,
    COMMAND_TIMEOUT,
    KEEPALIVE_FRAME,
    KEEPALIVE_INTERVAL,
    OWNSession,
)
from ..exceptions import (
    OWNAuthError,
    OWNConnectionError,
    OWNError,
    OWNNackError,
    OWNProtocolError,
    OWNTimeoutError,
)
from ..message import OWNMessage, OWNSignaling, is_who4_dimension_22

# Why every send path refuses WHO 4 dimension 22 (see
# ``OWNd.message.is_who4_dimension_22``): the gateway never gets the frame.
DESTRUCTIVE_FRAME_REASON = (
    "WHO 4 dimension 22 crashes the thermoregulation daemon (bt_termo) "
    "on Linux IP gateways"
)


def destructive_frame_error(frame: str) -> OWNProtocolError:
    """The error every send path raises or records for a WHO 4 dimension 22 frame."""
    return OWNProtocolError(
        f"Refusing to send `{frame}`: {DESTRUCTIVE_FRAME_REASON}",
        frame=frame,
        reason="destructive_frame",
    )


# Cooldown window (seconds) after an in-send() reconnect attempt fails, so
# concurrent callers queued behind _send_lock fail fast instead of each
# repeating a socket connect attempt while the gateway is unreachable.
SEND_RECONNECT_COOLDOWN = 2.0


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

    async def connect(
        self, *, raise_on_error: bool = False
    ) -> dict[str, Any] | None:
        self._last_reconnect_failure = None
        return await super().connect(raise_on_error=raise_on_error)

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
        if is_who4_dimension_22(frame):
            connection._refuse_destructive_frame(
                frame, message, raise_on_error=raise_on_error
            )
            return None
        try:
            if raise_on_error:
                await connection.connect(raise_on_error=True)
                return await connection.send(message, raise_on_error=True)
            await connection.connect()
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
            if result is None or not result.get("Success", False):
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
        self, frame: str, message: str | OWNMessage, *, raise_on_error: bool
    ) -> None:
        """Record and log the refusal of a WHO 4 dimension 22 frame, never written.

        ``frame`` is the serialised string the error carries; ``message`` is
        the caller's object, passed to the logger like every other send log
        line (formatted lazily, and what downstream tests assert on).
        """
        err = destructive_frame_error(frame)
        self._last_error = err
        self._logger.error(
            "%s Refusing to send `%s`: %s.",
            self._log_id,
            message,
            DESTRUCTIVE_FRAME_REASON,
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
        if is_who4_dimension_22(frame):
            self._refuse_destructive_frame(frame, message, raise_on_error=raise_on_error)
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
            if self._stream_reader is None or self._stream_writer is None:
                now = time.monotonic()
                if (
                    self._last_reconnect_failure is not None
                    and (now - self._last_reconnect_failure)
                    < SEND_RECONNECT_COOLDOWN
                ):
                    err = self._last_error or OWNConnectionError(
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

                self._connect_max_attempts_override = 1
                try:
                    result = await self.connect()
                finally:
                    self._connect_max_attempts_override = None

                if (
                    result is None
                    or not result.get("Success", False)
                    or self._stream_reader is None
                    or self._stream_writer is None
                ):
                    self._last_reconnect_failure = time.monotonic()
                    err = self._last_error or OWNConnectionError(
                        f"Command session unavailable; message `{frame}` not sent",
                        reason="connection_unavailable",
                    )
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
