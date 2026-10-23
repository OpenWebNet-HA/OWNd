"""WHO 1: Lighting subsystem events, commands, and motion constants."""

from __future__ import annotations

import colorsys
import datetime
import re
from typing import Any

from .base import (
    OWNCommand,
    OWNEvent,
    get_parse_gateway,
    register_command_parser,
    register_event_parser,
    require_non_empty_where,
)

MESSAGE_TYPE_ACTION = "hvac_action"
MESSAGE_TYPE_MOTION = "motion_detected"
MESSAGE_TYPE_PIR_SENSITIVITY = "pir_sensitivity"
MESSAGE_TYPE_ILLUMINANCE = "illuminance_value"
MESSAGE_TYPE_MOTION_TIMEOUT = "motion_timeout"

# WHAT 19 anomaly status per MH200N bt_luci binary disassembly (findings/MH200N/what19.md)
LIGHTING_STATE_ANOMALY = 19

# Legacy coarse-only dimmer transition-speed byte (0xF0 = 240) reported in WHO 1
# DIMENSION 1 (*#1*WHERE*1*LEVEL100*240##) by pre-09W29 BTicino F414 dimmers
# that only actuate live output on coarse WHAT 2..10 commands (MyHOME#767).
DIMMER_SPEED_COARSE_ONLY = 240

# Canonical BTicino libqtdevices (TS10_1_0_23, lighting_device.cpp) mapping
# between coarse WHO 1 WHAT 2..10 presets and fine 1..100 % levels.
COARSE_PRESET_TO_PERCENT: dict[int, int] = {
    2: 1,
    3: 10,
    4: 20,
    5: 30,
    6: 40,
    7: 50,
    8: 60,
    9: 75,
    10: 100,
}

# Per-(gateway_key, normalized_where) coarse-only dimmer registry.
# ``gateway_key`` is ``None`` for unscoped parse/command calls, or a normalized
# gateway identifier (serial/MAC or host) when scoped to a specific plant.
_COARSE_DIMMER_BY_GATEWAY: dict[tuple[str | None, str], bool] = {}

PIR_SENSITIVITY_MAPPING = ["low", "medium", "high", "very high"]


def brightness_preset_to_percent(preset: int) -> int:
    """Convert a coarse WHO 1 WHAT 2..10 preset to its canonical 1..100 % level.

    Matches ``libqtdevices`` ``dimmerLevelTo100`` (``2->1, 3->10, 4->20, 5->30,
    6->40, 7->50, 8->60, 9->75, 10->100``).
    """
    if isinstance(preset, bool) or (isinstance(preset, float) and preset % 1 != 0):
        raise ValueError("preset must be an integer between 2 and 10")
    preset_int = int(preset)
    if preset_int not in COARSE_PRESET_TO_PERCENT:
        raise ValueError("preset must be between 2 and 10")
    return COARSE_PRESET_TO_PERCENT[preset_int]


def percent_to_brightness_preset(level: int) -> int:
    """Convert a 0..100 % level to the coarse WHO 1 WHAT value (0 or 2..10).

    Matches ``libqtdevices`` ``dimmer100LevelTo10`` (``lighting_device.cpp:240-245``):
    ``<=0 -> 0``, ``1..4 -> 2``, ``5..15 -> 3``, ``16..25 -> 4``, ``26..35 -> 5``,
    ``36..45 -> 6``, ``46..53 -> 7``, ``54..67 -> 8``, ``68..85 -> 9``, ``>=86 -> 10``.
    """
    if isinstance(level, bool) or (isinstance(level, float) and level % 1 != 0):
        raise ValueError("level must be an integer")
    lvl = int(level)
    if lvl <= 0:
        return 0
    if lvl <= 4:
        return 2
    if lvl <= 15:
        return 3
    if lvl <= 25:
        return 4
    if lvl <= 35:
        return 5
    if lvl <= 45:
        return 6
    if lvl <= 53:
        return 7
    if lvl <= 67:
        return 8
    if lvl <= 85:
        return 9
    return 10


def is_apl_address(base: str) -> bool:
    """Check if base address is a valid OpenWebNet Point-to-Point (APL) address.

    Point-to-point addressing combinations:
      - A = 0; PL [1-9]        -> 2 digits (e.g. 02 = Area 0, PL 2; accepted by BTicino firmware)
      - A = 00; PL [01-15]     -> 4 digits (e.g. 0015 = Area 00, PL 15)
      - A [1-9]; PL [1-9]      -> 2 digits (e.g. 15 = Area 1, PL 5)
      - A = 10; PL [01-15]     -> 4 digits (e.g. 1015 = Area 10, PL 15)
      - A [01-09]; PL [10-15]  -> 4 digits (e.g. 0115 = Area 1, PL 15)
    """
    if not base.isdigit():
        return False
    if len(base) == 2:
        a = int(base[0])
        pl = int(base[1])
        if a == 0:
            return 1 <= pl <= 9
        return 1 <= a <= 9 and 1 <= pl <= 9
    if len(base) == 4:
        a = int(base[:2])
        pl = int(base[2:])
        if a == 0:
            return 1 <= pl <= 15
        if 1 <= a <= 9:
            return 10 <= pl <= 15
        if a == 10:
            return 1 <= pl <= 15
    return False


def area_of_where(where: str | int | None) -> str | None:
    """Return the area status WHERE for a given Point-to-Point (APL) WHERE."""
    if where is None:
        return None
    where_str = str(where).strip()
    parts = where_str.split("#", 1)
    base = parts[0]
    if not is_apl_address(base):
        return None
    if len(base) == 2:
        if base[0] == "0":
            return "00"
        return base[0]
    a = base[:2]
    if a == "00":
        return "00"
    if a == "10":
        return "100"
    return str(int(a))


def normalize_where(where: str | int | None) -> str:
    """Normalize OpenWebNet address while preserving Point-to-Point (APL) addressing."""
    if where is None:
        return ""
    where_str = str(where).strip()
    if not where_str:
        return ""
    parts = where_str.split("#", 1)
    base = parts[0]
    if is_apl_address(base) or base in ("00", "100", "0"):
        norm_base = base
    elif base.isdigit() and base.startswith("00") and int(base) > 15:
        norm_base = str(int(base))
    else:
        norm_base = base
    return f"{norm_base}#{parts[1]}" if len(parts) > 1 else norm_base


def _normalize_gateway_key(gateway: Any = None) -> str | None:
    """Resolve an optional gateway identifier or ``OWNGateway`` object to a lowercase key."""
    target = get_parse_gateway() if gateway is None else gateway
    if target is None:
        return None
    if isinstance(target, str):
        stripped = target.strip().lower()
        return stripped if stripped else None
    for attr in ("serial", "unique_id", "host", "address"):
        val = getattr(target, attr, None)
        if isinstance(val, str) and val.strip():
            return val.strip().lower()
    return None


def is_coarse_dimmer_where(
    where: str | int | None, *, gateway: Any = None
) -> bool:
    """Return True if ``where`` reported the 240 (0xF0) coarse-only dimmer speed.

    Learning is reactive: a WHO 1 ``DIMENSION 1`` or ``DIMENSION 4`` reply carrying
    ``transition == 240`` (``*#1*WHERE*1*LEVEL100*240##``) must be observed first
    (or registered via :func:`register_coarse_dimmer_where`).

    Resolution rules:
      - **Scoped lookup** (``gateway`` provided or active via ``OWNMessage.parse``):
        returns the state recorded for ``(gateway_key, normalize_where(where))`` if
        present, otherwise falls back to the unscoped ``(None, normalize_where(where))``
        entry (defaulting to ``False``).
      - **Unscoped lookup** (``gateway=None`` outside a scoped parse context):
        returns the explicit ``(None, normalize_where(where))`` entry if present;
        otherwise returns ``True`` if and only if at least one gateway has recorded
        ``where`` and **all** gateways that have observed ``where`` agree it is a
        coarse-only dimmer (``bool(scoped) and all(scoped)``).
    """
    norm = normalize_where(where)
    if not norm:
        return False
    gw_key = _normalize_gateway_key(gateway)
    if gw_key is not None:
        if (gw_key, norm) in _COARSE_DIMMER_BY_GATEWAY:
            return _COARSE_DIMMER_BY_GATEWAY[(gw_key, norm)]
        return _COARSE_DIMMER_BY_GATEWAY.get((None, norm), False)
    if (None, norm) in _COARSE_DIMMER_BY_GATEWAY:
        return _COARSE_DIMMER_BY_GATEWAY[(None, norm)]
    scoped = [
        v
        for (g, w), v in _COARSE_DIMMER_BY_GATEWAY.items()
        if g is not None and w == norm
    ]
    return bool(scoped) and all(scoped)


def register_coarse_dimmer_where(
    where: str | int | None,
    is_coarse: bool = True,
    *,
    gateway: Any = None,
) -> None:
    """Record or clear ``where`` as a coarse-only dimmer (speed 240 / 0xF0).

    Pass ``gateway`` (an :class:`OWNGateway` instance or gateway identifier string)
    to scope the entry to a specific plant in multi-gateway deployments.
    """
    norm = normalize_where(where)
    if not norm:
        return
    gw_key = _normalize_gateway_key(gateway)
    _COARSE_DIMMER_BY_GATEWAY[(gw_key, norm)] = bool(is_coarse)


def clear_coarse_dimmer_wheres(gateway: Any = None) -> None:
    """Clear learned coarse-only dimmer WHERE addresses (all gateways, or one gateway)."""
    if gateway is None:
        _COARSE_DIMMER_BY_GATEWAY.clear()
        return
    gw_key = _normalize_gateway_key(gateway)
    if gw_key is None:
        return
    for key in [k for k in _COARSE_DIMMER_BY_GATEWAY if k[0] == gw_key]:
        del _COARSE_DIMMER_BY_GATEWAY[key]


class OWNLightingEvent(OWNEvent):
    def __init__(self, data: str) -> None:
        super().__init__(data)

        self._type: str | None = None
        self._state: int | None = None
        self._unknown_state: int | None = None
        self._brightness: int | None = None
        self._brightness_preset: int | None = None
        self._transition: int | None = None
        self._is_coarse_dimmer: bool = False
        self._timer: float | None = None
        self._blinker: float | None = None
        self._illuminance: int | None = None
        self._motion: bool = False
        self._motion_end: bool = False
        self._is_anomaly: bool = False
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

        full_where = (
            f"{self._where}#{'#'.join(self._where_param)}"
            if self._where and self._where_param
            else self._where
        )

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
                if is_coarse_dimmer_where(full_where):
                    self._is_coarse_dimmer = True
                    self._brightness = brightness_preset_to_percent(self._state)
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
            elif self._state == LIGHTING_STATE_ANOMALY:
                # Byte 'E' (0x45) on SCS bus maps to decimal 19 in bt_luci
                # during load anomalies/overloads (findings/MH200N/what19.md)
                self._is_anomaly = True
                self._unknown_state = self._state
                self._state = None
                self._human_readable_log = f"Light {self._where}{self._interface_log_text} reports anomaly (WHAT 19)."
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
            elif self._state == 39:  # End of movement (the detector's occupancy timer ran out)
                # Specified by the ZigBee OpenWebNet WHO 1 table (34 movement, 39 end of
                # movement); observed on SCS from an F454 + Legrand 067226, ~45 s (its
                # DIMENSION 7 timeout) after the last WHAT 34 (MyHOME#777). Kept as
                # MESSAGE_TYPE_MOTION with motion False so consumers that only act on
                # ``motion is True`` ignore it as they did when it was unknown_state 39.
                self._type = MESSAGE_TYPE_MOTION
                self._motion = False
                self._motion_end = True
                self._human_readable_log = f"Light/motion sensor {self._where}{self._interface_log_text} no longer detects motion"
            else:
                # Not in the WHO 1 WHAT table: the on/off
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
                if self._transition is not None:
                    self._is_coarse_dimmer = (
                        self._transition == DIMMER_SPEED_COARSE_ONLY
                    )
                    register_coarse_dimmer_where(full_where, self._is_coarse_dimmer)
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
                    try:
                        h = int(self._dimension_value[0])
                        s = int(self._dimension_value[1])
                        v = int(self._dimension_value[2])
                    except (TypeError, ValueError):
                        h = s = v = -1
                    if (h, s, v) == (511, 127, 255):
                        self._supports_hsv = False
                        self._supports_rgb = False
                        self._human_readable_log = f"Light {self._where}{self._interface_log_text} reports HSV color is not supported."
                    elif 0 <= h <= 360 and 0 <= s <= 100 and 0 <= v <= 100:
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
    def brightness_preset_percent(self) -> int | None:
        """Fine 1..100 % equivalent for a coarse WHAT 2..10 preset, else None."""
        if self._brightness_preset is None:
            return None
        return COARSE_PRESET_TO_PERCENT.get(self._brightness_preset)

    @property
    def brightness(self) -> int | None:
        return self._brightness

    @property
    def transition(self) -> int | None:
        return self._transition

    @property
    def is_coarse_dimmer(self) -> bool:
        """True if this event indicates a coarse-only dimmer (speed 240 / 0xF0)."""
        return self._is_coarse_dimmer

    @property
    def is_on(self) -> bool | None:
        """True/False when the on/off state is known, None otherwise (e.g. a
        motion or end-of-movement event, a reply carrying only a dimension such as illuminance
        or a timer, an anomaly state, or a WHAT outside the published table; see unknown_state)."""
        if self._state is None or self._motion or self._motion_end or self._is_anomaly:
            return None
        return 0 < self._state < 32

    @property
    def is_anomaly(self) -> bool:
        """True if the light actuator reports an anomaly / fault state (WHAT 19)."""
        return self._is_anomaly

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
            or self._state in (34, 39)
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
        """True for ``*1*34*WHERE##`` (movement detected). False for every other frame,
        WHAT 39 included: use :attr:`motion_end` to tell an end of movement apart."""
        return self._motion

    @property
    def motion_end(self) -> bool:
        """True for ``*1*39*WHERE##``: the detector reports the end of movement."""
        return self._motion_end

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
    def color_temp_kelvin(self) -> int | None:
        """Color temperature in Kelvin when a valid mired reading (> 1) is present."""
        if self._color_temp is not None and self._color_temp > 1:
            return int(1000000 / self._color_temp)
        return None

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
    def hs_color(self) -> tuple[int, int] | None:
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
    def __init__(self, data: str) -> None:
        super().__init__(data)
        self._is_coarse_dimmer: bool = False

    @property
    def is_coarse_dimmer(self) -> bool:
        """True if this command was built for or targets a coarse-only dimmer."""
        return self._is_coarse_dimmer

    @property
    def brightness_preset(self) -> int | None:
        """Coarse WHO 1 preset (2..10) for WHAT 2..10 commands, else None."""
        if self._what is not None and 2 <= self._what <= 10:
            return self._what
        return None

    @property
    def brightness(self) -> int | None:
        """Decoded brightness percentage (0..100) for Dimension 1/4 writes or coarse WHAT 2..10 commands."""
        if self._dimension in (1, 4) and self._dimension_value:
            try:
                raw = int(self._dimension_value[0])
            except (TypeError, ValueError):
                return None
            if 100 <= raw <= 200:
                return raw - 100
        if self._what is not None and 2 <= self._what <= 10:
            full_where = (
                f"{self._where}#{'#'.join(self._where_param)}"
                if self._where and self._where_param
                else self._where
            )
            if self._is_coarse_dimmer or is_coarse_dimmer_where(
                full_where, gateway=self._gateway
            ):
                return brightness_preset_to_percent(self._what)
        return None

    @property
    def color_temp(self) -> int | None:
        """Decoded color temperature in mireds for Dimension 14 write commands."""
        if self._dimension == 14 and self._dimension_value:
            try:
                val = int(self._dimension_value[0])
            except (TypeError, ValueError):
                return None
            if val > 1:
                return val
        return None

    @property
    def color_temp_kelvin(self) -> int | None:
        """Decoded color temperature in Kelvin for Dimension 14 write commands."""
        ct = self.color_temp
        return int(1000000 / ct) if ct is not None and ct > 1 else None

    @property
    def hs(self) -> tuple[int, int] | None:
        """Decoded (hue, saturation) tuple for Dimension 12 write commands."""
        if self._dimension == 12 and len(self._dimension_value) >= 3:
            try:
                h = int(self._dimension_value[0])
                s = int(self._dimension_value[1])
                v = int(self._dimension_value[2])
            except (TypeError, ValueError):
                return None
            if 0 <= h <= 360 and 0 <= s <= 100 and 0 <= v <= 100:
                return (h, s)
        return None

    @property
    def hs_color(self) -> tuple[int, int] | None:
        """Alias for :attr:`hs`."""
        return self.hs

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
        if isinstance(preset, bool) or (isinstance(preset, float) and preset % 1 != 0):
            raise ValueError("preset must be an integer between 2 and 10")
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
        cls,
        where: str | int,
        _level: int = 30,
        _transition: int = 0,
        *,
        coarse: bool | None = None,
        gateway: Any = None,
    ) -> OWNLightingCommand:
        """Build a brightness command for ``where`` at ``_level`` % (0..100).

        By default (``coarse=None``), checks :func:`is_coarse_dimmer_where` for
        ``where`` (scoped to ``gateway`` when provided, or using the unscoped
        all-agree rule when ``gateway=None``). If ``where`` has reported the
        legacy ``SPEED = 240`` (``0xF0``) coarse-only sentinel in a prior
        ``DIMENSION 1``/``4`` reply — or if ``coarse=True`` is passed explicitly —
        emits ``*1*0*WHERE##`` for ``_level <= 0`` and ``*1*2..10*WHERE##`` via
        :func:`percent_to_brightness_preset` for ``1..100 %``. Otherwise emits the
        standard ``DIMENSION 1`` write ``*#1*WHERE*#1*<100+level>*<speed>##``.
        """
        if any(
            isinstance(x, bool) or (isinstance(x, float) and x % 1 != 0)
            for x in (_level, _transition)
        ):
            raise ValueError("brightness level and transition must be integers")
        use_coarse = (
            is_coarse_dimmer_where(where, gateway=gateway)
            if coarse is None
            else bool(coarse)
        )
        trans_int = int(_transition)
        transition_speed = trans_int if 0 <= trans_int <= 255 else 0
        if int(_level) <= 0:
            return cls.switch_off(
                where,
                None
                if use_coarse
                else (transition_speed if transition_speed > 0 else None),
            )
        if use_coarse:
            cmd = cls.set_brightness_preset(
                where, percent_to_brightness_preset(int(_level))
            )
            cmd._is_coarse_dimmer = True
            cmd._gateway = gateway
            return cmd
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

    @property
    def is_status_query(self) -> bool:
        """True if this message is a point/group/area lighting status query (*#1*WHERE##)."""
        return self.is_status_request and bool(self._where)

    @property
    def is_brightness_query(self) -> bool:
        """True if this message is a brightness dimension query (*#1*WHERE*1## or *#1*WHERE*4##)."""
        return (
            self.is_dimension_request
            and self._dimension in (1, 4)
            and bool(self._where)
        )

    @classmethod
    def report_brightness(
        cls, where: str | int, level: int, transition: int = 0
    ) -> OWNLightingCommand:
        """Build a WHO 1 Dimension 1 brightness reply frame (*#1*WHERE*1*LEVEL*SPEED##)."""
        target = require_non_empty_where(where)
        if any(
            isinstance(x, bool) or (isinstance(x, float) and x % 1 != 0)
            for x in (level, transition)
        ):
            raise ValueError("brightness level and transition must be integers")
        lvl = int(level)
        if not 0 <= lvl <= 100:
            raise ValueError("brightness level must be between 0 and 100")
        trans = int(transition)
        if not 0 <= trans <= 255:
            raise ValueError("transition must be between 0 and 255")
        own_level = lvl + 100
        message = cls(f"*#1*{target}*1*{own_level}*{trans}##")
        message._human_readable_log = (
            f"Reporting light {message._where}{message._interface_log_text} brightness at {lvl}%."
        )
        return message


register_event_parser(1, OWNLightingEvent)
register_command_parser(1, OWNLightingCommand)
