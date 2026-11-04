"""WHO 2: Automation subsystem events and commands.

Specification caveats (documentation context only; the decoding below is the
long-standing behaviour and is not changed on the strength of these notes, as
no committed on-wire plant trace exercises the advanced forms):

- ``WHO_2.pdf`` / Encyclopedia ``who-2-automation/what.md``: WHAT 0 Stop, 1 Up
  and 2 Down are the base command WHATs; ``*2*10#PRIORITY*WHERE##``,
  ``*2*11#STEP#PRIORITY*WHERE##`` and ``*2*12#STEP#PRIORITY*WHERE##`` are the
  published Advanced Stop / Up / Down forms (STEP ``1..99`` relative, ``100``
  or omitted end point; PRIORITY a 3-digit ``p1p2p3`` bit field), and ``13`` /
  ``14`` are listed only as DIMENSION 10 state values. ``OWNAutomationEvent``
  keeps reading any command WHAT into ``state`` as before.
- ``dimensions.md``: DIMENSION 10 is ``STATUS*LEVEL*PRIORITY*INFO`` (level
  ``255`` = unknown position; info ``0`` normal, ``12`` PUL + disabled, ``13``
  disabled, ``14`` command not executed, ``15`` PUL); DIMENSION 11 is the
  go-to-level write ``*#2*WHERE*#11#PRIORITY*LEVEL##``. The published
  event-session form is ``*#2*WHERE*#11#PRIORITY#LEVEL*SELECTOR##`` (LEVEL as
  the second ``#`` parameter), while an F461 2.0.11 echoes the write form
  ``*#2*25*#11#001#1*50##`` on the event session (golden fixture
  ``cover.evt.level.50.virtual.25.f461``); both shapes parse as
  ``OWNAutomationCommand`` and are not decoded further.
- ``addressing.md#where-forms``: WHERE is ``0``, ``A``, ``APL``, ``#GR`` or
  ``APL#4#INTERFACE``; an empty WHERE is not a WHO 2 address, and the firmware
  oracle NACKs ``*2*1*##`` / ``*#2**10##`` on all twelve emulated gateways, so
  the builders reject an empty or ``*`` WHERE (``require_non_empty_where``).
"""

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
    """A WHO 2 movement event or DIMENSION 10 status reply.

    ``state`` is the command WHAT of a command frame, or the DIMENSION 10
    ``shutterStatus`` of a status reply, with ``current_position`` from the
    DIMENSION 10 level; the priority and info fields are read into private
    attributes only. The advanced-command parameters (STEP, PRIORITY,
    SELECTOR) stay in ``what_param`` undecoded: see the module docstring.
    """

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
    """WHO 2 builders and parsed command frames.

    Every builder passes its WHERE through ``require_non_empty_where``: an
    empty, blank or ``*`` WHERE is not a WHO 2 address
    (``addressing.md#where-forms``) and the resulting ``*2*1*##`` /
    ``*#2**10##`` are NACKed by every emulated gateway in the firmware oracle.
    A DIMENSION 11 go-to-level frame (the write or the F461 event-session echo,
    see the module docstring) stays a plain command object.
    """

    @classmethod
    def status(cls, where: str | int) -> OWNAutomationCommand:
        target = require_non_empty_where(where)
        message = cls(f"*#2*{target}##")
        message._human_readable_log = (
            f"Requesting shutter {message._where}{message._interface_log_text} status."
        )
        return message

    @classmethod
    def get_shutter_status(cls, where: str | int) -> OWNAutomationCommand:
        target = require_non_empty_where(where)
        message = cls(f"*#2*{target}*10##")
        message._human_readable_log = f"Requesting shutter {message._where}{message._interface_log_text} advanced status (dimension 10)."
        return message

    @classmethod
    def raise_shutter(cls, where: str | int) -> OWNAutomationCommand:
        target = require_non_empty_where(where)
        message = cls(f"*2*1*{target}##")
        message._human_readable_log = (
            f"Raising shutter {message._where}{message._interface_log_text}."
        )
        return message

    @classmethod
    def lower_shutter(cls, where: str | int) -> OWNAutomationCommand:
        target = require_non_empty_where(where)
        message = cls(f"*2*2*{target}##")
        message._human_readable_log = (
            f"Lowering shutter {message._where}{message._interface_log_text}."
        )
        return message

    @classmethod
    def stop_shutter(cls, where: str | int) -> OWNAutomationCommand:
        target = require_non_empty_where(where)
        message = cls(f"*2*0*{target}##")
        message._human_readable_log = (
            f"Stopping shutter {message._where}{message._interface_log_text}."
        )
        return message

    @classmethod
    def set_shutter_level(cls, where: str | int, level: int = 30) -> OWNAutomationCommand:
        target = require_non_empty_where(where)
        if (
            isinstance(level, bool)
            or (isinstance(level, float) and level % 1 != 0)
            or not 0 <= int(level) <= 100
        ):
            raise ValueError("shutter level must be between 0 and 100")
        lvl = int(level)
        message = cls(f"*#2*{target}*#11#001*{lvl}##")
        message._human_readable_log = f"Setting shutter {message._where}{message._interface_log_text} position to {lvl}%."
        return message

    @property
    def is_status_query(self) -> bool:
        """True if this message is a shutter status query (*#2*WHERE##)."""
        return self.is_status_request and bool(self._where)

    @property
    def is_shutter_status_query(self) -> bool:
        """True if this message is an advanced shutter status query (*#2*WHERE*10##)."""
        return (
            self.is_dimension_request
            and self._dimension == 10
            and bool(self._where)
        )

    @classmethod
    def report_shutter_level(
        cls,
        where: str | int,
        level: int,
        state: int = 10,
        priority: int | str = 0,
        info: int = 0,
    ) -> OWNAutomationCommand:
        """Build a WHO 2 Dimension 10 advanced shutter status reply (*#2*WHERE*10*STATE*LEVEL*PRIORITY*INFO##)."""
        target = require_non_empty_where(where)
        if any(
            isinstance(x, bool) or (isinstance(x, float) and x % 1 != 0)
            for x in (level, state, priority, info)
        ):
            raise ValueError("shutter level, state, priority, and info must be integers")
        lvl = int(level)
        if not (0 <= lvl <= 100 or lvl == 255):
            raise ValueError("shutter level must be between 0 and 100 or 255")
        st = int(state)
        if not 10 <= st <= 15:
            raise ValueError("shutter state must be between 10 and 15")
        pr = int(priority)
        inf = int(info)
        if not (0 <= pr <= 255 and 0 <= inf <= 255):
            raise ValueError("priority and info must be between 0 and 255")
        pr_str = (
            priority.strip()
            if isinstance(priority, str)
            and priority.strip().isdigit()
            and len(priority.strip()) <= 3
            else str(pr)
        )
        message = cls(f"*#2*{target}*10*{st}*{lvl}*{pr_str}*{inf}##")
        message._human_readable_log = (
            f"Reporting shutter {message._where}{message._interface_log_text} position at {lvl}% (state {st})."
        )
        return message


register_event_parser(2, OWNAutomationEvent)
register_command_parser(2, OWNAutomationCommand)
