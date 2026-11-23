"""Typed exceptions for OpenWebNet connection, authentication, and protocol errors."""

from __future__ import annotations

from typing import Any


class OWNError(Exception):
    """Base exception for all OWNd errors."""

    def __init__(self, message: str = "OpenWebNet error", *, reason: str | None = None) -> None:
        super().__init__(message)
        self.reason = reason


class OWNConnectionError(OWNError):
    """Socket or transport connection failure (refused, reset, EOF, or unavailable)."""


class OWNTimeoutError(OWNConnectionError):
    """Timed out during TCP connection, session negotiation, or command response."""


class OWNAuthError(OWNError):
    """Gateway authentication failed (missing password, invalid password, or rejected digest)."""


class OWNNackError(OWNError):
    """Gateway rejected a frame or negotiation step with NACK (``*#*0##``)."""

    def __init__(
        self,
        message: str = "Gateway rejected frame with NACK",
        *,
        frame: str = "",
        responses: list[Any] | None = None,
        reason: str | None = "nack",
        busy: bool = False,
    ) -> None:
        super().__init__(message, reason=reason)
        self.frame = frame
        self.responses: list[Any] = list(responses) if responses is not None else []
        self.busy: bool = busy


class OWNProtocolError(OWNError):
    """Invalid outbound OpenWebNet frame or unexpected signaling response."""

    def __init__(
        self,
        message: str = "Invalid or unexpected OpenWebNet frame",
        *,
        frame: str = "",
        reason: str | None = "protocol_error",
    ) -> None:
        super().__init__(message, reason=reason)
        self.frame = frame


__all__ = [
    "OWNAuthError",
    "OWNConnectionError",
    "OWNError",
    "OWNNackError",
    "OWNProtocolError",
    "OWNTimeoutError",
]
