"""WHO 1: Lighting subsystem events, commands, and motion constants."""

from __future__ import annotations

import colorsys
import datetime
import re
from typing import Any

from .base import OWNCommand, OWNEvent, register_command_parser, register_event_parser

MESSAGE_TYPE_ACTION = "hvac_action"
MESSAGE_TYPE_MOTION = "motion_detected"
MESSAGE_TYPE_PIR_SENSITIVITY = "pir_sensitivity"
MESSAGE_TYPE_ILLUMINANCE = "illuminance_value"
MESSAGE_TYPE_MOTION_TIMEOUT = "motion_timeout"

PIR_SENSITIVITY_MAPPING = ["low", "medium", "high", "very high"]



class OWNLightingEvent(OWNEvent):
    def __init__(self, data: str) -> None:
        super().__init__(data)

        self._type: str | None = None
        self._state: int | None = None
        self._unknown_state: int | None = None
        self._brightness: int | None = None
        self._brightness_preset: int | None = None
        self._transition: int | None = None
        self._timer: float | None = None
        self._blinker: float | None = None
        self._illuminance: int | None = None
        self._motion: bool = False
        self._pir_sensitivity: int | None = None
        self._motion_timeout: datetime.timedelta | None = None
        self._color_temp: int | None = None
        self._supports_color_temp: bool | None = None
        self._hue: int | None = None
        self._saturation: int | None = None
        self._value: int | None = None
        self._hs: tuple[int, int] | None = None
        self._hsv: tuple[int, int, int] | None = None
        self._supports_hsv: bool | None = None
        self._rgb: tuple[int, int, int] | None = None
        self._supports_rgb: bool | None = None

        if self._what is not None and self._what != 1000:
            self._state = self._what

            if self._state == 0:  # Light off
                self._human_readable_log = (
                    f"Light {self._where}{self._interface_log_text} is switched off."
                )
            elif self._state == 1:  # Light on
                self._human_readable_log = (
                    f"Light {self._where}{self._interface_log_text} is switched on."
                )
            elif self._state > 1 and self._state < 11:  # Light dimmed to preset value
                self._brightness_preset = self._state
                # self._brightness = self._state * 10
                self._human_readable_log = f"Light {self._where}{self._interface_log_text} is switched on at brightness level {self._state}."  # pylint: disable=line-too-long
            elif self._state == 11:  # Timer at 1m
                self._timer = 60
                self._human_readable_log = f"Light {self._where}{self._interface_log_text} is switched on for {self._timer}s."
            elif self._state == 12:  # Timer at 2m
                self._timer = 120
                self._human_readable_log = f"Light {self._where}{self._interface_log_text} is switched on for {self._timer}s."
            elif self._state == 13:  # Timer at 3m
                self._timer = 180
                self._human_readable_log = f"Light {self._where}{self._interface_log_text} is switched on for {self._timer}s."
            elif self._state == 14:  # Timer at 4m
                self._timer = 240
                self._human_readable_log = f"Light {self._where}{self._interface_log_text} is switched on for {self._timer}s."
            elif self._state == 15:  # Timer at 5m
                self._timer = 300
                self._human_readable_log = f"Light {self._where}{self._interface_log_text} is switched on for {self._timer}s."
            elif self._state == 16:  # Timer at 15m
                self._timer = 900
                self._human_readable_log = f"Light {self._where}{self._interface_log_text} is switched on for {self._timer}s."
            elif self._state == 17:  # Timer at 30s
                self._timer = 30
                self._human_readable_log = f"Light {self._where}{self._interface_log_text} is switched on for {self._timer}s."
            elif self._state == 18:  # Timer at 0.5s
                self._timer = 0.5
                self._human_readable_log = f"Light {self._where}{self._interface_log_text} is switched on for {self._timer}s."
            elif self._state >= 20 and self._state <= 29:  # Light blinking
                self._blinker = 0.5 * (self._state - 19)
                self._human_readable_log = f"Light {self._where}{self._interface_log_text} is blinking every {self._blinker}s."
            elif self._state == 30 or self._state == 31:  # One level up/down
                direction = "up" if self._state == 30 else "down"
                self._human_readable_log = f"Light {self._where}{self._interface_log_text} is dimmed {direction} one level."  # pylint: disable=line-too-long
            elif self._state == 34:  # Motion detected
                self._type = MESSAGE_TYPE_MOTION
                self._motion = True
                self._human_readable_log = f"Light/motion sensor {self._where}{self._interface_log_text} detected motion"
            else:
                # Not in the WHO 1 WHAT table (e.g. 19, seen from an MH200
                # actuator next to a WHO 1001 autodiagnostic mask): the on/off
                # state is unknown, not "on".
                self._unknown_state = self._state
                self._state = None
                self._human_readable_log = f"Light {self._where}{self._interface_log_text} reports unknown lighting WHAT {self._unknown_state}."  # pylint: disable=line-too-long

        if self._dimension is not None and self._dimension_value:
            if self._dimension == 1 or self._dimension == 4:  # Brightness value
                self._brightness = int(self._dimension_value[0]) - 100
                # Some gateways omit the transition speed in the reply.
                self._transition = (
                    int(self._dimension_value[1])
                    if len(self._dimension_value) > 1
                    else None
                )
                if self._brightness == 0:
                    self._state = 0
                    self._human_readable_log = f"Light {self._where}{self._interface_log_text} is switched off."
                else:
                    self._state = 1
                    self._human_readable_log = f"Light {self._where}{self._interface_log_text} is switched on at {self._brightness}%."
            elif self._dimension == 2:  # Time value
                self._timer = (
                    int(self._dimension_value[0]) * 3600
                    + int(self._dimension_value[1]) * 60
                    + int(self._dimension_value[2])
                )
                self._human_readable_log = f"Light {self._where}{self._interface_log_text} is switched on for {self._timer}s."
            elif self._dimension == 5:  # PIR sensitivity
                self._type = MESSAGE_TYPE_PIR_SENSITIVITY
                self._pir_sensitivity = int(self._dimension_value[0])
                _sensitivity = (
                    PIR_SENSITIVITY_MAPPING[self._pir_sensitivity]
                    if 0 <= self._pir_sensitivity < len(PIR_SENSITIVITY_MAPPING)
                    else f"unknown ({self._pir_sensitivity})"
                )
                self._human_readable_log = f"Light/motion sensor {self._where}{self._interface_log_text} PIR sensitivity is {_sensitivity}."  # pylint: disable=line-too-long
            elif self._dimension == 6:  # Illuminance value
                self._type = MESSAGE_TYPE_ILLUMINANCE
                self._illuminance = int(self._dimension_value[0])
                self._human_readable_log = f"Light/motion sensor {self._where}{self._interface_log_text} detected an illuminance value of {self._illuminance} lx."  # pylint: disable=line-too-long
            elif self._dimension == 7:  # Motion timeout value
                self._type = MESSAGE_TYPE_MOTION_TIMEOUT
                self._motion_timeout = datetime.timedelta(
                    hours=int(self._dimension_value[0]),
                    minutes=int(self._dimension_value[1]),
                    seconds=int(self._dimension_value[2]),
                )
                self._human_readable_log = f"Light/motion sensor {self._where}{self._interface_log_text} has timeout set to {self._motion_timeout}."  # pylint: disable=line-too-long
            elif self._dimension == 12:  # HSV Color (BTicino F429 DALI)
                if len(self._dimension_value) >= 3:
                    h, s, v = (
                        int(self._dimension_value[0]),
                        int(self._dimension_value[1]),
                        int(self._dimension_value[2]),
                    )
                    if (h, s, v) == (511, 127, 255):
                        self._supports_hsv = False
                        self._supports_rgb = False
                        self._human_readable_log = f"Light {self._where}{self._interface_log_text} reports HSV color is not supported."
                    else:
                        self._supports_hsv = True
                        self._supports_rgb = True
                        self._hue = h
                        self._saturation = s
                        self._value = v
                        self._hs = (h, s)
                        self._hsv = (h, s, v)
                        r, g, b = colorsys.hsv_to_rgb(h / 360.0, s / 100.0, v / 100.0)
                        self._rgb = (round(r * 255), round(g * 255), round(b * 255))
                        self._human_readable_log = f"Light {self._where}{self._interface_log_text} HSV color is ({h}°, {s}%, {v}%)."
            elif self._dimension == 14:  # Color temperature (Tunable white, mireds)
                val = int(self._dimension_value[0])
                if val == 1:
                    self._supports_color_temp = False
                    self._human_readable_log = f"Light {self._where}{self._interface_log_text} reports tunable white is not supported."
                else:
                    self._supports_color_temp = True
                    self._color_temp = val
                    self._human_readable_log = f"Light {self._where}{self._interface_log_text} color temperature is {self._color_temp} mireds."
            else:
                self._human_readable_log = f"Light/motion sensor {self._where}{self._interface_log_text} has sent an unknown dimension {self._dimension}."

    @property
    def message_type(self) -> str | None:
        return self._type

    @property
    def brightness_preset(self) -> int | None:
        return self._brightness_preset

    @property
    def brightness(self) -> int | None:
        return self._brightness

    @property
    def transition(self) -> int | None:
        return self._transition

    @property
    def is_on(self) -> bool | None:
        """True/False when the on/off state is known, None otherwise (e.g. a
        motion event, a reply carrying only a dimension such as illuminance
        or a timer, or a WHAT outside the published table; see unknown_state)."""
        if self._state is None or self._motion:
            return None
        return 0 < self._state < 32

    @property
    def unknown_state(self) -> int | None:
        """The raw WHAT when it is not in the published WHO 1 WHAT table, else None.

        19 has been seen from an MH200 actuator next to a WHO 1001 DIMENSION 11
        autodiagnostic mask; the mask itself is not interpreted here.
        """
        return self._unknown_state

    @property
    def is_sensor(self) -> bool:
        return (
            self._motion
            or self._state == 34
            or (self._dimension is not None and self._dimension in (5, 6, 7))
            or self._type
            in (
                MESSAGE_TYPE_MOTION,
                MESSAGE_TYPE_ILLUMINANCE,
                MESSAGE_TYPE_PIR_SENSITIVITY,
                MESSAGE_TYPE_MOTION_TIMEOUT,
            )
        )

    @property
    def timer(self) -> float | None:
        return self._timer

    @property
    def blinker(self) -> float | None:
        return self._blinker

    @property
    def illuminance(self) -> int | None:
        return self._illuminance

    @property
    def motion(self) -> bool:
        return self._motion

    @property
    def pir_sensitivity(self) -> int | None:
        return self._pir_sensitivity

    @property
    def motion_timeout(self) -> datetime.timedelta | None:
        return self._motion_timeout

    @property
    def color_temp(self) -> int | None:
        return self._color_temp

    @property
    def supports_color_temp(self) -> bool | None:
        return self._supports_color_temp

    @property
    def hue(self) -> int | None:
        return self._hue

    @property
    def saturation(self) -> int | None:
        return self._saturation

    @property
    def value(self) -> int | None:
        return self._value

    @property
    def hs(self) -> tuple[int, int] | None:
        return self._hs

    @property
    def hsv(self) -> tuple[int, int, int] | None:
        return self._hsv

    @property
    def supports_hsv(self) -> bool | None:
        return self._supports_hsv

    @property
    def rgb(self) -> tuple[int, int, int] | None:
        return self._rgb

    @property
    def supports_rgb(self) -> bool | None:
        return self._supports_rgb



class OWNLightingCommand(OWNCommand):
    @classmethod
    def status(cls, where: str | int) -> OWNLightingCommand:
        message = cls(f"*#1*{where}##")
        message._human_readable_log = f"Requesting light or switch {message._where}{message._interface_log_text} status."
        return message

    @classmethod
    def get_brightness(cls, where: str | int) -> OWNLightingCommand:
        message = cls(f"*#1*{where}*1##")
        message._human_readable_log = f"Requesting light {message._where}{message._interface_log_text} brightness."
        return message

    @classmethod
    def get_pir_sensitivity(cls, where: str | int) -> OWNLightingCommand:
        message = cls(f"*#1*{where}*5##")
        message._human_readable_log = f"Requesting light/motion sensor {message._where}{message._interface_log_text} PIR sensitivity."
        return message

    @classmethod
    def get_illuminance(cls, where: str | int) -> OWNLightingCommand:
        message = cls(f"*#1*{where}*6##")
        message._human_readable_log = f"Requesting light/motion sensor {message._where}{message._interface_log_text} illuminance."
        return message

    @classmethod
    def get_motion_timeout(cls, where: str | int) -> OWNLightingCommand:
        message = cls(f"*#1*{where}*7##")
        message._human_readable_log = f"Requesting light/motion sensor {message._where}{message._interface_log_text} motion timeout."
        return message

    @classmethod
    def get_color_temperature(cls, where: str | int) -> OWNLightingCommand:
        message = cls(f"*#1*{where}*14##")
        message._human_readable_log = f"Requesting light {message._where}{message._interface_log_text} color temperature."
        return message

    @classmethod
    def set_color_temperature(cls, where: str | int, mireds: int) -> OWNLightingCommand:
        mireds = max(50, min(1000, int(mireds)))
        message = cls(f"*#1*{where}*#14*{mireds}##")
        message._human_readable_log = f"Setting light {message._where}{message._interface_log_text} color temperature to {mireds} mireds."
        return message

    @classmethod
    def get_hsv_color(cls, where: str | int) -> OWNLightingCommand:
        message = cls(f"*#1*{where}*12##")
        message._human_readable_log = f"Requesting light {message._where}{message._interface_log_text} HSV color."
        return message

    @classmethod
    def set_hsv_color(cls, where: str | int, h: int, s: int, v: int) -> OWNLightingCommand:
        h = max(0, min(359, int(h)))
        s = max(0, min(100, int(s)))
        v = max(0, min(100, int(v)))
        message = cls(f"*#1*{where}*#12*{h}*{s}*{v}##")
        message._human_readable_log = f"Setting light {message._where}{message._interface_log_text} HSV color to ({h}°, {s}%, {v}%)."
        return message

    @classmethod
    def get_rgb_color(cls, where: str | int) -> OWNLightingCommand:
        return cls.get_hsv_color(where)

    @classmethod
    def set_rgb_color(cls, where: str | int, r: int, g: int, b: int) -> OWNLightingCommand:
        r = max(0, min(255, int(r)))
        g = max(0, min(255, int(g)))
        b = max(0, min(255, int(b)))
        h_ratio, s_ratio, v_ratio = colorsys.rgb_to_hsv(r / 255.0, g / 255.0, b / 255.0)
        h = int(round(h_ratio * 360)) % 360
        s = int(round(s_ratio * 100))
        v = int(round(v_ratio * 100))
        return cls.set_hsv_color(where, h, s, v)

    @classmethod
    def flash(
        cls,
        where: str | int,
        _frequency: float | None = 0.5,
        _freqency: float | None = None,
    ) -> OWNLightingCommand:
        # Compatibility with the misspelled keyword exposed by bundled V2.
        if _freqency is not None:
            _frequency = _freqency
        if _frequency is not None and _frequency >= 0.5 and _frequency <= 5:
            _frequency = round(_frequency * 2) / 2
        else:
            _frequency = 0.5
        _what = int((_frequency / 0.5) + 19)
        message = cls(f"*1*{_what}*{where}##")
        message._human_readable_log = f"Flashing light {message._where}{message._interface_log_text} every {_frequency}s."
        return message

    @classmethod
    def switch_on(cls, where: str | int, _transition: int | None = None) -> OWNLightingCommand:
        if _transition is not None and _transition >= 0 and _transition <= 255:
            message = cls(f"*1*1#{_transition}*{where}##")
            message._human_readable_log = f"Switching ON light {message._where}{message._interface_log_text} with transition speed {_transition}."
        else:
            message = cls(f"*1*1*{where}##")
            message._human_readable_log = f"Switching ON light or switch {message._where}{message._interface_log_text}."
        return message

    @classmethod
    def switch_off(cls, where: str | int, _transition: int | None = None) -> OWNLightingCommand:
        if _transition is not None and _transition >= 0 and _transition <= 255:
            message = cls(f"*1*0#{_transition}*{where}##")
            message._human_readable_log = f"Switching OFF light {message._where}{message._interface_log_text} with transition speed {_transition}."
        else:
            message = cls(f"*1*0*{where}##")
            message._human_readable_log = f"Switching OFF light or switch {message._where}{message._interface_log_text}."
        return message

    @classmethod
    def set_brightness_preset(cls, where: str | int, preset: int) -> OWNLightingCommand:
        """Dimmer preset WHAT 2..10 (20 %..100 %), the frame libqtdevices
        DimmerDevice::setLevel100 sends (lighting_device.cpp:240-245)."""
        preset = int(preset)
        if not 2 <= preset <= 10:
            raise ValueError("preset must be between 2 and 10")
        message = cls(f"*1*{preset}*{where}##")
        message._human_readable_log = f"Setting light {message._where}{message._interface_log_text} to preset level {preset}."  # pylint: disable=line-too-long
        return message

    @classmethod
    def step_up(
        cls, where: str | int, delta: int | None = None, speed: int | None = None
    ) -> OWNLightingCommand:
        """One level up (WHAT 30), or ``30#delta#speed`` for a dimmer 100
        (libqtdevices lighting_device.cpp:230-233, 409-412)."""
        return cls._step(where, 30, "up", delta, speed)

    @classmethod
    def step_down(
        cls, where: str | int, delta: int | None = None, speed: int | None = None
    ) -> OWNLightingCommand:
        """One level down (WHAT 31), or ``31#delta#speed`` for a dimmer 100
        (libqtdevices lighting_device.cpp:235-238, 414-417)."""
        return cls._step(where, 31, "down", delta, speed)

    @classmethod
    def _step(
        cls, where: str | int, what: int, direction: str, delta: int | None, speed: int | None
    ) -> OWNLightingCommand:
        if delta is None:
            message = cls(f"*1*{what}*{where}##")
            message._human_readable_log = f"Dimming light {message._where}{message._interface_log_text} one level {direction}."  # pylint: disable=line-too-long
            return message
        delta = int(delta)
        speed = int(speed if speed is not None else 0)
        if not 1 <= delta <= 100 or not 0 <= speed <= 255:
            raise ValueError("delta must be 1..100 and speed 0..255")
        message = cls(f"*1*{what}#{delta}#{speed}*{where}##")
        message._human_readable_log = f"Dimming light {message._where}{message._interface_log_text} {direction} by {delta}% at speed {speed}."  # pylint: disable=line-too-long
        return message

    _FIXED_TIMERS = {11: 60, 12: 120, 13: 180, 14: 240, 15: 300, 16: 900, 17: 30, 18: 0.5}

    @classmethod
    def switch_on_timed(cls, where: str | int, what: int) -> OWNLightingCommand:
        """Fixed timer WHAT 11..18 (1, 2, 3, 4, 5, 15 min, 30 s, 0.5 s), the
        frame libqtdevices LightingDevice::fixedTiming sends (lighting_device.cpp:110-117)."""
        what = int(what)
        if what not in cls._FIXED_TIMERS:
            raise ValueError("timer WHAT must be between 11 and 18")
        message = cls(f"*1*{what}*{where}##")
        message._human_readable_log = f"Switching ON light {message._where}{message._interface_log_text} for {cls._FIXED_TIMERS[what]}s."  # pylint: disable=line-too-long
        return message

    @classmethod
    def set_variable_timer(
        cls, where: str | int, hours: int, minutes: int, seconds: int
    ) -> OWNLightingCommand:
        """``*#1*W*#2*H*M*S##`` (libqtdevices LightingDevice::variableTiming,
        lighting_device.cpp:119-124)."""
        h, m, s = int(hours), int(minutes), int(seconds)
        if not (0 <= h <= 255 and 0 <= m <= 59 and 0 <= s <= 59):
            raise ValueError("hours 0..255, minutes and seconds 0..59")
        message = cls(f"*#1*{where}*#2*{h}*{m}*{s}##")
        message._human_readable_log = f"Setting light {message._where}{message._interface_log_text} timer to {h}h {m}m {s}s."  # pylint: disable=line-too-long
        return message

    @classmethod
    def get_variable_timer(cls, where: str | int) -> OWNLightingCommand:
        """``*#1*W*2##`` (libqtdevices LightingDevice::requestVariableTiming,
        lighting_device.cpp:131-134)."""
        message = cls(f"*#1*{where}*2##")
        message._human_readable_log = f"Requesting light {message._where}{message._interface_log_text} timer."
        return message

    @classmethod
    def set_brightness(
        cls, where: str | int, _level: int = 30, _transition: int = 0
    ) -> OWNLightingCommand:
        transition_speed = _transition if 0 <= _transition <= 255 else 0
        if int(_level) <= 0:
            return cls.switch_off(
                where, transition_speed if transition_speed > 0 else None
            )
        level = min(int(_level), 100)
        command_level = level + 100
        message = cls(f"*#1*{where}*#1*{command_level}*{transition_speed}##")
        capped = f" (requested {_level}%)" if int(_level) > 100 else ""
        message._human_readable_log = (
            f"Setting light {message._where}{message._interface_log_text} brightness to {level}%{capped} with transition speed {transition_speed}."  # pylint: disable=line-too-long
            if transition_speed > 0
            else f"Setting light {message._where}{message._interface_log_text} brightness to {level}%{capped}."
        )
        return message


register_event_parser(1, OWNLightingEvent)
register_command_parser(1, OWNLightingCommand)
