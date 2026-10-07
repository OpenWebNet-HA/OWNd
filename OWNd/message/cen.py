"""WHO 15 & 25: CEN, CEN+, and Dry Contact / IR events and commands."""

from __future__ import annotations

import re

from .base import OWNCommand, OWNEvent, register_command_parser, register_event_parser


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
    def __init__(self, data: str) -> None:
        super().__init__(data)

        self._state = 1 if self._what == 31 else 0
        try:
            self._detection = int(self._what_param[0]) if self._what_param else 1
        except (IndexError, TypeError, ValueError):
            self._detection = 1
        where = self._where or ""
        self._sensor = (
            where[1:] if len(where) > 1 and where.startswith("3") else where
        )

        if self._detection == 1:
            self._human_readable_log = (
                f"Sensor {self._sensor} detected {'ON' if self._state == 1 else 'OFF'}."
            )
        else:
            self._human_readable_log = (
                f"Sensor {self._sensor} reported {'ON' if self._state == 1 else 'OFF'}."
            )

    @property
    def is_on(self) -> bool:
        return self._state == 1

    @property
    def sensor(self) -> str:
        return self._sensor

    @property
    def is_detection(self) -> bool:
        return self._detection == 1

    @property
    def human_readable_log(self) -> str:
        return self._human_readable_log



class OWNCENPlusEvent(OWNEvent):
    def __init__(self, data: str) -> None:
        super().__init__(data)

        self._state = self._what
        try:
            push_button = int(self._what_param[0]) if self._what_param else 0
            self.push_button = push_button if 0 <= push_button <= 31 else 0
        except (IndexError, TypeError, ValueError):
            self.push_button = 0
        where = self._where or ""
        self.object = where[1:] if len(where) > 1 and where.startswith("2") else where

        if self._state == 21:
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


class OWNScenarioPlusCommand(OWNCommand):
    """Builders for the five WHO 25 frames libqtdevices ScenarioPlusDevice sends."""

    @classmethod
    def turn_on(cls, where: str | int) -> OWNScenarioPlusCommand:
        message = cls(f"*25*11#0*{where}##")
        message._human_readable_log = f"Scenario plus {where}: on."
        return message

    @classmethod
    def turn_off(cls, where: str | int) -> OWNScenarioPlusCommand:
        message = cls(f"*25*12*{where}##")
        message._human_readable_log = f"Scenario plus {where}: off."
        return message

    @classmethod
    def increase(cls, where: str | int) -> OWNScenarioPlusCommand:
        message = cls(f"*25*13#0#5*{where}##")
        message._human_readable_log = f"Scenario plus {where}: increase."
        return message

    @classmethod
    def decrease(cls, where: str | int) -> OWNScenarioPlusCommand:
        message = cls(f"*25*14#0#5*{where}##")
        message._human_readable_log = f"Scenario plus {where}: decrease."
        return message

    @classmethod
    def stop(cls, where: str | int) -> OWNScenarioPlusCommand:
        message = cls(f"*25*15*{where}##")
        message._human_readable_log = f"Scenario plus {where}: stop."
        return message


class OWNDryContactCommand(OWNCommand):
    @classmethod
    def status(cls, where: str | int) -> OWNDryContactCommand:
        message = cls(f"*#25*{where}##")
        message._human_readable_log = f"Requesting dry contact {where} status."
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
        message = cls(f"*15*{cls._button(button)}*{where}##")
        message._human_readable_log = (
            f"Press on button {button} of CEN object {where}."
        )
        return message

    @classmethod
    def release_short_press(cls, where: str, button: int | str = 1) -> OWNCenCommand:
        """Release after short pressure on CEN button (*15*<button>#1*<where>##)."""
        message = cls(f"*15*{cls._button(button)}#1*{where}##")
        message._human_readable_log = (
            f"Release after short press on button {button} of CEN object {where}."
        )
        return message

    @classmethod
    def start_long_press(cls, where: str, button: int | str = 1) -> OWNCenCommand:
        """Extended pressure on CEN button (*15*<button>#3*<where>##)."""
        message = cls(f"*15*{cls._button(button)}#3*{where}##")
        message._human_readable_log = (
            f"Long press on button {button} of CEN object {where}."
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
        message = cls(f"*15*{cls._button(button)}#2*{where}##")
        message._human_readable_log = (
            f"Release after long press on button {button} of CEN object {where}."
        )
        return message



class OWNCenPlusCommand(OWNCommand):
    """Command builder for WHO=25 CEN+ scenario pushbuttons."""

    @classmethod
    def press(cls, where: str, button: int | str = 1) -> OWNCenPlusCommand:
        """CEN+ short press event (*25*21#<button>*<where>##)."""
        message = cls(f"*25*21#{button}*{where}##")
        message._human_readable_log = (
            f"CEN+ short press on button {button} of module {where}."
        )
        return message

    @classmethod
    def start_long_press(cls, where: str, button: int | str = 1) -> OWNCenPlusCommand:
        """CEN+ start long press event (*25*22#<button>*<where>##)."""
        message = cls(f"*25*22#{button}*{where}##")
        message._human_readable_log = (
            f"CEN+ start long press on button {button} of module {where}."
        )
        return message

    @classmethod
    def release(cls, where: str, button: int | str = 1) -> OWNCenPlusCommand:
        """CEN+ release after long press (*25*24#<button>*<where>##)."""
        message = cls(f"*25*24#{button}*{where}##")
        message._human_readable_log = (
            f"CEN+ release button {button} of module {where}."
        )
        return message

    @classmethod
    def still_held(cls, where: str, button: int | str = 1) -> OWNCenPlusCommand:
        """CEN+ heartbeat while still held (*25*23#<button>*<where>##)."""
        message = cls(f"*25*23#{button}*{where}##")
        message._human_readable_log = (
            f"CEN+ button {button} of module {where} still held."
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
