"""Serial transport for USB OpenWebNet interfaces (BTicino 3578 / Legrand 088328)."""

from __future__ import annotations

import asyncio
from collections.abc import Callable
import contextlib
import errno
import logging
import re
from typing import Any, Literal

from serialx import SerialException, open_serial_connection

from ..connection import COMMAND_RESPONSE_MAX_FRAMES, COMMAND_TIMEOUT
from ..connection.command_session import (
    destructive_frame_error,
    destructive_frame_reason,
)
from ..exceptions import (
    OWNConnectionError,
    OWNError,
    OWNNackError,
    OWNProtocolError,
    OWNTimeoutError,
)
from ..message import OWNGatewayCommand, OWNGatewayEvent, OWNMessage, OWNSignaling
from ..message.base import _has_zigbee_context
from ..profiles import Legrand3578Profile
from .base import OWNTransport

SEPARATOR = b"##"
DEFAULT_BAUDRATE = 19200
BUSY_RETRY_DELAY = 0.5
BUSY_RETRY_MAX_ATTEMPTS = 3
RECONNECT_BACKOFF_STEPS: tuple[float, ...] = (1.0, 2.0, 4.0, 8.0, 10.0)
RawFrameCallback = Callable[[Literal["rx", "tx"], str], Any]


class AsyncSerialTransport(OWNTransport):
    """Single-channel serial transport using ``serialx`` with in-band demux.

    Implements the ``serialx >= 1.8.2`` floor API (``open_serial_connection``
    with ``exclusive=True`` and default modem control lines) and the ZigBee
    USB interface handshake/demux semantics documented in ``openwebnet4j``
    ``USBConnector`` and Encyclopedia Machine KB claims ``ownkb:claim:c000652``,
    ``c000671``, ``c000674``, and ``c001825``.
    """

    def __init__(
        self,
        port: str,
        baudrate: int = DEFAULT_BAUDRATE,
        log_id: str | None = None,
        logger: logging.Logger | None = None,
        *,
        gateway: Any = None,
        busy_retry: bool = False,
        handshake: bool | None = None,
        reconnect: bool = True,
        on_state_change: Callable[[bool], Any] | None = None,
        raw_frame_callback: RawFrameCallback | None = None,
    ) -> None:
        super().__init__(log_id or f"[Legrand 3578 - {port}]", logger)
        self.port = port
        self.baudrate = baudrate
        self._gateway: Any = gateway if gateway is not None else Legrand3578Profile()
        self._busy_retry = busy_retry
        self._handshake = (
            _has_zigbee_context(self._gateway) if handshake is None else handshake
        )
        self._reconnect = reconnect
        self._on_state_change = on_state_change
        self._raw_frame_callback: RawFrameCallback | None = raw_frame_callback

        self._reader: asyncio.StreamReader | None = None
        self._writer: asyncio.StreamWriter | None = None
        self._reader_task: asyncio.Task[None] | None = None
        self._reconnect_task: asyncio.Task[None] | None = None
        self._supervisor_restore_task: asyncio.Task[None] | None = None
        self._command_lock = asyncio.Lock()
        self._pending_future: (
            asyncio.Future[list[OWNMessage | str] | bool | None] | None
        ) = None
        self._pending_request: OWNMessage | None = None
        self._pending_frames: list[OWNMessage | str] = []
        self._pending_busy = False
        self._pending_nack = False
        self._scan_pending_supervisor = False

        self._firmware_version: str | None = None
        self._firmware_tuple: tuple[int, int, int] | None = None
        self._ieee_address: str | None = None
        self._connected = False
        self._handshaking = False
        self._stopping = False
        self._auto_reconnect_enabled = False

    @property
    def is_connected(self) -> bool:
        return self._connected

    @property
    def transport_type(self) -> str:
        return "serial"

    @property
    def ieee_address(self) -> str | None:
        """Return the gateway IEEE EUI-64 address learned during handshake."""
        return self._ieee_address

    @property
    def firmware_version(self) -> str | None:
        """Return the gateway firmware version string learned during handshake."""
        return self._firmware_version

    @property
    def firmware_version_tuple(self) -> tuple[int, int, int] | None:
        """Return the gateway firmware version tuple learned during handshake."""
        return self._firmware_tuple

    @property
    def raw_frame_callback(self) -> RawFrameCallback | None:
        """Return the optional raw wire-frame tap callback."""
        return self._raw_frame_callback

    @raw_frame_callback.setter
    def raw_frame_callback(self, callback: RawFrameCallback | None) -> None:
        self._raw_frame_callback = callback

    def _set_connected(self, value: bool) -> None:
        if value == self._connected:
            return
        self._connected = value
        if self._on_state_change is not None:
            try:
                self._on_state_change(value)
            except Exception:  # noqa: BLE001
                self._logger.exception(
                    "%s on_state_change callback failed.", self.log_id
                )

    def _emit_raw_frame(self, direction: Literal["rx", "tx"], raw: str) -> None:
        if self._raw_frame_callback is not None:
            try:
                self._raw_frame_callback(direction, raw)
            except Exception:  # noqa: BLE001
                self._logger.exception(
                    "%s raw_frame_callback failed.", self.log_id
                )

    def _parse_frame(self, frame: str) -> OWNMessage | None:
        try:
            return OWNMessage.parse(frame, gateway=self._gateway)
        except (ValueError, IndexError, TypeError):
            return None

    def _classify_open_error(self, error: Exception) -> OWNConnectionError:
        err_no = getattr(error, "errno", None)
        cause_no = getattr(getattr(error, "__cause__", None), "errno", None)
        if err_no == errno.EBUSY or cause_no == errno.EBUSY:
            return OWNConnectionError(
                f"Serial port {self.port} is busy ({error})",
                reason="port_busy",
            )
        return OWNConnectionError(
            f"Could not open serial port {self.port}: {error}",
            reason="cannot_connect",
        )

    async def _close_streams(self) -> None:
        reader_task = self._reader_task
        self._reader_task = None
        if reader_task is not None and reader_task is not asyncio.current_task():
            reader_task.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await reader_task

        writer = self._writer
        self._reader = None
        self._writer = None
        if writer is not None:
            writer.close()
            with contextlib.suppress(OSError, SerialException):
                await writer.wait_closed()

    async def _run_handshake(self) -> bool:
        self._firmware_version = None
        self._firmware_tuple = None
        self._ieee_address = None

        keep = await self.send(OWNGatewayCommand.keep_connect())
        if not keep:
            err = OWNProtocolError(
                f"No OpenZigBee interface response on {self.port}",
                frame="*13*60*##",
                reason="no_zigbee_interface",
            )
            self._last_error = err
            self._logger.error("%s %s", self.log_id, err)
            return False

        fw_resp = await self.send(
            OWNGatewayCommand.request_firmware_version(), is_status_request=True
        )
        if isinstance(fw_resp, list):
            for item in fw_resp:
                if (
                    isinstance(item, OWNGatewayEvent)
                    and item.firmware_version is not None
                ):
                    self._firmware_version = item.firmware_version
                    self._firmware_tuple = item.firmware_version_tuple
                    break

        await self.send(OWNGatewayCommand.enable_supervisor())

        ieee_resp = await self.send(
            OWNGatewayCommand("*#13**12##"), is_status_request=True
        )
        if isinstance(ieee_resp, list):
            for item in ieee_resp:
                if (
                    isinstance(item, OWNGatewayEvent)
                    and item.ieee_address is not None
                ):
                    self._ieee_address = item.ieee_address
                    break
        return True

    async def _open_and_handshake(self, *, raise_on_error: bool = False) -> bool:
        if (
            self._reader is not None
            or self._writer is not None
            or self._reader_task is not None
        ):
            await self._close_streams()

        self._last_error = None
        try:
            self._reader, self._writer = await open_serial_connection(
                url=self.port,
                baudrate=self.baudrate,
                exclusive=True,
            )
        except (OSError, SerialException, TimeoutError, ValueError) as error:
            err = self._classify_open_error(error)
            self._last_error = err
            self._logger.error(
                "%s Could not open serial port %s: %s", self.log_id, self.port, error
            )
            if raise_on_error:
                raise err from error
            return False

        self._reader_task = asyncio.create_task(self._read_loop())
        self._handshaking = True
        try:
            if self._handshake and not await self._run_handshake():
                handshake_err = self._last_error
                await self._close_streams()
                self._last_error = handshake_err
                if raise_on_error and handshake_err is not None:
                    raise handshake_err
                return False
        except asyncio.CancelledError:
            await self._close_streams()
            raise
        finally:
            self._handshaking = False

        self._auto_reconnect_enabled = self._reconnect
        self._set_connected(True)
        return True

    async def connect(self, *, raise_on_error: bool = False) -> bool:
        if self._connected:
            return True
        reconnect_task = self._reconnect_task
        self._reconnect_task = None
        if reconnect_task is not None and reconnect_task is not asyncio.current_task():
            reconnect_task.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await reconnect_task
        self._stopping = False
        return await self._open_and_handshake(raise_on_error=raise_on_error)

    async def _reconnect_loop(self) -> None:
        attempt = 0
        try:
            while not self._stopping and self._auto_reconnect_enabled:
                delay = RECONNECT_BACKOFF_STEPS[
                    min(attempt, len(RECONNECT_BACKOFF_STEPS) - 1)
                ]
                attempt += 1
                await asyncio.sleep(delay)
                if self._stopping or not self._auto_reconnect_enabled:
                    return
                if await self._open_and_handshake(raise_on_error=False):
                    return
        except asyncio.CancelledError:
            raise

    async def _restore_supervisor(self) -> None:
        try:
            if self._connected:
                await self.send(OWNGatewayCommand.enable_supervisor())
        except Exception:  # noqa: BLE001
            self._logger.debug("%s Failed to restore ZigBee supervisor.", self.log_id)

    async def _read_loop(self) -> None:
        assert self._reader is not None
        try:
            while not self._stopping:
                data = await self._reader.readuntil(SEPARATOR)
                frame = data.decode(errors="replace").strip()
                if not frame or frame == "##":
                    continue
                if not frame.startswith("*") and "*" in frame:
                    idx = frame.index("*")
                    self._emit_raw_frame("rx", frame[:idx].strip())
                    frame = frame[idx:]
                self._process_frame(frame)
        except asyncio.CancelledError:
            raise
        except (
            asyncio.IncompleteReadError,
            asyncio.LimitOverrunError,
            OSError,
            SerialException,
        ) as error:
            if not self._stopping:
                self._logger.warning(
                    "%s Serial connection lost: %s", self.log_id, error
                )
        finally:
            self._set_connected(False)
            writer = self._writer
            if writer is not None:
                writer.close()
            pending = self._pending_future
            if pending is not None and not pending.done():
                pending.set_result(None)
            if not self._stopping and self._auto_reconnect_enabled:
                self._reconnect_task = asyncio.create_task(self._reconnect_loop())

    def _apply_rx_quirks(
        self, raw_frame: str, parsed: OWNMessage | None
    ) -> OWNMessage | None:
        """Apply conservative RX-only WHO 2 Up/Down swap for ``fw <= (1, 2, 0)``."""
        if (
            self._firmware_tuple is not None
            and self._firmware_tuple <= (1, 2, 0)
            and parsed is not None
            and parsed.who == 2
            and parsed.dimension is None
            and parsed.what in (1, 2)
        ):
            swapped_what = 2 if parsed.what == 1 else 1
            rewritten = re.sub(
                rf"^\*2\*{parsed.what}(?=[*#])",
                f"*2*{swapped_what}",
                raw_frame,
                count=1,
            )
            return self._parse_frame(rewritten)
        return parsed

    def _matches_status_reply_quirk(
        self, request: OWNMessage | None, parsed: OWNMessage | None
    ) -> bool:
        """True when a WHO 1/2 status frame completes a pending request on ``fw <= 1.2.3``."""
        if request is None or parsed is None:
            return False
        if request.who not in (1, 2) or not request.is_request:
            return False
        return (
            parsed.who == request.who
            and parsed.where == request.where
            and parsed.where_param == request.where_param
        )

    def _matches_pending_request(
        self, request: Any, parsed: OWNMessage | None
    ) -> bool:
        """Decide whether an inbound dimension frame belongs to the pending request."""
        if request is None or not isinstance(request, OWNMessage):
            return True
        if parsed is None or parsed.who != request.who:
            return False
        if request.who == 13 and request.dimension == 66:
            if parsed.dimension != 66:
                return False
            if not parsed.where and parsed.dimension_value == ["0"]:
                return True
            req_idx = (
                request.dimension_param[0]
                if request.dimension_param
                else (request.dimension_value[0] if request.dimension_value else None)
            )
            if req_idx is not None:
                if len(parsed.dimension_value) >= 2:
                    return parsed.dimension_value[0] == req_idx
                return parsed.dimension_param[:1] == [req_idx]
            if request.zigbee_device_id is not None:
                return parsed.zigbee_device_id == request.zigbee_device_id
            return (
                parsed.where == request.where
                and parsed.where_param == request.where_param
            )
        if request.who == 13 and request.dimension == 73:
            if parsed.dimension != 73:
                return False
            if request.dimension_param:
                return parsed.dimension_param == request.dimension_param
            return (
                parsed.where == request.where
                and parsed.where_param == request.where_param
            )
        if not request.is_request and request.dimension is None:
            return False
        if parsed.where != request.where or parsed.where_param != request.where_param:
            return False
        if request.dimension is not None:
            if request.who == 1 and request.dimension == 1:
                return parsed.dimension in (1, 4)
            return parsed.dimension == request.dimension
        return True

    def _process_frame(self, raw_frame: str) -> None:
        self._emit_raw_frame("rx", raw_frame)
        parsed = self._parse_frame(raw_frame)
        pending = self._pending_future

        if isinstance(parsed, OWNSignaling):
            if pending is None or pending.done():
                self._logger.debug(
                    "%s Ignoring stray signaling frame `%s`.", self.log_id, raw_frame
                )
                return
            if parsed.is_busy_nack():
                self._pending_busy = True
                return
            if parsed.is_ack():
                pending.set_result(list(self._pending_frames) or True)
            elif parsed.is_nack():
                self._pending_nack = True
                pending.set_result(None)
            else:
                pending.set_result(None)
            return

        is_status_frame = raw_frame.startswith("*") and not raw_frame.startswith("*#")
        if is_status_frame:
            parsed = self._apply_rx_quirks(raw_frame, parsed)
            message: OWNMessage | str = parsed if parsed is not None else raw_frame
            self.notify_listeners(message)
            if (
                self._firmware_tuple is not None
                and self._firmware_tuple <= (1, 2, 3)
                and pending is not None
                and not pending.done()
                and self._matches_status_reply_quirk(self._pending_request, parsed)
            ):
                pending.set_result(list(self._pending_frames) or True)
            return

        if (
            pending is not None
            and not pending.done()
            and self._matches_pending_request(self._pending_request, parsed)
        ):
            if len(self._pending_frames) >= COMMAND_RESPONSE_MAX_FRAMES:
                pending.set_exception(
                    TimeoutError(
                        f"command response exceeded {COMMAND_RESPONSE_MAX_FRAMES} frames"
                    )
                )
                return
            self._pending_frames.append(parsed if parsed is not None else raw_frame)
            return

        if (
            self._scan_pending_supervisor
            and parsed is not None
            and parsed.who == 13
            and parsed.dimension == 67
            and not parsed.is_request
        ):
            self._scan_pending_supervisor = False
            if self._connected and (
                self._supervisor_restore_task is None
                or self._supervisor_restore_task.done()
            ):
                self._supervisor_restore_task = asyncio.create_task(
                    self._restore_supervisor()
                )

        self.notify_listeners(parsed if parsed is not None else raw_frame)

    async def send(
        self,
        message: str | OWNMessage,
        is_status_request: bool = False,
        *,
        raise_on_error: bool = False,
        timeout: float | None = None,
    ) -> list[OWNMessage | str] | bool | None:
        del is_status_request
        if not (self._connected or self._handshaking) or self._writer is None:
            raise RuntimeError("Serial transport is not connected")
        self._last_error = None

        # Serialised once, terminator included: the frame checked is the
        # frame parsed, logged and written.
        text = str(message)
        if not text.endswith("##"):
            text += "##"
        reason = destructive_frame_reason(text)
        if reason is not None:
            err: OWNError = destructive_frame_error(text, reason)
            self._last_error = err
            self._logger.error(
                "%s Refusing to send `%s`: %s.",
                self.log_id,
                text,
                reason,
            )
            if raise_on_error:
                raise err
            return None
        msg_obj = (
            message if isinstance(message, OWNMessage) else self._parse_frame(text)
        )
        if (
            msg_obj is None
            or not msg_obj.is_valid
            or isinstance(msg_obj, OWNSignaling)
        ):
            err = OWNProtocolError(
                f"Invalid OpenWebNet frame `{text}`",
                frame=text,
                reason="invalid_frame",
            )
            self._last_error = err
            self._logger.error(
                "%s Refusing to send invalid OpenWebNet frame `%s`.",
                self.log_id,
                text,
            )
            if raise_on_error:
                raise err
            return None

        effective_timeout = COMMAND_TIMEOUT if timeout is None else timeout
        max_attempts = BUSY_RETRY_MAX_ATTEMPTS if self._busy_retry else 1

        async with self._command_lock:
            for attempt in range(1, max_attempts + 1):
                if not (self._connected or self._handshaking) or self._writer is None:
                    err = OWNConnectionError(
                        f"Serial connection lost before sending `{text}`",
                        reason="connection_lost",
                    )
                    self._last_error = err
                    if raise_on_error:
                        raise err
                    return None

                loop = asyncio.get_running_loop()
                self._pending_future = loop.create_future()
                self._pending_request = msg_obj
                self._pending_frames = []
                self._pending_busy = False
                self._pending_nack = False
                should_retry = False

                try:
                    self._emit_raw_frame("tx", text)
                    if msg_obj.who == 13 and msg_obj.what == 66:
                        self._scan_pending_supervisor = False
                    self._writer.write(text.encode())
                    await self._writer.drain()
                    result = await asyncio.wait_for(
                        self._pending_future, timeout=effective_timeout
                    )
                    if result is not None:
                        if msg_obj.who == 13 and msg_obj.what == 65:
                            self._scan_pending_supervisor = True
                        return result

                    if self._pending_nack:
                        if self._pending_busy:
                            if attempt < max_attempts:
                                self._logger.debug(
                                    "%s Gateway busy (`*#*6##` + `*#*0##`) on `%s`; retrying in %.1fs (%d/%d).",
                                    self.log_id,
                                    text,
                                    BUSY_RETRY_DELAY,
                                    attempt,
                                    max_attempts,
                                )
                                should_retry = True
                            else:
                                self._logger.warning(
                                    "%s Gateway busy (`*#*6##` + `*#*0##`) rejected `%s`.",
                                    self.log_id,
                                    text,
                                )
                                err = OWNNackError(
                                    f"Gateway busy (NACK) for `{text}`",
                                    frame=text,
                                    responses=list(self._pending_frames),
                                    reason="busy_nack",
                                    busy=True,
                                )
                                self._last_error = err
                                if raise_on_error:
                                    raise err
                                return None
                        else:
                            err = OWNNackError(
                                f"Gateway rejected message `{text}` with NACK",
                                frame=text,
                                responses=list(self._pending_frames),
                                reason="nack",
                                busy=False,
                            )
                            self._last_error = err
                            if raise_on_error:
                                raise err
                            return None
                    else:
                        if not (self._connected or self._handshaking) or self._stopping:
                            err = OWNConnectionError(
                                f"Serial connection lost before acknowledgement of `{text}`",
                                reason="connection_lost",
                            )
                        else:
                            err = OWNProtocolError(
                                f"Unexpected signaling response to `{text}`",
                                frame=text,
                                reason="protocol_error",
                            )
                        self._last_error = err
                        if raise_on_error:
                            raise err
                        return None

                except TimeoutError as error:
                    self._logger.warning(
                        "%s Timed out waiting for serial response to `%s`.",
                        self.log_id,
                        text,
                    )
                    err = OWNTimeoutError(
                        f"Timed out waiting for serial response to `{text}`",
                        reason="command_timeout",
                    )
                    self._last_error = err
                    if raise_on_error:
                        raise err from error
                    return None
                except (OSError, SerialException) as error:
                    self._logger.warning(
                        "%s Serial write failed for `%s`: %s",
                        self.log_id,
                        text,
                        error,
                    )
                    err = OWNConnectionError(
                        f"Serial write failed for `{text}` ({error})",
                        reason="connection_lost",
                    )
                    self._last_error = err
                    if raise_on_error:
                        raise err from error
                    return None
                finally:
                    self._pending_future = None
                    self._pending_request = None
                    self._pending_frames = []
                    self._pending_busy = False
                    self._pending_nack = False

                if should_retry:
                    await asyncio.sleep(BUSY_RETRY_DELAY)

        return None  # pragma: no cover

    async def disconnect(self) -> None:
        self._stopping = True
        self._auto_reconnect_enabled = False
        self._scan_pending_supervisor = False

        reconnect_task = self._reconnect_task
        self._reconnect_task = None
        if reconnect_task is not None and reconnect_task is not asyncio.current_task():
            reconnect_task.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await reconnect_task

        restore_task = self._supervisor_restore_task
        self._supervisor_restore_task = None
        if restore_task is not None and restore_task is not asyncio.current_task():
            restore_task.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await restore_task

        self._set_connected(False)

        pending = self._pending_future
        if pending is not None and not pending.done():
            pending.set_result(None)

        await self._close_streams()
