"""WHO 4: Heating / Thermoregulation events, commands, and helpers."""

from __future__ import annotations

import datetime
from decimal import Decimal, ROUND_HALF_UP
import math
import re
import warnings

from .base import (
    OWNCommand,
    OWNEvent,
    register_command_parser,
    register_event_parser,
    require_non_empty_where,
)
from .lighting import MESSAGE_TYPE_ACTION

MESSAGE_TYPE_MAIN_TEMPERATURE = "main_temperature"
MESSAGE_TYPE_MAIN_HUMIDITY = "main_humidity"
MESSAGE_TYPE_SECONDARY_TEMPERATURE = "secondary_temperature"
MESSAGE_TYPE_TARGET_TEMPERATURE = "target_temperature"
MESSAGE_TYPE_LOCAL_OFFSET = "local_offset"
MESSAGE_TYPE_LOCAL_TARGET_TEMPERATURE = "local_target_temperature"
MESSAGE_TYPE_MODE = "hvac_mode"
MESSAGE_TYPE_MODE_TARGET = "hvac_mode_target"
MESSAGE_TYPE_SEASON = "hvac_season"

MESSAGE_TYPE_FAN_SPEED = "fan_speed"
MESSAGE_TYPE_ZONE_STATE = "zone_state"
MESSAGE_TYPE_SPLIT_CONTROL = "split_control"

# ``OWNHeatingEvent.mode``: the coarse climate mode of a WHAT, the four
# historical values plus two the Encyclopedia keeps apart from them
# (``what.md`` "Protection and OFF states": antifreeze 102, thermal
# protection 202 and generic protection 302 are protection states, not OFF;
# "Manual and programmed operation": 115 / 215 / 315 daily holiday plan and
# "Vacation, program and scenario forms": ``13DDD`` / ``23DDD`` / ``33DDD``
# vacation are neither manual nor automatic). ``operating_mode`` carries the
# fine-grained state.
CLIMATE_MODE_OFF = "off"
CLIMATE_MODE_HEAT = "heat"
CLIMATE_MODE_COOL = "cool"
CLIMATE_MODE_AUTO = "auto"

# ``OWNHeatingEvent.operating_mode``: one value per published WHAT family
# (Encyclopedia ``who-4-temperature-control/what.md``). The protection
# values are the ``mode`` strings ``OWNHeatingCommand.set_mode`` takes.
OPERATING_MODE_OFF = "off"  # 103 / 203 / 303
OPERATING_MODE_ANTIFREEZE = "antifreeze"  # 102
OPERATING_MODE_THERMAL_PROTECTION = "thermal_protection"  # 202
OPERATING_MODE_PROTECTION = "protection"  # 302, generic protection
OPERATING_MODE_MANUAL = "manual"  # 110 / 210 / 310 (optionally #T)
OPERATING_MODE_AUTOMATIC = "automatic"  # 111 / 211 / 311
OPERATING_MODE_TIMED_MANUAL = "timed_manual"  # 112 / 212 / 312 (undocumented)
OPERATING_MODE_HOLIDAY = "holiday"  # 115 / 215 / 315, daily holiday plan
OPERATING_MODE_VACATION = "vacation"  # 13DDD / 23DDD / 33DDD
OPERATING_MODE_PROGRAM = "program"  # 11PP / 21PP / 31PP
OPERATING_MODE_SCENARIO = "scenario"  # 12SS / 22SS / 32SS
OPERATING_MODE_CANCEL_VACATION = "cancel_vacation"  # 3000, 3000#PROGRAM
OPERATING_MODE_RESTORE_LAST_PROGRAM = "restore_last_program"  # 3100
OPERATING_MODE_RESTORE_LAST_SCENARIO = "restore_last_scenario"  # 3200

# ``OWNHeatingEvent.scope``: the address class of the WHERE (Encyclopedia
# ``who-4-temperature-control/addressing.md``, "Published functional WHERE
# forms", "MyHOME_Suite address rules", "Actuator addressing" and
# "Historical central-unit variants"; the classes are not interchangeable,
# "clients must not normalize all Temperature Control WHERE values to one
# integer zone identifier").
SCOPE_CENTRAL = "central"  # #0 (3550), #0#C (4695 central unit C)
SCOPE_ZONE_VIA_CENTRAL = "zone_via_central"  # #Z, #Z#C
SCOPE_MASTER_PROBE = "master_probe"  # Z, 1..99
SCOPE_ALL_PROBES = "all_probes"  # 0 (every probe), 0ZZ (every probe of zone ZZ)
SCOPE_SLAVE_PROBE = "slave_probe"  # PZZ, probe P 1..8 of zone ZZ
SCOPE_EXTERNAL_PROBE = "external_probe"  # P00 (historical external-probe rule)
SCOPE_ACTUATOR = "actuator"  # Z#N (N 0 for all actuators of the zone)
SCOPE_SPLIT_UNIT = "split_unit"  # 3#Z#N under DIMENSION 22

# DIMENSION 22 split-unit fields (Encyclopedia ``dimensions.md`` "DIMENSION
# 22 - split control"): ``MOD`` and ``VEL``.
SPLIT_MODE_OFF = "off"
SPLIT_MODE_WINTER = "winter"
SPLIT_MODE_SUMMER = "summer"
SPLIT_MODE_FAN = "fan"
SPLIT_MODE_DEHUMIDIFICATION = "dehumidification"
SPLIT_MODE_AUTOMATIC = "automatic"
SPLIT_FAN_AUTOMATIC = "automatic"
SPLIT_FAN_MINIMUM = "minimum"
SPLIT_FAN_MEDIUM = "medium"
SPLIT_FAN_MAXIMUM = "maximum"
SPLIT_FAN_SILENT = "silent"
_SPLIT_MODES = {
    "0": SPLIT_MODE_OFF,
    "1": SPLIT_MODE_WINTER,
    "2": SPLIT_MODE_SUMMER,
    "3": SPLIT_MODE_FAN,
    "4": SPLIT_MODE_DEHUMIDIFICATION,
    "5": SPLIT_MODE_AUTOMATIC,
}
_SPLIT_FAN_SPEEDS = {
    "0": SPLIT_FAN_AUTOMATIC,
    "1": SPLIT_FAN_MINIMUM,
    "2": SPLIT_FAN_MEDIUM,
    "3": SPLIT_FAN_MAXIMUM,
    "4": SPLIT_FAN_SILENT,
}

SEASON_HEATING = "heating"
SEASON_CONDITIONING = "conditioning"

LOCAL_CONTROL_NORMAL = "normal"
LOCAL_CONTROL_OFFSET = "offset"
LOCAL_CONTROL_OFF = "local_off"
LOCAL_CONTROL_PROTECTION = "local_protection"
LOCAL_CONTROL_OVERRIDE = "local_override"
LOCAL_CONTROL_UNKNOWN = "unknown"

# WHO 4 DIMENSION 7, *#4*ZONE*7*CONTEXT*STATE[*TTTT]##: not in the public WHO 4
# document; the values follow the MyHOME_Suite ScenarioDevices templates.
ZONE_CONTEXT_GENERIC = "generic"
ZONE_CONTEXT_HEATING = "heating"
ZONE_CONTEXT_COOLING = "cooling"
ZONE_CONTEXT_AUTOMATIC = "automatic"

ZONE_STATE_SETPOINT = "setpoint"
ZONE_STATE_PROTECTION = "protection"
ZONE_STATE_COMFORT = "comfort"
ZONE_STATE_ECO = "eco"
ZONE_STATE_OFF = "off"

_ZONE_CONTEXTS = {
    "0": ZONE_CONTEXT_GENERIC,
    "1": ZONE_CONTEXT_HEATING,
    "2": ZONE_CONTEXT_COOLING,
    "3": ZONE_CONTEXT_AUTOMATIC,
}
_ZONE_STATES = {
    "1": ZONE_STATE_SETPOINT,
    "2": ZONE_STATE_PROTECTION,
    "3": ZONE_STATE_COMFORT,
    "4": ZONE_STATE_ECO,
    "5": ZONE_STATE_OFF,
}


_WHO4_TEMP_REGEX = re.compile(r"^[01][0-9]{3}$")
# A three-digit DIMENSION 15 value (``*#4*11*15*1*123*1111##``), unsigned tenths.
_WHO4_SHORT_TEMP_REGEX = re.compile(r"[0-9]{3}", re.ASCII)
# DIMENSION 22 ``SP``: tenths of a degree, three or four digits, unsigned.
_WHO4_SPLIT_SETPOINT_REGEX = re.compile(r"[0-9]{3,4}", re.ASCII)
_WHO4_HUMIDITY_REGEX = re.compile(r"[0-9]+(?:\.[0-9]+)?", re.ASCII)
# DIMENSION 19 fan-coil OFF states beyond the published 0..8 table.
_FAN_COIL_OFF_STATES = (14, 15, 16)

# WHO 4 DIMENSION 22 is the published split-unit (air conditioning) IR
# control: ``*#4*3#Z#N*22##`` requests the current setting and
# ``*#4*3#Z#N*#22*MOD*SP*VEL*SWING##`` writes it (WHO 4 specification,
# pp. 66-68). Sent with a WHERE that carries no actuator token (a zone
# ``*#4*Z*22##``, the general ``*#4*0*22##`` or the central unit
# ``*#4*#0*22##``, read or write) the frame kills the thermoregulation
# daemon (bt_termo) on the Linux IP gateways and a live F461 2.0.11 reboots
# about 3 minutes later (own-firmware-oracle ``thermo-dim22`` suite and
# ``tools/expected_divergences.yaml`` crash frames; live F461 2.0.11).
# The published split forms ``3#Z#N`` crashed none of the twelve emulated
# gateways: ten forward them to the bus as a telegram to zone Z, actuator N;
# the prefix-less ``Z#N`` forms are ``nack, silent`` on eleven and forwarded
# by the MH202 only, so they stay refused (``findings/thermo-dim22.md``;
# emulated firmware, ``harness=full``, not yet replayed on hardware).
#
# ``is_who4_dimension_22`` recognises every DIMENSION 22 spelling (the
# detector of OWNd 2.0.0b11); ``is_who4_dimension_22_crash_form`` is what the
# send paths refuse: every spelling except the split forms the oracle
# replayed without a crash. Untested spellings (``0ZZ`` all probes of a zone,
# ``#Z`` a zone through the central unit, ``#0#C``, ``Z#4#IF``, ``Z`` 0 (the
# general-zone sentinel bt_termo crashes on), two-digit actuator numbers,
# whitespace or ``+`` tokens, writes with fewer or more than four payload
# fields) stay refused: the allowance is the tested forms, not the
# complement of the crash set.
#
# Anchored to the first ``*`` of each ``##``-delimited frame: ``*#4*`` means
# WHO 4 only there. Mid-frame, ``*#4*`` is WHERE ``#4`` (group 4 in WHO 1, 2,
# 16 and 22, central-unit zone 4 in WHO 4) or DIMENSION ``#4`` (a dimension 4
# write), so ``*#2*#4*#11#001*22##`` or ``*#1*14*#4*1*22##`` must not match.
# The WHO and DIMENSION tokens accept whatever the gateway's atoi() reads as
# 4 / 22: leading zeros, surrounding whitespace and a ``+`` sign
# (``*#04*2* 22##``, ``*#4*2*+22##``, ``*#4*2*22 ``).
_WHO4_DIMENSION_22_REGEX = re.compile(
    r"^[^*]*\*#\s*\+?0*4\s*\*[^*]*\*\s*#?\s*\+?0*22(?:\s*$|[#*\s])"
)

# The frames the oracle forwarded without a crash, exactly as sent: WHO ``4``
# and DIMENSION ``22`` spelled canonically, WHERE the published split form
# ``3#Z#N`` (``Z`` 1..99, ``N`` 1..9, no leading zeros, no whitespace), as a
# request (``*22`` and nothing after it) or a write with exactly the four
# published payload fields ``MOD*SP*VEL*SWING`` (MOD 0..5, SP three or four
# digits, VEL 0..4, SWING 0 or 1, each optionally empty as the touchscreen
# writes ``*#22*3**1*1`` and ``*#22*0***``). The oracle sent ``Z`` 2 and 45
# with ``N`` 1 and the write ``1*0215*2*0``; the published ranges are
# allowed on the grammar, not on a replay of each value. ``\Z`` on both
# arms (``$`` also matches before a trailing newline); ASCII only, so a
# Unicode digit in the payload is no sendable frame. Anything else that
# ``_WHO4_DIMENSION_22_REGEX`` matches is a crash form.
_WHO4_DIMENSION_22_SENDABLE_REGEX = re.compile(
    r"^\*#4\*3#[1-9][0-9]?#[1-9]"
    r"(?:\*22|\*#22\*[0-5]?\*(?:[0-9]{3,4})?\*[0-4]?\*[01]?)\Z",
    re.ASCII,
)


def _decode_frame(frame: object) -> str:
    return (
        bytes(frame).decode("latin-1")
        if isinstance(frame, (bytes, bytearray, memoryview))
        else str(frame)
    )


def is_who4_dimension_22(frame: object) -> bool:
    """True if ``frame`` (or any ``##``-delimited frame in it) is WHO 4 DIMENSION 22.

    Every spelling, the actuator-addressed split forms included. The send
    paths refuse the narrower :func:`is_who4_dimension_22_crash_form`.
    ``bytes``, ``bytearray`` and ``memoryview`` are decoded as latin-1 (the
    wire encoding); anything else is checked through ``str()``.
    """
    raw = _decode_frame(frame)
    return any(_WHO4_DIMENSION_22_REGEX.search(chunk) for chunk in raw.split("##"))


def is_who4_dimension_22_crash_form(frame: object) -> bool:
    """True if ``frame`` holds a WHO 4 DIMENSION 22 frame that every send path refuses.

    That is every DIMENSION 22 spelling except the canonical published split
    forms the firmware oracle forwarded without a crash on ten of twelve
    emulated gateways: ``*#4*3#Z#N*22##`` and
    ``*#4*3#Z#N*#22*MOD*SP*VEL*SWING##`` with ``Z`` 1..99, ``N`` 1..9 and
    exactly four payload fields (the oracle replayed ``Z`` 2 and 45, ``N`` 1;
    the rest of the published ranges is allowed on the grammar). Refused: a
    zone (``Z``, ``0ZZ``), the general ``0`` and ``Z`` 0, the central unit
    (``#0``, ``#0#C``), a zone through it (``#Z``), an interface (``Z#4#IF``),
    the prefix-less actuator form ``Z#N`` (``nack, silent`` on eleven
    gateways, forwarded by the MH202 only), ``N`` 0 or two digits, a
    parameter after the request (``*22*1``, ``*22#1``), a bare ``*#22``, a
    write with fewer or more than four fields or out-of-range values, and
    any leading-zero, whitespace, ``+``, newline or non-ASCII spelling.
    Buffers are decoded like :func:`is_who4_dimension_22`.
    """
    raw = _decode_frame(frame)
    return any(
        _WHO4_DIMENSION_22_REGEX.search(chunk)
        and not _WHO4_DIMENSION_22_SENDABLE_REGEX.match(chunk)
        for chunk in raw.split("##")
    )


# A central-unit address: ``#0`` (3550 99-zone central unit) or ``#0#C`` (4695
# 4-zone central unit ``C``, 1..99 or ``01``..``99``: MyHOME_Suite OPEN.db
# ``#0#[ZA][ZB]``, MHCatalogue 4695 ``ZAZB_CENTRAL`` 1..99, oracle
# ``thermo-central-mode`` ``*4*0*#0#2##`` -> ``D1 02``), the two forms MyHOME
# and the golden corpus use. ``#Z`` (zone 1..99) and ``#Z#C`` (zone Z under
# 4-zone central unit C) are zone / probe addresses, not central-unit ones:
# libqtdevices ``ControlledProbeDevice`` sends them with bus command byte
# ``C2`` (``*4*311*#23#1##`` -> ``D1 01 03 02 C2 17 00 00``), whereas the
# central unit (``ThermalDevice``) is command byte ``C1``; ``set_mode`` builds
# them (see ``_zone_address_and_name``). ``#00``, ``#0#0`` and ``#0#00`` name
# no central unit, and three digits are out of range. ASCII digits only.
_WHO4_CENTRAL_WHERE_REGEX = re.compile(r"#0(?:#(?:0[1-9]|[1-9][0-9]?))?", re.ASCII)


def _validate_central_where(where: object, purpose: str = "Central unit command") -> str:
    """Return ``where`` stripped when it addresses a central unit, else raise.

    Shared by every ``OWNHeatingCommand`` central-unit builder (the ones that
    default to ``where="#0"``): ``#0`` and ``#0#C`` are accepted, whitespace
    around them is stripped; a bare zone (``1``), a zone through the central
    unit (``#1``, ``#23#1``, which ``set_mode`` builds), ``#00``, ``#0#0``,
    three-digit values and non-strings raise ``ValueError`` naming
    ``purpose`` and quoting the stripped value.
    """
    text = str(where).strip() if where is not None else ""
    if not _WHO4_CENTRAL_WHERE_REGEX.fullmatch(text):
        raise ValueError(
            f"{purpose} needs a central unit address such as '#0' or '#0#1' "
            f"(a zone '#Z' or '#Z#C' is addressed with set_mode): {text!r}"
        )
    return text


# WHO 4 WHERE for an actuator status request: a zone of one or two digits
# (``0..99``: ``Z``, ``#Z``, ``0`` / ``#0`` for every zone or the central
# unit), optionally one actuator digit (``Z#N``, ``#0#N``, ``#Z#N``; ``N`` is
# ``1..9``, ``0`` for all actuators of the zone: ``2#0``, ``0#0``), optionally
# a bus-interface suffix of exactly two digits (``#4#NN``: ``3#4#01``,
# ``#3#4#01``, ``2#1#4#01``). Three-digit addresses are secondary probes
# (``PZZ``, ``101..899``: no actuators, NACK on an F461) and the actuator
# index is one digit in the WHO 4 WHERE table, so both are refused the way
# ``get_fan_speed`` bounds its zone to ``1..99``. ASCII digits only; no ``*``, so no dimension can be
# injected through the address.
_WHO4_WHERE_REGEX = re.compile(r"#?[0-9]{1,2}(?:#[0-9])?(?:#4#[0-9]{2})?", re.ASCII)


def who4_temperature(raw: str) -> float | None:
    """Decode WHO 4 temperature ``SXXX`` (tenths of a degree)."""
    if not _WHO4_TEMP_REGEX.match(raw):
        return None
    magnitude = int(raw[1:]) / 10.0
    if raw[0] == "1" and magnitude != 0.0:
        return -magnitude
    return magnitude


def _zone_state(
    values: list[str],
) -> tuple[str | None, str | None, float | None]:
    """Decode DIMENSION 7 values into (context, state, setpoint temperature).

    Unknown context or state codes decode to None; the temperature is only
    read for the setpoint state.
    """
    context = _ZONE_CONTEXTS.get(values[0]) if values else None
    state = _ZONE_STATES.get(values[1]) if len(values) > 1 else None
    temperature = None
    if state == ZONE_STATE_SETPOINT and len(values) > 2:
        temperature = who4_temperature(values[2])
    return context, state, temperature


def _zone_state_text(values: list[str]) -> str | None:
    """'heating setpoint at 17.0°C', 'cooling protection', or None if unknown."""
    context, state, temperature = _zone_state(values)
    if context is None or state is None:
        return None
    if temperature is not None:
        return f"{context} {state} at {temperature}°C"
    return f"{context} {state}"


# The WHERE of a WHO 4 event, by address class (Encyclopedia
# ``who-4-temperature-control/addressing.md``). Leading zeros and the ``#``
# prefix are significant: ``1`` (master probe of zone 1), ``001`` (all probes
# of zone 1), ``#1`` (zone 1 through the central unit) and ``101`` (probe 1 of
# zone 1) are four addresses; ``0`` (all probes) is not ``#0`` (the central
# unit) and ``#0#C`` is the 4-zone central unit ``C``, not zone ``C``
# ("MyHOME_Suite address rules" ``#0#[ZA][ZB]``; "Historical central-unit
# variants": central-unit command ``#0#C``, zone command ``#Z#C``; ENCY_CONFIRM
# TC-H1 OPEN.db rule ``1004 four-zone control unit #0#[ZA][ZB]``; firmware
# oracle ``*4*303*#0#1##`` -> central-unit telegram with selector byte ``01``
# on ten of twelve gateways, ORACLE_CONFIRM H1). A trailing ``#4#NN`` is a
# bus-interface qualifier (``protocol/addressing.md`` routing qualifiers), not
# actuator 4. ASCII digits only.
_WHO4_INTERFACE_SUFFIX_REGEX = re.compile(r"(?P<base>.+)#4#(?P<interface>[0-9]{2})", re.ASCII)
_WHO4_ZONE_VIA_CENTRAL_REGEX = re.compile(
    r"#(?P<zone>[1-9][0-9]?)(?:#(?P<unit>0[1-9]|[1-9][0-9]?))?", re.ASCII
)
_WHO4_MASTER_PROBE_REGEX = re.compile(r"[1-9][0-9]?", re.ASCII)
_WHO4_ALL_PROBES_REGEX = re.compile(r"0|0(?P<zone>[0-9]{2})", re.ASCII)
_WHO4_SLAVE_PROBE_REGEX = re.compile(r"(?P<probe>[1-8])(?P<zone>0[1-9]|[1-9][0-9])", re.ASCII)
_WHO4_EXTERNAL_PROBE_REGEX = re.compile(r"(?P<probe>[1-9])00", re.ASCII)
_WHO4_ACTUATOR_REGEX = re.compile(r"(?P<zone>0|[1-9][0-9]?)#(?P<actuator>[0-9])", re.ASCII)
_WHO4_SPLIT_UNIT_REGEX = re.compile(r"3#(?P<zone>0|[1-9][0-9]?)#(?P<actuator>[1-9])", re.ASCII)
_WHO4_LEGACY_ZONE_REGEX = re.compile(r"#?(?P<zone>[0-9]+)(?:#[0-9]+)*", re.ASCII)


class _Who4Address:
    """The decoded WHERE of a WHO 4 event (see ``OWNHeatingEvent.scope``)."""

    __slots__ = (
        "address",
        "scope",
        "zone",
        "zone_number",
        "central_unit",
        "probe_number",
        "actuator",
        "interface",
        "base",
    )

    def __init__(self, where: str | None, where_param: list[str], dimension: int | None) -> None:
        self.address = "#".join([where or "", *where_param])
        self.scope: str | None = None
        # The legacy integer zone: 0 for ``#0`` and the general address, ``C``
        # for the 4-zone central unit ``#0#C`` (MyHOME routes ``#0#C`` frames
        # on ``zone == C``; ``scope`` / ``central_unit`` / ``unique_id`` carry
        # the central-unit identity).
        self.zone = 0
        self.zone_number: int | None = None
        self.central_unit: int | None = None
        self.probe_number: int | None = None
        self.actuator: int | None = None
        self.interface: str | None = None
        base = self.address
        if suffix := _WHO4_INTERFACE_SUFFIX_REGEX.fullmatch(base):
            base = suffix.group("base")
            self.interface = suffix.group("interface")
        self.base = base  # the address without its ``#4#NN`` interface qualifier
        if _WHO4_CENTRAL_WHERE_REGEX.fullmatch(base):
            self.scope = SCOPE_CENTRAL
            self.central_unit = int(base[3:]) if len(base) > 2 else None
            if self.central_unit is not None:
                self.zone = self.central_unit
        elif match := _WHO4_ZONE_VIA_CENTRAL_REGEX.fullmatch(base):
            self.scope = SCOPE_ZONE_VIA_CENTRAL
            self.zone = self.zone_number = int(match.group("zone"))
            self.central_unit = int(match.group("unit")) if match.group("unit") else None
        elif _WHO4_MASTER_PROBE_REGEX.fullmatch(base):
            self.scope = SCOPE_MASTER_PROBE
            self.zone = self.zone_number = int(base)
        elif match := _WHO4_ALL_PROBES_REGEX.fullmatch(base):
            self.scope = SCOPE_ALL_PROBES
            if match.group("zone") and int(match.group("zone")):
                self.zone = self.zone_number = int(match.group("zone"))
        elif match := _WHO4_SLAVE_PROBE_REGEX.fullmatch(base):
            self.scope = SCOPE_SLAVE_PROBE
            self.zone = self.zone_number = int(match.group("zone"))
            self.probe_number = int(match.group("probe"))
        elif match := _WHO4_EXTERNAL_PROBE_REGEX.fullmatch(base):
            self.scope = SCOPE_EXTERNAL_PROBE
            self.probe_number = int(match.group("probe"))
        elif dimension == 22 and (match := _WHO4_SPLIT_UNIT_REGEX.fullmatch(base)):
            self.scope = SCOPE_SPLIT_UNIT
            self.zone = self.zone_number = int(match.group("zone"))
            self.actuator = int(match.group("actuator"))
        elif match := _WHO4_ACTUATOR_REGEX.fullmatch(base):
            self.scope = SCOPE_ACTUATOR
            self.zone = self.zone_number = int(match.group("zone"))
            self.actuator = int(match.group("actuator"))
        elif match := _WHO4_LEGACY_ZONE_REGEX.fullmatch(base):
            # Not a published class (``#105``, ``2#10``, ``#0#0``, ``901``):
            # no scope; the legacy integer zone keeps the old reading.
            self.zone = int(match.group("zone"))
            if self.zone > 99:
                self.probe_number = int(str(self.zone)[:1])
                self.zone = int(str(self.zone)[1:])

    @property
    def unique_id(self) -> str:
        """``4-<WHERE>`` with the address class kept (``4-001`` is not ``4-1``, ``4-0`` is not ``4-#0``).

        ``#Z`` and ``#Z#C`` keep the legacy ``4-Z`` of the zone they control
        (the Encyclopedia calls ``#N`` "zone N through the central unit").
        """
        subject = str(self.zone_number) if self.scope == SCOPE_ZONE_VIA_CENTRAL else self.base
        if self.interface is not None:
            return f"4-{subject}#4#{self.interface}"
        return f"4-{subject}"

    @property
    def subject(self) -> str:
        """The subject of a log line: 'Zone 2', 'Central unit #0#1', 'Zone 1 (all probes)', ..."""
        if self.scope == SCOPE_CENTRAL:
            return f"Central unit {self.address}"
        if self.scope == SCOPE_ALL_PROBES and self.zone_number is None:
            return "Every probe"
        if self.scope == SCOPE_ALL_PROBES:
            return f"Every probe of zone {self.zone_number}"
        if self.scope == SCOPE_EXTERNAL_PROBE:
            return f"External probe {self.address}"
        if self.scope == SCOPE_SPLIT_UNIT:
            return f"Zone {self.zone_number}'s split unit {self.actuator}"
        return f"Zone {self.zone}"


# A builder WHERE: a zone ``Z`` (0..99) or ``#Z``, the central unit ``#0`` or
# ``#0#C``, a zone under a 4-zone central unit ``Z#C`` / ``#Z#C``. Exactly one
# or two digits per field: a three-digit ``001`` (all probes of zone 1) or
# ``105`` (probe 1 of zone 5) is a probe-class address the zone-setup forms
# ``#1..#99`` do not take (Encyclopedia ``what.md`` "Zone setup commands";
# ORACLE_CONFIRM H19: ``*#4*#105*#14*0200*1##`` is refused or forwarded with
# a zone byte 0x69 no documented zone has), so it is refused instead of being
# rewritten to ``#1`` / ``#105``.
_WHO4_BUILDER_ZONE_REGEX = re.compile(
    r"#?(?P<zone>[0-9]{1,2})(?:#(?P<unit>[0-9]{1,2}))?", re.ASCII
)


def _builder_zone_parts(where: str | int) -> tuple[str, int, int | None]:
    """Split a builder WHERE into (text without ``#``, zone, central selector), else raise ``ValueError``."""
    where_str = str(where).strip() if where is not None else ""
    match = _WHO4_BUILDER_ZONE_REGEX.fullmatch(where_str)
    if match is None:
        raise ValueError(
            f"Invalid zone address: {where!r} (a zone is 0..99, '#Z', '#0', '#0#C' or '#Z#C'; "
            "three-digit probe addresses such as '001' or '105' are not zones)"
        )
    zone = int(match.group("zone"))
    unit = int(match.group("unit")) if match.group("unit") is not None else None
    clean = where_str[1:] if where_str.startswith("#") else where_str
    return clean, zone, unit


def _zone_number(where: str | int) -> int:
    """Zone of a WHO 4 address: the first field, so ``#23#1`` and ``23#1`` are zone 23.

    libqtdevices TS10_1_0_23 addresses a probe ``#23#1`` and writes the plain
    zone for fan speed (``*#4*23*#11*3##``, test_probe_device.cpp line 139).
    A non-numeric shape raises ``ValueError("Invalid zone address ...")``;
    a zone above 99 or a three-digit probe-class address (``001``, ``105``)
    raises ``ValueError("Invalid zone number ...")``.
    """
    where_str = str(where).strip() if where is not None else ""
    if where_str.startswith("##"):
        raise ValueError(f"Invalid zone address: {where}")
    clean = where_str[1:] if where_str.startswith("#") else where_str
    parts = clean.split("#")
    if not parts or any(not p.isdigit() for p in parts) or len(parts) > 2:
        raise ValueError(f"Invalid zone address: {where}")
    if len(parts[0]) > 2 or int(parts[0]) > 99:
        raise ValueError(
            f"Invalid zone number: {parts[0]}. Zone must be 1..99 "
            "(three-digit addresses such as '001' or '105' are probes)"
        )
    return int(parts[0])


def _zone_address_and_name(
    where: str | int, standalone: bool = False
) -> tuple[str, str]:
    """Parse a WHO 4 WHERE address into (zone_str, zone_name).

    Preserves full compound addresses for central-unit controlled devices
    (``#23#1`` / ``23#1`` -> ``#23#1``, "zone 23") as expected by central
    units and libqtdevices TS10_1_0_23 (test_probe_device.cpp line 111,
    automatic ``*4*311*#23#1##`` and setpoint ``*#4*#23#1*#14*0250*3##``),
    and the central unit itself: ``#0`` ("the central unit") and ``#0#C``
    (the 4-zone central unit ``C``, Encyclopedia ``addressing.md``
    "Historical central-unit variants"; ``#0#1`` is the central unit with
    selector 1, not zone 1). The general address ``0`` is the central unit
    ``#0`` unless ``standalone`` is set, in which case the frame keeps the
    literal ``0`` (Encyclopedia "Published functional WHERE forms": ``0`` is
    every probe, ``#0`` the central unit; the firmware oracle NACKs
    ``*4*303*0##`` on all twelve gateways, ORACLE_CONFIRM H3, so a caller
    who wants the central unit passes ``#0``). Three-digit probe-class
    addresses (``001``, ``105``, ``#105``) raise ``ValueError``.
    """
    clean, zone_number, unit = _builder_zone_parts(where)
    if unit is not None:
        # Compound address: 4-zone central unit (#0#C) or zone under it (#Z#C / Z#C)
        zone_str = f"#{clean}"
        if zone_number == 0:
            zone_name = f"central unit {zone_str}"
        else:
            zone_name = f"zone {zone_number}"
    elif zone_number == 0:
        zone_str = "0" if standalone and not str(where).strip().startswith("#") else "#0"
        zone_name = "general" if zone_str == "0" else "central unit #0"
    else:
        zone_name = f"zone {zone_number}"
        zone_str = str(zone_number) if standalone else f"#{zone_number}"

    return zone_str, zone_name


class OWNHeatingEvent(OWNEvent):
    """A WHO 4 event or reply.

    The WHERE is kept in its address class (``scope``; Encyclopedia
    ``who-4-temperature-control/addressing.md``): ``zone`` is the legacy
    integer zone (0 for the central unit, the general address and an
    external probe), ``zone_number`` the zone of a zone-class address,
    ``central_unit`` the 4-zone central-unit selector ``C`` of ``#0#C`` /
    ``#Z#C``, ``probe_number`` the probe ``P`` of ``PZZ`` / ``P00``,
    ``actuator`` the ``N`` of ``Z#N`` / ``3#Z#N``, ``interface`` a trailing
    ``#4#NN`` bus-interface qualifier and ``address`` the whole WHERE.
    ``unique_id`` carries the address class: ``4-1`` (master probe), ``4-001``
    (all probes of zone 1), ``4-0`` (all probes), ``4-#0`` / ``4-#0#2``
    (central units), ``4-2#1`` (actuator), ``4-105`` (slave probe).

    A WHAT sets ``mode`` (coarse: heat / cool / auto / off / protection /
    holiday, see ``CLIMATE_MODE_*``), ``season`` and ``operating_mode``
    (``OPERATING_MODE_*``, one value per WHAT family of ``what.md``).
    """

    def __init__(self, data: str) -> None:
        super().__init__(data)

        self._type = None

        self._address = _Who4Address(self._where, self._where_param, self._dimension)
        self._zone = self._address.zone
        # ``_sensor`` is the probe number of a ``PZZ`` / ``P00`` WHERE (the
        # legacy name of ``probe_number``); DIMENSION 15 overrides it.
        self._sensor: int | None = self._address.probe_number
        self._actuator: int | None = self._address.actuator
        self._operating_mode: str | None = None
        self._split_mode: str | None = None
        self._split_setpoint: float | None = None
        self._split_fan_speed: str | None = None
        self._split_swing: bool | None = None

        self._mode = None
        self._mode_name = None
        self._season: str | None = None
        self._zone_context: str | None = None
        self._zone_state: str | None = None
        self._set_temperature = None
        self._local_offset = None
        self._local_offset_raw = None
        self._local_control_state = None
        self._local_set_temperature = None
        self._measured_temperature = None
        self._secondary_temperature = None
        self._measured_humidity = None
        self._program: int | None = None
        self._scenario: int | None = None
        self._holiday_end_date: tuple[int, int, int] | None = None
        self._holiday_end_time: tuple[int, int] | None = None
        self._manual_timed_duration: tuple[int, int] | None = None
        self._holiday_days: int | None = None

        self._is_active = None
        self._is_heating = None
        self._is_cooling = None

        self._fan_on = None
        self._fan_speed = None
        self._cooling_fan_on = None
        self._cooling_fan_speed = None

        _valve_active_states = ["1", "2", "6", "7", "8"]
        _actuator_active_states = ["1", "2", "6", "7", "8", "9"]
        subject = self._address.subject
        is_write = self._message_type == "DIMENSION_WRITING"

        if self._what is not None:
            self._mode = int(self._what)
            # Season of a season-specific WHAT: 1xx / 11xx / 12xx / 13xxx
            # heating, 2xx / 21xx / 22xx / 23xxx conditioning (Encyclopedia
            # what.md); generic 3xx forms have none.
            _family = str(self._what)[0] if 100 <= self._mode <= 39999 else ""
            _season = {"1": SEASON_HEATING, "2": SEASON_CONDITIONING}.get(_family)
            # The last two digits of a 3- or 4-digit WHAT name the operating
            # state (02 protection, 03 off, 10 manual, 11 automatic, 12 timed
            # manual, 15 daily holiday) or the program / scenario family
            # (x1PP, x2SS); five digits are the vacation days x3DDD.
            _coarse = {
                "1": CLIMATE_MODE_HEAT,
                "2": CLIMATE_MODE_COOL,
                "3": CLIMATE_MODE_AUTO,
            }.get(_family)

            if self._mode in (0, 1) and not self._what_param:
                # Zone operation mode frame: the zone (or the central unit)
                # is operating in the heating (1) or conditioning (0) season.
                # It is not an operating mode change: Legrand WHO 4 p. 13, 16,
                # 19 and 63 list it next to the setpoint frames as "zone
                # operation mode acquire frame"; the MyHomeServer1 translator
                # emits it with the dimension 12 setpoint report; BTicino's
                # client keeps a zone in automatic on it (libqtdevices
                # TS10_1_0_23 probe_device.cpp:240-253). Manual / automatic /
                # off arrive as 110 / 111 / 103 etc. WHAT 0 / 1 with a
                # parameter (0#T, 1#T) is in neither the specification nor
                # any capture, so it falls through to the unknown branch.
                self._type = MESSAGE_TYPE_SEASON
                self._mode_name = None
                self._season = (
                    SEASON_HEATING if self._mode == 1 else SEASON_CONDITIONING
                )
                self._human_readable_log = f"{subject}'s season is {self._season}."
            elif self._mode in (102, 202, 302):
                # Protection states (Encyclopedia what.md "Protection and OFF
                # states": 102 antifreeze, 202 thermal protection, 302 generic
                # protection). ``mode`` stays ``off`` (MyHOME turns the zone
                # OFF on them and pins the log line); the finer state is
                # ``operating_mode`` (ENCY_CONFIRM TC-H5: the touchscreen
                # client keeps "local protection" and "local OFF" apart).
                self._type = MESSAGE_TYPE_MODE
                self._mode_name = CLIMATE_MODE_OFF
                self._season = _season
                self._operating_mode = {
                    102: OPERATING_MODE_ANTIFREEZE,
                    202: OPERATING_MODE_THERMAL_PROTECTION,
                    302: OPERATING_MODE_PROTECTION,
                }[self._mode]
                self._human_readable_log = (
                    f"{subject}'s mode is set to '{self._mode_name}'"
                )
            elif self._mode in (103, 203, 303):
                self._type = MESSAGE_TYPE_MODE
                self._mode_name = CLIMATE_MODE_OFF
                self._season = _season
                self._operating_mode = OPERATING_MODE_OFF
                self._human_readable_log = (
                    f"{subject}'s mode is set to '{self._mode_name}'"
                )
            elif self._mode in (110, 210, 310, 111, 211, 311, 112, 212, 312):
                # Manual (x10), automatic (x11; Encyclopedia what.md "Manual
                # and programmed operation") and timed manual (x12: not in
                # the published table, the 312#TTTT#H form of libqtdevices
                # ThermalDevice4Zones::setManualTempTimed and the Encyclopedia
                # "Historical timed-manual DIMENSION 32"). ``mode`` keeps the
                # season-coloured heat / cool / auto values.
                self._type = MESSAGE_TYPE_MODE
                self._mode_name = _coarse
                self._season = _season
                self._operating_mode = {
                    0: OPERATING_MODE_MANUAL,
                    1: OPERATING_MODE_AUTOMATIC,
                    2: OPERATING_MODE_TIMED_MANUAL,
                }[self._mode % 10]
                self._human_readable_log = (
                    f"{subject}'s mode is set to '{self._mode_name}' ({self._operating_mode.replace('_', ' ')})"
                )
            elif self._mode in (115, 215, 315):
                # Daily holiday plan (Encyclopedia what.md "Manual and
                # programmed operation"): neither manual nor automatic;
                # ``mode`` keeps the season-coloured heat / cool / auto value
                # MyHOME pins, ``operating_mode`` says ``holiday``.
                self._type = MESSAGE_TYPE_MODE
                self._mode_name = _coarse
                self._season = _season
                self._operating_mode = OPERATING_MODE_HOLIDAY
                self._human_readable_log = (
                    f"{subject}'s mode is set to '{self._mode_name}' (daily holiday plan)"
                )
            elif (
                13001 <= self._mode <= 13255
                or 23001 <= self._mode <= 23255
                or 33001 <= self._mode <= 33255
            ):
                # Vacation for DDD days (Encyclopedia what.md "Vacation,
                # program and scenario forms", 001..255; Legrand WHO 4 p. 5 /
                # p. 64; libqtdevices thermal_device.cpp:58, 258-262, 303-307).
                self._type = MESSAGE_TYPE_MODE
                self._mode_name = _coarse
                self._season = _season
                self._operating_mode = OPERATING_MODE_VACATION
                self._holiday_days = self._mode % 1000
                self._human_readable_log = (
                    f"{subject}'s mode is set to '{self._mode_name}' (vacation for {self._holiday_days} days)"
                )
            elif (
                1101 <= self._mode <= 1103
                or 2101 <= self._mode <= 2103
                or 3101 <= self._mode <= 3116
            ):
                # Weekly program (Encyclopedia what.md: 1..3; 3104..3116 are
                # beyond the public domain but BTicino's own client serialises
                # program 12 and 15, ENCY_CONFIRM TC-H10, so they stay
                # accepted). Legrand WHO 4 p. 5 and p. 64; libqtdevices
                # thermal_device.cpp:209-211, 246-256, 291-301.
                self._type = MESSAGE_TYPE_MODE
                self._mode_name = _coarse
                self._season = _season
                self._operating_mode = OPERATING_MODE_PROGRAM
                self._program = self._mode % 100
                self._human_readable_log = (
                    f"{subject}'s mode is set to '{self._mode_name}' (weekly program {self._program})"
                )
            elif (
                1201 <= self._mode <= 1216
                or 2201 <= self._mode <= 2216
                or 3201 <= self._mode <= 3216
            ):
                self._type = MESSAGE_TYPE_MODE
                self._mode_name = _coarse
                self._season = _season
                self._operating_mode = OPERATING_MODE_SCENARIO
                self._scenario = self._mode % 100
                self._human_readable_log = (
                    f"{subject}'s mode is set to '{self._mode_name}' (scenario {self._scenario})"
                )
            elif self._mode == 3000:
                # Cancel vacation, restore the last weekly program (3000) or
                # choose one (3000#PROGRAM; Encyclopedia what.md "Vacation,
                # program and scenario forms").
                self._type = MESSAGE_TYPE_MODE
                self._mode_name = CLIMATE_MODE_AUTO
                self._operating_mode = OPERATING_MODE_CANCEL_VACATION
                self._human_readable_log = f"{subject} cancels its vacation"
            elif self._mode == 3100:
                self._type = MESSAGE_TYPE_MODE
                self._mode_name = CLIMATE_MODE_AUTO
                self._operating_mode = OPERATING_MODE_RESTORE_LAST_PROGRAM
                self._human_readable_log = f"{subject} restores its last weekly program"
            elif self._mode == 3200:
                self._type = MESSAGE_TYPE_MODE
                self._mode_name = CLIMATE_MODE_AUTO
                self._operating_mode = OPERATING_MODE_RESTORE_LAST_SCENARIO
                self._human_readable_log = f"{subject} restores its last scenario"
            elif self._mode == 20:
                self._mode_name = None
                self._human_readable_log = (
                    f"{subject}'s remote control is disabled"
                )
            elif self._mode == 21:
                self._mode_name = None
                self._human_readable_log = (
                    f"{subject}'s remote control is enabled"
                )
            elif self._mode in (22, 23, 24, 30, 31):
                # Central unit system status (Legrand WHO 4 p. 5, p. 64):
                # 22 at least one probe OFF, 23 at least one probe in
                # antifreeze, 24 at least one probe in manual, 30 failure
                # discovered, 31 central unit battery KO.
                self._mode_name = None
                _status_text = {
                    22: "at least one probe is OFF",
                    23: "at least one probe is in antifreeze",
                    24: "at least one probe is in manual mode",
                    30: "a failure was discovered",
                    31: "the central unit battery is KO",
                }[self._mode]
                self._human_readable_log = (
                    f"{subject}'s central unit reports {_status_text}"
                )
            elif self._mode == 40:
                # Release local probe adjustment (Encyclopedia what.md "Basic
                # operating states").
                self._mode_name = None
                self._human_readable_log = f"{subject} releases its local probe adjustment"
            else:
                self._mode_name = None
                self._human_readable_log = f"{subject}'s mode is unknown"

            if (
                self._operating_mode in (OPERATING_MODE_HOLIDAY, OPERATING_MODE_VACATION, OPERATING_MODE_CANCEL_VACATION)
                and self._what_param
                and self._what_param[0]
            ):
                # Holiday daily plan (115#P), holiday days (13DDD#P, 23DDD#P,
                # 33DDD#P, as sent by set_central_holiday) and cancel vacation
                # (3000#P): the parameter is the weekly program the central
                # unit resumes afterwards, 1101-1103 / 2101-2103 / 31PP
                # (Encyclopedia what.md; Legrand WHO 4 p. 56 and p. 64,
                # "115#parameterH"); libqtdevices reads it as whatArgN(0) % 100
                # (thermal_device.cpp:241, 286). It is not a temperature. The
                # grammar only admits digits in a WHAT parameter (base.py
                # _STATUS), so int() cannot fail.
                self._program = int(self._what_param[0]) % 100
                self._human_readable_log += f" (program {self._program})."
            elif (
                self._type == MESSAGE_TYPE_MODE
                and self._what_param
                and self._what_param[0] is not None
            ):
                # 110#T / 210#T manual with temperature (Legrand WHO 4 p. 23,
                # p. 56), 312#T timed manual (libqtdevices thermal_device.cpp:378).
                self._type = MESSAGE_TYPE_MODE_TARGET
                self._set_temperature = who4_temperature(self._what_param[0])
                if self._set_temperature is not None:
                    self._human_readable_log += f" at {self._set_temperature}°C."
                else:
                    self._human_readable_log += "."
            elif self._type != MESSAGE_TYPE_SEASON:
                self._human_readable_log += "."

        if self._dimension == 0 and not is_write:  # Temperature
            temp = (
                who4_temperature(self._dimension_value[0])
                if self._dimension_value
                else None
            )
            if self._sensor is None:
                self._type = MESSAGE_TYPE_MAIN_TEMPERATURE
                self._measured_temperature = temp
                if self._measured_temperature is not None:
                    self._human_readable_log = f"{subject}'s main sensor is reporting a temperature of {self._measured_temperature}°C."  # pylint: disable=line-too-long
            else:
                self._type = MESSAGE_TYPE_SECONDARY_TEMPERATURE
                self._secondary_temperature = temp
                if self._secondary_temperature is not None:
                    self._human_readable_log = f"{subject}'s secondary sensor {self._sensor} is reporting a temperature of {self._secondary_temperature}°C."  # pylint: disable=line-too-long

        elif self._dimension == 5 and self._dimension_value:  # Local control
            # MyHOME_Suite writes *#4*Z*#5*val##; the meaning of val is not
            # published, so only log it.
            self._human_readable_log = f"{subject}'s local control (dimension 5) is {self._dimension_value[0]}."  # pylint: disable=line-too-long

        elif self._dimension == 7 and self._dimension_value and not is_write:  # Zone state
            # MyHomeServer1 / Home+Control plants carry the zone's operating
            # state and setpoint here, and never in the reply to *#4*Z##.
            # The zone_* properties are only set with the message type, so a
            # half-known frame never looks like a valid state.
            # Dimension writes (*#4*Z*#7*...##) are commands handled by
            # OWNHeatingCommand; skipping them keeps write echoes typeless in
            # OWNEvent, agreeing with OWNMessage.parse.
            context, state, temperature = _zone_state(self._dimension_value)
            text = _zone_state_text(self._dimension_value)
            if text is None:
                self._human_readable_log = f"{subject} reports an unknown zone state {'*'.join(self._dimension_value)}."  # pylint: disable=line-too-long
            else:
                self._type = MESSAGE_TYPE_ZONE_STATE
                self._zone_context = context
                self._zone_state = state
                self._set_temperature = temperature
                self._human_readable_log = f"{subject} is in {text}."

        elif (
            self._dimension == 11
            and self._dimension_value
            and self._dimension_value[0].isdigit()
        ):  # Fan speed
            # ``*#4*WHERE*11*SPEED*##``: SPEED 0 automatic, 1..3, 15 OFF
            # (Encyclopedia dimensions.md "DIMENSION 11"); the trailing
            # field is empty. An empty SPEED (``*#4*1*11*##``) is no reading:
            # the frame stays untyped with every property ``None``. A write
            # (``*#4*1*#11*2##``) keeps the written speed in ``fan_speed``
            # but is a command, not a state: it stays untyped.
            if not is_write:
                self._type = MESSAGE_TYPE_FAN_SPEED
            _fan_mode = int(self._dimension_value[0])
            if _fan_mode < 4:
                self._fan_on = True
                self._is_active = True
                self._fan_speed = _fan_mode
                if _fan_mode > 0:
                    self._human_readable_log = (
                        f"{subject}'s fan is on at speed {self._fan_speed}."
                    )
                else:
                    self._human_readable_log = (
                        f"{subject}'s fan is on at 'Auto' speed."
                    )
            else:
                self._fan_on = False
                self._is_active = False
                self._human_readable_log = f"{subject}'s fan is off."

        elif self._dimension == 12 and not is_write:  # Local set temperature (set+offset)
            self._type = MESSAGE_TYPE_LOCAL_TARGET_TEMPERATURE
            self._local_set_temperature = (
                who4_temperature(self._dimension_value[0])
                if self._dimension_value
                else None
            )
            if self._local_set_temperature is not None:
                self._human_readable_log = f"{subject}'s local target temperature is set to {self._local_set_temperature}°C."  # pylint: disable=line-too-long

        elif self._dimension == 13 and self._dimension_value and not is_write:  # Local offset
            self._type = MESSAGE_TYPE_LOCAL_OFFSET
            self._local_offset_raw = self._dimension_value[0]
            if self._local_offset_raw in ("0", "00"):
                self._local_offset = 0
                self._local_control_state = LOCAL_CONTROL_NORMAL
            elif self._local_offset_raw in ("01", "02", "03"):
                self._local_offset = int(self._local_offset_raw[1:])
                self._local_control_state = LOCAL_CONTROL_OFFSET
            elif self._local_offset_raw in ("11", "12", "13"):
                self._local_offset = -int(self._local_offset_raw[1:])
                self._local_control_state = LOCAL_CONTROL_OFFSET
            elif self._local_offset_raw == "4":
                self._local_control_state = LOCAL_CONTROL_OFF
            elif self._local_offset_raw == "5":
                self._local_control_state = LOCAL_CONTROL_PROTECTION
            elif self._local_offset_raw == "6":
                # Observed on 3550 systems when the local/manual override is active.
                self._local_control_state = LOCAL_CONTROL_OVERRIDE
            else:
                self._local_control_state = LOCAL_CONTROL_UNKNOWN

            if self._local_offset is not None:
                self._human_readable_log = f"{subject}'s local offset is set to {self._local_offset}°C."
            else:
                self._human_readable_log = f"{subject}'s local control state is '{self._local_control_state}' (raw value {self._local_offset_raw})."

        elif self._dimension == 14:  # Set temperature
            # A write (``*#4*#1*#14*0205*1##``) is a command, not a state
            # (Encyclopedia dimensions.md "DIMENSION 14"), but a write echo
            # on the event path keeps its ``target_temperature`` type: MyHOME
            # updates the entity's target from it (its legacy-platform test
            # replays ``*#4*01*#14*0220*1##`` through ``OWNEvent.parse``).
            self._type = MESSAGE_TYPE_TARGET_TEMPERATURE
            # Some central units prefix the value with '#'
            # (*#4*#1*14*#0230*1##, MyHOME#139); the value is the same.
            self._set_temperature = (
                who4_temperature(self._dimension_value[0].removeprefix("#"))
                if self._dimension_value
                else None
            )
            if self._set_temperature is not None:
                self._human_readable_log = f"{subject}'s target temperature is set to {self._set_temperature}°C."  # pylint: disable=line-too-long

        elif self._dimension == 15 and not is_write:  # Probe temperature reading
            # ``*#4*WHERE*15*P*T[*...]##``. The touchscreen test report
            # ``*#4*11*15*1*123*1111##`` carries a three-digit value
            # (Encyclopedia dimensions.md "Historical external-probe
            # DIMENSION 15": "yields temperature value 123"); it is read as
            # unsigned tenths of a degree (12.3 °C), an inference from the
            # four-digit SXXX form, since the page does not spell the unit.
            self._type = MESSAGE_TYPE_SECONDARY_TEMPERATURE
            if self._dimension_value:
                if len(self._dimension_value) >= 2:
                    self._sensor = (
                        int(self._dimension_value[0])
                        if self._dimension_value[0].isdigit()
                        else None
                    )
                    temp_raw = self._dimension_value[1]
                else:
                    temp_raw = self._dimension_value[0]

                self._secondary_temperature = who4_temperature(temp_raw)
                if self._secondary_temperature is None and _WHO4_SHORT_TEMP_REGEX.fullmatch(temp_raw):
                    self._secondary_temperature = int(temp_raw) / 10.0

            if self._secondary_temperature is not None:
                if self._sensor is not None:
                    self._human_readable_log = f"{subject}'s secondary probe {self._sensor} is reporting a temperature of {self._secondary_temperature}°C."
                else:
                    self._human_readable_log = f"{subject}'s temperature probe is reporting a temperature of {self._secondary_temperature}°C."

        elif (
            self._dimension == 19
            and len(self._dimension_value) >= 2
            and all(v.isdigit() for v in self._dimension_value[:2])
            and not is_write
        ):  # Valves status
            # ``*#4*WHERE*19*CV*HV##`` (Encyclopedia dimensions.md "DIMENSION
            # 19"): 0 off, 1 on, 2 opened, 3 closed, 4 stop, 5 fan-coil off,
            # 6..8 fan-coil on at speed 1..3; 14, 15 and 16 are the fan-coil
            # OFF states "later information supplied by the MyHOME team"
            # documents (the page's only source, ENCY_CONFIRM TC-H8:
            # functional-only), not fan speeds 9..11.
            self._type = MESSAGE_TYPE_ACTION
            self._is_cooling = self._dimension_value[0] in _valve_active_states
            self._is_heating = self._dimension_value[1] in _valve_active_states
            # Handle cooling valve status relative to fan speed/status
            _cooling_value = int(self._dimension_value[0])
            if _cooling_value == 0:
                self._human_readable_log = f"{subject}'s cooling valve is off"
            elif _cooling_value == 1:
                self._human_readable_log = f"{subject}'s cooling valve is on"
            elif _cooling_value == 2:
                self._human_readable_log = (
                    f"{subject}'s cooling valve is opened"
                )
            elif _cooling_value == 3:
                self._human_readable_log = (
                    f"{subject}'s cooling valve is closed"
                )
            elif _cooling_value == 4:
                self._human_readable_log = (
                    f"{subject}'s cooling valve is stopped"
                )
            elif _cooling_value in _FAN_COIL_OFF_STATES:
                self._cooling_fan_on = False
                self._human_readable_log = (
                    f"{subject}'s cooling fan-coil is off (state {_cooling_value})"
                )
            else:
                _fan_mode = _cooling_value - 5
                if _fan_mode > 0:
                    self._cooling_fan_on = True
                    self._cooling_fan_speed = _fan_mode
                    self._human_readable_log = f"{subject}'s cooling fan is on at speed {self._cooling_fan_speed}"  # pylint: disable=line-too-long
                else:
                    self._cooling_fan_on = False
                    self._human_readable_log = f"{subject}'s cooling fan is off"
            # Handle heating valve status relative to fan speed/status
            _heating_value = int(self._dimension_value[1])
            if _heating_value == 0:
                self._human_readable_log += "; heating valve is off."
            elif _heating_value == 1:
                self._human_readable_log += "; heating valve is on."
            elif _heating_value == 2:
                self._human_readable_log += "; heating valve is opened."
            elif _heating_value == 3:
                self._human_readable_log += "; heating valve is closed."
            elif _heating_value == 4:
                self._human_readable_log += "; heating valve is stopped."
            elif _heating_value in _FAN_COIL_OFF_STATES:
                self._fan_on = False
                self._human_readable_log += f"; heating fan-coil is off (state {_heating_value})."
            else:
                _fan_mode = _heating_value - 5
                if _fan_mode > 0:
                    self._fan_on = True
                    self._fan_speed = _fan_mode
                    self._human_readable_log += (
                        f"; heating fan is on at speed {self._fan_speed}."
                    )
                else:
                    self._fan_on = False
                    self._human_readable_log += "; heating fan is off."
            # A fan-coil value on one side must not hide an open valve or a running fan
            # on the other side: *#4*2*19*5*1## (cooling fan off, heating valve on) is an
            # active zone (F461 plant capture, tests/test_f461_live_plant.py).
            self._is_active = bool(
                self._is_cooling
                or self._is_heating
                or self._cooling_fan_on
                or self._fan_on
            )

        elif (
            self._dimension == 20
            and self._dimension_value
            and self._dimension_value[0].isdigit()
            and not is_write
        ):  # Actuator status
            # ``*#4*Z#N*20*VALUE##`` (Encyclopedia dimensions.md "DIMENSION
            # 20"): one reply per actuator N, ``actuator`` names it (``None``
            # on a reply without ``#N``); a trailing ``#4#NN`` is the bus
            # interface, not actuator 4. VALUE 0..8 as DIMENSION 19, 9 =
            # fan-coil ON (no speed is published for it).
            self._type = MESSAGE_TYPE_ACTION
            self._is_active = self._dimension_value[0] in _actuator_active_states
            _actuator_text = (
                f"actuator {self._actuator}" if self._actuator is not None else "actuator"
            )
            _value = int(self._dimension_value[0])
            if _value == 0:
                self._human_readable_log = (
                    f"{subject}'s {_actuator_text} is off."
                )
            elif _value == 1:
                self._human_readable_log = (
                    f"{subject}'s {_actuator_text} is on."
                )
            elif _value == 2:
                self._human_readable_log = (
                    f"{subject}'s {_actuator_text} is opened."
                )
            elif _value == 3:
                self._human_readable_log = (
                    f"{subject}'s {_actuator_text} is closed."
                )
            elif _value == 4:
                self._human_readable_log = (
                    f"{subject}'s {_actuator_text} is stopped."
                )
            else:
                _fan_mode = _value - 5
                if _fan_mode > 0:
                    self._fan_on = True
                    self._is_active = True
                    if _fan_mode < 4:
                        self._fan_speed = _fan_mode
                        self._human_readable_log = (
                            f"{subject}'s fan is on at speed {self._fan_speed}."
                        )
                    else:
                        self._human_readable_log = (
                            f"{subject}'s fan-coil is on."
                        )
                else:
                    self._fan_on = False
                    self._is_active = False
                    self._human_readable_log = f"{subject}'s fan is off."

        elif self._dimension == 22 and self._dimension_value and not is_write:  # Split control
            # ``*#4*3#Z#N*22*MOD*SP*VEL*SWING##`` (Encyclopedia dimensions.md
            # "DIMENSION 22 - split control"): MOD 0 off, 1 winter, 2 summer,
            # 3 fan, 4 dehumidification, 5 automatic; SP tenths of a degree
            # (``000``..``1270``, unsigned); VEL 0 automatic, 1 minimum, 2
            # medium, 3 maximum, 4 silent; SWING 0 / 1. An empty field is a
            # value the unit does not report ("Historical partial split
            # writes"): the property stays ``None``. Parse only: the send
            # paths keep refusing every DIMENSION 22 spelling but the split
            # forms (``is_who4_dimension_22_crash_form``).
            values = self._dimension_value + [""] * (4 - len(self._dimension_value))
            self._type = MESSAGE_TYPE_SPLIT_CONTROL
            self._split_mode = _SPLIT_MODES.get(values[0])
            if _WHO4_SPLIT_SETPOINT_REGEX.fullmatch(values[1]):
                self._split_setpoint = int(values[1]) / 10.0
            self._split_fan_speed = _SPLIT_FAN_SPEEDS.get(values[2])
            if values[3] in ("0", "1"):
                self._split_swing = values[3] == "1"
            _parts = [
                f"mode {self._split_mode}" if self._split_mode is not None else None,
                f"setpoint {self._split_setpoint}°C" if self._split_setpoint is not None else None,
                f"fan {self._split_fan_speed}" if self._split_fan_speed is not None else None,
                f"swing {'on' if self._split_swing else 'off'}" if self._split_swing is not None else None,
            ]
            _text = ", ".join(part for part in _parts if part is not None) or "no values"
            self._human_readable_log = f"{subject} reports {_text}."

        elif (
            self._dimension == 30
            and self._dimension_value
            and len(self._dimension_value) >= 3
            and all(v.isdigit() for v in self._dimension_value[:3])
            and not is_write
        ):  # Holiday / weekend end date (DD*MM*YYYY)
            d, m, y = (
                int(self._dimension_value[0]),
                int(self._dimension_value[1]),
                int(self._dimension_value[2]),
            )
            self._holiday_end_date = (d, m, y)
            self._human_readable_log = (
                f"{subject}'s holiday end date is {d:02d}/{m:02d}/{y:04d}."
            )

        elif (
            self._dimension == 31
            and self._dimension_value
            and len(self._dimension_value) >= 2
            and all(v.isdigit() for v in self._dimension_value[:2])
            and not is_write
        ):  # Holiday / weekend end time (HH*MM)
            h, m = int(self._dimension_value[0]), int(self._dimension_value[1])
            self._holiday_end_time = (h, m)
            self._human_readable_log = (
                f"{subject}'s holiday end time is {h:02d}:{m:02d}."
            )

        elif (
            self._dimension == 32
            and self._dimension_value
            and len(self._dimension_value) >= 2
            and all(v.isdigit() for v in self._dimension_value[:2])
            and not is_write
        ):  # Timed manual duration (HH*MM)
            h, m = int(self._dimension_value[0]), int(self._dimension_value[1])
            self._manual_timed_duration = (h, m)
            self._human_readable_log = (
                f"{subject}'s timed manual duration is {h:02d}h {m:02d}m."
            )

        elif (
            self._dimension == 60
            and self._dimension_value
            and _WHO4_HUMIDITY_REGEX.fullmatch(self._dimension_value[0])
            and not is_write
        ):  # Humidity
            # An empty value (``*#4*1*60*##``) is no reading: untyped, ``None``.
            self._type = MESSAGE_TYPE_MAIN_HUMIDITY
            self._measured_humidity = float(self._dimension_value[0])
            self._human_readable_log = f"{subject}'s main sensor is reporting a humidity of {self._measured_humidity}%."  # pylint: disable=line-too-long

    @property
    def unique_id(self) -> str:
        """``4-<WHERE>`` with the address class kept.

        ``4-1`` (master probe of zone 1) is not ``4-001`` (all probes of
        zone 1), ``4-0`` (all probes) is not ``4-#0`` (the central unit),
        ``4-#0#1`` / ``4-#0#2`` are the 4-zone central units 1 and 2,
        ``4-2#1`` / ``4-2#2`` the actuators of zone 2, ``4-105`` probe 1 of
        zone 5; a bus interface is appended (``4-2#4#01``). ``#Z`` and
        ``#Z#C`` keep the legacy ``4-Z`` of the zone they control.
        """
        return self._address.unique_id

    @property
    def message_type(self) -> str | None:
        return self._type

    @property
    def zone(self) -> int:
        """The legacy integer zone.

        0 for the central unit ``#0``, the general address and an external
        probe; the selector ``C`` for the 4-zone central unit ``#0#C`` (MyHOME
        routes those frames on it; ``scope`` / ``central_unit`` / ``unique_id``
        carry the central-unit identity).
        """
        return self._zone

    @property
    def address(self) -> str:
        """The whole WHERE as sent (``#0#2``, ``001``, ``2#1#4#01``, ``3#2#1``)."""
        return self._address.address

    @property
    def scope(self) -> str | None:
        """The address class of the WHERE (``SCOPE_*``), or ``None`` for an unpublished form.

        ``SCOPE_CENTRAL`` (``#0``, ``#0#C``), ``SCOPE_ZONE_VIA_CENTRAL``
        (``#Z``, ``#Z#C``), ``SCOPE_MASTER_PROBE`` (``Z``),
        ``SCOPE_ALL_PROBES`` (``0``, ``0ZZ``), ``SCOPE_SLAVE_PROBE`` (``PZZ``),
        ``SCOPE_EXTERNAL_PROBE`` (``P00``), ``SCOPE_ACTUATOR`` (``Z#N``) and
        ``SCOPE_SPLIT_UNIT`` (``3#Z#N`` under DIMENSION 22); Encyclopedia
        ``who-4-temperature-control/addressing.md``.
        """
        return self._address.scope

    @property
    def zone_number(self) -> int | None:
        """Zone 1..99 named by the WHERE, else ``None`` (central unit, all probes ``0``, external probe)."""
        return self._address.zone_number

    @property
    def central_unit(self) -> int | None:
        """The 4-zone central-unit selector ``C`` of ``#0#C`` / ``#Z#C``, else ``None`` (``#0`` is the 3550)."""
        return self._address.central_unit

    @property
    def probe_number(self) -> int | None:
        """Probe ``P`` of a ``PZZ`` slave probe or ``P00`` external probe, or the probe of a DIMENSION 15 report."""
        return self._sensor

    @property
    def actuator(self) -> int | None:
        """Actuator ``N`` of a ``Z#N`` (DIMENSION 20) or ``3#Z#N`` (DIMENSION 22) WHERE, else ``None``."""
        return self._actuator

    @property
    def interface(self) -> str | None:
        """The bus interface ``NN`` of a trailing ``#4#NN`` WHERE qualifier, else ``None``."""
        return self._address.interface

    @property
    def mode(self) -> str | None:
        """The coarse climate mode of the WHAT (``CLIMATE_MODE_*``), else ``None``.

        ``heat`` / ``cool`` / ``auto`` for manual, automatic, timed manual,
        daily holiday plan (x15), vacation (x3DDD), program and scenario WHATs
        in the heating / conditioning / generic context, ``off`` for 103 /
        203 / 303 and the protection WHATs 102 / 202 / 302 (MyHOME routes on
        these values); ``operating_mode`` tells the families apart.
        """
        return self._mode_name

    @property
    def operating_mode(self) -> str | None:
        """The WHAT family (``OPERATING_MODE_*``), else ``None``.

        ``antifreeze`` (102), ``thermal_protection`` (202), ``protection``
        (302), ``off`` (x03), ``manual`` (x10), ``automatic`` (x11),
        ``timed_manual`` (x12), ``holiday`` (x15), ``vacation`` (x3DDD),
        ``program`` (x1PP), ``scenario`` (x2SS), ``cancel_vacation`` (3000),
        ``restore_last_program`` (3100), ``restore_last_scenario`` (3200);
        Encyclopedia ``who-4-temperature-control/what.md``.
        """
        return self._operating_mode

    @property
    def split_mode(self) -> str | None:
        """DIMENSION 22 ``MOD`` (``SPLIT_MODE_*``), else ``None``."""
        return self._split_mode

    @property
    def split_setpoint(self) -> float | None:
        """DIMENSION 22 ``SP`` in °C, else ``None``."""
        return self._split_setpoint

    @property
    def split_fan_speed(self) -> str | None:
        """DIMENSION 22 ``VEL`` (``SPLIT_FAN_*``), else ``None``."""
        return self._split_fan_speed

    @property
    def split_swing(self) -> bool | None:
        """DIMENSION 22 ``SWING``, else ``None``."""
        return self._split_swing

    @property
    def season(self) -> str | None:
        """SEASON_HEATING or SEASON_CONDITIONING named by the WHAT, else None.

        Set for the bare season frame (WHAT 1 / 0, message_type
        MESSAGE_TYPE_SEASON, mode None) and for every season-specific mode
        WHAT (1xx, 11xx, 12xx, 13xxx heating; 2xx, 21xx, 22xx, 23xxx
        conditioning). Generic WHATs (3xx, 31xx, 32xx, 33xxx) have no season.
        """
        return self._season

    @property
    def zone_context(self) -> str | None:
        """DIMENSION 7 thermal context (ZONE_CONTEXT_*), else None."""
        return self._zone_context

    @property
    def zone_state(self) -> str | None:
        """DIMENSION 7 operating state (ZONE_STATE_*), else None.

        For ZONE_STATE_SETPOINT the temperature is in set_temperature.
        ZONE_STATE_PROTECTION is the wire name for both cases: MyHOME_Suite
        calls it antifreeze in the heating context (the zone also reports
        *4*102*Z##) and thermal protection in cooling (*4*202*Z##).
        """
        return self._zone_state

    def is_active(self) -> bool | None:
        return self._is_active

    def is_heating(self) -> bool | None:
        return self._is_heating

    def is_cooling(self) -> bool | None:
        return self._is_cooling

    @property
    def main_temperature(self) -> float | None:
        return self._measured_temperature

    @property
    def main_humidity(self) -> float | None:
        return self._measured_humidity

    @property
    def secondary_temperature(self) -> list[int | float | None]:
        return [self._sensor, self._secondary_temperature]

    @property
    def probe_temperature(self) -> float | None:
        return self._secondary_temperature

    @property
    def set_temperature(self) -> float | None:
        return self._set_temperature

    @property
    def local_offset(self) -> int | None:
        return self._local_offset

    @property
    def local_offset_raw(self) -> str | None:
        return self._local_offset_raw

    @property
    def local_control_state(self) -> str | None:
        return self._local_control_state

    @property
    def local_set_temperature(self) -> float | None:
        return self._local_set_temperature

    @property
    def fan_speed(self) -> int | None:
        return self._fan_speed

    @property
    def fan_on(self) -> bool | None:
        return self._fan_on

    @property
    def cooling_fan_speed(self) -> int | None:
        return self._cooling_fan_speed

    @property
    def cooling_fan_on(self) -> bool | None:
        return self._cooling_fan_on

    @property
    def program(self) -> int | None:
        """Weekly program number named by the WHAT, else None.

        The Encyclopedia (``what.md`` "Vacation, program and scenario forms")
        publishes programs 1..3 (``1101..1103``, ``2101..2103``,
        ``3101..3103``); ``3104..3116`` are beyond that public domain but
        BTicino's own touchscreen client serialises program 12 and 15
        (ENCY_CONFIRM TC-H10), so they are decoded as well.
        """
        return self._program

    @property
    def scenario(self) -> int | None:
        """Scenario number (1..16) named by the WHAT, else None."""
        return self._scenario

    @property
    def holiday_end_date(self) -> tuple[int, int, int] | None:
        """Holiday / weekend end date (day, month, year), or None."""
        return self._holiday_end_date

    @property
    def holiday_days(self) -> int | None:
        """Holiday days (1..255) named by a 13xxx/23xxx/33xxx WHAT, else None."""
        return self._holiday_days

    @property
    def holiday_end_time(self) -> tuple[int, int] | None:
        """Holiday / weekend end time (hour, minute), or None."""
        return self._holiday_end_time

    @property
    def manual_timed_duration(self) -> tuple[int, int] | None:
        """Timed manual duration (hours, minutes), or None."""
        return self._manual_timed_duration



class OWNHeatingCommand(OWNCommand):
    def __init__(self, data: str) -> None:
        super().__init__(data)
        # A dimension write seen on the event session: MyHomeServer1 runs its
        # schedule by writing DIMENSION 7 and re-asserts DIMENSION 5.  The
        # dimension 7 status that follows is the authoritative state.
        if self._message_type == "DIMENSION_WRITING" and self._dimension_value:
            if self._dimension == 7:
                text = _zone_state_text(self._dimension_value)
                if text is None:
                    text = f"unknown zone state {'*'.join(self._dimension_value)}"
                self._human_readable_log = f"Setting zone {self._where} to {text}."
            elif self._dimension == 5:
                self._human_readable_log = f"Setting zone {self._where}'s local control (dimension 5) to {self._dimension_value[0]}."  # pylint: disable=line-too-long
            elif self._dimension == 30 and len(self._dimension_value) >= 3:
                day, month, year = (
                    self._dimension_value[0],
                    self._dimension_value[1],
                    self._dimension_value[2],
                )
                self._human_readable_log = (
                    f"Setting zone {self._where}'s holiday end date to {day}/{month}/{year}."
                )
            elif self._dimension == 31 and len(self._dimension_value) >= 2:
                hour, minute = self._dimension_value[0], self._dimension_value[1]
                self._human_readable_log = (
                    f"Setting zone {self._where}'s holiday end time to {hour}:{minute}."
                )
            elif self._dimension == 32 and len(self._dimension_value) >= 2:
                hour, minute = self._dimension_value[0], self._dimension_value[1]
                self._human_readable_log = (
                    f"Setting zone {self._where}'s timed manual duration to {hour}h {minute}m."
                )

    @classmethod
    def status(cls, where: str | int) -> OWNHeatingCommand:
        message = cls(f"*#4*{where}##")
        message._human_readable_log = f"Requesting climate status update for {message._where}{message._interface_log_text}."
        return message

    @classmethod
    def valves_status(cls, where: str | int) -> OWNHeatingCommand:
        message = cls(f"*#4*{where}*19##")
        message._human_readable_log = f"Requesting climate valve status update for {message._where}{message._interface_log_text}."
        return message

    @classmethod
    def actuators_status(cls, where: str | int) -> OWNHeatingCommand:
        """Request actuator status (``*#4*WHERE*20##``), one reply per actuator.

        ``where`` is a zone of one or two digits (``2``, ``#2``), one actuator
        (``2#1``; ``2#0`` for all actuators of the zone), the central-unit
        form (``#0``, ``#0#N``) for every zone, or ``#Z#N`` (an actuator
        addressed through the central unit; WHO 4 WHERE table, see
        ``_zone_address_and_name``). Each form may be routed through a bus interface
        with a two-digit ``#4#NN`` suffix (``3#4#01``, ``#3#4#01``,
        ``2#1#4#01``) because the suffix is spec-legal grammar, but no
        emulated firmware routes it across an F422: own-firmware-oracle#65
        (``thermo-zone-requests``, decoded ``scs_bus_hex``) shows that F450,
        F454, F459, F460, F461 and MyHomeServer1 truncate ``WHERE`` at the
        first ``#`` and answer ``*#4*2#4#01*20##`` (also ``*#4*2#4#12*20##``
        and ``*#4*2#1#4#01*20##``) with the bytes of the unqualified
        ``*#4*2*20##``, polling local main-bus zone 2; MH202 010024 reads
        the trailing ``#4#01`` as local zone 4, actuator 1 (and rejects
        ``#4#12``, actuator 12 > 9); F453, F453AV, H4684, MH200 and MH200N
        drop the frame. Callers must therefore gate ``#4#NN`` polling on the
        gateway profile's ``supports_interface_zone_requests`` (MyHOME#816)
        instead of expecting the interface to be honoured. The MH202 010024
        thermoregulation daemon crashes (``SIGSEGV``) on the dimensionless
        status forms ``*#4*Z#N##`` (``N`` 1..9) and ``*#4*Z#4#01..09##``
        (``thermo_open2scs+0x394``); this builder only emits the dimension-20
        form.
        A live F461 2.0.11 (2026-10-23) answers ``*#4*2*20##`` with
        ``*#4*2#1*20*0##`` (valve, off) on the command session and
        ``*#4*2#2*20*5##`` (fan coil, off) on the event session, and
        ``*#4*#0*20##`` with both; a live MyHomeServer1 3.87.13 answers
        ``*#4*35*20##`` with ``*#4*35#1*20*0##``. Whitespace around ``where``
        is stripped. Anything else (``*``, an empty string, a three-digit
        secondary probe such as ``105``, a two-digit actuator such as
        ``2#10``, a one- or three-digit interface such as ``3#4#1`` or
        ``3#4#001``) raises ``ValueError``. The log line carries the whole
        address as written (``2#1#4#01``), not only the zone the parser
        keeps in ``where``.
        """
        where_str = str(where).strip() if where is not None else ""
        if not _WHO4_WHERE_REGEX.fullmatch(where_str):
            raise ValueError(f"Invalid zone address: {where}")
        message = cls(f"*#4*{where_str}*20##")
        message._human_readable_log = f"Requesting climate actuator status update for {where_str}."
        return message

    @classmethod
    def get_temperature(cls, where: str | int) -> OWNHeatingCommand:
        message = cls(f"*#4*{where}*0##")
        message._human_readable_log = f"Requesting climate status update for {message._where}{message._interface_log_text}."
        return message

    @classmethod
    def get_probe_temperature(
        cls, where: str | int, sensor: int | None = None
    ) -> OWNHeatingCommand:
        """Request probe temperature status update (*#4*WHERE*15## or *#4*WHERE*15#SENSOR##)."""
        if sensor is not None:
            try:
                sensor_num = int(sensor)
            except (ValueError, TypeError):
                raise ValueError(f"Invalid sensor number: {sensor}")
            if sensor_num < 1:
                raise ValueError(f"Invalid sensor number: {sensor}")
            message = cls(f"*#4*{where}*15#{sensor_num}##")
            message._human_readable_log = (
                f"Requesting probe {sensor_num} temperature status update for "
                f"{message._where}{message._interface_log_text}."
            )
        else:
            message = cls(f"*#4*{where}*15##")
            message._human_readable_log = (
                f"Requesting probe temperature status update for "
                f"{message._where}{message._interface_log_text}."
            )
        return message

    @classmethod
    def get_fan_speed(cls, where: str | int) -> OWNHeatingCommand:
        """Request fan speed status update for a zone (*#4*ZONE*11##).

        BTicino client (libqtdevices TS10_1_0_23 ControlledProbeDevice::requestFancoilStatus)
        sends *#4*ZONE*11## using the plain zone number.
        """
        where_str = str(where)
        if where_str in ("#0", "0") or where_str.startswith("#0#"):
            raise ValueError(
                f"Fan speed cannot be requested on central unit or general zone: {where}"
            )
        zone_number = _zone_number(where_str)
        if zone_number < 1:
            raise ValueError(f"Invalid zone number: {zone_number}. Zone must be 1..99")

        message = cls(f"*#4*{zone_number}*11##")
        message._human_readable_log = (
            f"Requesting zone {zone_number} fan speed update{message._interface_log_text}."
        )
        return message

    @classmethod
    def set_mode(
        cls, where: str | int, mode: str, standalone: bool = False
    ) -> OWNHeatingCommand | None:
        """Set zone operation mode.

        Supports standard off/auto as well as protection, antifreeze, and
        thermal_protection matching libqtdevices ControlledProbeDevice::setProtection.
        """
        zone, zone_name = _zone_address_and_name(where, standalone=standalone)

        mode_name = mode
        if mode == CLIMATE_MODE_AUTO:
            # Automatic is the central unit's program: the firmware refuses *4*311*Z##
            # (NACK, no bus frame across all 11 emulated gateways in thermo-zone-mode.tsv
            # and ownd-pr82-heating.tsv; OWNd#77 A3) and only forwards *4*311*#Z##, a
            # frame addressed to the central unit (bus D1 00 03 02 C2 ZZ 00 00), so
            # standalone does not apply. Protection (302 / 102 / 202) is different:
            # the plain zone form is forwarded as a direct zone command (bus
            # 93 ZZ 30 04, like *4*303*Z## -> 93 ZZ 30 0F in thermo-zone-mode.tsv)
            # and is the only form a standalone thermostat acts on; the #Z form goes
            # to a central unit (bus D1 00 03 02 C2 ZZ 07 00 in thermo-ts10.tsv) and
            # is ignored when there is none (F461 plant capture,
            # tests/test_f461_live_plant.py).
            if not zone.startswith("#"):
                zone = f"#{zone}"

        if mode == CLIMATE_MODE_OFF:
            mode_code = 303
        elif mode == CLIMATE_MODE_AUTO:
            mode_code = 311
        elif mode == "protection":
            mode_code = 302
        elif mode == "antifreeze":
            mode_code = 102
        elif mode == "thermal_protection":
            mode_code = 202
        else:
            return None

        message = cls(f"*4*{mode_code}*{zone}##")
        message._human_readable_log = f"Setting {zone_name} mode to '{mode_name}'."
        return message

    @classmethod
    def set_protection(
        cls, where: str | int, mode: str = "protection", standalone: bool = False
    ) -> OWNHeatingCommand | None:
        """Set zone protection mode ('protection', 'antifreeze', or 'thermal_protection')."""
        return cls.set_mode(where=where, mode=mode, standalone=standalone)

    @classmethod
    def turn_off(
        cls, where: str | int, standalone: bool = False
    ) -> OWNHeatingCommand | None:
        return cls.set_mode(where=where, mode=CLIMATE_MODE_OFF, standalone=standalone)

    @classmethod
    def set_temperature(
        cls, where: str | int, temperature: float, mode: str, standalone: bool = False
    ) -> OWNHeatingCommand:
        """Manual setpoint ``*#4*#WHERE*#14*TTTT*M##`` (Encyclopedia what.md "Zone setup commands").

        ``where`` is a zone (``1``..``99``, sent as ``#Z``, or the plain
        ``Z`` with ``standalone``), ``#Z#C`` / ``Z#C`` under a 4-zone central
        unit, or the central unit ``#0`` / ``#0#C``; a three-digit
        probe-class address (``001`` all probes of zone 1, ``105`` probe 1 of
        zone 5, ``#105``) raises ``ValueError`` instead of being rewritten
        to ``#1`` / ``#105`` (ORACLE_CONFIRM H2, H19). The temperature is
        clamped to ``5.0..40.0`` (``T`` is ``0050..0400``; MyHOME relies on
        the clamp) and rounded to 0.5 °C; only a non-finite value raises.
        """
        zone, zone_name = _zone_address_and_name(where, standalone=standalone)

        temp_val = float(temperature)
        if not math.isfinite(temp_val):
            raise ValueError("temperature must be finite")
        # ``T`` is ``0050..0400`` in 0.5 °C steps (Encyclopedia what.md
        # "Zone setup commands"): clamp, as ``set_central_temperature`` does.
        temperature = round(max(5.0, min(40.0, temp_val)) * 2) / 2
        temperature_print = f"{temperature}"
        temperature_code = int(temperature * 10)

        mode_name = mode
        if mode in (CLIMATE_MODE_HEAT, 1, "1"):
            mode_code = 1
        elif mode in (CLIMATE_MODE_COOL, 2, "2"):
            mode_code = 2
        elif mode in (CLIMATE_MODE_AUTO, "generic", 3, "3"):
            mode_code = 3
        else:
            raise ValueError(
                "mode must be 'heat' (1), 'cool' (2), or 'auto'/'generic' (3)"
            )

        message = cls(f"*#4*{zone}*#14*{temperature_code:04d}*{mode_code}##")
        message._human_readable_log = (
            f"Setting {zone_name} to {temperature_print}°C in mode '{mode_name}'."
        )
        return message

    @classmethod
    def set_fan_speed(
        cls, where: str | int, speed: int, standalone: bool = False
    ) -> OWNHeatingCommand:
        """Build a fan speed command; ``standalone`` is ignored (kept for compatibility)."""
        where_str = str(where)
        if where_str in ("#0", "0") or where_str.startswith("#0#"):
            raise ValueError(
                f"Fan speed cannot be set on central unit or general zone: {where}"
            )
        zone_number = _zone_number(where_str)
        if zone_number < 1:
            raise ValueError(f"Invalid zone number: {zone_number}. Zone must be 1..99")
        try:
            speed_code = int(speed)
        except (ValueError, TypeError):
            raise ValueError(f"Invalid fan speed: {speed}")
        if not (0 <= speed_code <= 3):
            raise ValueError(f"Invalid fan speed: {speed_code}. Speed must be 0..3")

        message = cls(f"*#4*{zone_number}*#11*{speed_code}##")
        message._human_readable_log = (
            f"Setting zone {zone_number} fan speed to {speed_code}."
        )
        return message

    @classmethod
    def set_central_mode(
        cls, where: str = "#0", mode: str = CLIMATE_MODE_HEAT
    ) -> OWNHeatingCommand:
        """Set operation mode for Central Unit (3550 99-zone or 4695 4-zone).

        The codes are the ones BTicino's touch-screen client sends to a central
        unit (libqtdevices ``thermal_device.cpp``): 303 generic off, 1 winter,
        0 summer, 302 generic protection. 102 is the winter (antifreeze)
        protection; 202, the summer protection, is not offered because it
        would also switch the plant to summer. 311 is the generic automatic
        command libqtdevices sends to zones; on ``#0`` it puts every zone back
        on the central unit's program.

        ``where`` is the central unit itself: ``#0`` (3550, 99 zones) or
        ``#0#C`` with ``C`` the 4695 unit's configured zone 1..99 or
        ``01``..``99`` (the forms MyHOME and the golden corpus use);
        whitespace around it is stripped. Central-unit WHATs address the
        central unit by API contract (OWNd#77 fix 3). A zone addressed
        through the central unit, ``#Z`` or ``#Z#C`` (zone ``Z`` under
        4-zone central unit ``C``, bus command byte ``C2`` from libqtdevices'
        ``ControlledProbeDevice``), is a zone mode: ``set_mode`` builds it
        (``set_mode("23#1", CLIMATE_MODE_AUTO)`` -> ``*4*311*#23#1##``), and
        this builder raises ``ValueError`` for it, as it does for a bare zone,
        ``#00``, ``#0#0``, ``#0#00`` and three-digit values (``#0#100``).
        The plain zone form ``*4*311*Z##`` is ``nack``/``silent`` on
        all 12 emulated gateways (firmware oracle ``thermo-zone-mode`` and
        ``ownd-pr82-heating``), and a live F461 2.0.11 NACKs ``*4*311*2##``
        while it ACKs ``*4*311*#2##``. ``*4*1*Z##`` and ``*4*303*Z##`` are
        forwarded by some gateways, but as zone commands, not central ones.
        """
        where = _validate_central_where(where, "Central unit mode")
        mode_map = {
            CLIMATE_MODE_OFF: 303,
            CLIMATE_MODE_HEAT: 1,
            CLIMATE_MODE_COOL: 0,
            CLIMATE_MODE_AUTO: 311,
            "antifreeze": 102,
            "protection": 302,
        }
        mode_code = mode_map.get(mode)
        if mode_code is None:
            raise ValueError(f"Unsupported central unit mode: {mode}")
        message = cls(f"*4*{mode_code}*{where}##")
        message._human_readable_log = (
            f"Setting Central Unit {where} mode to '{mode}' (code {mode_code})."
        )
        return message

    @classmethod
    def set_central_temperature(
        cls, where: str = "#0", temperature: float = 20.0, mode: str = CLIMATE_MODE_HEAT
    ) -> OWNHeatingCommand:
        """Set master setpoint temperature on Central Unit."""
        where = _validate_central_where(where, "Central unit setpoint")
        temp_val = float(temperature)
        if not math.isfinite(temp_val):
            raise ValueError("temperature must be finite")
        temperature = round(temp_val * 2) / 2
        temperature = max(5.0, min(40.0, temperature))
        temp_code = int(temperature * 10)
        if mode in (CLIMATE_MODE_HEAT, 1, "1"):
            mode_code = 1
        elif mode in (CLIMATE_MODE_COOL, 2, "2"):
            mode_code = 2
        elif mode in (CLIMATE_MODE_AUTO, "generic", 3, "3"):
            mode_code = 3
        else:
            raise ValueError(
                "mode must be 'heat' (1), 'cool' (2), or 'auto'/'generic' (3)"
            )
        message = cls(f"*#4*{where}*#14*{temp_code:04d}*{mode_code}##")
        message._human_readable_log = (
            f"Setting Central Unit {where} setpoint to {temperature}°C in mode '{mode}'."
        )
        return message

    @classmethod
    def set_central_program(
        cls, where: str = "#0", program: int = 1
    ) -> OWNHeatingCommand:
        """Select weekly program (1..16) on Central Unit (*4*31PP*WHERE##).

        BTicino client (libqtdevices TS10_1_0_23 ThermalDevice::setWeekProgram)
        sends *4*3100+prog*WHERE##.
        """
        where = _validate_central_where(where, "Central unit weekly program")
        try:
            prog_num = int(program)
        except (ValueError, TypeError):
            raise ValueError(f"Invalid program number: {program}")
        if not (1 <= prog_num <= 16):
            raise ValueError(
                f"Invalid program number: {program}. Program must be 1..16"
            )
        what = 3100 + prog_num
        message = cls(f"*4*{what}*{where}##")
        message._human_readable_log = (
            f"Setting Central Unit {where} weekly program to {prog_num} (code {what})."
        )
        return message

    @classmethod
    def set_central_scenario(
        cls, where: str = "#0", scenario: int = 1
    ) -> OWNHeatingCommand:
        """Select preset scenario (1..16) on 99-zone Central Unit (*4*32SS*WHERE##).

        BTicino client (libqtdevices TS10_1_0_23 ThermalDevice99Zones::setScenario)
        sends *4*3200+scen*WHERE##.
        """
        where = _validate_central_where(where, "Central unit scenario")
        try:
            scen_num = int(scenario)
        except (ValueError, TypeError):
            raise ValueError(f"Invalid scenario number: {scenario}")
        if not (1 <= scen_num <= 16):
            raise ValueError(
                f"Invalid scenario number: {scenario}. Scenario must be 1..16"
            )
        what = 3200 + scen_num
        message = cls(f"*4*{what}*{where}##")
        message._human_readable_log = (
            f"Setting Central Unit {where} scenario to {scen_num} (code {what})."
        )
        return message

    @classmethod
    def set_timed_manual(
        cls,
        where: str | int,
        temperature: float,
        hours: int = 2,
        standalone: bool = False,
    ) -> OWNHeatingCommand:
        """Set timed manual operation temperature (*4*312#TTTT#H*WHERE##).

        BTicino client (libqtdevices TS10_1_0_23 ThermalDevice4Zones::setManualTempTimed)
        sends *4*312#TTTT#H*WHERE##.
        """
        zone, zone_name = _zone_address_and_name(where, standalone=standalone)
        temp_val = float(temperature)
        if not math.isfinite(temp_val):
            raise ValueError("temperature must be finite")
        temperature = round(temp_val * 2) / 2
        temperature = max(5.0, min(40.0, temperature))
        temp_code = int(temperature * 10)
        try:
            h = int(hours)
        except (ValueError, TypeError):
            raise ValueError(f"Invalid duration hours: {hours}")
        if not (1 <= h <= 24):
            raise ValueError(f"Invalid duration hours: {hours}. Hours must be 1..24")

        message = cls(f"*4*312#{temp_code:04d}#{h}*{zone}##")
        message._human_readable_log = (
            f"Setting {zone_name} timed manual to {temperature}°C for {h} hours."
        )
        return message

    @classmethod
    def set_central_weekend(
        cls, where: str = "#0", program: int = 1
    ) -> OWNHeatingCommand:
        """Set Central Unit weekend mode to run program (1..16) (*4*315#31PP*WHERE##).

        BTicino client (libqtdevices TS10_1_0_23 ThermalDevice::setWeekendDateTime)
        sends *4*315#3100+prog*WHERE##.
        """
        where = _validate_central_where(where, "Central unit weekend mode")
        try:
            prog_num = int(program)
        except (ValueError, TypeError):
            raise ValueError(f"Invalid program number: {program}")
        if not (1 <= prog_num <= 16):
            raise ValueError(
                f"Invalid program number: {program}. Program must be 1..16"
            )
        prog_code = 3100 + prog_num
        message = cls(f"*4*315#{prog_code}*{where}##")
        message._human_readable_log = (
            f"Setting Central Unit {where} weekend mode with program {prog_num}."
        )
        return message

    @classmethod
    def set_central_holiday(
        cls, where: str = "#0", days: int = 1, program: int = 1
    ) -> OWNHeatingCommand:
        """Set Central Unit holiday mode for days (1..255) with program (1..16) (*4*33DDD#31PP*WHERE##).

        BTicino client (libqtdevices TS10_1_0_23 ThermalDevice::setHolidayDateTime)
        sends *4*33000+days#3100+prog*WHERE##.
        """
        where = _validate_central_where(where, "Central unit holiday mode")
        try:
            d = int(days)
        except (ValueError, TypeError):
            raise ValueError(f"Invalid holiday days: {days}")
        if not (1 <= d <= 255):
            raise ValueError(f"Invalid holiday days: {days}. Days must be 1..255")
        try:
            prog_num = int(program)
        except (ValueError, TypeError):
            raise ValueError(f"Invalid program number: {program}")
        if not (1 <= prog_num <= 16):
            raise ValueError(
                f"Invalid program number: {program}. Program must be 1..16"
            )
        holiday_code = 33000 + d
        prog_code = 3100 + prog_num
        message = cls(f"*4*{holiday_code}#{prog_code}*{where}##")
        message._human_readable_log = (
            f"Setting Central Unit {where} holiday mode for {d} days with program {prog_num}."
        )
        return message

    @classmethod
    def set_holiday_end_date(
        cls, where: str = "#0", day: int = 1, month: int = 1, year: int = 2026
    ) -> OWNHeatingCommand:
        """Set holiday / weekend end date (*#4*WHERE*#30*DD*MM*YYYY##).

        BTicino client (libqtdevices TS10_1_0_23 ThermalDevice::setHolidayEndDate)
        sends *#4*WHERE*#30*DD*MM*YYYY##.
        """
        where = _validate_central_where(where, "Central unit holiday end date")
        try:
            d, m, y = int(day), int(month), int(year)
        except (ValueError, TypeError):
            raise ValueError(f"Invalid date: {day}/{month}/{year}")
        if not (1 <= d <= 31 and 1 <= m <= 12 and 2000 <= y <= 2099):
            raise ValueError(f"Invalid date values: {d}/{m}/{y}")
        try:
            # A real calendar date (Encyclopedia dimensions.md "DIMENSION 30 -
            # holiday end": "Validate the actual calendar date as well as
            # individual field ranges"; the firmware oracle NACKs 31 February
            # on all twelve gateways, ORACLE_CONFIRM H18).
            datetime.date(y, m, d)
        except ValueError:
            raise ValueError(f"Invalid calendar date: {d:02d}/{m:02d}/{y:04d}") from None
        message = cls(f"*#4*{where}*#30*{d:02d}*{m:02d}*{y:04d}##")
        message._human_readable_log = (
            f"Setting Central Unit {where} holiday end date to {d:02d}/{m:02d}/{y:04d}."
        )
        return message

    @classmethod
    def set_holiday_end_time(
        cls, where: str = "#0", hour: int = 0, minute: int = 0
    ) -> OWNHeatingCommand:
        """Set holiday / weekend end time (*#4*WHERE*#31*HH*MM##).

        BTicino client (libqtdevices TS10_1_0_23 ThermalDevice::setHolidayEndTime)
        sends *#4*WHERE*#31*HH*MM##.
        """
        where = _validate_central_where(where, "Central unit holiday end time")
        try:
            h, m = int(hour), int(minute)
        except (ValueError, TypeError):
            raise ValueError(f"Invalid time: {hour}:{minute}")
        if not (0 <= h <= 23 and 0 <= m <= 59):
            raise ValueError(f"Invalid time values: {h}:{m}")
        message = cls(f"*#4*{where}*#31*{h:02d}*{m:02d}##")
        message._human_readable_log = (
            f"Setting Central Unit {where} holiday end time to {h:02d}:{m:02d}."
        )
        return message

    @classmethod
    def set_timed_manual_end_time(
        cls, where: str = "#0", hour: int = 0, minute: int = 0
    ) -> OWNHeatingCommand:
        """Set timed manual duration/end time (*#4*WHERE*#32*HH*MM##).

        BTicino client (libqtdevices TS10_1_0_23 ThermalDevice4Zones::setEndTime)
        sends *#4*WHERE*#32*HH*MM##.
        """
        where = _validate_central_where(where, "Central unit timed manual end time")
        try:
            h, m = int(hour), int(minute)
        except (ValueError, TypeError):
            raise ValueError(f"Invalid time: {hour}:{minute}")
        if not (0 <= h <= 24 and 0 <= m <= 59):
            raise ValueError(f"Invalid time values: {h}:{m}")
        message = cls(f"*#4*{where}*#32*{h:02d}*{m:02d}##")
        message._human_readable_log = (
            f"Setting Central Unit {where} timed manual duration to {h:02d}h {m:02d}m."
        )
        return message

    @classmethod
    def central_status(cls, where: str = "#0") -> OWNHeatingCommand:
        """Deprecated: builds ``*#4*WHERE*14##``, which gateways refuse.

        A real MyHomeServer1 3.1.8 (OWNd#77 gateway probe) answers ``*#*0##``
        (NACK); on an F454 (MyHOME#629) dimension 14 silently timed out while
        ``status("#0")`` (``*#4*#0##``) answered within 0.13 s. Use
        ``status(where)`` to poll a central unit. The frame is kept unchanged
        for existing callers.
        """
        warnings.warn(
            "OWNHeatingCommand.central_status() builds *#4*WHERE*14##, which gateways "
            "refuse; use OWNHeatingCommand.status(where) instead",
            DeprecationWarning,
            stacklevel=2,
        )
        message = cls(f"*#4*{where}*14##")
        message._human_readable_log = f"Requesting Central Unit {where} status."
        return message

    @property
    def is_temperature_query(self) -> bool:
        """True if this message is a temperature dimension query (*#4*WHERE*0##)."""
        return (
            self.is_dimension_request
            and self._dimension == 0
            and bool(self._where)
        )

    @staticmethod
    def encode_temperature(temperature: float) -> str:
        """Encode a temperature in °C into WHO 4 4-digit SXXX format (tenths of a degree)."""
        if isinstance(temperature, bool):
            raise ValueError("temperature must be finite")
        temp_val = float(temperature)
        if not math.isfinite(temp_val):
            raise ValueError("temperature must be finite")
        if not -99.9 <= temp_val <= 99.9:
            raise ValueError("temperature must be between -99.9 and 99.9")
        tenths = int(
            (Decimal(str(temp_val)) * Decimal(10)).quantize(
                Decimal("1"), rounding=ROUND_HALF_UP
            )
        )
        if tenths < 0:
            return f"1{abs(tenths):03d}"
        return f"0{tenths:03d}"

    @classmethod
    def report_temperature(
        cls, where: str | int, temperature: float
    ) -> OWNHeatingCommand:
        """Build a WHO 4 Dimension 0 temperature report frame (*#4*WHERE*0*TTTT##)."""
        target = require_non_empty_where(where)
        encoded = cls.encode_temperature(temperature)
        decoded = who4_temperature(encoded)
        message = cls(f"*#4*{target}*0*{encoded}##")
        message._human_readable_log = (
            f"Reporting temperature {decoded}°C for {message._where}{message._interface_log_text}."
        )
        return message

    @classmethod
    def write_temperature(
        cls, where: str | int, temperature: float
    ) -> OWNHeatingCommand:
        """Build a WHO 4 Dimension #0 temperature write frame (*#4*WHERE*#0*TTTT##)."""
        target = require_non_empty_where(where)
        encoded = cls.encode_temperature(temperature)
        decoded = who4_temperature(encoded)
        message = cls(f"*#4*{target}*#0*{encoded}##")
        message._human_readable_log = (
            f"Writing temperature {decoded}°C for {message._where}{message._interface_log_text}."
        )
        return message


register_event_parser(4, OWNHeatingEvent)
register_command_parser(4, OWNHeatingCommand)


# WHO 1004: thermoregulation autodiagnostics (Encyclopedia Machine KB
# ``ownkb:chunk:r000204``-``r000209``, ``ownkb:claim:c004423``,
# ``ownkb:claim:c004429``-``c004448``, WHO_4 v2.0.0 pp. 69-74; unpacked by
# ``OPN_OpenScsDiagGenTr`` / ``OPN_OpenScsDiagTermoTr`` in ``libdiag.so``).
#
# WHERE grammar, as ``OPN_ThermoWhereTransl`` in ``libwhere.so`` accepts it:
#
# - ``#0`` / ``#0#C``: the central unit (``_WHO4_CENTRAL_WHERE_REGEX``), scope
#   ``"central"``;
# - ``#Z`` / ``#Z#C`` (``Z`` 1..99, ``C`` 1..99): zone ``Z`` through the
#   central unit, scope ``"zone"``;
# - ``Z`` (1..99): the master probe of zone ``Z``, scope ``"probe"``;
# - ``NZZ`` (``N`` 1..8, ``ZZ`` 01..99: 101..899): slave probe ``N`` of zone
#   ``ZZ``, scope ``"slave_probe"``;
# - ``[1-9]00`` (100..900): an external probe, scope ``"external_probe"``;
# - ``Z#N`` (``Z`` 1..99, ``N`` 1..9): actuator ``N`` of zone ``Z``, scope
#   ``"actuator"``;
# - anything else (``0``, ``901``, ``66#0``, ``#0#0``, ``#66#1#2``): no scope.
#
# DIMENSIONS 7, 8, 11 and 12 are 24-bit ``0``/``1`` masks of the central
# unit and of the addressed devices (``s2o_diagnosticsA``); DIMENSIONS 21
# and 22 are 16-bit masks of a zone (``s2o_autoDiagnostics``, zone 1..99;
# 22 is pushed by the gateway only, no request exists for it); DIMENSION 23
# on the central unit is two counts, non-responding units and faulty units
# (``s2o_autoDiagnostics``, zone 100); DIMENSION 20 is a request-only
# trigger answered with zero or more DIMENSION 21 frames. ``1`` is a healthy
# bit, ``0`` an active one; WHO_4 v2.0.0 pp. 69-74 names the active-low
# conditions of bits 13..16 and 21..24 of the 24-bit central mask and
# 11..16 of the 16-bit zone mask, but their indexing on the bus has not been
# confirmed by fault injection, so the mask is exposed as sent with the
# positions of its cleared bits, as ``OWNLightingDiagnosticEvent`` does for
# WHO 1001.
_WHO1004_ZONE_REGEX = re.compile(r"[1-9][0-9]?", re.ASCII)
_WHO1004_CENTRAL_ZONE_REGEX = re.compile(
    r"#(?P<zone>[1-9][0-9]?)(?:#(?P<unit>[1-9][0-9]?))?", re.ASCII
)
_WHO1004_SLAVE_PROBE_REGEX = re.compile(r"(?P<probe>[1-8])(?P<zone>0[1-9]|[1-9][0-9])", re.ASCII)
_WHO1004_EXTERNAL_PROBE_REGEX = re.compile(r"[1-9]00", re.ASCII)
_WHO1004_ACTUATOR_REGEX = re.compile(r"(?P<zone>[1-9][0-9]?)#(?P<actuator>[1-9])", re.ASCII)
_WHO1004_DEVICE_REGEX = re.compile(
    r"[1-9][0-9]?(?:#[1-9])?|[1-8](?:0[1-9]|[1-9][0-9])|[1-9]00", re.ASCII
)
_WHO1004_DEVICE_SCOPES = frozenset({"central", "probe", "slave_probe", "external_probe", "actuator"})
_WHO1004_MASK_DIMENSIONS_24 = frozenset({7, 8, 11, 12})
_WHO1004_MASK_DIMENSIONS_16 = frozenset({21, 22})
_WHO1004_REQUEST_DIMENSIONS = (7, 8, 11, 12)
_WHO1004_COUNT_REGEX = re.compile(r"[0-9]+", re.ASCII)


def _who1004_address(where: str | None, where_param: list[str]) -> str:
    """The full WHERE of a WHO 1004 frame (``#0#2``, ``#66#2``, ``66#1``)."""
    return "#".join([where or "", *where_param])


def _who1004_unique_id(where: str | None, where_param: list[str]) -> str:
    """``1004-<full WHERE>``: ``#0#2``, ``#0`` and ``#0#1`` must not collide.

    WHO 1004 is not in ``OWNMessage.interface`` (``#0#C`` is a central unit,
    not a bus interface), so the inherited ``unique_id`` would drop the
    WHERE parameters and give ``#0`` / ``#0#1`` / ``#0#2``, ``#66`` / ``#66#2``
    and ``66`` / ``66#1`` the same id.
    """
    address = _who1004_address(where, where_param)
    return f"1004-{address}" if address else "1004"


class OWNHeatingDiagnosticEvent(OWNEvent):
    """WHO 1004: autodiagnostics of the thermoregulation system.

    WHO 1004 is the diagnostic WHO of the "Temperature control system"
    (Encyclopedia Machine KB ``ownkb:chunk:r000204``-``r000209``,
    ``ownkb:claim:c004423``, ``ownkb:claim:c004429``-``c004448``;
    ``libdiag.so`` unpacks the SCS bytes). The first physical frames come
    from an H/L4684 6.0.11 with a 3550 central unit and an F430/4 on zone
    66, pushed once the actuator channel ``66#1`` came back online
    (MyHOME#839, fixture ``issue_466``
    ``myhome_trace_HL4684_all_2026-11-01T11-30-19.json``):

    - ``*#1004*66*11*111111111111111111111111##``: master probe 66,
      DIMENSION 11, 24-bit mask (``scope`` ``"probe"``);
    - ``*#1004*#66*22*1111111111111111##``: zone 66 through the central
      unit, DIMENSION 22, 16-bit mask (``scope`` ``"zone"``);
    - ``*#1004*#0*11*111111111111111111111111##``: the 3550 central unit,
      DIMENSION 11, 24-bit mask (``scope`` ``"central"``).

    ``scope`` follows the ``OPN_ThermoWhereTransl`` WHERE grammar:
    ``"central"`` (``#0``, ``#0#C``), ``"zone"`` (``#Z``, ``#Z#C``;
    ``zone_number``), ``"probe"`` (``Z``; ``zone_number``), ``"slave_probe"``
    (``NZZ``; ``zone_number`` ``ZZ``, ``probe_number`` ``N``),
    ``"external_probe"`` (``[1-9]00``; no zone), ``"actuator"`` (``Z#N``;
    ``zone_number``, ``actuator_number``) or ``None``. WHO 1004 is not in
    ``OWNMessage.interface`` (the ``#4#IF`` suffix of WHO 1 / 2 would read
    ``#0#C`` as an interface), and ``unique_id`` carries the full WHERE so
    ``#0`` / ``#0#2``, ``#66`` / ``#66#2`` and ``66`` / ``66#1`` stay apart.

    ``diagnostic_mask`` is the 24-bit mask of DIMENSIONS 7, 8, 11 and 12 on
    the central unit and on the addressed devices (``ownkb:claim:c004423``)
    or the 16-bit mask of DIMENSIONS 21 and 22 on a zone, only when the
    frame carries exactly one all-``0``/``1`` value of that length;
    ``cleared_bits`` and ``has_fault`` follow it. ``1`` is a healthy bit and
    ``0`` an active one. WHO_4 v2.0.0 pp. 69-74 (``ownkb:chunk:r000206``-
    ``r000207``) documents active-low conditions for bits 13..16 and 21..24
    of the 24-bit central mask and 11..16 of the 16-bit zone mask; the
    bit-order indexing on the bus has not been confirmed by hardware fault
    injection, so the mask is kept raw and nothing is interpreted.
    DIMENSION 23 on the central unit (``*#1004*#0*23*NO_RESPONSE*FAULTS##``,
    ``ownkb:claim:c004442``) is decoded into ``non_responding_units`` and
    ``faulty_units`` when it carries exactly two decimal values. Any other
    value shape, dimension or WHERE fails closed with the raw values in
    ``dimension_value``. The WHO 4 DIMENSION 22 guard anchors on WHO ``4``,
    so ``*#1004*#66*22*...##`` is not a crash form.
    """

    def __init__(self, data: str) -> None:
        super().__init__(data)
        self._scope: str | None = None
        self._zone_number: int | None = None
        self._probe_number: int | None = None
        self._actuator_number: int | None = None
        self._diagnostic_mask: str | None = None
        self._cleared_bits: tuple[int, ...] | None = None
        self._non_responding_units: int | None = None
        self._faulty_units: int | None = None

        address = _who1004_address(self._where, self._where_param)
        if _WHO4_CENTRAL_WHERE_REGEX.fullmatch(address):
            self._scope = "central"
            subject = f"Thermoregulation central unit {address}"
        elif zone_match := _WHO1004_CENTRAL_ZONE_REGEX.fullmatch(address):
            self._scope = "zone"
            self._zone_number = int(zone_match.group("zone"))
            unit = zone_match.group("unit")
            subject = f"Thermoregulation zone {self._zone_number}" + (
                f" of central unit {unit}" if unit else ""
            )
        elif actuator_match := _WHO1004_ACTUATOR_REGEX.fullmatch(address):
            self._scope = "actuator"
            self._zone_number = int(actuator_match.group("zone"))
            self._actuator_number = int(actuator_match.group("actuator"))
            subject = f"Thermoregulation zone {self._zone_number} actuator {self._actuator_number}"
        elif _WHO1004_EXTERNAL_PROBE_REGEX.fullmatch(address):
            self._scope = "external_probe"
            subject = f"Thermoregulation external probe {address}"
        elif slave_match := _WHO1004_SLAVE_PROBE_REGEX.fullmatch(address):
            self._scope = "slave_probe"
            self._zone_number = int(slave_match.group("zone"))
            self._probe_number = int(slave_match.group("probe"))
            subject = f"Thermoregulation zone {self._zone_number} slave probe {self._probe_number}"
        elif _WHO1004_ZONE_REGEX.fullmatch(address):
            self._scope = "probe"
            self._zone_number = int(address)
            subject = f"Thermoregulation probe {self._zone_number}"
        else:
            subject = f"Thermoregulation device {address}"

        # Exactly one value of exactly the published length for this scope and
        # dimension, all 0/1: a trailing value, another length, a non-binary
        # character, an unrecognised WHERE or a mask dimension the scope does
        # not report fail closed.
        if self._dimension in _WHO1004_MASK_DIMENSIONS_24 and self._scope in _WHO1004_DEVICE_SCOPES:
            expected_length: int | None = 24
        elif self._dimension in _WHO1004_MASK_DIMENSIONS_16 and self._scope == "zone":
            expected_length = 16
        else:
            expected_length = None
        values = self._dimension_value
        if expected_length is not None and len(values) == 1:
            value = values[0]
            if len(value) == expected_length and set(value) <= {"0", "1"}:
                self._diagnostic_mask = value
                self._cleared_bits = tuple(i for i, bit in enumerate(value, 1) if bit == "0")
                self._human_readable_log = (
                    f"{subject} autodiagnostic mask is {value}"
                    f" (cleared bits: {', '.join(map(str, self._cleared_bits)) or 'none'})."
                )
        elif (
            self._dimension == 23
            and self._scope == "central"
            and len(values) == 2
            and all(_WHO1004_COUNT_REGEX.fullmatch(v) for v in values)
        ):
            self._non_responding_units = int(values[0])
            self._faulty_units = int(values[1])
            self._human_readable_log = (
                f"{subject} reports {self._non_responding_units} non-responding unit(s)"
                f" and {self._faulty_units} faulty unit(s)."
            )

    @property
    def unique_id(self) -> str:
        """``1004-<full WHERE>`` (``1004-#0#2``, ``1004-#66#2``, ``1004-66#1``)."""
        return _who1004_unique_id(self._where, self._where_param)

    @property
    def scope(self) -> str | None:
        """``"central"``, ``"zone"``, ``"probe"``, ``"slave_probe"``, ``"external_probe"``, ``"actuator"`` or ``None``."""
        return self._scope

    @property
    def zone_number(self) -> int | None:
        """Zone 1..99 of a zone, probe, slave probe or actuator; ``None`` for a central unit, an external probe or an unrecognized WHERE."""
        return self._zone_number

    @property
    def probe_number(self) -> int | None:
        """Slave probe number ``N`` (1..8) of a ``NZZ`` WHERE, else ``None``."""
        return self._probe_number

    @property
    def actuator_number(self) -> int | None:
        """Actuator number ``N`` (1..9) of a ``Z#N`` WHERE, else ``None``."""
        return self._actuator_number

    @property
    def diagnostic_mask(self) -> str | None:
        """The 24-bit (DIMENSIONS 7, 8, 11, 12) or 16-bit (DIMENSIONS 21, 22) bitmask as sent, else ``None``."""
        return self._diagnostic_mask

    @property
    def cleared_bits(self) -> tuple[int, ...] | None:
        """1-based positions, from the left, of the mask's ``0`` bits (``()`` when all set)."""
        return self._cleared_bits

    @property
    def has_fault(self) -> bool | None:
        """True when the mask has a cleared bit, False when all bits are set, ``None`` without a mask."""
        return bool(self._cleared_bits) if self._cleared_bits is not None else None

    @property
    def non_responding_units(self) -> int | None:
        """First count of a central-unit DIMENSION 23 report (``*#1004*#0*23*NO_RESPONSE*FAULTS##``), else ``None``."""
        return self._non_responding_units

    @property
    def faulty_units(self) -> int | None:
        """Second count of a central-unit DIMENSION 23 report, else ``None``."""
        return self._faulty_units


def _validate_who1004_dimension(dimension: object, purpose: str) -> int:
    """Return ``dimension`` as one of the 24-bit mask DIMENSIONS 7, 8, 11, 12, else raise ``ValueError``."""
    if isinstance(dimension, bool) or not isinstance(dimension, (int, str)):
        raise ValueError(f"{purpose} needs a dimension of 7, 8, 11 or 12: {dimension!r}")
    try:
        value = int(dimension)
    except ValueError:
        raise ValueError(f"{purpose} needs a dimension of 7, 8, 11 or 12: {dimension!r}") from None
    if value not in _WHO1004_REQUEST_DIMENSIONS:
        raise ValueError(f"{purpose} needs a dimension of 7, 8, 11 or 12: {dimension!r}")
    return value


def _validate_who1004_device_where(where: object, purpose: str) -> str:
    """Return ``where`` stripped when it addresses a bus device of WHO 1004, else raise ``ValueError``.

    Accepted (``OPN_ThermoWhereTransl``): a master probe ``Z`` (1..99), a
    slave probe ``NZZ`` (101..899), an external probe ``[1-9]00`` and an
    actuator ``Z#N`` (``N`` 1..9). The central unit and the ``#Z`` zone
    forms are refused: they take ``request_central_diagnostic`` and
    ``request_zone_diagnostic``.
    """
    if isinstance(where, bool) or not isinstance(where, (int, str)):
        raise ValueError(f"{purpose} needs a device address Z, NZZ, N00 or Z#N: {where!r}")
    text = str(where).strip()
    if not _WHO1004_DEVICE_REGEX.fullmatch(text):
        raise ValueError(f"{purpose} needs a device address Z, NZZ, N00 or Z#N: {text!r}")
    return text


def _validate_who1004_zone_where(where: object, purpose: str) -> str:
    """Return the ``R21P0`` target: ``#0``, ``#0#C``, ``#Z`` or ``#Z#C`` (a bare zone 1..99 becomes ``#Z``)."""
    if isinstance(where, bool) or not isinstance(where, (int, str)):
        raise ValueError(f"{purpose} needs '#0', '#0#C', a zone 1..99, '#Z' or '#Z#C': {where!r}")
    text = str(where).strip()
    if _WHO1004_ZONE_REGEX.fullmatch(text):
        return f"#{text}"
    if _WHO4_CENTRAL_WHERE_REGEX.fullmatch(text) or _WHO1004_CENTRAL_ZONE_REGEX.fullmatch(text):
        return text
    raise ValueError(f"{purpose} needs '#0', '#0#C', a zone 1..99, '#Z' or '#Z#C': {text!r}")


class OWNHeatingDiagnosticCommand(OWNCommand):
    """WHO 1004 requests: thermoregulation autodiagnostic reads.

    Every builder emits one of the DIMENSION requests ``libdiag.so``
    registers for WHO 1004 (``OPN_OpenScsDiagTermoTr``: ``R7P0``, ``R8P0``,
    ``R11P0``, ``R12P0``, ``R20P0``, ``R21P0``, ``R23P0``; Encyclopedia
    Machine KB ``ownkb:chunk:r000204``-``r000209``). There is no ``R22P0``:
    DIMENSION 22 is pushed by the gateway only, so no builder emits
    ``*22##``. The replies are decoded by :class:`OWNHeatingDiagnosticEvent`.
    None of these frames has been replayed on the firmware oracle.
    """

    @property
    def unique_id(self) -> str:
        """``1004-<full WHERE>``, as :attr:`OWNHeatingDiagnosticEvent.unique_id`."""
        return _who1004_unique_id(self._where, self._where_param)

    @classmethod
    def request_central_diagnostic(
        cls, where: str = "#0", *, dimension: int = 7
    ) -> OWNHeatingDiagnosticCommand:
        """24-bit mask of the central unit: ``*#1004*#0*7##`` (``#0#C``; DIMENSION 7, 8, 11 or 12).

        DIMENSION 7 is the diagnostic mask ``ownkb:chunk:r000205`` documents
        for the request; 8, 11 and 12 are the other 24-bit masks
        ``libdiag.so`` answers (``R8P0``, ``R11P0``, ``R12P0``).
        """
        target = _validate_central_where(where, "Central unit diagnostic request")
        dim = _validate_who1004_dimension(dimension, "Central unit diagnostic request")
        message = cls(f"*#1004*{target}*{dim}##")
        message._human_readable_log = (
            f"Requesting autodiagnostic mask (dimension {dim}) of thermoregulation central unit {target}."
        )
        return message

    @classmethod
    def request_device_diagnostic(
        cls, where: int | str, *, dimension: int = 7
    ) -> OWNHeatingDiagnosticCommand:
        """24-bit mask of a bus device: ``*#1004*WHERE*7##`` (DIMENSION 7, 8, 11 or 12).

        WHERE is a master probe ``Z`` (1..99), a slave probe ``NZZ``
        (101..899), an external probe ``[1-9]00`` or an actuator ``Z#N``.
        """
        target = _validate_who1004_device_where(where, "Device diagnostic request")
        dim = _validate_who1004_dimension(dimension, "Device diagnostic request")
        message = cls(f"*#1004*{target}*{dim}##")
        message._human_readable_log = (
            f"Requesting autodiagnostic mask (dimension {dim}) of thermoregulation device {target}."
        )
        return message

    @classmethod
    def request_zones_with_failures(cls, where: str = "#0") -> OWNHeatingDiagnosticCommand:
        """Zones with failures: ``*#1004*#0*20##`` (``R20P0``; ``#0#C``).

        Answered with zero or more ``*#1004*#Z*21*<16-bit mask>##`` frames,
        one per faulty zone.
        """
        target = _validate_central_where(where, "Zones with failures request")
        message = cls(f"*#1004*{target}*20##")
        message._human_readable_log = f"Requesting zones with failures of thermoregulation central unit {target}."
        return message

    @classmethod
    def request_zone_diagnostic(cls, where: int | str = "#0") -> OWNHeatingDiagnosticCommand:
        """16-bit zone mask: ``*#1004*#Z*21##`` (``R21P0``).

        ``where`` is ``#0`` / ``#0#C`` (every zone of the central unit), a
        zone ``1..99`` (sent as ``#Z``), ``#Z`` or ``#Z#C``.
        """
        target = _validate_who1004_zone_where(where, "Zone diagnostic request")
        message = cls(f"*#1004*{target}*21##")
        message._human_readable_log = f"Requesting zone autodiagnostic mask of thermoregulation {target}."
        return message

    @classmethod
    def request_fault_counts(cls, where: str = "#0") -> OWNHeatingDiagnosticCommand:
        """Non-responding and faulty unit counts: ``*#1004*#0*23##`` (``R23P0``; ``#0#C``)."""
        target = _validate_central_where(where, "Fault counts request")
        message = cls(f"*#1004*{target}*23##")
        message._human_readable_log = f"Requesting fault counts of thermoregulation central unit {target}."
        return message


register_event_parser(1004, OWNHeatingDiagnosticEvent)
register_command_parser(1004, OWNHeatingDiagnosticCommand)
