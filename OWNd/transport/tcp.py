"""TCP transport for OpenWebNet IP gateways."""

from __future__ import annotations

import asyncio
import contextlib
import logging

from ..connection import OWNCommandSession, OWNEventSession, OWNGateway
from ..message import OWNMessage
from .base import OWNTransport


class AsyncTcpTransport(OWNTransport):
    """Dual-session TCP transport with event and command channels."""

    def __init__(
        self, gateway: OWNGateway, logger: logging.Logger | None = None
    ) -> None:
        super().__init__(log_id=gateway.log_id, logger=logger)
        self.gateway = gateway
        self._event_session: OWNEventSession | None = None
        self._command_session: OWNCommandSession | None = None
        self._listener_task: asyncio.Task[None] | None = None
        self._stopping = False

    @property
    def is_connected(self) -> bool:
        return bool(
            self._event_session
            and self._event_session.is_connected
            and self._command_session
            and self._command_session.is_connected
        )

    @property
    def transport_type(self) -> str:
        return "tcp"

    async def connect(self) -> bool:
        if self._event_session is not None or self._command_session is not None:
            await self.disconnect()

        self._stopping = False
        event_session = OWNEventSession(gateway=self.gateway, logger=self._logger)
        command_session = OWNCommandSession(gateway=self.gateway, logger=self._logger)
        self._event_session = event_session
        self._command_session = command_session

        event_result = await event_session.connect()
        if event_result is None or not event_result.get("Success", False):
            await self.disconnect()
            return False

        command_result = await command_session.connect()
        if command_result is None or not command_result.get("Success", False):
            await self.disconnect()
            return False

        self._listener_task = asyncio.create_task(self._listen_loop())
        return True

    async def _listen_loop(self) -> None:
        try:
            while not self._stopping and self._event_session is not None:
                message = await self._event_session.get_next()
                if message is not None:
                    self.notify_listeners(message)
        except asyncio.CancelledError:
            raise
        except Exception:  # noqa: BLE001
            self._logger.exception("%s TCP listener stopped unexpectedly.", self.log_id)

    async def disconnect(self) -> None:
        self._stopping = True

        listener_task = self._listener_task
        self._listener_task = None
        if listener_task is not None and listener_task is not asyncio.current_task():
            listener_task.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await listener_task

        event_session = self._event_session
        command_session = self._command_session
        self._event_session = None
        self._command_session = None
        if event_session is not None:
            await event_session.close()
        if command_session is not None:
            await command_session.close()

    async def send(
        self, message: str, is_status_request: bool = False
    ) -> list[OWNMessage | str] | bool | None:
        if self._command_session is None:
            raise RuntimeError("TCP transport is not connected")
        return await self._command_session.send(message, is_status_request)
