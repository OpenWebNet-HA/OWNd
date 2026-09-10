"""Serial transport for the Legrand 3578 OpenWebNet interface."""

from __future__ import annotations

import asyncio
import contextlib
import logging

from ..connection import COMMAND_RESPONSE_MAX_FRAMES, COMMAND_TIMEOUT
from ..message import OWNMessage, OWNSignaling
from .base import OWNTransport

SEPARATOR = b"##"
DEFAULT_BAUDRATE = 19200


class AsyncSerialTransport(OWNTransport):
    """Single-channel transport that separates events from command replies."""

    def __init__(
        self,
        port: str,
        baudrate: int = DEFAULT_BAUDRATE,
        log_id: str | None = None,
        logger: logging.Logger | None = None,
    ) -> None:
        super().__init__(log_id or f"[Legrand 3578 - {port}]", logger)
        self.port = port
        self.baudrate = baudrate
        self._reader: asyncio.StreamReader | None = None
        self._writer: asyncio.StreamWriter | None = None
        self._reader_task: asyncio.Task[None] | None = None
        self._command_lock = asyncio.Lock()
        self._pending_future: (
            asyncio.Future[list[OWNMessage | str] | bool | None] | None
        ) = None
        self._pending_request: OWNMessage | None = None
        self._pending_frames: list[OWNMessage | str] = []
        self._connected = False
        self._stopping = False

    @property
    def is_connected(self) -> bool:
        return self._connected

    @property
    def transport_type(self) -> str:
        return "serial"

    async def connect(self) -> bool:
        if self._connected:
            return True
        if self._reader is not None or self._writer is not None:
            await self.disconnect()

        try:
            import serial_asyncio
        except ImportError:
            self._logger.error(
                "%s Serial support requires the 'serial' package extra.", self.log_id
            )
            return False

        self._stopping = False
        try:
            self._reader, self._writer = await serial_asyncio.open_serial_connection(
                url=self.port,
                baudrate=self.baudrate,
            )
        except (OSError, ValueError) as error:
            self._logger.error(
                "%s Could not open serial port %s: %s", self.log_id, self.port, error
            )
            return False

        self._connected = True
        self._reader_task = asyncio.create_task(self._read_loop())
        return True

    async def _read_loop(self) -> None:
        assert self._reader is not None
        try:
            while not self._stopping:
                data = await self._reader.readuntil(SEPARATOR)
                frame = data.decode(errors="replace").strip()
                if frame and frame != "##":
                    self._process_frame(frame)
        except asyncio.CancelledError:
            raise
        except (
            asyncio.IncompleteReadError,
            asyncio.LimitOverrunError,
            OSError,
        ) as error:
            if not self._stopping:
                self._logger.warning(
                    "%s Serial connection lost: %s", self.log_id, error
                )
        finally:
            self._connected = False
            if self._writer is not None:
                self._writer.close()
            pending = self._pending_future
            if pending is not None and not pending.done():
                pending.set_result(None)

    def _process_frame(self, frame: str) -> None:
        parsed = OWNMessage.parse(frame)
        message = parsed or frame
        unsolicited = frame.startswith("*") and not frame.startswith("*#")

        pending = self._pending_future
        if unsolicited or pending is None or pending.done():
            self.notify_listeners(message)
            return

        if isinstance(parsed, OWNSignaling):
            if parsed.is_ack():
                pending.set_result(self._pending_frames or True)
            elif parsed.is_nack():
                pending.set_result(None)
            else:
                pending.set_result(None)
            return

        request = self._pending_request
        if (
            parsed is not None
            and request is not None
            and (parsed.who != request.who or parsed.where != request.where)
        ):
            self.notify_listeners(parsed)
            return

        if len(self._pending_frames) >= COMMAND_RESPONSE_MAX_FRAMES:
            pending.set_exception(
                TimeoutError(
                    f"command response exceeded {COMMAND_RESPONSE_MAX_FRAMES} frames"
                )
            )
            return
        self._pending_frames.append(message)

    async def send(
        self, message: str, is_status_request: bool = False
    ) -> list[OWNMessage | str] | bool | None:
        del is_status_request
        if not self._connected or self._writer is None:
            raise RuntimeError("Serial transport is not connected")

        async with self._command_lock:
            loop = asyncio.get_running_loop()
            self._pending_future = loop.create_future()
            self._pending_request = OWNMessage.parse(str(message))
            self._pending_frames = []
            try:
                frame = str(message).encode()
                if not frame.endswith(SEPARATOR):
                    frame += SEPARATOR
                self._writer.write(frame)
                await self._writer.drain()
                return await asyncio.wait_for(
                    self._pending_future, timeout=COMMAND_TIMEOUT
                )
            except TimeoutError:
                self._logger.warning(
                    "%s Timed out waiting for serial response to `%s`.",
                    self.log_id,
                    message,
                )
                return None
            finally:
                self._pending_future = None
                self._pending_request = None
                self._pending_frames = []

    async def disconnect(self) -> None:
        self._stopping = True
        self._connected = False

        pending = self._pending_future
        if pending is not None and not pending.done():
            pending.set_result(None)

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
            with contextlib.suppress(OSError):
                await writer.wait_closed()
