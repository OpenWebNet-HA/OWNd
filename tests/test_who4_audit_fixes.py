"""WHO 4 fixes from the Encyclopedia audit (report 21, rows H1..H19).

Sources: ``encyclopedia_functional/who-4-temperature-control/addressing.md``
("Published functional WHERE forms", "MyHOME_Suite address rules", "Actuator
addressing", "Historical central-unit variants"), ``what.md`` ("Basic
operating states", "Protection and OFF states", "Manual and programmed
operation", "Vacation, program and scenario forms", "Zone setup commands")
and ``dimensions.md`` ("DIMENSION 11", "DIMENSION 12", "Historical
external-probe DIMENSION 15", "DIMENSION 19", "DIMENSION 20", "DIMENSION 22",
"DIMENSION 30"); the firmware oracle rows recorded in ORACLE_CONFIRM.md for
H1, H2, H3, H18 and H19 (``*4*303*#0#1##`` -> central-unit telegram with
selector byte 01; ``*#4*001*0##`` -> probes 1..8 of zone 1 where ``*#4*1*0##``
-> probe 0; ``*4*303*0##`` NACKed on 12/12; 31 February NACKed on 12/12;
``#105`` refused or forwarded with a zone byte no documented zone has).
DIMENSION 19 values 14 / 15 / 16 (H8) and the three-digit DIMENSION 15 value
(H16) are functional-page-only evidence (ENCY_CONFIRM TC-H8, TC-H16).
"""

from __future__ import annotations

import pytest

from OWNd.message import (
    CLIMATE_MODE_AUTO,
    CLIMATE_MODE_COOL,
    CLIMATE_MODE_HEAT,
    CLIMATE_MODE_OFF,
    MESSAGE_TYPE_ACTION,
    MESSAGE_TYPE_FAN_SPEED,
    MESSAGE_TYPE_MAIN_HUMIDITY,
    MESSAGE_TYPE_MAIN_TEMPERATURE,
    MESSAGE_TYPE_MODE,
    MESSAGE_TYPE_MODE_TARGET,
    MESSAGE_TYPE_SEASON,
    MESSAGE_TYPE_SECONDARY_TEMPERATURE,
    MESSAGE_TYPE_SPLIT_CONTROL,
    MESSAGE_TYPE_TARGET_TEMPERATURE,
    OPERATING_MODE_ANTIFREEZE,
    OPERATING_MODE_AUTOMATIC,
    OPERATING_MODE_CANCEL_VACATION,
    OPERATING_MODE_HOLIDAY,
    OPERATING_MODE_MANUAL,
    OPERATING_MODE_OFF,
    OPERATING_MODE_PROGRAM,
    OPERATING_MODE_PROTECTION,
    OPERATING_MODE_RESTORE_LAST_PROGRAM,
    OPERATING_MODE_RESTORE_LAST_SCENARIO,
    OPERATING_MODE_SCENARIO,
    OPERATING_MODE_THERMAL_PROTECTION,
    OPERATING_MODE_TIMED_MANUAL,
    OPERATING_MODE_VACATION,
    SCOPE_ACTUATOR,
    SCOPE_ALL_PROBES,
    SCOPE_CENTRAL,
    SCOPE_EXTERNAL_PROBE,
    SCOPE_MASTER_PROBE,
    SCOPE_SLAVE_PROBE,
    SCOPE_SPLIT_UNIT,
    SCOPE_ZONE_VIA_CENTRAL,
    SEASON_CONDITIONING,
    SEASON_HEATING,
    SPLIT_FAN_MEDIUM,
    SPLIT_FAN_MINIMUM,
    SPLIT_MODE_FAN,
    SPLIT_MODE_OFF,
    SPLIT_MODE_WINTER,
    OWNEvent,
    OWNHeatingCommand,
    OWNHeatingEvent,
    OWNMessage,
)


def _event(frame: str) -> OWNHeatingEvent:
    message = OWNMessage.parse(frame)
    assert isinstance(message, OWNHeatingEvent), frame
    return message


# ---------------------------------------------------------------- H1: #0#C is the central unit C


@pytest.mark.parametrize(
    ("frame", "central_unit", "message_type"),
    [
        ("*4*1*#0#2##", 2, MESSAGE_TYPE_SEASON),
        ("*4*303*#0#1##", 1, MESSAGE_TYPE_MODE),
        ("*#4*#0#2*14*0205*1##", 2, MESSAGE_TYPE_TARGET_TEMPERATURE),
        ("*#4*#0#2*14*#0200*1##", 2, MESSAGE_TYPE_TARGET_TEMPERATURE),
        ("*4*1*#0##", None, MESSAGE_TYPE_SEASON),
    ],
)
def test_h1_four_zone_central_unit_is_not_zone_c(
    frame: str, central_unit: int | None, message_type: str
) -> None:
    event = _event(frame)
    assert event.scope == SCOPE_CENTRAL
    assert event.central_unit == central_unit
    # ``zone`` keeps the selector ``C`` (MyHOME routes ``#0#C`` on it);
    # the central-unit identity is ``scope`` / ``central_unit`` / ``unique_id``.
    assert event.zone == (central_unit or 0)
    assert event.zone_number is None
    assert event.message_type == message_type
    assert event.human_readable_log.startswith(f"Central unit {event.address}")


def test_h1_unique_id_distinguishes_the_central_units() -> None:
    ids = {_event(f"*4*303*{where}##").unique_id for where in ("#0", "#0#1", "#0#2")}
    assert ids == {"4-#0", "4-#0#1", "4-#0#2"}
    assert _event("*4*303*#0#2##").unique_id != _event("*4*303*#2##").unique_id
    assert _event("*#4*#0#2*14*0205*1##").unique_id != _event("*#4*2*14*0205*1##").unique_id


def test_h1_builders_log_the_central_unit() -> None:
    off = OWNHeatingCommand.turn_off("#0#1")
    assert str(off) == "*4*303*#0#1##"
    assert off.human_readable_log == "Setting central unit #0#1 mode to 'off'."
    setpoint = OWNHeatingCommand.set_temperature("#0#2", 21.0, CLIMATE_MODE_HEAT)
    assert str(setpoint) == "*#4*#0#2*#14*0210*1##"
    assert "central unit #0#2" in setpoint.human_readable_log
    assert OWNHeatingCommand.turn_off("#0").human_readable_log == "Setting central unit #0 mode to 'off'."


def test_zone_under_a_four_zone_central_unit_keeps_its_zone() -> None:
    event = _event("*#4*#23#1*14*0250*3##")
    assert event.scope == SCOPE_ZONE_VIA_CENTRAL
    assert (event.zone, event.zone_number, event.central_unit) == (23, 23, 1)
    assert event.unique_id == "4-23"
    assert _event("*4*311*#2##").unique_id == "4-2"


def test_zone_forms_share_the_master_probe_unique_id() -> None:
    # ``#Z`` and ``#Z#C`` keep the ``4-Z`` of the master probe ``Z`` (MyHOME
    # routes a zone on it); the probe / actuator / central classes are distinct.
    assert _event("*4*311*#1##").unique_id == _event("*4*311*1##").unique_id == "4-1"
    assert _event("*4*311*#1#2##").unique_id == "4-1"
    assert _event("*#4*#1#4#01*14*0205*1##").unique_id == _event("*#4*1#4#01*14*0205*1##").unique_id == "4-1#4#01"
    distinct = {_event(f).unique_id for f in ("*4*311*1##", "*#4*001*0*0215##", "*4*303*0##", "*4*303*#0##", "*4*303*#0#1##", "*#4*1#1*20*1##")}
    assert distinct == {"4-1", "4-001", "4-0", "4-#0", "4-#0#1", "4-1#1"}


# ---------------------------------------------------------------- H2 / H3: address classes


def test_h2_all_probes_of_a_zone_is_not_the_master_probe() -> None:
    all_probes = _event("*#4*001*0*0215##")
    master = _event("*#4*1*0*0215##")
    assert all_probes.scope == SCOPE_ALL_PROBES
    assert master.scope == SCOPE_MASTER_PROBE
    assert all_probes.zone == master.zone == 1
    assert all_probes.zone_number == master.zone_number == 1
    assert all_probes.where == "001" and master.where == "1"
    assert (all_probes.unique_id, master.unique_id) == ("4-001", "4-1")
    assert all_probes.main_temperature == master.main_temperature == 21.5
    assert all_probes.message_type == MESSAGE_TYPE_MAIN_TEMPERATURE


def test_h3_all_probes_is_not_the_central_unit() -> None:
    general = _event("*4*1*0##")
    central = _event("*4*1*#0##")
    assert general.scope == SCOPE_ALL_PROBES
    assert central.scope == SCOPE_CENTRAL
    assert general.zone == central.zone == 0
    assert general.zone_number is None
    assert (general.unique_id, central.unique_id) == ("4-0", "4-#0")
    temperature = _event("*#4*0*0*0215##")
    assert temperature.unique_id == "4-0"
    assert temperature.human_readable_log == "Every probe's main sensor is reporting a temperature of 21.5°C."
    assert _event("*#4*000*0*0215##").unique_id == "4-000"


def test_h3_standalone_general_address_is_not_rewritten_to_the_central_unit() -> None:
    assert str(OWNHeatingCommand.turn_off("0")) == "*4*303*#0##"
    standalone = OWNHeatingCommand.turn_off("0", standalone=True)
    assert str(standalone) == "*4*303*0##"
    assert standalone.human_readable_log == "Setting general mode to 'off'."
    assert str(OWNHeatingCommand.turn_off("#0", standalone=True)) == "*4*303*#0##"


@pytest.mark.parametrize("where", ["0#1", "0#3", "0#9"])
def test_builders_refuse_the_actuator_form_of_zone_zero(where: str) -> None:
    # ``0#N`` is actuator N of zone 0 (SCOPE_ACTUATOR), not the 4-zone central
    # unit ``#0#N``: refused, not retargeted. ``#0#N`` itself still builds.
    for build in (
        lambda w: OWNHeatingCommand.set_temperature(w, 20.0, CLIMATE_MODE_HEAT),
        OWNHeatingCommand.turn_off,
        lambda w: OWNHeatingCommand.set_mode(w, CLIMATE_MODE_HEAT),
        lambda w: OWNHeatingCommand.set_timed_manual(w, 20.0),
    ):
        with pytest.raises(ValueError, match="actuator N of zone 0"):
            build(where)
    assert str(OWNHeatingCommand.set_temperature(f"#{where}", 20.0, CLIMATE_MODE_HEAT)) == f"*#4*#{where}*#14*0200*1##"


def test_central_unit_setpoint_target_is_the_one_set_central_temperature_builds() -> None:
    # ``#0`` / ``#0#C`` / legacy ``0`` were accepted before (D5): same frame as set_central_temperature.
    for where in ("#0", 0, "0"):
        assert str(OWNHeatingCommand.set_temperature(where, 20.0, CLIMATE_MODE_HEAT)) == str(
            OWNHeatingCommand.set_central_temperature("#0", 20.0, CLIMATE_MODE_HEAT)
        )
    assert str(OWNHeatingCommand.set_temperature("#0#1", 20.0, CLIMATE_MODE_HEAT)) == "*#4*#0#1*#14*0200*1##"


@pytest.mark.parametrize("where", ["001", "105", "#105", "#001", "899", "0105"])
def test_h2_h19_builders_refuse_probe_class_addresses(where: str) -> None:
    with pytest.raises(ValueError, match="Invalid zone address"):
        OWNHeatingCommand.set_temperature(where, 20.0, CLIMATE_MODE_HEAT)
    with pytest.raises(ValueError, match="Invalid zone address"):
        OWNHeatingCommand.turn_off(where)
    with pytest.raises(ValueError, match="Invalid zone address"):
        OWNHeatingCommand.set_timed_manual(where, 20.0)


@pytest.mark.parametrize("where", ["001", "105", "100"])
def test_h2_fan_builders_refuse_probe_class_addresses(where: str) -> None:
    with pytest.raises(ValueError, match="Invalid zone number"):
        OWNHeatingCommand.get_fan_speed(where)
    with pytest.raises(ValueError, match="Invalid zone number"):
        OWNHeatingCommand.set_fan_speed(where, 1)


def test_slave_and_external_probes_keep_their_literal_where() -> None:
    slave = _event("*#4*105*0*0296##")
    assert slave.scope == SCOPE_SLAVE_PROBE
    assert (slave.zone, slave.zone_number, slave.probe_number) == (5, 5, 1)
    assert slave.unique_id == "4-105"
    assert slave.secondary_temperature == [1, 29.6]
    external = _event("*#4*100*0*0215##")
    assert external.scope == SCOPE_EXTERNAL_PROBE
    assert (external.zone, external.zone_number, external.probe_number) == (0, None, 1)
    assert external.unique_id == "4-100"


# ---------------------------------------------------------------- H4: 3#Z#N and DIMENSION 22


def test_h4_split_prefix_names_zone_and_actuator() -> None:
    event = _event("*#4*3#2#1*22*1*0215*2*0##")
    assert event.scope == SCOPE_SPLIT_UNIT
    assert (event.zone, event.zone_number, event.actuator) == (2, 2, 1)
    assert event.unique_id == "4-3#2#1"
    assert event.address == "3#2#1"
    assert event.message_type == MESSAGE_TYPE_SPLIT_CONTROL
    assert event.split_mode == SPLIT_MODE_WINTER
    assert event.split_setpoint == 21.5
    assert event.split_fan_speed == SPLIT_FAN_MEDIUM
    assert event.split_swing is False
    assert event.human_readable_log == "Zone 2's split unit 1 reports mode winter, setpoint 21.5°C, fan medium, swing off."


def test_h4_partial_split_report_leaves_omitted_fields_none() -> None:
    event = _event("*#4*3#45#1*22*3**1*1##")
    assert (event.zone, event.actuator) == (45, 1)
    assert (event.split_mode, event.split_setpoint, event.split_fan_speed, event.split_swing) == (
        SPLIT_MODE_FAN,
        None,
        SPLIT_FAN_MINIMUM,
        True,
    )
    off = _event("*#4*3#45#1*22*0***##")
    assert (off.split_mode, off.split_setpoint, off.split_fan_speed, off.split_swing) == (
        SPLIT_MODE_OFF,
        None,
        None,
        None,
    )
    assert off.human_readable_log == "Zone 45's split unit 1 reports mode off."
    short = _event("*#4*3#2#1*22*5*000##")
    assert (short.split_mode, short.split_setpoint, short.split_fan_speed, short.split_swing) == (
        "automatic",
        0.0,
        None,
        None,
    )
    unknown = _event("*#4*3#2#1*22*7*12345*9*2##")
    assert unknown.message_type == MESSAGE_TYPE_SPLIT_CONTROL
    assert (unknown.split_mode, unknown.split_setpoint, unknown.split_fan_speed, unknown.split_swing) == (
        None,
        None,
        None,
        None,
    )
    assert unknown.human_readable_log == "Zone 2's split unit 1 reports no values."


def test_h4_split_write_echo_is_not_a_state() -> None:
    event = OWNEvent.parse("*#4*3#2#1*#22*1*0215*2*0##")
    assert isinstance(event, OWNHeatingEvent)
    assert event.scope == SCOPE_SPLIT_UNIT
    assert event.message_type is None
    assert event.split_mode is None


def test_split_prefix_outside_dimension_22_has_no_scope() -> None:
    event = _event("*#4*3#2#1*20*1##")
    assert event.scope is None
    assert event.zone == 3


# ---------------------------------------------------------------- H5 / H6 / H7: WHATs


@pytest.mark.parametrize(
    ("frame", "mode", "operating_mode", "season"),
    [
        ("*4*102*#1##", CLIMATE_MODE_OFF, OPERATING_MODE_ANTIFREEZE, SEASON_HEATING),
        ("*4*202*#1##", CLIMATE_MODE_OFF, OPERATING_MODE_THERMAL_PROTECTION, SEASON_CONDITIONING),
        ("*4*302*#1##", CLIMATE_MODE_OFF, OPERATING_MODE_PROTECTION, None),
        ("*4*103*#1##", CLIMATE_MODE_OFF, OPERATING_MODE_OFF, SEASON_HEATING),
        ("*4*203*#1##", CLIMATE_MODE_OFF, OPERATING_MODE_OFF, SEASON_CONDITIONING),
        ("*4*303*#1##", CLIMATE_MODE_OFF, OPERATING_MODE_OFF, None),
        ("*4*110*#1##", CLIMATE_MODE_HEAT, OPERATING_MODE_MANUAL, SEASON_HEATING),
        ("*4*210*#1##", CLIMATE_MODE_COOL, OPERATING_MODE_MANUAL, SEASON_CONDITIONING),
        ("*4*310*#1##", CLIMATE_MODE_AUTO, OPERATING_MODE_MANUAL, None),
        ("*4*111*#1##", CLIMATE_MODE_HEAT, OPERATING_MODE_AUTOMATIC, SEASON_HEATING),
        ("*4*211*#1##", CLIMATE_MODE_COOL, OPERATING_MODE_AUTOMATIC, SEASON_CONDITIONING),
        ("*4*311*#1##", CLIMATE_MODE_AUTO, OPERATING_MODE_AUTOMATIC, None),
        ("*4*112*#1##", CLIMATE_MODE_HEAT, OPERATING_MODE_TIMED_MANUAL, SEASON_HEATING),
        ("*4*212*#1##", CLIMATE_MODE_COOL, OPERATING_MODE_TIMED_MANUAL, SEASON_CONDITIONING),
        ("*4*312*#1##", CLIMATE_MODE_AUTO, OPERATING_MODE_TIMED_MANUAL, None),
        ("*4*115*#1##", CLIMATE_MODE_HEAT, OPERATING_MODE_HOLIDAY, SEASON_HEATING),
        ("*4*215*#1##", CLIMATE_MODE_COOL, OPERATING_MODE_HOLIDAY, SEASON_CONDITIONING),
        ("*4*315*#1##", CLIMATE_MODE_AUTO, OPERATING_MODE_HOLIDAY, None),
        ("*4*13005*#0##", CLIMATE_MODE_HEAT, OPERATING_MODE_VACATION, SEASON_HEATING),
        ("*4*23005*#0##", CLIMATE_MODE_COOL, OPERATING_MODE_VACATION, SEASON_CONDITIONING),
        ("*4*33005*#0##", CLIMATE_MODE_AUTO, OPERATING_MODE_VACATION, None),
        ("*4*1101*#0##", CLIMATE_MODE_HEAT, OPERATING_MODE_PROGRAM, SEASON_HEATING),
        ("*4*2103*#0##", CLIMATE_MODE_COOL, OPERATING_MODE_PROGRAM, SEASON_CONDITIONING),
        ("*4*3102*#0##", CLIMATE_MODE_AUTO, OPERATING_MODE_PROGRAM, None),
        ("*4*3116*#0##", CLIMATE_MODE_AUTO, OPERATING_MODE_PROGRAM, None),
        ("*4*1201*#0##", CLIMATE_MODE_HEAT, OPERATING_MODE_SCENARIO, SEASON_HEATING),
        ("*4*2216*#0##", CLIMATE_MODE_COOL, OPERATING_MODE_SCENARIO, SEASON_CONDITIONING),
        ("*4*3212*#0##", CLIMATE_MODE_AUTO, OPERATING_MODE_SCENARIO, None),
        ("*4*3000*#0##", CLIMATE_MODE_AUTO, OPERATING_MODE_CANCEL_VACATION, None),
        ("*4*3100*#0##", CLIMATE_MODE_AUTO, OPERATING_MODE_RESTORE_LAST_PROGRAM, None),
        ("*4*3200*#0##", CLIMATE_MODE_AUTO, OPERATING_MODE_RESTORE_LAST_SCENARIO, None),
    ],
)
def test_h5_h6_h7_every_what_family_has_its_own_operating_mode(
    frame: str, mode: str, operating_mode: str, season: str | None
) -> None:
    event = _event(frame)
    assert event.message_type == MESSAGE_TYPE_MODE
    assert event.mode == mode
    assert event.operating_mode == operating_mode
    assert event.season == season


def test_h5_protection_is_distinguishable_from_off() -> None:
    # ``mode`` and the log line stay ``off`` (MyHOME turns the zone OFF on a
    # protection WHAT and pins "Zone 2's mode is set to 'off'." on its F461
    # trace); ``operating_mode`` tells protection and OFF apart.
    for what in (102, 202, 302, 303):
        assert _event(f"*4*{what}*#1##").human_readable_log == "Zone 1's mode is set to 'off'."
    assert _event("*4*102*#1##").mode == _event("*4*103*#1##").mode == CLIMATE_MODE_OFF
    assert _event("*4*102*#1##").operating_mode != _event("*4*103*#1##").operating_mode


def test_h6_timed_manual_keeps_its_setpoint() -> None:
    event = _event("*4*312#0250#2*#1##")
    assert event.message_type == MESSAGE_TYPE_MODE_TARGET
    assert event.operating_mode == OPERATING_MODE_TIMED_MANUAL
    assert event.set_temperature == 25.0
    assert event.human_readable_log == "Zone 1's mode is set to 'auto' (timed manual) at 25.0°C."
    manual = _event("*4*110#0215*#0##")
    assert manual.operating_mode == OPERATING_MODE_MANUAL
    assert manual.set_temperature == 21.5


def test_h6_holiday_and_vacation_carry_their_programs_and_days() -> None:
    daily = _event("*4*115#1101*#0##")
    assert (daily.mode, daily.operating_mode, daily.program, daily.set_temperature) == (
        CLIMATE_MODE_HEAT,
        OPERATING_MODE_HOLIDAY,
        1,
        None,
    )
    assert daily.human_readable_log == "Central unit #0's mode is set to 'heat' (daily holiday plan) (program 1)."
    vacation = _event("*4*33002#3103*#0##")
    assert (vacation.operating_mode, vacation.holiday_days, vacation.program) == (OPERATING_MODE_VACATION, 2, 3)
    assert vacation.human_readable_log == "Central unit #0's mode is set to 'auto' (vacation for 2 days) (program 3)."
    assert _event("*4*13000*#0##").mode is None
    assert _event("*4*13256*#0##").mode is None


def test_h7_release_cancel_and_restore_whats_are_decoded() -> None:
    release = _event("*4*40*#1##")
    assert release.message_type is None
    assert release.mode is None
    assert release.human_readable_log == "Zone 1 releases its local probe adjustment."
    cancel = _event("*4*3000*#0##")
    assert cancel.human_readable_log == "Central unit #0 cancels its vacation."
    assert cancel.program is None
    cancel_program = _event("*4*3000#3102*#0##")
    assert cancel_program.operating_mode == OPERATING_MODE_CANCEL_VACATION
    assert cancel_program.program == 2
    assert cancel_program.human_readable_log == "Central unit #0 cancels its vacation (program 2)."
    assert _event("*4*3100*#0##").human_readable_log == "Central unit #0 restores its last weekly program."
    assert _event("*4*3200*#0##").human_readable_log == "Central unit #0 restores its last scenario."
    assert _event("*4*3100*#0##").program is None
    assert _event("*4*3200*#0##").scenario is None


# ---------------------------------------------------------------- H8: DIMENSION 19 fan-coil OFF states


@pytest.mark.parametrize("value", [14, 15, 16])
def test_h8_dimension_19_off_states_are_not_fan_speeds(value: int) -> None:
    cooling = _event(f"*#4*1*19*{value}*0##")
    assert cooling.message_type == MESSAGE_TYPE_ACTION
    assert cooling.cooling_fan_on is False
    assert cooling.cooling_fan_speed is None
    assert cooling.is_cooling() is False
    assert cooling.is_active() is False
    assert cooling.human_readable_log == f"Zone 1's cooling fan-coil is off (state {value}); heating valve is off."
    heating = _event(f"*#4*1*19*0*{value}##")
    assert heating.fan_on is False
    assert heating.fan_speed is None
    assert heating.is_heating() is False
    assert heating.is_active() is False
    assert heating.human_readable_log == f"Zone 1's cooling valve is off; heating fan-coil is off (state {value})."


def test_h8_published_fan_coil_values_are_unchanged() -> None:
    on = _event("*#4*1*19*8*6##")
    assert (on.cooling_fan_on, on.cooling_fan_speed, on.fan_on, on.fan_speed, on.is_active()) == (True, 3, True, 1, True)
    off = _event("*#4*2*19*5*1##")
    assert (off.cooling_fan_on, off.is_heating(), off.is_active()) == (False, True, True)


# ---------------------------------------------------------------- H9: empty values


@pytest.mark.parametrize("frame", ["*#4*1*11*##", "*#4*1*60*##"])
def test_h9_empty_values_do_not_raise(frame: str) -> None:
    message = OWNMessage.parse(frame)
    assert isinstance(message, OWNHeatingEvent)
    assert message.message_type is None
    assert message.fan_speed is None
    assert message.fan_on is None
    assert message.main_humidity is None
    assert message.human_readable_log == frame
    event = OWNEvent.parse(frame)
    assert isinstance(event, OWNHeatingEvent)
    assert event.message_type is None


def test_h9_filled_values_still_decode() -> None:
    fan = _event("*#4*1*11*3*##")
    assert (fan.message_type, fan.fan_speed, fan.fan_on) == (MESSAGE_TYPE_FAN_SPEED, 3, True)
    off = _event("*#4*1*11*15*##")
    assert (off.message_type, off.fan_speed, off.fan_on) == (MESSAGE_TYPE_FAN_SPEED, None, False)
    humidity = _event("*#4*1*60*45##")
    assert (humidity.message_type, humidity.main_humidity) == (MESSAGE_TYPE_MAIN_HUMIDITY, 45.0)


# ---------------------------------------------------------------- H13 / H14: actuators and interfaces


def test_h13_actuator_is_exposed_and_part_of_the_identity() -> None:
    first = _event("*#4*2#1*20*0##")
    second = _event("*#4*2#2*20*5##")
    every = _event("*#4*2#0*20*1##")
    assert first.scope == second.scope == every.scope == SCOPE_ACTUATOR
    assert (first.actuator, second.actuator, every.actuator) == (1, 2, 0)
    assert (first.zone, second.zone, every.zone) == (2, 2, 2)
    assert len({first.unique_id, second.unique_id, every.unique_id}) == 3
    assert first.unique_id == "4-2#1"
    bare = _event("*#4*2*20*1##")
    assert bare.actuator is None
    assert bare.scope == SCOPE_MASTER_PROBE
    assert bare.human_readable_log == "Zone 2's actuator is on."
    assert bare.is_active() is True


def test_h14_interface_suffix_is_not_actuator_4() -> None:
    routed = _event("*#4*2#4#01*20*0##")
    assert routed.actuator is None
    assert routed.interface == "01"
    assert (routed.zone, routed.scope) == (2, SCOPE_MASTER_PROBE)
    assert routed.unique_id == "4-2#4#01"
    assert routed.human_readable_log == "Zone 2's actuator is off."
    routed_actuator = _event("*#4*2#1#4#01*20*0##")
    assert (routed_actuator.actuator, routed_actuator.interface, routed_actuator.zone) == (1, "01", 2)
    assert routed_actuator.unique_id == "4-2#1#4#01"
    pump = _event("*#4*0#3*20*1##")
    assert (pump.zone, pump.actuator, pump.unique_id) == (0, 3, "4-0#3")


def test_h15_dimension_20_value_9_is_fan_coil_on() -> None:
    event = _event("*#4*2#1*20*9##")
    assert event.fan_on is True
    assert event.fan_speed is None
    assert event.is_active() is True
    assert event.human_readable_log == "Zone 2's fan-coil is on."


# ---------------------------------------------------------------- H16: three-digit DIMENSION 15 value


def test_h16_three_digit_probe_value_decodes() -> None:
    short = _event("*#4*11*15*1*123*1111##")
    long = _event("*#4*11*15*1*0123*1111##")
    assert short.message_type == long.message_type == MESSAGE_TYPE_SECONDARY_TEMPERATURE
    assert short.secondary_temperature == long.secondary_temperature == [1, 12.3]
    assert short.probe_number == 1
    assert short.human_readable_log == "Zone 11's secondary probe 1 is reporting a temperature of 12.3°C."
    assert _event("*#4*11*15*1*12*1111##").probe_temperature is None
    assert _event("*#4*11*15*1**1111##").probe_temperature is None


# ---------------------------------------------------------------- H17: write echoes on the event path


@pytest.mark.parametrize(
    "frame",
    ["*#4*50*#0*0215##", "*#4*2*#11*3##", "*#4*2*#7*1*1*0170##", "*#4*2*#12*0215*3##"],
)
def test_h17_dimension_writes_are_not_typed_as_state(frame: str) -> None:
    event = OWNEvent.parse(frame)
    assert isinstance(event, OWNHeatingEvent)
    assert event.message_type is None
    assert event.main_temperature is None
    assert event.local_set_temperature is None
    assert event.zone_state is None


def test_h17_written_values_stay_readable_without_a_type() -> None:
    # The Dimension 14 write echo keeps its type: MyHOME updates the target
    # temperature from ``OWNEvent.parse("*#4*01*#14*0220*1##")``.
    setpoint = OWNEvent.parse("*#4*#1*#14*0205*1##")
    assert isinstance(setpoint, OWNHeatingEvent)
    assert setpoint.set_temperature == 20.5
    assert setpoint.message_type == MESSAGE_TYPE_TARGET_TEMPERATURE
    fan = OWNEvent.parse("*#4*2*#11*3##")
    assert isinstance(fan, OWNHeatingEvent)
    assert fan.fan_speed == 3
    assert fan.message_type is None
    reply = OWNEvent.parse("*#4*#1*14*0205*1##")
    assert isinstance(reply, OWNHeatingEvent)
    assert reply.message_type == MESSAGE_TYPE_TARGET_TEMPERATURE


# ---------------------------------------------------------------- H18 / H19: builder validation


@pytest.mark.parametrize(("day", "month", "year"), [(31, 2, 2026), (30, 2, 2028), (31, 4, 2026), (29, 2, 2027)])
def test_h18_holiday_end_date_must_be_a_calendar_date(day: int, month: int, year: int) -> None:
    with pytest.raises(ValueError, match="Invalid calendar date"):
        OWNHeatingCommand.set_holiday_end_date("#0", day, month, year)


def test_h18_valid_calendar_dates_are_built() -> None:
    assert str(OWNHeatingCommand.set_holiday_end_date("#0", 28, 2, 2026)) == "*#4*#0*#30*28*02*2026##"
    assert str(OWNHeatingCommand.set_holiday_end_date("#0", 29, 2, 2028)) == "*#4*#0*#30*29*02*2028##"
    with pytest.raises(ValueError, match="Invalid date values"):
        OWNHeatingCommand.set_holiday_end_date("#0", 32, 1, 2026)


@pytest.mark.parametrize(
    ("temperature", "code"),
    [(4.9, "0050"), (4.0, "0050"), (-3.0, "0050"), (0.0, "0050"), (40.2, "0400"), (40.5, "0400"), (50.0, "0400")],
)
def test_h19_set_temperature_clamps_out_of_range_values(temperature: float, code: str) -> None:
    # MyHOME relies on the clamp (its ``test_set_temperature_clamp_low`` /
    # ``_high``); only the address class is refused, see above.
    assert str(OWNHeatingCommand.set_temperature("1", temperature, CLIMATE_MODE_HEAT)) == f"*#4*#1*#14*{code}*1##"


def test_h19_set_temperature_in_range_rounds_to_half_degrees() -> None:
    assert str(OWNHeatingCommand.set_temperature("1", 5.0, CLIMATE_MODE_HEAT)) == "*#4*#1*#14*0050*1##"
    assert str(OWNHeatingCommand.set_temperature("1", 40.0, CLIMATE_MODE_HEAT)) == "*#4*#1*#14*0400*1##"
    assert str(OWNHeatingCommand.set_temperature("1", 20.3, CLIMATE_MODE_HEAT)) == "*#4*#1*#14*0205*1##"
    with pytest.raises(ValueError, match="finite"):
        OWNHeatingCommand.set_temperature("1", float("nan"), CLIMATE_MODE_HEAT)


# ---------------------------------------------------------------- legacy frames MyHOME relies on


@pytest.mark.parametrize(
    ("frame", "zone", "unique_id", "message_type", "mode"),
    [
        ("*#4*2*0*0241##", 2, "4-2", MESSAGE_TYPE_MAIN_TEMPERATURE, None),
        ("*#4*2*14*0230*3##", 2, "4-2", MESSAGE_TYPE_TARGET_TEMPERATURE, None),
        ("*4*303*2##", 2, "4-2", MESSAGE_TYPE_MODE, CLIMATE_MODE_OFF),
        ("*4*311*#2##", 2, "4-2", MESSAGE_TYPE_MODE, CLIMATE_MODE_AUTO),
        ("*4*1*2##", 2, "4-2", MESSAGE_TYPE_SEASON, None),
        ("*#4*2#1*20*1##", 2, "4-2#1", MESSAGE_TYPE_ACTION, None),
        ("*#4*2*19*5*1##", 2, "4-2", MESSAGE_TYPE_ACTION, None),
        ("*#4*2*11*0##", 2, "4-2", MESSAGE_TYPE_FAN_SPEED, None),
        ("*4*110#0215*#0##", 0, "4-#0", MESSAGE_TYPE_MODE_TARGET, CLIMATE_MODE_HEAT),
        ("*4*202*#0##", 0, "4-#0", MESSAGE_TYPE_MODE, CLIMATE_MODE_OFF),
        ("*4*0*#0#1##", 1, "4-#0#1", MESSAGE_TYPE_SEASON, None),
        ("*#4*#0#1*20*0##", 1, "4-#0#1", MESSAGE_TYPE_ACTION, None),
    ],
)
def test_myhome_trace_frames_keep_their_zone_and_type(
    frame: str, zone: int, unique_id: str, message_type: str, mode: str | None
) -> None:
    event = _event(frame)
    assert event.zone == zone
    assert event.unique_id == unique_id
    assert event.message_type == message_type
    assert event.mode == mode


def test_unpublished_where_forms_keep_the_legacy_zone_without_a_scope() -> None:
    assert (_event("*4*303*#105##").scope, _event("*4*303*#105##").zone) == (None, 5)
    assert _event("*#4*2#10*20*1##").scope is None
    assert _event("*4*1*#0#0##").scope is None
    empty = OWNHeatingEvent("*#4**0*0215##")
    assert (empty.scope, empty.zone, empty.unique_id) == (None, 0, "4-")
    assert OWNHeatingCommand.set_mode("1", "unknown") is None


@pytest.mark.parametrize("where", ["00", "0#1"])
def test_fan_builders_refuse_zone_zero_spellings(where: str) -> None:
    with pytest.raises(ValueError, match="Invalid zone number"):
        OWNHeatingCommand.get_fan_speed(where)
    with pytest.raises(ValueError, match="Invalid zone number"):
        OWNHeatingCommand.set_fan_speed(where, 1)
