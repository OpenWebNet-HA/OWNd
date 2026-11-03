"""WHO 2: Automation subsystem events and commands.

Evidence (OpenWebNet Encyclopedia, ``encyclopedia_functional/who-2-automation/``):

- ``what.md#base-commands``: WHAT 0 Stop, 1 Up, 2 Down are the command WHATs.
- ``what.md#advanced-commands`` / ``#parameter-format``: ``*2*10#PRIORITY*WHERE##``
  (Advanced Stop), ``*2*11#STEP#PRIORITY*WHERE##`` (Advanced Up) and
  ``*2*12#STEP#PRIORITY*WHERE##`` (Advanced Down); the event-session form
  appends a set/clear ``SELECTOR`` (``*2*10#PRIORITY#SELECTOR*WHERE##``,
  ``*2*11#STEP#PRIORITY#SELECTOR*WHERE##``). STEP ``1..99`` is a relative
  movement, ``100`` or omitted means the end point; PRIORITY is a 3-digit
  bit field ``p1p2p3`` = Safety, High, Medium. "parsing only the leading
  number loses the requested step and priority operation". On-wire frames
  of an LN4660M2 (``#observed-physical-transmitter-frames``):
  ``*2*11#100#001#1*0##``, ``*2*12#100#001#1*0##``, ``*2*10#001#1*0##``.
- ``what.md#state-values-are-not-commands`` and
  ``dimensions.md#shutter-status``: ``10..14`` are DIMENSION 10 state values
  (Stop, Up, Down, step-by-step Up, step-by-step Down); ``13`` and ``14`` "are
  not established ordinary command WHAT values".
- ``dimensions.md#dimension-10---shutter-status``: payload
  ``SHUTTER_STATUS*SHUTTER_LEVEL*SHUTTER_PRIORITY*SHUTTER_INFO``; level
  ``255`` = unknown position (``#shutter-level``); info ``0`` normal, ``12``
  PUL + disabled, ``13`` disabled, ``14`` command not executed, ``15`` PUL
  (``#shutter-information``).
- ``dimensions.md#dimension-11---go-to-level``: the only position write is
  ``*#2*WHERE*#11#SHUTTER_PRIORITY*SHUTTER_LEVEL##`` (there is no
  DIMENSION 10 write); ``#resulting-state-traffic``: "Event traffic can
  therefore include the DIMENSION 11 operation" (captured as
  ``*#2*25*#11#001#1*50##`` on an F461 2.0.11, golden fixture
  ``cover.evt.level.50.virtual.25.f461``). Both the write and its echo keep
  parsing as ``OWNAutomationCommand`` (DIMENSION 11 is write-only for WHO 2
  and MyHOME pins the class for scope echoes); the command object decodes
  ``target_level``, ``priority`` and ``selector``, and claims no movement.
- ``addressing.md#where-forms``: WHERE is ``0``, ``A``, ``APL``, ``#GR`` or
  ``APL#4#INTERFACE``; an empty WHERE or ``*`` is not a WHO 2 address.
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

_require_non_empty_where = require_non_empty_where

#: DIMENSION 10 ``shutterStatus`` values (``dimensions.md#shutter-status``).
SHUTTER_STATUS_STOP = 10
SHUTTER_STATUS_UP = 11
SHUTTER_STATUS_DOWN = 12
SHUTTER_STATUS_STEP_UP = 13
SHUTTER_STATUS_STEP_DOWN = 14
SHUTTER_STATUSES = range(SHUTTER_STATUS_STOP, SHUTTER_STATUS_STEP_DOWN + 1)

#: DIMENSION 10 ``shutterInfo`` values (``dimensions.md#shutter-information``).
SHUTTER_INFO_NAMES: dict[int, str] = {
    0: "normal",
    12: "PUL + disabled",
    13: "disabled",
    14: "command not executed",
    15: "PUL",
}

#: Advanced command WHATs (``what.md#advanced-commands``).
ADVANCED_STOP = 10
ADVANCED_UP = 11
ADVANCED_DOWN = 12

_PRIORITY_BITFIELD = re.compile(r"^[01]{3}$")
_SHUTTER_LEVEL_UNKNOWN = 255


def _priority_bitfield(value: str | None) -> str | None:
    """The ``p1p2p3`` bit field of a priority value, None when it is not one.

    Rule: exactly three ``0`` / ``1`` characters are the bit field (Safety,
    High, Medium; ``what.md#parameter-format``, ``dimensions.md#shutter-priority``,
    the ``001`` every gateway capture carries). Anything else (``1``, ``7``,
    ``10``) is only a decimal ``priority`` integer with no bit field: the
    Encyclopedia records no shortened form, and reading ``10`` as ``010`` would
    invent a High flag. ``report_shutter_level(priority=10)`` therefore emits
    ``*10*`` and parses back as ``priority 10``, ``priority_bitfield None``.
    """
    if value is None or not _PRIORITY_BITFIELD.match(value):
        return None
    return value


def _int_or_none(value: str | None) -> int | None:
    if value is None or value == "":
        return None
    try:
        return int(value)
    except ValueError:
        return None


def _decode_go_to_level_fields(
    dimension_param: list[str], dimension_value: list[str]
) -> tuple[int | None, str | None, int | None, int | None]:
    """``#PRIORITY[#SEL]`` and ``*LEVEL`` of a DIMENSION 11 frame.

    Returns ``(priority, priority_bitfield, selector, target_level)``;
    ``dimensions.md#dimension-11---go-to-level`` / ``#target-level``: the level
    is 0..100, ``255`` is not a target position.
    """
    priority = dimension_param[0] if dimension_param else None
    selector = _int_or_none(dimension_param[1]) if len(dimension_param) > 1 else None
    if selector not in (None, 0, 1):
        selector = None
    level = _int_or_none(dimension_value[0]) if dimension_value else None
    target = level if level is not None and 0 <= level <= 100 else None
    return _int_or_none(priority), _priority_bitfield(priority), selector, target


def _priority_log_suffix(priority: int | None, bitfield: str | None, selector: int | None) -> str:
    parts: list[str] = []
    if bitfield is not None:
        parts.append(f"priority {bitfield}")
    elif priority is not None:
        parts.append(f"priority {priority}")
    if selector == 1:
        parts.append("set")
    elif selector == 0:
        parts.append("clear")
    return f" ({', '.join(parts)})" if parts else ""


class OWNAutomationEvent(OWNEvent):
    """A WHO 2 movement event, advanced command echo or status reply.

    ``state`` is the movement state only: WHAT ``0`` / ``1`` / ``2`` of a base
    command frame, or the DIMENSION 10 ``shutterStatus`` ``10..14`` of a
    status reply. Advanced WHATs ``10`` / ``11`` / ``12`` are decoded into
    ``is_advanced_stop`` / ``is_advanced_up`` / ``is_advanced_down`` with
    ``step``, ``priority`` and ``selector``; they claim no position and no
    closed state. WHAT ``13`` / ``14`` (and any other WHAT) are not WHO 2
    commands (``what.md#state-values-are-not-commands``): nothing is claimed.
    """

    def __init__(self, data: str) -> None:
        super().__init__(data)

        self._state: int | None = None
        self._position: int | None = None
        self._position_unknown = False
        self._priority: int | None = None
        self._priority_bitfield: str | None = None
        self._info: int | None = None
        self._is_opening: bool | None = None
        self._is_closing: bool | None = None
        self._is_closed: bool | None = None
        self._advanced: int | None = None
        self._step: int | None = None
        self._selector: int | None = None
        self._target_level: int | None = None
        self._end_point: bool | None = None
        self._unknown_what: int | None = None

        if self._what in (0, 1, 2):
            self._state = self._what
        elif self._what in (ADVANCED_STOP, ADVANCED_UP, ADVANCED_DOWN):
            self._decode_advanced()
        elif self._what is not None and self._what != 1000:
            # 13 / 14 are DIMENSION 10 state values, not command WHATs; any
            # other value is not a WHO 2 command either. Fail closed.
            self._unknown_what = self._what
            self._human_readable_log = f"Cover {self._where}{self._interface_log_text}: unknown command code {self._what}."  # pylint: disable=line-too-long

        if self._dimension == 10 and self._message_type == "DIMENSION_REQUEST_REPLY":
            self._decode_shutter_status()
        elif self._dimension == 11 and self._message_type == "DIMENSION_WRITING":
            self._decode_go_to_level()

        if self._state == 0:
            self._human_readable_log = (
                f"Cover {self._where}{self._interface_log_text} stopped."
            )
            self._is_opening = False
            self._is_closing = False
        elif self._state == SHUTTER_STATUS_STOP:
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
            self._human_readable_log = self._human_readable_log[:-1] + self._info_log_suffix + "."
        elif self._state == 1:
            self._human_readable_log = (
                f"Cover {self._where}{self._interface_log_text} is opening."
            )
            self._is_opening = True
            self._is_closing = False
        elif self._state in (SHUTTER_STATUS_UP, SHUTTER_STATUS_STEP_UP):
            self._human_readable_log = f"Cover {self._where}{self._interface_log_text} is opening from {self._initial_position_text}{self._info_log_suffix}."  # pylint: disable=line-too-long
            self._is_opening = True
            self._is_closing = False
            self._is_closed = False
        elif self._state == 2:
            self._human_readable_log = (
                f"Cover {self._where}{self._interface_log_text} is closing."
            )
            self._is_closing = True
            self._is_opening = False
        elif self._state in (SHUTTER_STATUS_DOWN, SHUTTER_STATUS_STEP_DOWN):
            self._human_readable_log = f"Cover {self._where}{self._interface_log_text} is closing from {self._initial_position_text}{self._info_log_suffix}."  # pylint: disable=line-too-long
            self._is_closing = True
            self._is_opening = False
            self._is_closed = False

    def _decode_advanced(self) -> None:
        """``*2*10#PRIORITY[#SEL]*W##``, ``*2*11#STEP#PRIORITY[#SEL]*W##``, ``*2*12#...``."""
        self._advanced = self._what
        params = list(self._what_param)
        if self._what == ADVANCED_STOP:
            priority = params[0] if params else None
            selector = params[1] if len(params) > 1 else None
        elif params:
            # The grammar fixes the first field as STEP (what.md#parameter-format:
            # ``11#STEP#PRIORITY``), so a single parameter is the STEP and the
            # priority is simply absent. STEP 1..99 relative, 100 end point
            # (what.md#step); anything else is not a step and is left as None
            # with the raw what_param.
            step = _int_or_none(params[0])
            self._step = step if step is not None and 1 <= step <= 100 else None
            priority = params[1] if len(params) > 1 else None
            selector = params[2] if len(params) > 2 else None
        else:
            priority = None
            selector = None
        self._priority_bitfield = _priority_bitfield(priority)
        self._priority = _int_or_none(priority)
        self._selector = _int_or_none(selector)
        if self._selector not in (None, 0, 1):
            self._selector = None

        suffix = self._advanced_log_suffix
        if self._what == ADVANCED_STOP:
            self._is_opening = False
            self._is_closing = False
            self._human_readable_log = (
                f"Cover {self._where}{self._interface_log_text} advanced stop{suffix}."
            )
            return
        direction = "up" if self._what == ADVANCED_UP else "down"
        self._is_opening = self._what == ADVANCED_UP
        self._is_closing = self._what == ADVANCED_DOWN
        if not params:
            # No parameter at all: an omitted STEP is the end point (what.md#step).
            self._end_point = True
            movement = "to the end point"
        elif self._step is None:
            self._end_point = None
            movement = "(step not decoded)"
        else:
            self._end_point = self._step == 100
            movement = "to the end point" if self._end_point else f"by {self._step}%"
        self._human_readable_log = f"Cover {self._where}{self._interface_log_text} advanced {direction} {movement}{suffix}."  # pylint: disable=line-too-long

    @property
    def _advanced_log_suffix(self) -> str:
        return _priority_log_suffix(self._priority, self._priority_bitfield, self._selector)

    def _decode_shutter_status(self) -> None:
        """``*#2*WHERE*10*STATUS*LEVEL*PRIORITY*INFO##`` (``dimensions.md#dimension-10---shutter-status``)."""
        values = self._dimension_value
        status = _int_or_none(values[0]) if values else None
        # 10..14 only: anything else is not a shutter status.
        self._state = status if status in SHUTTER_STATUSES else None
        self._position = _int_or_none(values[1]) if len(values) > 1 else None
        # shutterLevel is 0-100; 255 means "unknown position" and anything
        # else out of range is treated the same way.
        if self._position is not None and not 0 <= self._position <= 100:
            self._position = None
            self._position_unknown = True
        priority = values[2] if len(values) > 2 else None
        self._priority = _int_or_none(priority)
        self._priority_bitfield = _priority_bitfield(priority)
        self._info = _int_or_none(values[3]) if len(values) > 3 else None

    def _decode_go_to_level(self) -> None:
        """``*#2*WHERE*#11#PRIORITY[#SEL]*LEVEL##`` handed directly to ``OWNEvent.parse``.

        ``OWNMessage.parse`` never routes a DIMENSION 11 frame here (it stays an
        ``OWNAutomationCommand``, which decodes the same fields); this keeps the
        event class consistent when a caller parses the echo as an event.
        """
        (
            self._priority,
            self._priority_bitfield,
            self._selector,
            self._target_level,
        ) = _decode_go_to_level_fields(self._dimension_param, self._dimension_value)
        target = (
            f"go to level {self._target_level}%"
            if self._target_level is not None
            else "go to an invalid level"
        )
        self._human_readable_log = f"Cover {self._where}{self._interface_log_text} {target}{self._advanced_log_suffix}."  # pylint: disable=line-too-long

    @property
    def _info_log_suffix(self) -> str:
        """`` (command not executed)`` and the other non-normal shutterInfo names."""
        if self._info in (None, 0):
            return ""
        name = SHUTTER_INFO_NAMES.get(self._info)
        return f" ({name})" if name is not None else f" (info {self._info})"

    @property
    def _initial_position_text(self) -> str:
        if self._position_unknown:
            return "an unknown position"
        return f"initial position {self._position}"

    @property
    def state(self) -> int | None:
        """Movement state: WHAT 0/1/2 of a base command, or shutterStatus 10..14 of a Dimension 10 reply."""
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

    @property
    def is_advanced_stop(self) -> bool:
        """``*2*10#PRIORITY[#SELECTOR]*WHERE##`` (``what.md#advanced-commands``)."""
        return self._advanced == ADVANCED_STOP

    @property
    def is_advanced_up(self) -> bool:
        """``*2*11#STEP#PRIORITY[#SELECTOR]*WHERE##``."""
        return self._advanced == ADVANCED_UP

    @property
    def is_advanced_down(self) -> bool:
        """``*2*12#STEP#PRIORITY[#SELECTOR]*WHERE##``."""
        return self._advanced == ADVANCED_DOWN

    @property
    def step(self) -> int | None:
        """Advanced Up/Down STEP: 1..99 relative movement, 100 end point; None when absent or not a step."""
        return self._step

    @property
    def moves_to_end_point(self) -> bool | None:
        """Advanced Up/Down: True for STEP 100 or an omitted STEP, False for 1..99, None when not decoded."""
        return self._end_point

    @property
    def priority(self) -> int | None:
        """Priority field as an integer (``001`` -> 1) of an advanced command, a Dimension 10 reply or a Dimension 11 echo."""
        return self._priority

    @property
    def priority_bitfield(self) -> str | None:
        """Priority as the 3-digit ``p1p2p3`` bit field (Safety, High, Medium), None when the field is not one."""
        return self._priority_bitfield

    @property
    def priority_safety(self) -> bool | None:
        return None if self._priority_bitfield is None else self._priority_bitfield[0] == "1"

    @property
    def priority_high(self) -> bool | None:
        return None if self._priority_bitfield is None else self._priority_bitfield[1] == "1"

    @property
    def priority_medium(self) -> bool | None:
        return None if self._priority_bitfield is None else self._priority_bitfield[2] == "1"

    @property
    def selector(self) -> int | None:
        """Event-session set/clear selector: 1 set priority, 0 clear priority, None when absent."""
        return self._selector

    @property
    def info(self) -> int | None:
        """Dimension 10 ``shutterInfo`` as sent (0, 12, 13, 14, 15)."""
        return self._info

    @property
    def info_name(self) -> str | None:
        """``shutterInfo`` name: normal, PUL + disabled, disabled, command not executed, PUL; None for other values."""
        return SHUTTER_INFO_NAMES.get(self._info) if self._info is not None else None

    @property
    def is_command_not_executed(self) -> bool | None:
        """True when ``shutterInfo`` is 14, None when the reply carries no info field."""
        return None if self._info is None else self._info == 14

    @property
    def target_level(self) -> int | None:
        """Dimension 11 target position 0..100 when the frame was parsed as an event directly."""
        return self._target_level

    @property
    def is_go_to_level(self) -> bool:
        """True for ``*#2*WHERE*#11#PRIORITY[#SELECTOR]*LEVEL##`` parsed as an event directly."""
        return self._dimension == 11 and self._message_type == "DIMENSION_WRITING"

    @property
    def unknown_command_code(self) -> int | None:
        """A WHAT that is not a WHO 2 command (13, 14 or any other value), None otherwise."""
        return self._unknown_what


class OWNAutomationCommand(OWNCommand):
    """WHO 2 builders. Every WHERE goes through ``_require_non_empty_where``:
    ``addressing.md#where-forms`` defines ``0``, ``A``, ``APL``, ``#GR`` and
    ``APL#4#INTERFACE`` only, so ``''`` and ``'*'`` raise ``ValueError``.

    A parsed DIMENSION 11 go-to-level frame (the write
    ``*#2*WHERE*#11#PRIORITY*LEVEL##`` or its event-session echo
    ``*#2*25*#11#001#1*50##``, ``dimensions.md#dimension-11---go-to-level``)
    stays a command object: it exposes ``target_level``, ``priority``,
    ``priority_bitfield``, ``selector`` and ``is_go_to_level`` and never
    claims a movement, so a general / area / group echo is not a stop.
    """

    def __init__(self, data: str) -> None:
        super().__init__(data)
        self._priority: int | None = None
        self._priority_bitfield: str | None = None
        self._selector: int | None = None
        self._target_level: int | None = None
        if self.is_go_to_level:
            (
                self._priority,
                self._priority_bitfield,
                self._selector,
                self._target_level,
            ) = _decode_go_to_level_fields(self._dimension_param, self._dimension_value)
            target = (
                f"go to level {self._target_level}%"
                if self._target_level is not None
                else "go to an invalid level"
            )
            suffix = _priority_log_suffix(self._priority, self._priority_bitfield, self._selector)
            self._human_readable_log = f"Cover {self._where}{self._interface_log_text} {target}{suffix}."

    @property
    def is_go_to_level(self) -> bool:
        """True for ``*#2*WHERE*#11#PRIORITY[#SELECTOR]*LEVEL##`` (write or event-session echo)."""
        return self._dimension == 11 and self._message_type == "DIMENSION_WRITING"

    @property
    def target_level(self) -> int | None:
        """Dimension 11 target position 0..100 (``255`` is not a target), else ``None``."""
        return self._target_level

    @property
    def priority(self) -> int | None:
        """Priority field of a go-to-level frame as an integer (``001`` -> 1), else ``None``."""
        return self._priority

    @property
    def priority_bitfield(self) -> str | None:
        """Priority as the 3-digit ``p1p2p3`` bit field, ``None`` when absent or not one."""
        return self._priority_bitfield

    @property
    def selector(self) -> int | None:
        """Event-session set/clear selector of a go-to-level echo (1 set, 0 clear), else ``None``."""
        return self._selector

    @classmethod
    def status(cls, where: str | int) -> OWNAutomationCommand:
        target = _require_non_empty_where(where)
        message = cls(f"*#2*{target}##")
        message._human_readable_log = (
            f"Requesting shutter {message._where}{message._interface_log_text} status."
        )
        return message

    @classmethod
    def get_shutter_status(cls, where: str | int) -> OWNAutomationCommand:
        target = _require_non_empty_where(where)
        message = cls(f"*#2*{target}*10##")
        message._human_readable_log = f"Requesting shutter {message._where}{message._interface_log_text} advanced status (dimension 10)."
        return message

    @classmethod
    def raise_shutter(cls, where: str | int) -> OWNAutomationCommand:
        target = _require_non_empty_where(where)
        message = cls(f"*2*1*{target}##")
        message._human_readable_log = (
            f"Raising shutter {message._where}{message._interface_log_text}."
        )
        return message

    @classmethod
    def lower_shutter(cls, where: str | int) -> OWNAutomationCommand:
        target = _require_non_empty_where(where)
        message = cls(f"*2*2*{target}##")
        message._human_readable_log = (
            f"Lowering shutter {message._where}{message._interface_log_text}."
        )
        return message

    @classmethod
    def stop_shutter(cls, where: str | int) -> OWNAutomationCommand:
        target = _require_non_empty_where(where)
        message = cls(f"*2*0*{target}##")
        message._human_readable_log = (
            f"Stopping shutter {message._where}{message._interface_log_text}."
        )
        return message

    @classmethod
    def set_shutter_level(cls, where: str | int, level: int = 30) -> OWNAutomationCommand:
        """``*#2*WHERE*#11#001*LEVEL##`` (``dimensions.md#dimension-11---go-to-level``, priority 001 = Medium)."""
        target = _require_non_empty_where(where)
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
        """Build a WHO 2 Dimension 10 advanced shutter status reply.

        ``*#2*WHERE*10*STATE*LEVEL*PRIORITY*INFO##`` (``dimensions.md#dimension-10---shutter-status``):
        ``state`` 10..14, ``level`` 0..100 or 255 (unknown position),
        ``priority`` as the 3-digit ``p1p2p3`` bit field given as a string
        (``"001"``, sent as given), or as an int 0..255 emitted as its decimal
        text (``0`` -> ``*0*``, the pre-existing form MyHOME's expose replies
        pin), ``info`` 0, 12, 13, 14 or 15.
        """
        target = _require_non_empty_where(where)
        numbers = [level, state, info] + ([] if isinstance(priority, str) else [priority])
        if any(
            isinstance(x, bool) or (isinstance(x, float) and x % 1 != 0)
            for x in numbers
        ):
            raise ValueError("shutter level, state, priority, and info must be integers")
        lvl = int(level)
        if not (0 <= lvl <= 100 or lvl == _SHUTTER_LEVEL_UNKNOWN):
            raise ValueError("shutter level must be between 0 and 100 or 255")
        st = int(state)
        if st not in SHUTTER_STATUSES:
            raise ValueError("shutter state must be between 10 and 14")
        pr_str = cls._priority_field(priority)
        inf = int(info)
        if inf not in SHUTTER_INFO_NAMES:
            raise ValueError("shutter info must be 0, 12, 13, 14 or 15")
        message = cls(f"*#2*{target}*10*{st}*{lvl}*{pr_str}*{inf}##")
        position = (
            "at an unknown position"
            if lvl == _SHUTTER_LEVEL_UNKNOWN
            else f"position at {lvl}%"
        )
        message._human_readable_log = (
            f"Reporting shutter {message._where}{message._interface_log_text} {position} (state {st})."
        )
        return message

    @staticmethod
    def _priority_field(priority: int | str) -> str:
        """The priority field as before: a string of up to three digits is sent
        as given (``"001"`` is the ``p1p2p3`` bit field), anything else is an
        int 0..255 sent as its decimal text (``0`` -> ``*0*``).

        Kept unchanged for MyHOME, whose expose replies pin
        ``*#2*21*10*12*40*0*0##`` and ``priority="00001"`` -> ``*1*``.
        """
        text = priority.strip() if isinstance(priority, str) else str(int(priority))
        value = int(text)
        if not 0 <= value <= 255:
            raise ValueError("priority must be between 0 and 255")
        return text if text.isdigit() and len(text) <= 3 else str(value)


register_event_parser(2, OWNAutomationEvent)
register_command_parser(2, OWNAutomationCommand)
