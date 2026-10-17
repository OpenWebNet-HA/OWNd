"""WHO 2: Automation subsystem events and commands."""

from __future__ import annotations

import re

from .base import (
    OWNCommand,
    OWNEvent,
    register_command_parser,
    register_event_parser,
    require_non_empty_where,
)


class OWNAutomationEvent(OWNEvent):
    def __init__(self, data: str) -> None:
        super().__init__(data)

        self._state = None
        self._position = None
        self._position_unknown = False
        self._priority = None
        self._info = None
        self._is_opening = None
        self._is_closing = None
        self._is_closed = None

        if self._what is not None and self._what != 1000:
            self._state = self._what

        if self._dimension == 10:
            try:
                self._state = (
                    int(self._dimension_value[0])
                    if len(self._dimension_value) > 0 and self._dimension_value[0]
                    else None
                )
                self._position = (
                    int(self._dimension_value[1])
                    if len(self._dimension_value) > 1 and self._dimension_value[1]
                    else None
                )
                # shutterLevel is 0-100; 255 means "unknown position" and
                # anything else out of range is treated the same way.
                if self._position is not None and not 0 <= self._position <= 100:
                    self._position = None
                    self._position_unknown = True
                self._priority = (
                    int(self._dimension_value[2])
                    if len(self._dimension_value) > 2 and self._dimension_value[2]
                    else None
                )
                self._info = (
                    int(self._dimension_value[3])
                    if len(self._dimension_value) > 3 and self._dimension_value[3]
                    else None
                )
            except (IndexError, TypeError, ValueError):
                pass

        if self._state == 0:
            self._human_readable_log = (
                f"Cover {self._where}{self._interface_log_text} stopped."
            )
            self._is_opening = False
            self._is_closing = False
        elif self._state == 10:
            self._is_opening = False
            self._is_closing = False
            if self._position_unknown:
                self._human_readable_log = f"Cover {self._where}{self._interface_log_text} is stopped at an unknown position."  # pylint: disable=line-too-long
            elif self._position == 0:
                self._human_readable_log = (
                    f"Cover {self._where}{self._interface_log_text} is closed."
                )
                self._is_closed = True
            else:
                self._human_readable_log = f"Cover {self._where}{self._interface_log_text} is opened at {self._position}%."
                self._is_closed = False
        elif self._state == 1:
            self._human_readable_log = (
                f"Cover {self._where}{self._interface_log_text} is opening."
            )
            self._is_opening = True
            self._is_closing = False
        elif self._state == 11 or self._state == 13:
            self._human_readable_log = f"Cover {self._where}{self._interface_log_text} is opening from {self._initial_position_text}."  # pylint: disable=line-too-long
            self._is_opening = True
            self._is_closing = False
            self._is_closed = False
        elif self._state == 2:
            self._human_readable_log = (
                f"Cover {self._where}{self._interface_log_text} is closing."
            )
            self._is_closing = True
            self._is_opening = False
        elif self._state == 12 or self._state == 14:
            self._human_readable_log = f"Cover {self._where}{self._interface_log_text} is closing from {self._initial_position_text}."  # pylint: disable=line-too-long
            self._is_closing = True
            self._is_opening = False
            self._is_closed = False

    @property
    def _initial_position_text(self) -> str:
        if self._position_unknown:
            return "an unknown position"
        return f"initial position {self._position}"

    @property
    def state(self) -> int | None:
        return self._state

    @property
    def is_opening(self) -> bool | None:
        return self._is_opening

    @property
    def is_closing(self) -> bool | None:
        return self._is_closing

    @property
    def is_closed(self) -> bool | None:
        return self._is_closed

    @property
    def current_position(self) -> int | None:
        return self._position

    @property
    def is_position_unknown(self) -> bool:
        """True when the shutter level is 255 (unknown) or outside 0-100."""
        return self._position_unknown



class OWNAutomationCommand(OWNCommand):
    @classmethod
    def status(cls, where: str | int) -> OWNAutomationCommand:
        message = cls(f"*#2*{where}##")
        message._human_readable_log = (
            f"Requesting shutter {message._where}{message._interface_log_text} status."
        )
        return message

    @classmethod
    def get_shutter_status(cls, where: str | int) -> OWNAutomationCommand:
        message = cls(f"*#2*{where}*10##")
        message._human_readable_log = f"Requesting shutter {message._where}{message._interface_log_text} advanced status (dimension 10)."
        return message

    @classmethod
    def raise_shutter(cls, where: str | int) -> OWNAutomationCommand:
        message = cls(f"*2*1*{where}##")
        message._human_readable_log = (
            f"Raising shutter {message._where}{message._interface_log_text}."
        )
        return message

    @classmethod
    def lower_shutter(cls, where: str | int) -> OWNAutomationCommand:
        message = cls(f"*2*2*{where}##")
        message._human_readable_log = (
            f"Lowering shutter {message._where}{message._interface_log_text}."
        )
        return message

    @classmethod
    def stop_shutter(cls, where: str | int) -> OWNAutomationCommand:
        message = cls(f"*2*0*{where}##")
        message._human_readable_log = (
            f"Stopping shutter {message._where}{message._interface_log_text}."
        )
        return message

    @classmethod
    def set_shutter_level(cls, where: str | int, level: int = 30) -> OWNAutomationCommand:
        target = require_non_empty_where(where)
        lvl = int(level)
        if not 0 <= lvl <= 100:
            raise ValueError("shutter level must be between 0 and 100")
        message = cls(f"*#2*{target}*#11#001*{lvl}##")
        message._human_readable_log = f"Setting shutter {message._where}{message._interface_log_text} position to {lvl}%."
        return message


register_event_parser(2, OWNAutomationEvent)
register_command_parser(2, OWNAutomationCommand)
