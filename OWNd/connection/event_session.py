"""Long-lived event bus session and automatic reconnection stream."""

from __future__ import annotations

import asyncio
import contextlib
import logging
import time
from collections.abc import Callable
from typing import Any

from .gateway import OWNGateway
from .session import (
    DROP_BURST_COUNT,
    DROP_BURST_WINDOW,
    DROP_WARNING_INTERVAL,
    EVENT_INACTIVITY_TIMEOUT,
    EVENT_KEEPALIVE_FRAME,
    OWNSession,
    RECONNECT_PAUSE,
    RECONNECT_PAUSE_FATAL,
    _AUTH_NEGOTIATION_ERRORS,
    _FATAL_NEGOTIATION_ERRORS,
)
from ..exceptions import OWNAuthError
from ..message import OWNMessage


class OWNEventSession(OWNSession):
    def __init__(
        self,
        gateway: OWNGateway | None = None,
        logger: logging.Logger | None = None,
        inactivity_timeout: float | None = EVENT_INACTIVITY_TIMEOUT,
        on_state_change: Callable[[bool], None] | None = None,
        on_auth_error: Callable[[OWNAuthError], Any] | None = None,
        raise_on_auth_error: bool = False,
    ):
        super().__init__(
            gateway=gateway,
            connection_type="event",
            logger=logger,
            on_state_change=on_state_change,
            on_auth_error=on_auth_error,
        )
        # Passive watchdog: reconnect if no frame arrives for this long.
        # Set to None to disable (pure blocking read, never times out).
        self._inactivity_timeout = inactivity_timeout
        self._raise_on_auth_error = raise_on_auth_error
        # The event session is the long-lived monitored connection: let the OS
        # actively probe it so a silent outage is detected in ~60s.
        self._tcp_keepalive = True
        self._keepalive_interval = (
            gateway.profile.event_keepalive_interval if gateway is not None else None
        )
        self._keepalive_task: asyncio.Task[None] | None = None
        self._recent_drops: list[float] = []
        self._last_drop_warning: float | None = None

    async def connect(
        self, *, raise_on_error: bool = False
    ) -> dict[str, Any] | None:
        await self._stop_keepalive()
        result = await super().connect(raise_on_error=raise_on_error)
        if result is not None and result.get("Success"):
            self._start_keepalive()
        return result

    def _start_keepalive(self) -> None:
        if self._keepalive_interval is None:
            return
        self._keepalive_task = asyncio.create_task(self._keepalive_loop())

    async def _stop_keepalive(self) -> None:
        task = self._keepalive_task
        self._keepalive_task = None
        if task is None or task is asyncio.current_task():
            return
        task.cancel()
        with contextlib.suppress(asyncio.CancelledError):
            await task

    async def _keepalive_loop(self) -> None:
        assert self._keepalive_interval is not None
        try:
            while True:
                await asyncio.sleep(self._keepalive_interval)
                if self._stream_writer is None:
                    return
                self._stream_writer.write(EVENT_KEEPALIVE_FRAME)
                await self._stream_writer.drain()
                self._logger.debug("%s Event session keepalive sent.", self._log_id)
        except asyncio.CancelledError:
            raise
        except (ConnectionError, OSError) as error:
            self._logger.warning(
                "%s Event session keepalive failed (%s).", self._log_id, error
            )
            if self._stream_writer is not None:
                self._stream_writer.close()

    async def _close_streams(self) -> None:
        # Both the explicit close() and an internal recycle go through here,
        # so the keepalive can never outlive the socket it writes to.
        await self._stop_keepalive()
        await super()._close_streams()

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

    def _maybe_raise_auth_error(
        self,
        result: dict[str, Any] | None,
        raise_on_auth_error: bool | None,
    ) -> None:
        should_raise = (
            self._raise_on_auth_error
            if raise_on_auth_error is None
            else raise_on_auth_error
        )
        if not should_raise:
            return
        err = (
            self._last_error
            if isinstance(self._last_error, OWNAuthError)
            else (
                OWNAuthError(
                    f"Gateway authentication failed ({result.get('Message')})",
                    reason=str(result.get("Message")),
                )
                if result is not None
                and result.get("Message") in _AUTH_NEGOTIATION_ERRORS
                else None
            )
        )
        if err is not None:
            self._last_error = err
            raise err

    async def _reconnect_and_check_auth(
        self, raise_on_auth_error: bool | None
    ) -> dict[str, Any] | None:
        result = await self._reconnect()
        if self._stream_reader is None:
            self._maybe_raise_auth_error(result, raise_on_auth_error)
        return result

    async def get_next(
        self, *, raise_on_auth_error: bool | None = None
    ) -> OWNMessage | str | None:
        """Acts as an entry point to read messages on the event bus.
        It will read one frame and return it as an OWNMessage object.

        Bus silence is normal, so the read does not time out aggressively;
        however a *very* long silence (``inactivity_timeout``, set above the
        gateway's own session lifetime) is treated as a dead connection and
        triggers a reconnect — this catches a silent death (power loss, cable
        pulled) where no clean FIN/RST is ever received. On any loss of
        connectivity it transparently reconnects and returns None for that
        cycle; the caller simply calls it again.
        """
        if self._stream_reader is None:
            # No live connection (e.g. a previous reconnect attempt gave up).
            self._logger.warning(
                "%s Event session not connected, reconnecting...",
                self._log_id,
            )
            result = await self._reconnect_and_check_auth(raise_on_auth_error)
            if self._stream_reader is None:
                # Still no stream: connect() gave up or failed fatally and
                # returned IMMEDIATELY (its internal back-off only covers the
                # transient retries). Pause here, otherwise the caller's read
                # loop would re-enter this branch instantly and flood the
                # gateway with connection attempts.
                pause = (
                    RECONNECT_PAUSE_FATAL
                    if result is not None
                    and result.get("Message") in _FATAL_NEGOTIATION_ERRORS
                    else RECONNECT_PAUSE
                )
                self._logger.warning(
                    "%s Reconnection failed; next attempt in %ss.",
                    self._log_id,
                    pause,
                )
                await asyncio.sleep(pause)
            return None
        try:
            read = self._stream_reader.readuntil(OWNSession.SEPARATOR)
            if self._inactivity_timeout is not None:
                data = await asyncio.wait_for(read, timeout=self._inactivity_timeout)
            else:
                data = await read
        except TimeoutError:
            self._logger.warning(
                "%s No bus traffic for %ss; assuming stale connection, reconnecting...",
                self._log_id,
                self._inactivity_timeout,
            )
            await self._reconnect_and_check_auth(raise_on_auth_error)
            return None
        except asyncio.LimitOverrunError:
            self._logger.warning(
                "%s Received oversized or garbage frame, dropping connection and reconnecting...",
                self._log_id,
            )
            await self._reconnect_and_check_auth(raise_on_auth_error)
            return None
        except (
            asyncio.IncompleteReadError,
            ConnectionError,
            OSError,
        ):
            # Covers EOF, RST (ConnectionResetError), aborted connections and
            # other socket errors: reconnect in all cases. A single drop is
            # routine (MH200/MH201 recycle the session every hour) and is
            # logged at DEBUG so healthy reconnects do not alarm downstream
            # consumers; only a burst of drops is escalated to WARNING.
            now = time.monotonic()
            self._recent_drops = [
                t for t in self._recent_drops if now - t < DROP_BURST_WINDOW
            ]
            self._recent_drops.append(now)
            if len(self._recent_drops) >= DROP_BURST_COUNT and (
                self._last_drop_warning is None
                or now - self._last_drop_warning >= DROP_WARNING_INTERVAL
            ):
                # Report the span the drops actually covered, not the window
                # they were measured in: three drops five seconds apart is a
                # very different symptom from three spread over ten minutes.
                self._logger.warning(
                    "%s Event connection dropped %d times in %.0fs; "
                    "network may be unstable. Reconnecting...",
                    self._log_id,
                    len(self._recent_drops),
                    now - self._recent_drops[0],
                )
                self._last_drop_warning = now
            else:
                self._logger.debug(
                    "%s Event connection lost, reconnecting...", self._log_id
                )
            await self._reconnect_and_check_auth(raise_on_auth_error)
            return None
        except Exception:  # pylint: disable=broad-except
            self._logger.exception(
                "%s Event session crashed, reconnecting...", self._log_id
            )
            await self._reconnect_and_check_auth(raise_on_auth_error)
            return None

        # A frame was read successfully: from here on, any failure is a
        # *parsing* problem, not a connection problem. Never tear the session
        # down (and lose bus events) over a frame we could not make sense of.
        try:
            _decoded_data = data.decode()
            _message = OWNMessage.parse(_decoded_data, gateway=self._gateway)
            return _message if _message else _decoded_data
        except (UnicodeDecodeError, ValueError, IndexError, TypeError) as error:
            _decoded_data = data.decode(errors="replace")
            self._logger.warning(
                "%s Malformed event frame %r: %s",
                self._log_id,
                _decoded_data,
                error,
            )
            return _decoded_data
