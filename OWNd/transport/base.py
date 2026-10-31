"""Common interface for OpenWebNet transports."""

from __future__ import annotations

import logging
from abc import ABC, abstractmethod
from collections.abc import Callable
from typing import Any

from ..exceptions import OWNError
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
        self._last_error: OWNError | None = None

    @property
    def last_error(self) -> OWNError | None:
        """The error recorded by the last ``send()``, if any.

        Both transports record a local refusal (``OWNProtocolError``); the
        TCP transport exposes its command session's ``last_error``, which
        also covers NACK, timeout and connection errors. A serial NACK or
        timeout returns ``None`` without recording an error.
        """
        return self._last_error

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
        self,
        message: str | OWNMessage,
        is_status_request: bool = False,
        *,
        raise_on_error: bool = False,
    ) -> list[OWNMessage | str] | bool | None:
        """Send one command and return its response.

        Raises ``RuntimeError`` when the transport is not connected. A frame
        that is refused locally (invalid, or a WHO 4 dimension 22 frame without
        an actuator token in WHERE, which crashes the gateway's
        thermoregulation daemon) is logged at ERROR, kept in
        ``last_error`` and answered with ``None``; with ``raise_on_error`` it
        raises ``OWNProtocolError`` (``reason`` ``invalid_frame`` or
        ``destructive_frame``) instead, like ``OWNCommandSession.send``.
        """

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
