"""WHO 15 & 25: CEN, CEN+, and Dry Contact / IR events and commands."""

from __future__ import annotations

import re

from .base import (
    OWNCommand,
    OWNEvent,
    register_command_parser,
    register_event_parser,
    require_non_empty_where,
)


class OWNCENEvent(OWNEvent):
    def __init__(self, data: str) -> None:
        super().__init__(data)

        self._state: str | None = self._what_param[0] if self._what_param else None
        self.push_button = self._what
        self.object = self._where

        if self._state is None:
            self._human_readable_log = f"Button {self.push_button} of CEN object {self.object}{self._interface_log_text} has been pressed."  # pylint: disable=line-too-long
        elif int(self._state) == 3:
            self._human_readable_log = f"Button {self.push_button} of CEN object {self.object}{self._interface_log_text} is being held pressed."  # pylint: disable=line-too-long
        elif int(self._state) == 1:
            self._human_readable_log = f"Button {self.push_button} of CEN object {self.object}{self._interface_log_text} has been released after a short press."  # pylint: disable=line-too-long
        elif int(self._state) == 2:
            self._human_readable_log = f"Button {self.push_button} of CEN object {self.object}{self._interface_log_text} has been released after a long press."  # pylint: disable=line-too-long
        else:
            self._human_readable_log = f"Button {self.push_button} of CEN object {self.object}{self._interface_log_text} state is {self._state}."

    @property
    def is_pressed(self) -> bool:
        return self._state is None

    @property
    def is_held(self) -> bool:
        return self._state is not None and int(self._state) == 3

    @property
    def is_released_after_short_press(self) -> bool:
        return self._state is not None and int(self._state) == 1

    @property
    def is_released_after_long_press(self) -> bool:
        return self._state is not None and int(self._state) == 2



class OWNDryContactEvent(OWNEvent):
    """WHO 25 WHAT 31 / 32 dry contact and IR frames.

    Page grammar (Encyclopedia ``functional/who-25-transversal/dry-contact-ir.md``
    #what, #where): ``*25*31#P*WHERE##`` is ON / IR detection, ``*25*32#P*WHERE##``
    OFF / no detection; the parameter ``P`` is always present, ``0`` for a state
    returned by a request and ``1`` for an event. ``WHERE`` is ``1..201`` for
    automation interfaces or ``[1-9][1-9]`` (``Z`` ``N``) for alarm / IR devices.

    Firmware behaviour (ORACLE_CONFIRM.md row T1, report 21 §Confirmation): the
    emulated gateways read a leading ``3`` on the WHERE as a prefix in front of
    the sensor number: ``*#25*35##`` polls sensor ``05`` (bus telegram
    ``$04B4009005``), ``*#25*39##`` sensor ``09``, ``*#25*339##`` sensor ``39``,
    and the prefix-less ``*#25*5##`` is refused by all 12 gateways. Every dry
    contact captured on a bus carries that prefix (``31``, ``33``, ``331..339``
    on MH200N, MH202, F454 and H4890; golden fixture ``dry_contact.event.on.339``).
    ``where`` keeps the bus form; ``sensor`` is the number the firmware reads
    (the prefix stripped), so a documented page address ``35`` and the bus form
    of sensor ``5`` are the same frame on the wire.

    A frame without the ``P`` parameter (``*25*31*33##``) is not a published
    form: ``is_detection`` and ``is_state_reply`` are both ``False`` and the log
    says so.
    """

    def __init__(self, data: str) -> None:
        super().__init__(data)

        self._state = 1 if self._what == 31 else 0
        self._detection: int | None
        try:
            self._detection = int(self._what_param[0]) if self._what_param else None
        except (IndexError, TypeError, ValueError):
            self._detection = None
        where = self._where or ""
        self._sensor = (
            where[1:] if len(where) > 1 and where.startswith("3") else where
        )

        state_text = "ON" if self._state == 1 else "OFF"
        if self._detection == 1:
            self._human_readable_log = f"Sensor {self._sensor} detected {state_text}."
        elif self._detection == 0:
            self._human_readable_log = f"Sensor {self._sensor} reported {state_text}."
        else:
            self._human_readable_log = (
                f"Sensor {self._sensor} sent {state_text} without the WHAT parameter "
                "(not a published WHO 25 form: dry-contact-ir.md#what)."
            )

    @property
    def is_on(self) -> bool:
        return self._state == 1

    @property
    def sensor(self) -> str:
        """Sensor number as the firmware reads it: the bus WHERE without its ``3`` prefix.

        ``*25*31#1*339##`` -> ``"39"``; ``*25*31#1*35##`` -> ``"5"``. The inverse
        builder is ``OWNDryContactCommand.status_for_sensor``.
        """
        return self._sensor

    @property
    def is_detection(self) -> bool:
        """True for an event (``#1``); False for a state reply or a missing parameter."""
        return self._detection == 1

    @property
    def is_state_reply(self) -> bool:
        """True for a state returned by a request (``#0``)."""
        return self._detection == 0

    @property
    def human_readable_log(self) -> str:
        return self._human_readable_log



class OWNCENPlusEvent(OWNEvent):
    """WHO 25 WHAT 21..28 CEN+ frames (``*25*WHAT#PUSHBUTTON*2OBJECT##``).

    Encyclopedia ``functional/who-25-transversal/cen-plus.md``: #pushbutton-parameter
    gives the pushbutton range ``0..31`` (``0`` is a real button), #where---virtual-object
    the WHERE as the prefix ``2`` followed by an Object ``0..2047``. A pushbutton
    outside the range, or a missing one, leaves ``push_button`` ``None`` instead of
    pretending button 0 was pressed; a bare WHERE ``2`` carries no Object and
    leaves ``object`` ``None``. Both are logged.
    """

    def __init__(self, data: str) -> None:
        super().__init__(data)

        self._state = self._what
        self.push_button: int | None
        try:
            push_button = int(self._what_param[0]) if self._what_param else None
        except (IndexError, TypeError, ValueError):
            push_button = None
        self.push_button = (
            push_button if push_button is not None and 0 <= push_button <= 31 else None
        )
        where = self._where or ""
        self.object: str | None
        if len(where) > 1 and where.startswith("2"):
            self.object = where[1:]
        elif where == "2":
            self.object = None
        else:
            self.object = where

        if self.push_button is None:
            self._human_readable_log = (
                f"CEN+ object {self.object} sent WHAT {self._state} with pushbutton "
                f"{self._what_param[0] if self._what_param else 'missing'} "
                "(outside the published 0..31: cen-plus.md#pushbutton-parameter)."
            )
        elif self.object is None:
            self._human_readable_log = (
                f"CEN+ WHAT {self._state} on bare WHERE 2 carries no Object "
                "(WHERE is 2 + OBJECT: cen-plus.md#where---virtual-object)."
            )
        elif self._state == 21:
            self._human_readable_log = f"Button {self.push_button} of CEN+ object {self.object} has been pressed"  # pylint: disable=line-too-long
        elif self._state == 22:
            self._human_readable_log = f"Button {self.push_button} of CEN+ object {self.object} is being held pressed"  # pylint: disable=line-too-long
        elif self._state == 23:
            self._human_readable_log = f"Button {self.push_button} of CEN+ object {self.object} is still being held pressed"  # pylint: disable=line-too-long
        elif self._state == 24:
            self._human_readable_log = f"Button {self.push_button} of CEN+ object {self.object} has been released"  # pylint: disable=line-too-long
        elif self._state == 25:
            self._human_readable_log = f"Button {self.push_button} of CEN+ object {self.object} has been slowly rotated clockwise"  # pylint: disable=line-too-long
        elif self._state == 26:
            self._human_readable_log = f"Button {self.push_button} of CEN+ object {self.object} has been quickly rotated clockwise"  # pylint: disable=line-too-long
        elif self._state == 27:
            self._human_readable_log = f"Button {self.push_button} of CEN+ object {self.object} has been slowly rotated counter-clockwise"  # pylint: disable=line-too-long
        elif self._state == 28:
            self._human_readable_log = f"Button {self.push_button} of CEN+ object {self.object} has been quickly rotated counter-clockwise"  # pylint: disable=line-too-long
        else:
            self._human_readable_log = f"Button {self.push_button} of CEN+ object {self.object} state is {self._state}."  # pylint: disable=line-too-long

    @property
    def is_short_pressed(self) -> bool:
        return self._state == 21

    @property
    def is_held(self) -> bool:
        return self._state == 22

    @property
    def is_still_held(self) -> bool:
        return self._state == 23

    @property
    def is_released(self) -> bool:
        return self._state == 24

    @property
    def is_slowly_turned_cw(self) -> bool:
        return self._state == 25

    @property
    def is_quickly_turned_cw(self) -> bool:
        return self._state == 26

    @property
    def is_slowly_turned_ccw(self) -> bool:
        return self._state == 27

    @property
    def is_quickly_turned_ccw(self) -> bool:
        return self._state == 28

    @property
    def human_readable_log(self) -> str:
        return self._human_readable_log



class OWNScenarioPlusEvent(OWNEvent):
    """WHO 25 WHAT 11-15: scenario-plus / dimmer-like commands on a WHERE.

    libqtdevices ScenarioPlusDevice sends 11#0 on, 12 off, 13#0#5 increase,
    14#0#5 decrease, 15 stop (scenario_device.cpp:37-41, 163-186); mhs1 bt_luci
    accepts all five and echoes them on the monitor port.
    """

    _NAMES = {11: "on", 12: "off", 13: "increase", 14: "decrease", 15: "stop"}

    def __init__(self, data: str) -> None:
        super().__init__(data)
        self._action = self._NAMES.get(self._what) if self._what is not None else None
        self.object = self._where
        _params = "#".join(self._what_param) if self._what_param else ""
        self._human_readable_log = (
            f"Scenario plus {self._where}: {self._action}"
            + (f" (parameters {_params})" if _params else "")
            + "."
        )

    @property
    def action(self) -> str | None:
        return self._action


_require_non_empty_where = require_non_empty_where


class OWNScenarioPlusCommand(OWNCommand):
    """Builders for the five WHO 25 frames libqtdevices ScenarioPlusDevice sends."""

    _NAMES = {11: "on", 12: "off", 13: "increase", 14: "decrease", 15: "stop"}

    def __init__(self, data: str) -> None:
        super().__init__(data)
        self._action = self._NAMES.get(self._what) if self._what is not None else None
        self.object = self._where
        self._human_readable_log = f"Scenario plus {self._where}: {self._action}."

    @property
    def action(self) -> str | None:
        return self._action

    @classmethod
    def turn_on(cls, where: str | int) -> OWNScenarioPlusCommand:
        return cls(f"*25*11#0*{_require_non_empty_where(where)}##")

    @classmethod
    def turn_off(cls, where: str | int) -> OWNScenarioPlusCommand:
        return cls(f"*25*12*{_require_non_empty_where(where)}##")

    @classmethod
    def increase(cls, where: str | int) -> OWNScenarioPlusCommand:
        return cls(f"*25*13#0#5*{_require_non_empty_where(where)}##")

    @classmethod
    def decrease(cls, where: str | int) -> OWNScenarioPlusCommand:
        return cls(f"*25*14#0#5*{_require_non_empty_where(where)}##")

    @classmethod
    def stop(cls, where: str | int) -> OWNScenarioPlusCommand:
        return cls(f"*25*15*{_require_non_empty_where(where)}##")


class OWNDryContactCommand(OWNCommand):
    """WHO 25 dry contact / IR status request ``*#25*WHERE##``.

    The page (``dry-contact-ir.md`` #what, #where) writes the request with the
    configured address (``1..201`` or ``ZN``). The emulated gateways read a
    leading ``3`` as a prefix in front of the sensor number (ORACLE_CONFIRM.md
    row T1): ``*#25*39##`` -> sensor ``09``, ``*#25*35##`` -> ``05``,
    ``*#25*339##`` -> ``39``, ``*#25*5##`` refused 12/12. On a bus the same
    string can therefore be the bus form of one sensor or the page address of
    another (``39``: bus form of sensor 9, page address of sensor 39), so the
    two builders say which one they take:

    - ``status(where)`` sends the bus-form WHERE verbatim: what
      ``OWNDryContactEvent.where`` carried and what MyHOME configures
      (``33``, ``339`` in the captures).
    - ``status_for_sensor(sensor)`` takes the sensor number the firmware
      reads, as ``OWNDryContactEvent.sensor`` reports it, and adds the prefix:
      ``status_for_sensor(39)`` -> ``*#25*339##``, ``status_for_sensor(5)`` ->
      ``*#25*35##``.
    """

    @classmethod
    def status(cls, where: str | int) -> OWNDryContactCommand:
        """Status request with the bus-form WHERE sent as given (``339`` -> ``*#25*339##``)."""
        w = _require_non_empty_where(where)
        message = cls(f"*#25*{w}##")
        message._human_readable_log = f"Requesting dry contact {w} status."
        return message

    @classmethod
    def status_for_sensor(cls, sensor: str | int) -> OWNDryContactCommand:
        """Status request for the sensor number the firmware reads (``39`` -> ``*#25*339##``).

        The inverse of ``OWNDryContactEvent.sensor``: the ``3`` prefix the
        gateways strip is put back. ``sensor`` must be digits; the prefix is
        never doubled by the caller (pass ``39``, not ``339``).
        """
        s = str(sensor).strip()
        if not s.isdigit():
            raise ValueError("dry contact sensor must be a number (the WHERE without its 3 prefix)")
        message = cls(f"*#25*3{s}##")
        message._human_readable_log = f"Requesting dry contact sensor {s} status (WHERE 3{s})."
        return message



class OWNCenCommand(OWNCommand):
    """Command builder for WHO=15 CEN scenario pushbuttons.

    The button (00..31) is the WHAT and the phase is a WHAT parameter:
    ``*15*BUTTON[#PHASE]*WHERE##``. A short press is ``press`` followed by
    ``release_short_press``; a long press is ``press``, one or more
    ``start_long_press``/``still_held``, then ``release``.
    """

    @staticmethod
    def _button(button: int | str) -> str:
        value = int(button)
        if not 0 <= value <= 31:
            raise ValueError("CEN button must be between 0 and 31")
        return f"{value:02d}"

    @classmethod
    def press(cls, where: str, button: int | str = 1) -> OWNCenCommand:
        """Pressure on CEN button (*15*<button>*<where>##)."""
        w = _require_non_empty_where(where)
        message = cls(f"*15*{cls._button(button)}*{w}##")
        message._human_readable_log = (
            f"Press on button {button} of CEN object {w}."
        )
        return message

    @classmethod
    def release_short_press(cls, where: str, button: int | str = 1) -> OWNCenCommand:
        """Release after short pressure on CEN button (*15*<button>#1*<where>##)."""
        w = _require_non_empty_where(where)
        message = cls(f"*15*{cls._button(button)}#1*{w}##")
        message._human_readable_log = (
            f"Release after short press on button {button} of CEN object {w}."
        )
        return message

    @classmethod
    def start_long_press(cls, where: str, button: int | str = 1) -> OWNCenCommand:
        """Extended pressure on CEN button (*15*<button>#3*<where>##)."""
        w = _require_non_empty_where(where)
        message = cls(f"*15*{cls._button(button)}#3*{w}##")
        message._human_readable_log = (
            f"Long press on button {button} of CEN object {w}."
        )
        return message

    @classmethod
    def still_held(cls, where: str, button: int | str = 1) -> OWNCenCommand:
        """Extended pressure repeated while held (*15*<button>#3*<where>##).

        Same frame as start_long_press: WHO 15 has no separate first-held
        frame, and the first frame of a hold is the plain press. Only CEN+
        (WHO 25) distinguishes start (22) from still held (23).
        """
        return cls.start_long_press(where, button)

    @classmethod
    def release(cls, where: str, button: int | str = 1) -> OWNCenCommand:
        """Release after extended pressure on CEN button (*15*<button>#2*<where>##)."""
        w = _require_non_empty_where(where)
        message = cls(f"*15*{cls._button(button)}#2*{w}##")
        message._human_readable_log = (
            f"Release after long press on button {button} of CEN object {w}."
        )
        return message



class OWNCenPlusCommand(OWNCommand):
    """Command builder for WHO=25 CEN+ scenario pushbuttons (``WHAT 21..24``).

    Only the pushbutton action frames of ``cen-plus.md`` (#short-pressure---what-21
    to #end-of-extended-pressure---what-24) are built. The rotary-selector
    values ``WHAT 25..28`` (#rotary-selector-events---what-2528) are decoded by
    ``OWNCENPlusEvent`` but the page describes them as events of a physical
    selector and gives no action frame for them, so there is no rotary builder.
    """

    @staticmethod
    def _button(button: int | str) -> int:
        value = int(button)
        if not 0 <= value <= 31:
            raise ValueError("CEN+ button must be between 0 and 31")
        return value

    @classmethod
    def press(cls, where: str, button: int | str = 1) -> OWNCenPlusCommand:
        """CEN+ short press event (*25*21#<button>*<where>##)."""
        w = _require_non_empty_where(where)
        btn = cls._button(button)
        message = cls(f"*25*21#{btn}*{w}##")
        message._human_readable_log = (
            f"CEN+ short press on button {btn} of module {w}."
        )
        return message

    @classmethod
    def start_long_press(cls, where: str, button: int | str = 1) -> OWNCenPlusCommand:
        """CEN+ start long press event (*25*22#<button>*<where>##)."""
        w = _require_non_empty_where(where)
        btn = cls._button(button)
        message = cls(f"*25*22#{btn}*{w}##")
        message._human_readable_log = (
            f"CEN+ start long press on button {btn} of module {w}."
        )
        return message

    @classmethod
    def release(cls, where: str, button: int | str = 1) -> OWNCenPlusCommand:
        """CEN+ release after long press (*25*24#<button>*<where>##)."""
        w = _require_non_empty_where(where)
        btn = cls._button(button)
        message = cls(f"*25*24#{btn}*{w}##")
        message._human_readable_log = (
            f"CEN+ release button {btn} of module {w}."
        )
        return message

    @classmethod
    def still_held(cls, where: str, button: int | str = 1) -> OWNCenPlusCommand:
        """CEN+ heartbeat while still held (*25*23#<button>*<where>##)."""
        w = _require_non_empty_where(where)
        btn = cls._button(button)
        message = cls(f"*25*23#{btn}*{w}##")
        message._human_readable_log = (
            f"CEN+ button {btn} of module {w} still held."
        )
        return message



def _parse_who25_event(data: str) -> OWNEvent:
    if data.startswith("*#"):
        return OWNDryContactEvent(data)
    parts = data.strip("#").split("*")
    what_part = parts[2] if len(parts) > 2 else ""
    try:
        what_code = int(what_part.split("#")[0])
    except ValueError:
        what_code = None
    if what_code is not None and 21 <= what_code <= 28:
        return OWNCENPlusEvent(data)
    if what_code is not None and 11 <= what_code <= 15:
        return OWNScenarioPlusEvent(data)
    if what_code is not None and what_code not in (31, 32):
        return OWNEvent(data)
    return OWNDryContactEvent(data)


def _parse_who25_command(data: str) -> OWNCommand:
    if data.startswith("*#"):
        return OWNDryContactCommand(data)
    parts = data.strip("#").split("*")
    what_part = parts[2] if len(parts) > 2 else ""
    try:
        what_code = int(what_part.split("#")[0])
    except ValueError:
        what_code = None
    if what_code is not None and 21 <= what_code <= 28:
        return OWNCenPlusCommand(data)
    if what_code is not None and 11 <= what_code <= 15:
        return OWNScenarioPlusCommand(data)
    # Same rule as _parse_who25_event: only WHAT 31/32 are dry contacts.
    if what_code is not None and what_code not in (31, 32):
        return OWNCommand(data)
    return OWNDryContactCommand(data)


register_event_parser(15, OWNCENEvent)
register_command_parser(15, OWNCenCommand)
register_event_parser(25, _parse_who25_event)
register_command_parser(25, _parse_who25_command)
