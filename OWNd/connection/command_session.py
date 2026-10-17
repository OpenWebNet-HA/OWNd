"""Command queue pacing, synchronized send, and request/reply tracking."""

from __future__ import annotations

import asyncio
import contextlib
import logging
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
from ..message import OWNMessage, OWNSignaling

class OWNCommandSession(OWNSession):
    def __init__(
        self,
        gateway: OWNGateway | None = None,
        logger: logging.Logger | None = None,
        on_state_change: Callable[[bool], None] | None = None,
    ):
        super().__init__(
            gateway=gateway,
            connection_type="command",
            logger=logger,
            on_state_change=on_state_change,
        )
        # Serializes concurrent senders sharing this session (e.g. the
        # keepalive loop and a regular command): interleaved write/read pairs
        # on the same stream would steal each other's acknowledgements.
        self._send_lock = asyncio.Lock()

    @classmethod
    async def send_to_gateway(
        cls, message: str | OWNMessage, gateway: OWNGateway
    ) -> list[OWNMessage | str] | bool | None:
        connection = cls(gateway)
        try:
            await connection.connect()
            return await connection.send(message)
        finally:
            with contextlib.suppress(Exception):
                await connection.close()

    @classmethod
    async def connect_to_gateway(
        cls, gateway: OWNGateway
    ) -> dict[str, Any] | None:
        connection = cls(gateway)
        try:
            return await connection.connect()
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
                    resulting_message = OWNMessage.parse(raw_response)
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
        self, message: str | OWNMessage, is_status_request: bool = False
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
            return await self._locked_send(message, is_status_request)

    async def _locked_send(
        self, message: str | OWNMessage, is_status_request: bool = False
    ) -> list[OWNMessage | str] | bool | None:
        msg_obj = (
            message
            if isinstance(message, OWNMessage)
            else OWNMessage.parse(str(message))
        )
        is_valid_frame = (
            msg_obj is not None
            and msg_obj.is_valid
            and not isinstance(msg_obj, OWNSignaling)
        )
        if not is_valid_frame:
            self._logger.error(
                "%s Refusing to send invalid OpenWebNet frame `%s`.",
                self._log_id,
                message,
            )
            return None

        # One retry is enough for a command NACK or for a connection that was
        # already unavailable.  A NACKed status request is not retried: the
        # gateway has answered (the device or subsystem is absent), and on an
        # MH200N every NACK costs ~2 s of a shared queue (MyHOME#425).  More
        # importantly, never replay a command after it was written: the
        # gateway may have executed it even if its acknowledgement was lost.
        # Status requests are idempotent and can be retried safely after a
        # transport reset.
        max_attempts = 2

        for attempt in range(1, max_attempts + 1):
            # After an outage the previous connect()/reconnect may have given up
            # and left the writer at None; rebuild the session here so commands
            # resume automatically when the gateway comes back, instead of
            # crashing forever on `NoneType.write`.
            if self._stream_reader is None or self._stream_writer is None:
                result = await self.connect()
                if (
                    result is None
                    or not result.get("Success", False)
                    or self._stream_reader is None
                    or self._stream_writer is None
                ):
                    await self.close()
                    self._logger.warning(
                        "%s Command session unavailable; message `%s` not sent.",
                        self._log_id,
                        message,
                    )
                    return None

            written = False
            try:
                self._stream_writer.write(str(message).encode())
                written = True
                await self._stream_writer.drain()

                resulting_message, collected = await self._read_command_response()

                if resulting_message.is_ack():
                    log_message = "%s Message `%s` was successfully sent."
                    if not is_status_request:
                        self._logger.info(log_message, self._log_id, message)
                    else:
                        self._logger.debug(log_message, self._log_id, message)
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
                return None

            except asyncio.CancelledError:
                await self.close()
                raise
            except TimeoutError:
                await self.close()
                self._logger.warning(
                    "%s Timed out awaiting the complete response for `%s`; "
                    "command session closed.",
                    self._log_id,
                    message,
                )
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
                if attempt < max_attempts and (is_status_request or not written):
                    self._logger.debug(
                        "%s Command session connection lost (%s), retrying once...",
                        self._log_id,
                        error,
                    )
                    continue
                # No retry: this is a definitive loss, and the consumer hears it.
                self._set_connected(False)
                self._logger.warning(
                    "%s Connection lost before acknowledgement of `%s`; "
                    "message will not be replayed.",
                    self._log_id,
                    message,
                )
                return None
            except Exception:  # pylint: disable=broad-except
                await self.close()
                self._logger.exception(
                    "%s Command session crashed.", self._log_id
                )
                return None

        return None  # pragma: no cover

