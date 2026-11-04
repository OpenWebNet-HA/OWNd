"""Regression tests for OpenWebNet message protocol edge cases."""

from __future__ import annotations

import datetime

import pytest

from OWNd.message import (
    OWNAlarmCommand,
    OWNAlarmEvent,
    OWNAutomationCommand,
    OWNAutomationEvent,
    OWNCENEvent,
    OWNCENPlusEvent,
    OWNCenCommand,
    OWNCommand,
    OWNDryContactCommand,
    OWNDryContactEvent,
    OWNEnergyEvent,
    OWNEvent,
    OWNGatewayCommand,
    OWNGatewayEvent,
    OWNHeatingCommand,
    OWNHeatingEvent,
    OWNLightingCommand,
    OWNLightingEvent,
    MESSAGE_TYPE_FAN_SPEED,
    OWNMessage,
    OWNSoundCommand,
    OWNStatusRequest,
)


def test_invalid_message_has_defensive_defaults() -> None:
    message = OWNMessage("not-an-openwebnet-frame")

    assert message.is_valid is False
    assert message.who is None
    assert message.where is None
    assert message.dimension is None


@pytest.mark.parametrize(
    "frame",
    ["*8*1#1#4*11##", "*8*9#1#4*20##", "*6*9**##"],
)
def test_unspecialized_who_event_returns_generic_event(frame: str) -> None:
    message = OWNEvent.parse(frame)

    assert isinstance(message, OWNEvent)
    assert isinstance(message, OWNMessage)


def test_who25_routes_by_what_instead_of_where_prefix() -> None:
    dry_contact = OWNEvent.parse("*25*31*21##")
    cen_plus = OWNEvent.parse("*25*21#1*21##")

    assert isinstance(dry_contact, OWNDryContactEvent)
    assert dry_contact.sensor == "21"
    assert isinstance(cen_plus, OWNCENPlusEvent)
    assert cen_plus.push_button == 1


def test_who25_malformed_parameters_do_not_raise() -> None:
    cen_plus = OWNCENPlusEvent("*25*21*21##")
    dry_contact = OWNDryContactEvent("*25*31*21##")

    assert cen_plus.push_button == 0
    assert dry_contact.is_detection is True


def test_who25_status_request_is_a_dry_contact_command() -> None:
    message = OWNCommand.parse("*#25*21##")

    assert isinstance(message, OWNDryContactCommand)


def test_status_requests_can_omit_where() -> None:
    alarm = OWNMessage.parse("*#5##")
    auxiliary = OWNMessage.parse("*#9##")

    assert isinstance(alarm, OWNAlarmCommand)
    assert alarm.where is None
    assert alarm.unique_id == "5"
    assert isinstance(auxiliary, OWNStatusRequest)
    assert auxiliary.where is None
    assert auxiliary.unique_id == "9"
    assert str(OWNStatusRequest.request(9)) == "*#9##"
    assert str(OWNStatusRequest.request(9, "1")) == "*#9*1##"


def test_alarm_command_helpers_and_dispatch() -> None:
    assert str(OWNAlarmCommand.disarm()) == "*5*2*0##"
    assert str(OWNAlarmCommand.disengage()) == "*5*9*0##"
    assert str(OWNAlarmCommand.disengage("1")) == "*5*9*1##"
    assert str(OWNAlarmCommand.arm_away()) == "*5*1*0##"
    assert str(OWNAlarmCommand.engage()) == "*5*8*0##"
    assert str(OWNAlarmCommand.engage("1")) == "*5*8*1##"
    assert str(OWNAlarmCommand.arm_home()) == "*5*1*0##"
    assert str(OWNAlarmCommand.trigger()) == "*5*17*0##"
    assert str(OWNAlarmCommand.panic()) == "*5*17*0##"
    assert str(OWNAlarmCommand.status()) == "*#5*0##"
    assert str(OWNAlarmCommand.status("1")) == "*#5*#1##"
    assert str(OWNAlarmCommand.status("#2")) == "*#5*#2##"
    assert str(OWNAlarmCommand.status(None)) == "*#5##"
    assert str(OWNAlarmCommand.status("")) == "*#5##"
    assert isinstance(OWNCommand.parse("*5*2*0##"), OWNAlarmCommand)
    assert isinstance(OWNCommand.parse("*5*8*0##"), OWNAlarmCommand)
    assert isinstance(OWNCommand.parse("*5*9*0##"), OWNAlarmCommand)


@pytest.mark.parametrize(
    ("frames", "armed"),
    [
        (["*5*2*0##", "*5*1*0##", "*5*9*0##"], [False, False, False]),
        (["*5*1*0##", "*5*8*0##"], [False, True]),
        (["*5*1*##", "*5*9*##"], [False, False]),
    ],
)
def test_alarm_what_1_never_reads_as_armed(frames: list[str], armed: list[bool]) -> None:
    """F454 trace (MyHOME#311): WHAT 1 is sent on disarm and in disarmed dumps; only WHAT 8 is armed."""
    events = [OWNMessage.parse(f) for f in frames]
    assert [e.is_armed_away for e in events] == armed


def test_alarm_central_telemetry_and_events() -> None:
    """Central unit WHO 5 broadcasts (*5*<what>*0##) verify all state and power telemetry properties."""
    act = OWNMessage.parse("*5*1*0##")
    assert isinstance(act, OWNAlarmEvent)
    assert act.general is True
    assert act.is_active is True
    assert act.is_armed_away is False
    assert act.is_disarmed is False

    eng = OWNMessage.parse("*5*8*0##")
    assert isinstance(eng, OWNAlarmEvent)
    assert eng.general is True
    assert eng.is_engaged is True
    assert eng.is_armed_away is True
    assert eng.is_disarmed is False

    dis = OWNMessage.parse("*5*9*0##")
    assert isinstance(dis, OWNAlarmEvent)
    assert dis.general is True
    assert dis.is_disarmed is True
    assert dis.is_armed_away is False
    assert dis.is_engaged is False

    bat_fault4 = OWNMessage.parse("*5*4*0##")
    assert isinstance(bat_fault4, OWNAlarmEvent)
    assert bat_fault4.is_battery_fault is True
    assert bat_fault4.is_power_telemetry is True

    bat_fault10 = OWNMessage.parse("*5*10*0##")
    assert isinstance(bat_fault10, OWNAlarmEvent)
    assert bat_fault10.is_battery_fault is True
    assert bat_fault10.is_power_telemetry is True

    bat_ok = OWNMessage.parse("*5*5*0##")
    assert isinstance(bat_ok, OWNAlarmEvent)
    assert bat_ok.general is True
    assert bat_ok.is_battery_ok is True
    assert bat_ok.is_power_telemetry is True

    mains_fault = OWNMessage.parse("*5*6*0##")
    assert isinstance(mains_fault, OWNAlarmEvent)
    assert mains_fault.is_mains_fault is True
    assert mains_fault.is_power_telemetry is True

    mains_ok = OWNMessage.parse("*5*7*0##")
    assert isinstance(mains_ok, OWNAlarmEvent)
    assert mains_ok.general is True
    assert mains_ok.is_mains_ok is True
    assert mains_ok.is_power_telemetry is True

    # Alarm event subtypes
    ev_tech = OWNMessage.parse("*5*12*0##")
    assert isinstance(ev_tech, OWNAlarmEvent)
    assert ev_tech.is_technical is True
    assert ev_tech.is_alarm is True

    ev_int = OWNMessage.parse("*5*15*0##")
    assert isinstance(ev_int, OWNAlarmEvent)
    assert ev_int.is_intrusion is True
    assert ev_int.is_alarm is True

    ev_tamper = OWNMessage.parse("*5*16*0##")
    assert isinstance(ev_tamper, OWNAlarmEvent)
    assert ev_tamper.is_tamper is True
    assert ev_tamper.is_alarm is True

    ev_panic = OWNMessage.parse("*5*17*0##")
    assert isinstance(ev_panic, OWNAlarmEvent)
    assert ev_panic.is_panic is True
    assert ev_panic.is_alarm is True

    ev_silent = OWNMessage.parse("*5*31*0##")
    assert isinstance(ev_silent, OWNAlarmEvent)
    assert ev_silent.is_silent is True
    assert ev_silent.is_alarm is True


def test_alarm_zone_telemetry_does_not_pollute_system_arm_state() -> None:
    """Active zone partition reports (*5*11*#1##) must never trigger is_armed_home."""
    z_act = OWNMessage.parse("*5*11*#1##")
    assert isinstance(z_act, OWNAlarmEvent)
    assert z_act.general is False
    assert z_act.zone == "1"
    assert z_act.is_zone_active is True
    assert z_act.is_armed_home is False
    assert z_act.is_armed_away is False

    z_byp = OWNMessage.parse("*5*18*#7##")
    assert isinstance(z_byp, OWNAlarmEvent)
    assert z_byp.general is False
    assert z_byp.zone == "7"
    assert z_byp.is_zone_inactive is True
    assert z_byp.is_zone_active is False
    assert z_byp.is_disarmed is False


def test_f454_time_without_timezone_is_parsed_safely() -> None:
    event = OWNGatewayEvent("*#13**0*14*30*45##")
    command = OWNGatewayCommand("*#13**#0*12*00*00##")

    assert event._hour == "14"
    assert event._minute == "30"
    assert event._second == "45"
    assert event._timezone == ""
    assert command._hour == "12"
    assert command._timezone == ""


@pytest.mark.parametrize(
    ("suffix", "expected"),
    [
        ("", "15:00:01"),
        ("*", "15:00:01"),
        ("*002", "15:00:01+02:00"),
        ("*105", "15:00:01-05:00"),
    ],
)
def test_gateway_time_supports_optional_timezone(
    suffix: str, expected: str
) -> None:
    message = OWNMessage.parse(f"*#13**0*15*00*01{suffix}##")

    assert isinstance(message, OWNGatewayEvent)
    assert message._time == datetime.time.fromisoformat(expected)


@pytest.mark.parametrize(
    "frame",
    [
        "*#13**#0*15*00##",
        "*#13**0*25*00*00##",
        "*#13**0*15*00*00*200##",
        "*#13**#1*03*09*09##",
        "*#13**22*15*00*01*002*03*31*02*2026##",
    ],
)
def test_malformed_gateway_clock_is_rejected(frame: str) -> None:
    with pytest.raises(ValueError):
        OWNMessage.parse(frame)


def test_gateway_time_command_has_no_empty_trailing_value() -> None:
    message = OWNGatewayCommand.set_time_to_now("UTC")

    assert str(message).endswith("##")
    assert not str(message).endswith("*##")


def test_heating_fan_speed_dimension_has_message_type() -> None:
    event = OWNHeatingEvent("*#4*1*11*2##")

    assert event.message_type == MESSAGE_TYPE_FAN_SPEED
    assert event.fan_speed == 2
    assert event.fan_on is True
    assert str(OWNHeatingCommand.set_fan_speed("1", 2)) == "*#4*1*#11*2##"

    automatic = OWNHeatingEvent("*#4*1*11*0##")
    assert automatic.fan_speed == 0
    assert automatic.fan_on is True


def test_shutter_dimension_10_supports_short_and_full_replies() -> None:
    short_reply = OWNAutomationEvent("*#2*21*10*10*75##")
    full_reply = OWNAutomationEvent("*#2*21*10*10*75*1*0##")

    assert short_reply.current_position == 75
    assert full_reply.current_position == 75
    assert str(OWNAutomationCommand.get_shutter_status("21")) == "*#2*21*10##"


def test_shutter_level_255_is_an_unknown_position() -> None:
    # Encyclopedia who-2-automation/dimensions.md: 255 = "Unknown position".
    stopped = OWNAutomationEvent("*#2*21*10*10*255*0*0##")
    moving = OWNAutomationEvent("*#2*21*10*11*255*0*0##")
    known = OWNAutomationEvent("*#2*21*10*10*100*0*0##")

    assert stopped.current_position is None
    assert stopped.is_position_unknown is True
    assert stopped.is_closed is None
    assert stopped.is_opening is False
    assert "unknown position" in stopped.human_readable_log
    assert moving.current_position is None
    assert moving.is_opening is True
    assert "from an unknown position" in moving.human_readable_log
    assert "None" not in moving.human_readable_log
    assert known.current_position == 100
    assert known.is_position_unknown is False


def test_shutter_level_outside_0_100_is_an_unknown_position() -> None:
    # Same rule as MyHOME#430: anything outside 0-100 is not a level.
    stopped = OWNAutomationEvent("*#2*0112*10*10*150*001*0##")
    closing = OWNAutomationEvent("*#2*0112*10*12*101*001*0##")
    closed = OWNAutomationEvent("*#2*0112*10*10*0*001*0##")

    assert stopped.current_position is None
    assert stopped.is_position_unknown is True
    assert "unknown position" in stopped.human_readable_log
    assert closing.current_position is None
    assert closing.is_closing is True
    assert "closing from an unknown position" in closing.human_readable_log
    assert closed.current_position == 0
    assert closed.is_closed is True
    assert closed.is_position_unknown is False


def test_lighting_what_19_is_an_anomaly_state() -> None:
    # MH200N bt_luci binary disassembly: byte 'E' (0x45) on SCS bus maps
    # to decimal 19 on load anomalies/overloads (findings/MH200N/what19.md).
    msg = OWNEvent.parse("*1*19*74##")

    assert isinstance(msg, OWNLightingEvent)
    assert msg.is_on is None
    assert msg.is_anomaly is True
    assert msg.unknown_state == 19
    assert msg.human_readable_log == "Light 74 reports anomaly (WHAT 19)."


@pytest.mark.parametrize("what", [32, 33, 35, 38, 99])
def test_lighting_what_outside_the_table_is_an_unknown_state(what: int) -> None:
    msg = OWNLightingEvent(f"*1*{what}*21##")

    assert msg.is_on is None
    assert msg.is_anomaly is False
    assert msg.unknown_state == what
    assert msg.is_sensor is False
    assert f"unknown lighting WHAT {what}" in msg.human_readable_log


@pytest.mark.parametrize(
    ("what", "is_on"),
    [(0, False), *((w, True) for w in range(1, 19)), *((w, True) for w in range(20, 32))],
)
def test_lighting_what_in_the_table_keeps_its_state(what: int, is_on: bool) -> None:
    msg = OWNLightingEvent(f"*1*{what}*21##")

    assert msg.is_on is is_on
    assert msg.unknown_state is None
    assert "unknown" not in msg.human_readable_log


def test_lighting_motion_what_34_is_not_an_unknown_state() -> None:
    # 34 is not in WHO_1.pdf; OWNd decodes it as motion (ZigBee variant).
    # A motion frame says nothing about on/off, so is_on is None (fedem95 review on PR #59).
    msg = OWNLightingEvent("*1*34*21##")

    assert msg.motion is True
    assert msg.is_on is None
    assert msg.unknown_state is None
    assert msg.is_sensor is True

    # Frame cited in review: *1*34*74##
    msg74 = OWNLightingEvent("*1*34*74##")
    assert msg74.motion is True
    assert msg74.is_on is None
    assert msg74.unknown_state is None


@pytest.mark.parametrize("frame", ["*1*1000#1*74##", "*1*1000#19*74##"])
def test_lighting_translation_wrapper_is_not_an_unknown_state(frame: str) -> None:
    msg = OWNLightingEvent(frame)

    assert msg.is_translation is True
    assert msg.is_on is None
    assert msg.unknown_state is None


@pytest.mark.parametrize(
    ("frame", "log"),
    [
        ("*1*30*21##", "Light 21 is dimmed up one level."),
        ("*1*31*21##", "Light 21 is dimmed down one level."),
        ("*1*30#2#3*21##", "Light 21 is dimmed up one level."),
        ("*1*31#2#3*21##", "Light 21 is dimmed down one level."),
    ],
)
def test_lighting_step_what_has_a_log(frame: str, log: str) -> None:
    msg = OWNLightingEvent(frame)

    assert msg.is_on is True
    assert msg.unknown_state is None
    assert msg.human_readable_log == log


def test_sound_volume_down_uses_documented_step_what() -> None:
    # Encyclopedia who-16-sound-system: up = 1001..1015, down = 1101..1115.
    assert str(OWNSoundCommand.volume_up("21")) == "*16*1001*21##"
    assert str(OWNSoundCommand.volume_down("21")) == "*16*1101*21##"


@pytest.mark.parametrize(
    ("method", "frame"),
    [
        ("press", "*15*02*11##"),
        ("release_short_press", "*15*02#1*11##"),
        ("start_long_press", "*15*02#3*11##"),
        ("still_held", "*15*02#3*11##"),
        ("release", "*15*02#2*11##"),
    ],
)
def test_cen_builders_put_the_button_in_what(method: str, frame: str) -> None:
    built = getattr(OWNCenCommand, method)("11", 2)
    assert str(built) == frame

    # What OWNd sends must read back as the same button on the same source.
    event = OWNCENEvent(str(built))
    assert int(event.push_button) == 2
    assert event.object == "11"


def test_cen_builder_keeps_local_bus_where() -> None:
    assert str(OWNCenCommand.press("36#4#01", 6)) == "*15*06*36#4#01##"


@pytest.mark.parametrize("button", [-1, 32])
def test_cen_builder_rejects_buttons_outside_00_31(button: int) -> None:
    with pytest.raises(ValueError, match="between 0 and 31"):
        OWNCenCommand.press("11", button)


def test_stop_and_go_energy_addresses_are_supported() -> None:
    event = OWNEnergyEvent("*#18*11*51*2500##")
    single_digit = OWNEnergyEvent("*#18*1*51*1200##")
    invalid_date = OWNEnergyEvent("*#18*11*511#2#30*1*50##")

    assert event.total_consumption == 2500
    assert event.sensor == "1"
    assert single_digit.total_consumption == 1200
    assert single_digit.sensor == "1"
    assert invalid_date.message_type is None


@pytest.mark.parametrize(
    ("frame", "attribute"),
    [
        ("*#18*1*113*##", "active_power"),
        ("*#18*1*51*##", "total_consumption"),
        ("*#18*1*54*##", "current_day_partial_consumption"),
        ("*#18*1*53*##", "current_month_partial_consumption"),
    ],
)
def test_empty_energy_value_is_zero(frame: str, attribute: str) -> None:
    event = OWNEnergyEvent(frame)

    assert getattr(event, attribute) == 0


def test_incomplete_hourly_energy_sample_is_ignored() -> None:
    event = OWNEnergyEvent("*#18*1*511#1#1*##")

    assert event.message_type is None


@pytest.mark.parametrize("button", [0, 31])
def test_cenplus_supports_full_button_range(button: int) -> None:
    message = OWNEvent.parse(f"*25*21#{button}*21##")

    assert isinstance(message, OWNCENPlusEvent)
    assert message.push_button == button


@pytest.mark.parametrize(
    ("what", "property_name"),
    [
        (25, "is_slowly_turned_cw"),
        (26, "is_quickly_turned_cw"),
        (27, "is_slowly_turned_ccw"),
        (28, "is_quickly_turned_ccw"),
    ],
)
def test_cenplus_supports_rotary_actions(what: int, property_name: str) -> None:
    message = OWNEvent.parse(f"*25*{what}#1*21##")

    assert isinstance(message, OWNCENPlusEvent)
    assert getattr(message, property_name) is True


def test_cenplus_unknown_state_has_a_diagnostic_log() -> None:
    message = OWNCENPlusEvent("*25*99#1*21##")

    assert "state is 99" in message.human_readable_log


def test_flash_accepts_bundled_v2_keyword_alias() -> None:
    message = OWNLightingCommand.flash("21", _freqency=1.0)

    assert str(message) == "*1*21*21##"


def test_own_message_helper_properties_and_effective_what() -> None:
    from OWNd.message import (
        OWNAutomationCommand,
        OWNEnergyCommand,
        OWNGatewayCommand,
        OWNHeatingCommand,
        OWNMessage,
    )
    import datetime as dt

    status_req = OWNMessage.parse("*#1*99##")
    assert status_req is not None
    assert status_req.is_status_request is True
    assert status_req.is_dimension_request is False
    assert status_req.is_dimension_writing is False
    assert status_req.is_dimension_reply is False
    assert status_req.effective_what is None
    assert isinstance(status_req, OWNLightingCommand)
    assert status_req.is_status_query is True
    assert status_req.is_brightness_query is False

    dim_req = OWNMessage.parse("*#1*99*1##")
    assert dim_req is not None
    assert dim_req.is_dimension_request is True
    assert isinstance(dim_req, OWNLightingCommand)
    assert dim_req.is_brightness_query is True
    assert dim_req.is_status_query is False

    dim_write = OWNMessage.parse("*#1*99*#1*150*0##")
    assert dim_write is not None
    assert dim_write.is_dimension_writing is True

    dim_reply = OWNMessage.parse("*#1*99*1*150*0##")
    assert dim_reply is not None
    assert dim_reply.is_dimension_reply is True

    trans_on = OWNMessage.parse("*1*1000#1*99##")
    assert trans_on is not None
    assert trans_on.is_translation is True
    assert trans_on.what == 1000
    assert trans_on.effective_what == 1

    direct_on = OWNMessage.parse("*1*1*99##")
    assert direct_on is not None
    assert direct_on.is_translation is False
    assert direct_on.effective_what == 1

    # Lighting report_brightness
    rep_b = OWNLightingCommand.report_brightness("99", 75, 0)
    assert str(rep_b) == "*#1*99*1*175*0##"
    assert "75%" in rep_b.human_readable_log

    # Automation queries & report_shutter_level
    shutter_q = OWNAutomationCommand("*#2*98##")
    assert shutter_q.is_status_query is True
    assert shutter_q.is_shutter_status_query is False
    shutter_dim_q = OWNAutomationCommand("*#2*98*10##")
    assert shutter_dim_q.is_shutter_status_query is True
    rep_shutter = OWNAutomationCommand.report_shutter_level("98", 60, state=10)
    assert str(rep_shutter) == "*#2*98*10*10*60*0*0##"
    rep_shutter_bitfield = OWNAutomationCommand.report_shutter_level(
        "31", 40, state=10, priority="001"
    )
    assert str(rep_shutter_bitfield) == "*#2*31*10*10*40*001*0##"
    rep_shutter_unk = OWNAutomationCommand.report_shutter_level("98", 255)
    assert str(rep_shutter_unk) == "*#2*98*10*10*255*0*0##"

    # Heating encode_temperature, report_temperature, write_temperature
    assert OWNHeatingCommand.encode_temperature(18.5) == "0185"
    assert OWNHeatingCommand.encode_temperature(-3.2) == "1032"
    assert OWNHeatingCommand.encode_temperature(0.0) == "0000"
    assert OWNHeatingCommand.encode_temperature(-0.02) == "0000"
    rep_temp = OWNHeatingCommand.report_temperature("000", -3.2)
    assert str(rep_temp) == "*#4*000*0*1032##"
    wr_temp = OWNHeatingCommand.write_temperature("000", -3.2)
    assert str(wr_temp) == "*#4*000*#0*1032##"
    assert "-3.2°C" in wr_temp.human_readable_log
    ev_temp_000 = OWNHeatingEvent("*#4*000*0*1032##")
    assert ev_temp_000.unique_id == "4-#0"
    assert ev_temp_000.main_temperature == -3.2
    ev_temp_101 = OWNHeatingEvent("*#4*101*0*1032##")
    assert ev_temp_101.unique_id == "4-101"
    assert ev_temp_101.probe_temperature == -3.2
    assert ev_temp_101.secondary_temperature == [1, -3.2]
    temp_q = OWNHeatingCommand("*#4*000*0##")
    assert temp_q.is_temperature_query is True

    # Energy report builders & queries
    en_q = OWNEnergyCommand("*#18*51*113##")
    assert en_q.is_dimension_query is True
    assert en_q.is_auto_update_command is False
    assert en_q.stream_duration is None
    en_stream = OWNEnergyCommand.start_sending_instant_power("51", duration=65)
    assert en_stream.is_auto_update_command is True
    assert en_stream.stream_duration == 65
    assert str(OWNEnergyCommand.report_active_power("51", 640)) == "*#18*51*113*640##"
    assert str(OWNEnergyCommand.report_total_energy("51", 12345)) == "*#18*51*51*12345##"
    assert str(OWNEnergyCommand.report_current_month_energy("51", 500)) == "*#18*51*52*500##"
    assert str(OWNEnergyCommand.report_current_month_energy("51", 500, 2026, 10)) == "*#18*51*52#26#10*500##"
    assert str(OWNEnergyCommand.report_partial_month_energy("51", 300)) == "*#18*51*53*300##"
    assert str(OWNEnergyCommand.report_partial_month_energy("51", 300, 10)) == "*#18*51*53#10*300##"
    assert str(OWNEnergyCommand.report_partial_day_energy("51", 120)) == "*#18*51*54*120##"
    assert str(OWNEnergyCommand.report_partial_day_energy("51", 120, 18)) == "*#18*51*54#18*120##"
    assert str(OWNEnergyCommand.report_streaming_state("51", 65, 1)) == "*#18*51*1200#1*65##"

    # Gateway clock builders & queries
    clk_q = OWNGatewayCommand("*#13**22##")
    assert clk_q.is_clock_query is True
    sample_dt = dt.datetime(2026, 10, 18, 14, 30, 0, tzinfo=dt.timezone.utc)
    assert str(OWNGatewayCommand.set_datetime(sample_dt, "Europe/Brussels")) == "*#13**#22*16*30*00*002*00*18*10*2026##"
    assert str(OWNGatewayCommand.report_datetime(sample_dt, "Europe/Brussels")) == "*#13**22*16*30*00*002*00*18*10*2026##"
    assert str(OWNGatewayCommand.set_date(sample_dt, "Europe/Brussels")) == "*#13**#1*00*18*10*2026##"
    assert str(OWNGatewayCommand.report_date(sample_dt, "Europe/Brussels")) == "*#13**1*00*18*10*2026##"
    assert str(OWNGatewayCommand.set_time(sample_dt, "Europe/Brussels")) == "*#13**#0*16*30*00*002##"
    assert str(OWNGatewayCommand.report_time(sample_dt, "Europe/Brussels")) == "*#13**0*16*30*00*002##"
    # Naive time with explicit time_zone (string or tzinfo) and aware time with/without time_zone
    from zoneinfo import ZoneInfo

    naive_t = dt.time(12, 0, 0)
    aware_t = dt.time(12, 0, 0, tzinfo=dt.timezone.utc)
    zone_t = dt.time(12, 0, 0, tzinfo=ZoneInfo("Europe/Brussels"))
    assert str(OWNGatewayCommand.set_time(aware_t)) == "*#13**#0*12*00*00*000##"
    assert (
        str(OWNGatewayCommand.set_time(aware_t, dt.timezone(dt.timedelta(hours=2))))
        == "*#13**#0*14*00*00*002##"
    )
    assert str(OWNGatewayCommand.set_time(zone_t)).startswith("*#13**#0*12*00*00*00")
    assert str(OWNGatewayCommand.set_time(naive_t, dt.timezone.utc)) == "*#13**#0*12*00*00*000##"
    assert str(OWNGatewayCommand.report_time(naive_t, "America/New_York")).startswith("*#13**0*12*00*00*10")
    # The TZ field carries whole hours only: half- and quarter-hour offsets raise
    for tz_name in ("Asia/Kolkata", "Asia/Kathmandu", "America/St_Johns"):
        with pytest.raises(ValueError, match="whole number of hours"):
            OWNGatewayCommand.set_datetime(sample_dt, tz_name)
        with pytest.raises(ValueError, match="whole number of hours"):
            OWNGatewayCommand.report_time(naive_t, tz_name)
        with pytest.raises(ValueError, match="whole number of hours"):
            OWNGatewayCommand.set_time_to_now(tz_name)


def test_expose_builders_infeasible_inputs() -> None:
    import datetime as dt

    from OWNd.message import (
        OWNAutomationCommand,
        OWNEnergyCommand,
        OWNGatewayCommand,
        OWNHeatingCommand,
        OWNLightingCommand,
    )

    # 1. WHO 1 report_brightness
    for bad_where in ("", "   ", "11*1"):
        with pytest.raises(ValueError, match="non-empty address"):
            OWNLightingCommand.report_brightness(bad_where, 50)
    for bad_int in (True, False, 50.9, 0.5, float("inf"), float("-inf"), float("nan")):
        with pytest.raises(ValueError, match="must be integers"):
            OWNLightingCommand.report_brightness("11", bad_int)  # type: ignore[arg-type]
        with pytest.raises(ValueError, match="must be integers"):
            OWNLightingCommand.report_brightness("11", 50, bad_int)  # type: ignore[arg-type]
    for bad_lvl in (-1, 101):
        with pytest.raises(ValueError, match="brightness level must be between 0 and 100"):
            OWNLightingCommand.report_brightness("11", bad_lvl)
    for bad_trans in (-1, 256):
        with pytest.raises(ValueError, match="transition must be between 0 and 255"):
            OWNLightingCommand.report_brightness("11", 50, bad_trans)

    # 2. WHO 2 set_shutter_level & report_shutter_level
    for bad_set_lvl in (True, 50.9, float("inf"), -1, 101):
        with pytest.raises(ValueError, match="shutter level must be between 0 and 100"):
            OWNAutomationCommand.set_shutter_level("21", bad_set_lvl)  # type: ignore[arg-type]
    for bad_where in ("", "21*1"):
        with pytest.raises(ValueError, match="non-empty address"):
            OWNAutomationCommand.report_shutter_level(bad_where, 50)
    for bool_args in (
        (True, 10, 0, 0),
        (50, True, 0, 0),
        (50, 10, True, 0),
        (50, 10, 0, True),
        (50.9, 10, 0, 0),
        (50, 10.5, 0, 0),
        (50, 10, 0.5, 0),
        (50, 10, 0, 1.5),
        (float("inf"), 10, 0, 0),
        (50, float("inf"), 0, 0),
        (50, 10, float("inf"), 0),
        (50, 10, 0, float("inf")),
    ):
        with pytest.raises(ValueError, match="must be integers"):
            OWNAutomationCommand.report_shutter_level("21", *bool_args)  # type: ignore[arg-type]
    for bad_lvl in (-1, 101, 254, 256):
        with pytest.raises(ValueError, match="shutter level must be between 0 and 100 or 255"):
            OWNAutomationCommand.report_shutter_level("21", bad_lvl)
    for bad_state in (9, 16):
        with pytest.raises(ValueError, match="shutter state must be between 10 and 15"):
            OWNAutomationCommand.report_shutter_level("21", 50, state=bad_state)
    for bad_pr, bad_inf in ((-1, 0), (256, 0), (0, -1), (0, 256)):
        with pytest.raises(ValueError, match="priority and info must be between 0 and 255"):
            OWNAutomationCommand.report_shutter_level(
                "21", 50, state=10, priority=bad_pr, info=bad_inf
            )
    assert (
        str(OWNAutomationCommand.report_shutter_level("31", 40, state=10, priority="00001"))
        == "*#2*31*10*10*40*1*0##"
    )

    # 3. WHO 4 encode_temperature, report_temperature, write_temperature
    assert OWNHeatingCommand.encode_temperature(20.25) == "0203"
    assert OWNHeatingCommand.encode_temperature(20.35) == "0204"
    assert OWNHeatingCommand.encode_temperature(-20.25) == "1203"
    for non_finite in (True, False, float("nan"), float("inf"), float("-inf")):
        with pytest.raises(ValueError, match="temperature must be finite"):
            OWNHeatingCommand.encode_temperature(non_finite)
    for out_of_range in (-100.0, -150.0, 100.0, 150.0):
        with pytest.raises(ValueError, match="temperature must be between -99.9 and 99.9"):
            OWNHeatingCommand.encode_temperature(out_of_range)
    for bad_where in ("", "000*1"):
        with pytest.raises(ValueError, match="non-empty address"):
            OWNHeatingCommand.report_temperature(bad_where, 20.0)
        with pytest.raises(ValueError, match="non-empty address"):
            OWNHeatingCommand.write_temperature(bad_where, 20.0)

    # 4. WHO 18 energy report builders
    for bad_val in (True, False, -1, -0.1, float("nan"), float("inf"), float("-inf")):
        with pytest.raises(ValueError, match="must be a finite non-negative number"):
            OWNEnergyCommand.report_active_power("51", bad_val)
        with pytest.raises(ValueError, match="must be a finite non-negative number"):
            OWNEnergyCommand.report_total_energy("51", bad_val)
        with pytest.raises(ValueError, match="must be a finite non-negative number"):
            OWNEnergyCommand.report_current_month_energy("51", bad_val)
        with pytest.raises(ValueError, match="must be a finite non-negative number"):
            OWNEnergyCommand.report_partial_month_energy("51", bad_val)
        with pytest.raises(ValueError, match="must be a finite non-negative number"):
            OWNEnergyCommand.report_partial_day_energy("51", bad_val)

    with pytest.raises(ValueError, match="both be provided or both omitted"):
        OWNEnergyCommand.report_current_month_energy("51", 100, year=2026, month=None)
    with pytest.raises(ValueError, match="both be provided or both omitted"):
        OWNEnergyCommand.report_current_month_energy("51", 100, year=None, month=10)
    for bad_ym in (
        (True, 10),
        (2026, False),
        (2026.5, 10),
        (2026, 10.5),
        (float("inf"), 10),
        (2026, float("inf")),
    ):
        with pytest.raises(ValueError, match="year and month must be integers"):
            OWNEnergyCommand.report_current_month_energy("51", 100, year=bad_ym[0], month=bad_ym[1])  # type: ignore[arg-type]
    for bad_year in (1999, 2100):
        with pytest.raises(ValueError, match="year must be between 2000 and 2099"):
            OWNEnergyCommand.report_current_month_energy("51", 100, year=bad_year, month=10)
    for bad_month in (0, 13):
        with pytest.raises(ValueError, match="month must be between 1 and 12"):
            OWNEnergyCommand.report_current_month_energy("51", 100, year=2026, month=bad_month)
        with pytest.raises(ValueError, match="month must be between 1 and 12"):
            OWNEnergyCommand.report_partial_month_energy("51", 100, month=bad_month)
    for bad_pm in (True, 10.5, float("inf")):
        with pytest.raises(ValueError, match="month must be between 1 and 12"):
            OWNEnergyCommand.report_partial_month_energy("51", 100, month=bad_pm)  # type: ignore[arg-type]
    for bad_day in (0, 32, True, 18.5, float("inf")):
        with pytest.raises(ValueError, match="day must be between 1 and 31"):
            OWNEnergyCommand.report_partial_day_energy("51", 100, day=bad_day)  # type: ignore[arg-type]

    for bad_de in (
        (True, 1),
        (60, False),
        (60.5, 1),
        (60, 1.5),
        (float("inf"), 1),
        (60, float("inf")),
    ):
        with pytest.raises(ValueError, match="duration and energy_type must be integers"):
            OWNEnergyCommand.report_streaming_state("51", bad_de[0], bad_de[1])  # type: ignore[arg-type]
    for bad_et in (0, 5):
        with pytest.raises(ValueError, match="energy_type must be between 1 and 4"):
            OWNEnergyCommand.report_streaming_state("51", 60, energy_type=bad_et)
    for bad_dur in (-1, 256):
        with pytest.raises(ValueError, match="duration must be between 0 and 255"):
            OWNEnergyCommand.report_streaming_state("51", bad_dur, energy_type=1)

    # 5. WHO 13 gateway clock builders
    for bad_dt in ("2026-01-01", dt.date(2026, 1, 1), dt.time(12, 0)):
        with pytest.raises(ValueError, match="dt must be a datetime.datetime instance"):
            OWNGatewayCommand.set_datetime(bad_dt)  # type: ignore[arg-type]
        with pytest.raises(ValueError, match="dt must be a datetime.datetime instance"):
            OWNGatewayCommand.report_datetime(bad_dt)  # type: ignore[arg-type]
    naive_dt = dt.datetime(2026, 10, 18, 12, 0, 0)
    with pytest.raises(ValueError, match="Naive datetime/time requires an explicit time_zone"):
        OWNGatewayCommand.set_datetime(naive_dt)
    with pytest.raises(ValueError, match="Naive datetime/time requires an explicit time_zone"):
        OWNGatewayCommand.report_datetime(naive_dt)
    with pytest.raises(ValueError, match="Naive datetime/time requires an explicit time_zone"):
        OWNGatewayCommand.set_date(naive_dt)
    with pytest.raises(ValueError, match="Naive datetime/time requires an explicit time_zone"):
        OWNGatewayCommand.report_date(naive_dt)
    with pytest.raises(ValueError, match="Naive datetime/time requires an explicit time_zone"):
        OWNGatewayCommand.set_time(naive_dt)
    with pytest.raises(ValueError, match="Naive datetime/time requires an explicit time_zone"):
        OWNGatewayCommand.report_time(naive_dt)
    with pytest.raises(ValueError, match="Naive datetime/time requires an explicit time_zone"):
        OWNGatewayCommand.set_time(dt.time(12, 0, 0))
    with pytest.raises(ValueError, match="Naive datetime/time requires an explicit time_zone"):
        OWNGatewayCommand.report_time(dt.time(12, 0, 0))
    with pytest.raises(ValueError, match="time_zone must be a datetime.tzinfo"):
        OWNGatewayCommand.set_datetime(naive_dt, 123)  # type: ignore[arg-type]
    with pytest.raises(ValueError, match="time_zone must be a datetime.tzinfo"):
        OWNGatewayCommand.set_date(dt.date(2026, 10, 18), 123)  # type: ignore[arg-type]
    assert (
        str(OWNGatewayCommand.set_datetime(naive_dt, dt.timezone.utc))
        == "*#13**#22*12*00*00*000*00*18*10*2026##"
    )
    assert (
        str(OWNGatewayCommand.set_date(naive_dt, dt.timezone.utc))
        == "*#13**#1*00*18*10*2026##"
    )
    assert (
        str(OWNGatewayCommand.set_date(dt.date(2026, 10, 18), dt.timezone.utc))
        == "*#13**#1*00*18*10*2026##"
    )
    assert (
        str(OWNGatewayCommand.set_time(naive_dt, dt.timezone.utc))
        == "*#13**#0*12*00*00*000##"
    )
    for bad_year_dt in (
        dt.datetime(1999, 12, 31, 12, 0, tzinfo=dt.timezone.utc),
        dt.datetime(2100, 1, 1, 12, 0, tzinfo=dt.timezone.utc),
    ):
        with pytest.raises(ValueError, match="year must be between 2000 and 2099"):
            OWNGatewayCommand.set_datetime(bad_year_dt)
        with pytest.raises(ValueError, match="year must be between 2000 and 2099"):
            OWNGatewayCommand.report_datetime(bad_year_dt)

    for bad_d in ("2026-01-01", dt.time(12, 0), 12345):
        with pytest.raises(ValueError, match="d must be a datetime.date"):
            OWNGatewayCommand.set_date(bad_d)  # type: ignore[arg-type]
        with pytest.raises(ValueError, match="d must be a datetime.date"):
            OWNGatewayCommand.report_date(bad_d)  # type: ignore[arg-type]
    for bad_year_d in (dt.date(1999, 12, 31), dt.date(2100, 1, 1)):
        with pytest.raises(ValueError, match="year must be between 2000 and 2099"):
            OWNGatewayCommand.set_date(bad_year_d)
        with pytest.raises(ValueError, match="year must be between 2000 and 2099"):
            OWNGatewayCommand.report_date(bad_year_d)

    for bad_t in ("12:00:00", dt.date(2026, 1, 1), 12345):
        with pytest.raises(ValueError, match="t must be a datetime.time"):
            OWNGatewayCommand.set_time(bad_t)  # type: ignore[arg-type]
        with pytest.raises(ValueError, match="t must be a datetime.time"):
            OWNGatewayCommand.report_time(bad_t)  # type: ignore[arg-type]


