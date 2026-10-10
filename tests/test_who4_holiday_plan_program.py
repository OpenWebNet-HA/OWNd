"""WHO 4: the parameter of 115#/215#/315# is a weekly program, not a temperature.

Evidence: Legrand "Open Web Net Language, WHO = 4" v2.0.0 p. 56 and p. 64
("115#parameterH", parameterH = 1101-1103); libqtdevices TS10_1_0_23
thermal_device.cpp:241 and :286 (``values_list[DIM_PROGRAM] = msg.whatArgN(0) % 100``);
firmware replay: ``*4*115#1102*#0##`` is ACKed by bt_termo on MyHomeServer1, F454,
F459, F461 and F450 and forwarded as ``D1 00 03 02 C1 14 01 00`` (program byte 01,
no temperature field), see docs in the pull request.
"""

from OWNd.message import (
    CLIMATE_MODE_AUTO,
    CLIMATE_MODE_COOL,
    CLIMATE_MODE_HEAT,
    OWNEvent,
    OWNHeatingCommand,
    OWNHeatingEvent,
)


def test_holiday_plan_parameter_is_a_program_not_a_temperature():
    msg = OWNEvent.parse("*4*115#1102*#0##")
    assert isinstance(msg, OWNHeatingEvent)
    assert msg.mode == CLIMATE_MODE_HEAT
    assert msg.program == 2
    assert msg.set_temperature is None
    assert msg.message_type == "hvac_mode"


def test_cooling_holiday_plan_parameter():
    msg = OWNEvent.parse("*4*215#2102*#0##")
    assert msg.mode == CLIMATE_MODE_COOL
    assert msg.program == 2
    assert msg.set_temperature is None


def test_program_and_scenario_numbers_are_exposed():
    # thermal_device.cpp:209-211: program = what - commandRange(what)
    assert OWNEvent.parse("*4*1102*#0##").program == 2
    assert OWNEvent.parse("*4*2102*#0##").program == 2
    assert OWNEvent.parse("*4*3113*#0##").program == 13
    assert OWNEvent.parse("*4*1203*#0##").scenario == 3
    assert OWNEvent.parse("*4*3209*#0##").scenario == 9
    assert OWNEvent.parse("*4*1*23##").program is None
    assert OWNEvent.parse("*4*1*23##").scenario is None


def test_manual_with_temperature_parameter_still_reads_the_temperature():
    # Legrand WHO 4 p. 23 / p. 56: 110#T manual heating with temperature.
    msg = OWNEvent.parse("*4*110#0215*#0##")
    assert msg.set_temperature == 21.5
    assert msg.message_type == "hvac_mode_target"
    # thermal_device.cpp:378: 312#T#2 timed manual, generic mode.
    msg = OWNEvent.parse("*4*312#0220#2*#0##")
    assert msg.set_temperature == 22.0
    assert msg.message_type == "hvac_mode_target"


def test_holiday_days_parameter_is_a_program_not_a_temperature():
    # 13DDD#P / 23DDD#P / 33DDD#P carry the program the plant resumes after the
    # holiday, exactly like 115#P; 13005#1102 used to read as -10.2 degrees.
    heat = OWNEvent.parse("*4*13005#1102*#0##")
    assert heat.mode == CLIMATE_MODE_HEAT
    assert heat.holiday_days == 5
    assert heat.program == 2
    assert heat.set_temperature is None
    assert heat.message_type == "hvac_mode"

    cool = OWNEvent.parse("*4*23005#2102*#0##")
    assert cool.mode == CLIMATE_MODE_COOL
    assert cool.holiday_days == 5
    assert cool.program == 2
    assert cool.set_temperature is None
    assert cool.message_type == "hvac_mode"

    auto = OWNEvent.parse("*4*33005#3102*#0##")
    assert auto.mode == CLIMATE_MODE_AUTO
    assert auto.holiday_days == 5
    assert auto.program == 2
    assert auto.set_temperature is None
    assert auto.message_type == "hvac_mode"
    assert "program 2" in auto.human_readable_log


def test_set_central_holiday_round_trips_without_a_temperature():
    command = OWNHeatingCommand.set_central_holiday(days=5, program=2)
    assert str(command) == "*4*33005#3102*#0##"

    event = OWNHeatingEvent(str(command))
    assert event.mode == CLIMATE_MODE_AUTO
    assert event.holiday_days == 5
    assert event.program == 2
    assert event.set_temperature is None
    assert event.message_type == "hvac_mode"


def test_holiday_days_without_a_parameter_keep_no_program():
    msg = OWNEvent.parse("*4*13005*#0##")
    assert msg.holiday_days == 5
    assert msg.program is None
    assert msg.set_temperature is None


def test_multi_day_vacation_uses_the_generic_return_program_in_every_season():
    # Encyclopedia WHO 4 "Vacation, program and scenario forms": the multi-day
    # vacation commands use 3101..3103 in all three contexts (13DDD / 23DDD /
    # 33DDD), unlike the daily holiday plan (1101..1103 / 2101..2103).
    # 3102 used to decode as a -10.2 degree setpoint.
    heat = OWNEvent.parse("*4*13005#3102*#0##")
    assert (heat.mode, heat.holiday_days, heat.program) == (CLIMATE_MODE_HEAT, 5, 2)
    assert heat.set_temperature is None
    assert heat.message_type == "hvac_mode"

    cool = OWNEvent.parse("*4*23005#3102*#0##")
    assert (cool.mode, cool.holiday_days, cool.program) == (CLIMATE_MODE_COOL, 5, 2)
    assert cool.set_temperature is None
    assert cool.message_type == "hvac_mode"
