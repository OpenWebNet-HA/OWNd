"""Regression tests for the MyHomeServer1 firmware findings in OWNd#77.

One test per finding. Each docstring names the source of the frames it uses:

* **Firmware**: gdluck ran the MyHomeServer1 translator programs on an emulated SCS
  bus and recorded whether a message produced a bus frame (OWNd#77, README and
  ``audit_myhome_ownd-20261002T083846-5835.zip``: ``au1.tsv`` .. ``au4.tsv``).
* **Emitted**: messages that firmware produces for a bus frame (OWNd#77 README).
* **Gateway**: read-only requests answered by a real MyHomeServer1, fw 3.1.8
  (``gateway_probe.txt`` in the same zip).
* **Capture**: frames recorded on a real plant, kept in the MyHOME repository under
  ``tests/fixtures/traces``.
* **Encyclopedia**: the official specification as recorded in the OpenWebNet
  Encyclopedia.

The frames are copied verbatim from those sources. Do not edit them.
"""

from __future__ import annotations

import datetime
import re
from pathlib import Path

import pytest

from OWNd.message import (
    CLIMATE_MODE_AUTO,
    CLIMATE_MODE_COOL,
    CLIMATE_MODE_HEAT,
    CLIMATE_MODE_OFF,
    OWNCenPlusCommand,
    OWNCENPlusEvent,
    OWNCommand,
    OWNDryContactCommand,
    OWNDryContactEvent,
    OWNEnergyCommand,
    OWNEvent,
    OWNHeatingCommand,
    OWNHeatingEvent,
    OWNLightingCommand,
    OWNMessage,
)
from OWNd.message import MESSAGE_TYPE_SEASON, SEASON_CONDITIONING, SEASON_HEATING  # OWNd#94

REPO_ROOT = Path(__file__).resolve().parents[1]


# ── Fix 1: central unit mode ────────────────────────────────────────────────


@pytest.mark.parametrize("where", ["#0", "#0#2"])
@pytest.mark.parametrize(
    ("mode", "what", "parsed_mode"),
    [
        (CLIMATE_MODE_OFF, 303, CLIMATE_MODE_OFF),
        (CLIMATE_MODE_HEAT, 1, None),
        (CLIMATE_MODE_COOL, 0, None),
        (CLIMATE_MODE_AUTO, 311, CLIMATE_MODE_AUTO),
        ("antifreeze", 102, CLIMATE_MODE_OFF),
        ("protection", 302, CLIMATE_MODE_OFF),
    ],
)
def test_fix1_central_mode_uses_the_who4_what_table(
    where: str, mode: str, what: int, parsed_mode: str | None
) -> None:
    """Central-unit modes use WHAT 303 / 1 / 0 / 311 / 102 / 302.

    Firmware: 303, 1, 0, 311 and 102 produce a bus frame for ``#0`` and ``#0#2``;
    the old 100 / 101 / 110 produce none, and the old 102 (cool), 103 and 111
    are forwarded but mean something else.
    BTicino client (libqtdevices TS10_1_0_23 ``thermal_device.cpp`` and
    ``test/test_thermal_device.cpp``): the central unit is sent ``*4*303*#0##``
    (off), ``*4*1*#0##`` (winter), ``*4*0*#0##`` (summer) and ``*4*302*#0##``
    (protection). Its enum names 102 winter protection, 202 summer protection
    and 302 generic protection, so "protection" is 302: 202 would also switch
    the plant to summer.
    Encyclopedia: ``functional/who-4-temperature-control/what.md`` lists 0 cooling,
    1 heating, 102 antifreeze, 202 thermal protection, 303 OFF generic and
    311 automatic generic.
    Not verified: how a physical central unit reacts to them.

    OWNd's own parser must read each frame back as the mode that was asked for
    (antifreeze and protection are shown as off). WHAT 1 / 0 are the season
    frames: they come back as ``season`` heating / conditioning with no
    operating mode (Legrand WHO 4 v2.0.0 p. 5, 13, 63).
    """
    command = OWNHeatingCommand.set_central_mode(where, mode)

    assert str(command) == f"*4*{what}*{where}##"
    event = OWNHeatingEvent(str(command))
    assert event.mode == parsed_mode
    if what in (1, 0):
        assert event.message_type == MESSAGE_TYPE_SEASON
        assert event.season == (SEASON_HEATING if what == 1 else SEASON_CONDITIONING)


def test_fix1_captured_central_unit_mode_parses_as_cooling() -> None:
    """Capture: a MyHomeServer1 plant switched to summer mode reported ``*4*0*#0##``.

    MyHOME ``tests/fixtures/traces/issue_453/myhome_trace_MyHomeServer1_all_2026-09-25T19-40-15.json``
    (MyHOME#453, @nicolacavallo84): WHAT 0 is the mode the builder now sends for "cool".
    """
    event = OWNHeatingEvent("*4*0*#0##")

    assert event.message_type == MESSAGE_TYPE_SEASON
    assert event.season == SEASON_CONDITIONING
    assert event.mode is None
    assert str(OWNHeatingCommand.set_central_mode("#0", CLIMATE_MODE_COOL)) == "*4*0*#0##"


# ── Fix 2: fan speed ────────────────────────────────────────────────────────


@pytest.mark.parametrize("speed", [0, 1, 2, 3])
@pytest.mark.parametrize("zone", [1, 99])
def test_fix2_fan_speed_uses_the_plain_zone(zone: int, speed: int) -> None:
    """Firmware: ``*#4*1*#11*0##`` .. ``*#4*1*#11*3##`` and zone 99 produce a bus frame.

    The ``#Z`` form (``*#4*#1*#11*1##``) produces none, so a zone managed by a
    central unit must still be written as the plain zone.
    Encyclopedia: speed is 0 automatic or 1..3.
    """
    expected = f"*#4*{zone}*#11*{speed}##"

    assert str(OWNHeatingCommand.set_fan_speed(zone, speed)) == expected
    assert str(OWNHeatingCommand.set_fan_speed(str(zone), speed)) == expected
    assert str(OWNHeatingCommand.set_fan_speed(f"#{zone}", speed)) == expected
    assert str(OWNHeatingCommand.set_fan_speed(f"#{zone:02d}", speed)) == expected
    assert str(OWNHeatingCommand.set_fan_speed(zone, speed, standalone=True)) == expected


@pytest.mark.parametrize("where", ["#0", "#0#2", "0", 0])
def test_fix2_fan_speed_refuses_central_unit_addresses(where: str | int) -> None:
    """Firmware: ``*#4*#0*#11*1##`` and ``*#4*#0#2*#11*1##`` produce no bus frame."""
    with pytest.raises(ValueError, match="central unit or general zone"):
        OWNHeatingCommand.set_fan_speed(where, 1)


@pytest.mark.parametrize("speed", [4, 15, -1])
def test_fix2_fan_speed_refuses_speeds_outside_0_to_3(speed: int) -> None:
    """Firmware: ``*#4*1*#11*4##`` produces no bus frame."""
    with pytest.raises(ValueError, match="Invalid fan speed"):
        OWNHeatingCommand.set_fan_speed(1, speed)


def test_fix2_fan_speed_refuses_input_that_is_not_a_zone_or_speed() -> None:
    """Code: the builder raises ValueError instead of building a frame from bad input."""
    with pytest.raises(ValueError, match="Invalid zone number"):
        OWNHeatingCommand.set_fan_speed(100, 1)
    with pytest.raises(ValueError, match="Invalid zone address"):
        OWNHeatingCommand.set_fan_speed("invalid", 1)
    with pytest.raises(ValueError, match="Invalid fan speed"):
        OWNHeatingCommand.set_fan_speed(1, "invalid")  # type: ignore[arg-type]


@pytest.mark.parametrize("where", ["#23#1", "23#1", "#23#2"])
def test_fix2_fan_speed_takes_the_zone_from_the_first_field(where: str) -> None:
    """BTicino client: a probe addressed ``#23#1`` sets its fan coil as zone 23.

    libqtdevices TS10_1_0_23 ``ControlledProbeDevice::setFancoilSpeed`` writes
    the plain zone, test ``sendSetFancoilSpeed``: ``*#4*23*#11*3##``. Taking the
    last ``#`` field instead built zone 1 (review of OWNd#82, finding 3).
    """
    assert str(OWNHeatingCommand.set_fan_speed(where, 3)) == "*#4*23*#11*3##"


@pytest.mark.parametrize("where", ["#23#1", "23#1"])
def test_zone_builders_preserve_compound_probe_addresses(where: str) -> None:
    """BTicino client: set_mode and set_temperature preserve the full address for compound probes.

    libqtdevices TS10_1_0_23 test_probe_device.cpp (line 111, ControlledProbeDevice("23#1", ...))
    expects:
    - fan speed (line 139): *#4*23*#11*3## (plain zone)
    - automatic (line 132): *4*311*#23#1## (full address)
    - manual setpoint (line 125): *#4*#23#1*#14*0250*3## (full address)
    """
    assert str(OWNHeatingCommand.set_fan_speed(where, 3)) == "*#4*23*#11*3##"
    assert str(OWNHeatingCommand.set_mode(where, CLIMATE_MODE_OFF)) == "*4*303*#23#1##"
    assert str(OWNHeatingCommand.set_mode(where, CLIMATE_MODE_OFF, standalone=True)) == "*4*303*#23#1##"
    assert str(OWNHeatingCommand.set_mode(where, CLIMATE_MODE_AUTO, standalone=True)) == "*4*311*#23#1##"
    assert (
        str(OWNHeatingCommand.set_temperature(where, 21.0, CLIMATE_MODE_HEAT))
        == "*#4*#23#1*#14*0210*1##"
    )
    assert (
        str(OWNHeatingCommand.set_temperature(where, 21.0, CLIMATE_MODE_HEAT, standalone=True))
        == "*#4*#23#1*#14*0210*1##"
    )


def test_zone_builders_simple_zone_addresses() -> None:
    """Simple zone addresses build standard plain or # frames."""
    assert str(OWNHeatingCommand.set_mode("#23", CLIMATE_MODE_OFF)) == "*4*303*#23##"
    assert str(OWNHeatingCommand.set_mode("23", CLIMATE_MODE_OFF, standalone=True)) == "*4*303*23##"
    assert str(OWNHeatingCommand.set_mode("23", CLIMATE_MODE_AUTO, standalone=True)) == "*4*311*#23##"
    assert (
        str(OWNHeatingCommand.set_temperature("#23", 21.0, CLIMATE_MODE_HEAT))
        == "*#4*#23*#14*0210*1##"
    )
    assert (
        str(OWNHeatingCommand.set_temperature("23", 21.0, CLIMATE_MODE_HEAT, standalone=True))
        == "*#4*23*#14*0210*1##"
    )


@pytest.mark.parametrize(
    "bad_where",
    ["##23", "invalid", "-1", "#23#invalid", "#23#-1", "23#1#2", ""],
)
def test_zone_builders_refuse_invalid_addresses(bad_where: str) -> None:
    """Code: set_mode, set_temperature and set_fan_speed reject malformed addresses."""
    with pytest.raises(ValueError, match="Invalid zone address"):
        OWNHeatingCommand.set_mode(bad_where, CLIMATE_MODE_OFF)
    with pytest.raises(ValueError, match="Invalid zone address"):
        OWNHeatingCommand.set_temperature(bad_where, 21.0, CLIMATE_MODE_HEAT)
    with pytest.raises(ValueError, match="Invalid zone address"):
        OWNHeatingCommand.set_fan_speed(bad_where, 1)


def test_central_status_is_deprecated_and_unchanged() -> None:
    """Capture + Gateway: gateways refuse ``*#4*#0*14##``; ``*#4*#0##`` is answered.

    An F454 answered ``*#4*#0##`` within 0.13 s and nothing for dimension 14
    (MyHOME#629); a real MyHomeServer1 3.1.8 refuses ``*#4*#0*14##`` (gateway
    probe). central_status() keeps its frame for existing callers but warns.
    """
    with pytest.warns(DeprecationWarning, match=r"use OWNHeatingCommand\.status"):
        command = OWNHeatingCommand.central_status("#0")

    assert str(command) == "*#4*#0*14##"
    assert str(OWNHeatingCommand.status("#0")) == "*#4*#0##"


# ── Fix 3: AUTO on a standalone zone ────────────────────────────────────────


def test_fix3_auto_is_always_built_for_the_hash_zone() -> None:
    """Firmware: ``*4*311*1##`` produces no bus frame; ``*4*311*#1##`` does.

    So AUTO is built as ``#Z`` even for a zone flagged standalone. MyHOME flags
    every zone that is not a central unit standalone by default, so returning
    None here would drop AUTO for zones that do run under a central unit.
    BTicino client (libqtdevices TS10_1_0_23 ``ControlledProbeDevice::setAutomatic``,
    test ``sendSetAutomatic``): ``*4*311*#23#1##``, the ``#`` form.
    ``*4*303*1##`` (off) works in the plain form, so off still follows ``standalone``.
    Encyclopedia: automatic mode is commanded through the central unit,
    ``*4*311*#WHERE##``.
    """
    assert str(OWNHeatingCommand.set_mode("1", CLIMATE_MODE_AUTO, standalone=True)) == "*4*311*#1##"
    assert str(OWNHeatingCommand.set_mode("1", CLIMATE_MODE_AUTO)) == "*4*311*#1##"
    assert str(OWNHeatingCommand.set_mode("#0", CLIMATE_MODE_AUTO, standalone=True)) == "*4*311*#0##"
    assert str(OWNHeatingCommand.set_mode("1", CLIMATE_MODE_OFF, standalone=True)) == "*4*303*1##"


# ── Fix 4: actuator status without an actuator number ──────────────────────


@pytest.mark.parametrize("frame", ["*#4*#0*20*0##", "*#4*100*20*0##"])
def test_fix4_actuator_status_without_actuator_falls_back_to_actuator_1(
    frame: str,
) -> None:
    """Emitted: the firmware sends dimension 20 without ``#actuator`` (141 messages).

    Before the fix these raised IndexError and the event session dropped them.
    """
    event = OWNEvent.parse(frame)

    assert isinstance(event, OWNHeatingEvent)
    assert event._actuator == "1"
    assert event.is_active() is False


def test_fix4_captured_actuator_status_keeps_its_actuator() -> None:
    """Capture: ``*#4*1#1*20*1##`` (MyHOME#466 MH200N sweep and others) names actuator 1."""
    event = OWNHeatingEvent("*#4*1#1*20*1##")

    assert event._actuator == "1"
    assert event.is_active() is True


# ── Fix 5: valve status with an empty field ────────────────────────────────


@pytest.mark.parametrize("frame", ["*#4*40*19**0##", "*#4*40*19*1*##"])
def test_fix5_valve_status_with_an_empty_field_is_not_decoded(frame: str) -> None:
    """Emitted: the firmware prints an empty field for a status byte outside its table.

    Before the fix ``int("")`` raised ValueError and the frame was dropped.
    """
    event = OWNEvent.parse(frame)

    assert isinstance(event, OWNHeatingEvent)
    assert event.is_active() is None


def test_fix5_gateway_valve_status_is_still_decoded() -> None:
    """Gateway: ``*#4*41*19##`` was answered with ``*#4*41*19*0*0##``."""
    event = OWNHeatingEvent("*#4*41*19*0*0##")

    assert event.is_active() is False
    assert event._is_cooling is False
    assert event._is_heating is False


# ── Fix 6: dimension requests with parameters ──────────────────────────────


@pytest.mark.parametrize(
    ("frame", "dimension", "params"),
    [
        ("*#18*51*511#10#1##", 511, ["10", "1"]),
        ("*#18*51*511#10#2##", 511, ["10", "2"]),
        ("*#18*51*52#26#9##", 52, ["26", "9"]),
    ],
)
def test_fix6_dimension_request_with_parameters_parses(
    frame: str, dimension: int, params: list[str]
) -> None:
    """Gateway: the real gateway accepted ``*#18*51*511#10#1##`` and ``*#18*51*52#26#9##``.

    Encyclopedia: requests are ``*#18*WHERE*511#M#D##`` and ``*#18*WHERE*52#Y#M##``.
    """
    message = OWNMessage.parse(frame)

    assert isinstance(message, OWNEnergyCommand)
    assert message.is_valid
    assert message.who == 18
    assert message.dimension == dimension
    assert message._dimension_param == params
    assert isinstance(OWNCommand.parse(frame), OWNEnergyCommand)


def test_fix6_energy_history_builders_build_valid_requests() -> None:
    """Code: OWNd could not parse the two requests its own builders produce."""
    hourly = OWNEnergyCommand.get_hourly_consumption("51", datetime.date.today())
    monthly = OWNEnergyCommand.get_monthly_consumption("51", 2026, 9)

    assert hourly is not None
    assert hourly.is_valid and hourly.who == 18 and hourly.dimension == 511
    assert str(monthly) == "*#18*51*52#26#9##"
    assert monthly.is_valid and monthly.who == 18 and monthly.dimension == 52


# ── Fix 7: brightness 0 ─────────────────────────────────────────────────────


@pytest.mark.parametrize(
    ("transition", "frame"),
    [(0, "*1*0*31##"), (1, "*1*0#1*31##"), (5, "*1*0#5*31##"), (255, "*1*0#255*31##")],
)
def test_fix7_brightness_0_switches_off(transition: int, frame: str) -> None:
    """Firmware: ``*#1*31*#1*100*0##`` / ``*100*5##`` produce no bus frame.

    ``*1*0*31##``, ``*1*0#1*31##``, ``*1*0#5*31##`` and ``*1*0#255*31##`` do
    (``au1.tsv``, ``au4.tsv`` and the OWNd#77 README).
    """
    assert str(OWNLightingCommand.set_brightness("31", 0, transition)) == frame


@pytest.mark.parametrize("level", range(-5, 121))
def test_fix7_brightness_never_writes_level_100(level: int) -> None:
    """Firmware: level 100 is refused; ``*#1*31*#1*101*0##`` and ``*#1*31*#1*150*5##`` work."""
    frame = str(OWNLightingCommand.set_brightness("31", level, 5))

    assert "*#1*31*#1*100*" not in frame
    if level > 0:
        assert frame == f"*#1*31*#1*{min(level, 100) + 100}*5##"


@pytest.mark.parametrize(
    ("level", "transition", "logged"),
    [
        (120, 0, "brightness to 100% (requested 120%)."),
        (120, 5, "brightness to 100% (requested 120%) with transition speed 5."),
        (100, 0, "brightness to 100%."),
        (50, 0, "brightness to 50%."),
    ],
)
def test_fix7_log_shows_the_level_that_is_sent(level: int, transition: int, logged: str) -> None:
    """Code: a capped level is logged as sent, with the request alongside (review of OWNd#82, finding 5)."""
    command = OWNLightingCommand.set_brightness("31", level, transition)

    assert command.human_readable_log.endswith(logged)


# ── Fix 8: interface for WHO 0 and WHO 14 ───────────────────────────────────


@pytest.mark.parametrize("frame", ["*0*1*31#4#01##", "*14*0*31#4#01##"])
def test_fix8_interface_is_read_for_scenarios_and_who14(frame: str) -> None:
    """Firmware: both route through interface 01 like a light does.

    Encyclopedia (WHO 0): ``01..99#4#I`` is a scenario module on a local bus, and
    the interface is part of the address.
    """
    on_01 = OWNEvent.parse(frame)
    on_02 = OWNEvent.parse(frame.replace("#4#01", "#4#02"))

    assert on_01 is not None and on_02 is not None
    assert on_01.interface == "01"
    assert on_01.unique_id != on_02.unique_id


# ── Fix 9: other WHO 25 messages ────────────────────────────────────────────


@pytest.mark.parametrize("frame", ["*25*11#121*10##", "*25*12*131##"])
def test_fix9_other_who25_messages_are_not_dry_contacts(frame: str) -> None:
    """Emitted: the firmware sends WHAT 11..15 on ``1xx`` addresses.

    Encyclopedia: dry contacts are WHAT 31 and 32 only.
    """
    event = OWNEvent.parse(frame)

    assert type(event) is OWNEvent
    assert not isinstance(event, OWNDryContactEvent)


@pytest.mark.parametrize(
    ("frame", "cls"),
    [
        ("*25*31#1*339##", OWNDryContactEvent),
        ("*25*32#1*33##", OWNDryContactEvent),
        ("*25*21#1*21##", OWNCENPlusEvent),
        ("*25*23#8*233##", OWNCENPlusEvent),
    ],
)
def test_fix9_captured_who25_messages_keep_their_class(frame: str, cls: type) -> None:
    """Capture: WHO 25 frames from the MyHOME trace fixtures (MyHOME#453, #466)."""
    assert isinstance(OWNEvent.parse(frame), cls)


@pytest.mark.parametrize(
    ("frame", "cls"),
    [
        ("*25*11#121*10##", OWNCommand),
        ("*25*12*131##", OWNCommand),
        ("*25*31#1*339##", OWNDryContactCommand),
        ("*25*32#1*33##", OWNDryContactCommand),
        ("*#25*331##", OWNDryContactCommand),
        ("*25*21#1*21##", OWNCenPlusCommand),
        ("*25*bad*21##", OWNDryContactCommand),
    ],
)
def test_fix9_command_parser_uses_the_same_who25_rule(frame: str, cls: type) -> None:
    """Code: the command parser follows the event parser (review of OWNd#82, finding 4).

    Only WHAT 31/32 (and ``*#25*`` status requests) are dry contacts; 21..28 are
    CEN+; any other numeric WHAT is a plain command. A WHAT that is not a number
    stays a dry contact, as in the event parser.
    """
    command = OWNCommand.parse(frame)

    assert type(command) is cls


# ── Fix 10: conformance matrix ──────────────────────────────────────────────

_MATRIX = REPO_ROOT / "docs" / "protocol_conformance_matrix.md"

# Firmware (au1.tsv, au2.own) and Gateway: each of these is refused.
_REFUSED_EXAMPLES = [
    "*2*1*21#4#1##",
    "*#1*1*#1*20##",
    "*#2*1*#1*50##",
    "*#18*51*52##",
    "*25*21*0001##",
    "*25*22*0001##",
    "*25*23*0001##",
    "*15*01*0001##",
    "*15*01#1*0001##",
    "*15*01#2*0001##",
    "*15*01#3*0001##",
]


def _matrix_frames() -> list[str]:
    rows = [
        line
        for line in _MATRIX.read_text(encoding="utf-8").splitlines()
        if line.startswith("| **")
    ]
    return [frame for row in rows for frame in re.findall(r"`(\*[^`]*##)`", row)]


def test_fix10_matrix_lists_no_frame_the_firmware_refuses() -> None:
    """Firmware / Gateway: the six examples flagged in OWNd#77 are refused."""
    frames = _matrix_frames()

    assert frames
    assert not set(frames) & set(_REFUSED_EXAMPLES)


def test_fix10_matrix_examples_all_parse() -> None:
    """Code: every example in the matrix is a frame OWNd can parse."""
    for frame in _matrix_frames():
        if frame in ("*#*1##", "*#*0##"):
            continue
        message = OWNMessage.parse(frame)
        assert message is not None, frame
        assert message.is_valid, frame


# ── Libqtdevices TS10_1_0_23 parity tests ─────────────────────────────────────


def test_libqtdevices_probe_device_commands() -> None:
    """Test parity with NonControlledProbeDevice and ControlledProbeDevice."""
    # NonControlledProbeDevice: status request for internal probe vs external probe (sensor 1)
    assert str(OWNHeatingCommand.get_probe_temperature("11")) == "*#4*11*15##"
    assert str(OWNHeatingCommand.get_probe_temperature("11", sensor=1)) == "*#4*11*15#1##"

    with pytest.raises(ValueError, match="Invalid sensor number"):
        OWNHeatingCommand.get_probe_temperature("11", sensor="invalid")  # type: ignore[arg-type]
    with pytest.raises(ValueError, match="Invalid sensor number"):
        OWNHeatingCommand.get_probe_temperature("11", sensor=0)

    # ControlledProbeDevice::requestFancoilStatus: *#4*ZONE*11##
    assert str(OWNHeatingCommand.get_fan_speed("23")) == "*#4*23*11##"
    assert str(OWNHeatingCommand.get_fan_speed(1)) == "*#4*1*11##"
    assert str(OWNHeatingCommand.get_fan_speed("#23#1")) == "*#4*23*11##"

    with pytest.raises(ValueError, match="central unit or general zone"):
        OWNHeatingCommand.get_fan_speed("#0")
    with pytest.raises(ValueError, match="central unit or general zone"):
        OWNHeatingCommand.get_fan_speed("0")
    with pytest.raises(ValueError, match="central unit or general zone"):
        OWNHeatingCommand.get_fan_speed("#0#1")
    with pytest.raises(ValueError, match="Invalid zone address"):
        OWNHeatingCommand.get_fan_speed("invalid")
    with pytest.raises(ValueError, match="Invalid zone number"):
        OWNHeatingCommand.get_fan_speed(100)

    # ControlledProbeDevice::setProtection / setOff / setAutomatic
    assert str(OWNHeatingCommand.set_mode("1", "protection", standalone=True)) == "*4*302*#1##"
    assert str(OWNHeatingCommand.set_mode("#1", "protection")) == "*4*302*#1##"
    assert str(OWNHeatingCommand.set_mode("#23#1", "protection")) == "*4*302*#23#1##"
    assert str(OWNHeatingCommand.set_protection("1", "protection")) == "*4*302*#1##"
    assert str(OWNHeatingCommand.set_mode("1", "antifreeze", standalone=True)) == "*4*102*#1##"
    assert str(OWNHeatingCommand.set_mode("1", "thermal_protection", standalone=True)) == "*4*202*#1##"
    assert OWNHeatingCommand.set_mode("1", "unknown_mode") is None


def test_libqtdevices_thermal_device_commands() -> None:
    """Test parity with ThermalDevice (4-zone and 99-zone central units)."""
    # Weekly program selection: *4*31PP*#0##
    assert str(OWNHeatingCommand.set_central_program("#0", 13)) == "*4*3113*#0##"
    with pytest.raises(ValueError, match="Invalid program number"):
        OWNHeatingCommand.set_central_program("#0", "invalid")  # type: ignore[arg-type]
    with pytest.raises(ValueError, match="Program must be 1..16"):
        OWNHeatingCommand.set_central_program("#0", 0)
    with pytest.raises(ValueError, match="Program must be 1..16"):
        OWNHeatingCommand.set_central_program("#0", 17)

    # Preset scenario selection (99-zone): *4*32SS*#0##
    assert str(OWNHeatingCommand.set_central_scenario("#0", 12)) == "*4*3212*#0##"
    with pytest.raises(ValueError, match="Invalid scenario number"):
        OWNHeatingCommand.set_central_scenario("#0", "invalid")  # type: ignore[arg-type]
    with pytest.raises(ValueError, match="Scenario must be 1..16"):
        OWNHeatingCommand.set_central_scenario("#0", 0)
    with pytest.raises(ValueError, match="Scenario must be 1..16"):
        OWNHeatingCommand.set_central_scenario("#0", 17)

    # Timed manual (4-zone): *4*312#TTTT#H*#0##
    assert str(OWNHeatingCommand.set_timed_manual("#0", 20.0, hours=2)) == "*4*312#0200#2*#0##"
    assert str(OWNHeatingCommand.set_timed_manual("#23#1", 21.5, hours=3)) == "*4*312#0215#3*#23#1##"
    assert str(OWNHeatingCommand.set_timed_manual("1", 2.0, hours=1, standalone=True)) == "*4*312#0050#1*1##"
    assert str(OWNHeatingCommand.set_timed_manual("1", 50.0, hours=1)) == "*4*312#0400#1*#1##"
    with pytest.raises(ValueError, match="Invalid duration hours"):
        OWNHeatingCommand.set_timed_manual("1", 20.0, hours="invalid")  # type: ignore[arg-type]
    with pytest.raises(ValueError, match="Hours must be 1..24"):
        OWNHeatingCommand.set_timed_manual("1", 20.0, hours=0)
    with pytest.raises(ValueError, match="Hours must be 1..24"):
        OWNHeatingCommand.set_timed_manual("1", 20.0, hours=25)

    # Weekend mode: *4*315#31PP*#0##
    assert str(OWNHeatingCommand.set_central_weekend("#0", 12)) == "*4*315#3112*#0##"
    with pytest.raises(ValueError, match="Invalid program number"):
        OWNHeatingCommand.set_central_weekend("#0", "invalid")  # type: ignore[arg-type]
    with pytest.raises(ValueError, match="Program must be 1..16"):
        OWNHeatingCommand.set_central_weekend("#0", 0)
    with pytest.raises(ValueError, match="Program must be 1..16"):
        OWNHeatingCommand.set_central_weekend("#0", 17)

    # Holiday mode: *4*33DDD#31PP*#0##
    assert str(OWNHeatingCommand.set_central_holiday("#0", days=2, program=15)) == "*4*33002#3115*#0##"
    with pytest.raises(ValueError, match="Invalid holiday days"):
        OWNHeatingCommand.set_central_holiday("#0", days="invalid", program=1)  # type: ignore[arg-type]
    with pytest.raises(ValueError, match="Days must be 1..255"):
        OWNHeatingCommand.set_central_holiday("#0", days=0, program=1)
    with pytest.raises(ValueError, match="Days must be 1..255"):
        OWNHeatingCommand.set_central_holiday("#0", days=256, program=1)
    with pytest.raises(ValueError, match="Invalid program number"):
        OWNHeatingCommand.set_central_holiday("#0", days=2, program="invalid")  # type: ignore[arg-type]
    with pytest.raises(ValueError, match="Program must be 1..16"):
        OWNHeatingCommand.set_central_holiday("#0", days=2, program=0)
    with pytest.raises(ValueError, match="Program must be 1..16"):
        OWNHeatingCommand.set_central_holiday("#0", days=2, program=17)

    # Dimensions 30, 31, 32 write frames
    assert str(OWNHeatingCommand.set_holiday_end_date("#0", 29, 8, 2012)) == "*#4*#0*#30*29*08*2012##"
    with pytest.raises(ValueError, match="Invalid date"):
        OWNHeatingCommand.set_holiday_end_date("#0", "bad", 1, 2026)  # type: ignore[arg-type]
    with pytest.raises(ValueError, match="Invalid date values"):
        OWNHeatingCommand.set_holiday_end_date("#0", 32, 1, 2026)

    assert str(OWNHeatingCommand.set_holiday_end_time("#0", 23, 8)) == "*#4*#0*#31*23*08##"
    with pytest.raises(ValueError, match="Invalid time"):
        OWNHeatingCommand.set_holiday_end_time("#0", "bad", 1)  # type: ignore[arg-type]
    with pytest.raises(ValueError, match="Invalid time values"):
        OWNHeatingCommand.set_holiday_end_time("#0", 25, 0)

    assert str(OWNHeatingCommand.set_timed_manual_end_time("#0", 13, 5)) == "*#4*#0*#32*13*05##"
    with pytest.raises(ValueError, match="Invalid time"):
        OWNHeatingCommand.set_timed_manual_end_time("#0", "bad", 1)  # type: ignore[arg-type]
    with pytest.raises(ValueError, match="Invalid time values"):
        OWNHeatingCommand.set_timed_manual_end_time("#0", 25, 0)


def test_libqtdevices_thermal_device_event_and_write_parsing() -> None:
    """Test OWNHeatingEvent and OWNHeatingCommand parsing of libqtdevices frames."""
    # Holiday date event: *#4*#0*30*29*08*2012##
    evt_date = OWNEvent.parse("*#4*#0*30*29*08*2012##")
    assert isinstance(evt_date, OWNHeatingEvent)
    assert evt_date.holiday_end_date == (29, 8, 2012)
    assert "29/08/2012" in evt_date.human_readable_log

    # Holiday time event: *#4*#0*31*23*08##
    evt_time = OWNEvent.parse("*#4*#0*31*23*08##")
    assert isinstance(evt_time, OWNHeatingEvent)
    assert evt_time.holiday_end_time == (23, 8)
    assert "23:08" in evt_time.human_readable_log

    # Timed manual duration event: *#4*#0*32*24*59##
    evt_dur = OWNEvent.parse("*#4*#0*32*24*59##")
    assert isinstance(evt_dur, OWNHeatingEvent)
    assert evt_dur.manual_timed_duration == (24, 59)
    assert "24h 59m" in evt_dur.human_readable_log

    # Default event has None for holiday/duration properties
    evt_plain = OWNHeatingEvent("*#4*1*0*0215##")
    assert evt_plain.holiday_end_date is None
    assert evt_plain.holiday_end_time is None
    assert evt_plain.manual_timed_duration is None

    # Dimension writing logs in OWNHeatingCommand
    cmd_date = OWNHeatingCommand("*#4*#0*#30*29*08*2012##")
    assert "holiday end date to 29/08/2012" in cmd_date.human_readable_log

    cmd_time = OWNHeatingCommand("*#4*#0*#31*23*08##")
    assert "holiday end time to 23:08" in cmd_time.human_readable_log

    cmd_dur = OWNHeatingCommand("*#4*#0*#32*13*05##")
    assert "timed manual duration to 13h 05m" in cmd_dur.human_readable_log

    # Event mode parsing for timed manual, programs, scenarios, holiday
    assert OWNHeatingEvent("*4*212*#0##").mode == CLIMATE_MODE_COOL
    assert OWNHeatingEvent("*4*112*#0##").mode == CLIMATE_MODE_HEAT
    assert OWNHeatingEvent("*4*312*#0##").mode == CLIMATE_MODE_AUTO
    assert OWNHeatingEvent("*4*3113*#0##").mode == CLIMATE_MODE_AUTO
    assert OWNHeatingEvent("*4*3212*#0##").mode == CLIMATE_MODE_AUTO
    assert OWNHeatingEvent("*4*33002*#0##").mode == CLIMATE_MODE_AUTO

