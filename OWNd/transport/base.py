"""Common interface for OpenWebNet transports."""

from __future__ import annotations

import logging
from abc import ABC, abstractmethod
from collections.abc import Callable
from typing import Any

from ..message import OWNMessage

Listener = Callable[[OWNMessage | str], Any]


class OWNTransport(ABC):
    """Abstract transport used by consumers independently of the hardware."""

    def __init__(
        self,
        log_id: str = "[OpenWebNet transport]",
        logger: logging.Logger | None = None,
    ) -> None:
        self.log_id = log_id
        self._logger = logger or logging.getLogger(__name__)
        self._listeners: set[Listener] = set()

    @property
    @abstractmethod
    def is_connected(self) -> bool:
        """Return whether the transport is connected and ready."""

    @property
    @abstractmethod
    def transport_type(self) -> str:
        """Return the transport identifier."""

    @abstractmethod
    async def connect(self) -> bool:
        """Connect to the OpenWebNet interface."""

    @abstractmethod
    async def disconnect(self) -> None:
        """Close the transport and release its resources."""

    @abstractmethod
    async def send(
        self, message: str, is_status_request: bool = False
    ) -> list[OWNMessage | str] | bool | None:
        """Send one command and return its response."""

    def register_listener(self, callback: Listener) -> Callable[[], None]:
        """Register an inbound-message callback and return its unsubscribe."""
        self._listeners.add(callback)

        def unsubscribe() -> None:
            self._listeners.discard(callback)

        return unsubscribe

    def notify_listeners(self, message: OWNMessage | str) -> None:
        """Deliver an inbound message without letting one listener stop others."""
        for callback in tuple(self._listeners):
            try:
                callback(message)
            except Exception:  # noqa: BLE001
                self._logger.exception("%s Listener callback failed.", self.log_id)
