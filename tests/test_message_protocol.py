"""Regression tests for OpenWebNet message protocol edge cases."""

from __future__ import annotations

import datetime

import pytest

from OWNd.message import (
    OWNAlarmCommand,
    OWNAutomationCommand,
    OWNAutomationEvent,
    OWNCENPlusEvent,
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
    MESSAGE_TYPE_FAN_SPEED,
    OWNMessage,
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
    assert str(OWNAlarmCommand.arm_away()) == "*5*1*0##"
    assert str(OWNAlarmCommand.arm_home()) == "*5*1*0##"
    assert str(OWNAlarmCommand.trigger()) == "*5*17*0##"
    assert str(OWNAlarmCommand.panic()) == "*5*17*0##"
    assert str(OWNAlarmCommand.status()) == "*#5*0##"
    assert str(OWNAlarmCommand.status("1")) == "*#5*#1##"
    assert str(OWNAlarmCommand.status("#2")) == "*#5*#2##"
    assert str(OWNAlarmCommand.status(None)) == "*#5##"
    assert str(OWNAlarmCommand.status("")) == "*#5##"
    assert isinstance(OWNCommand.parse("*5*2*0##"), OWNAlarmCommand)


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
    assert str(OWNHeatingCommand.set_fan_speed("1", 2)) == "*#4*#1*#11*2##"

    automatic = OWNHeatingEvent("*#4*1*11*0##")
    assert automatic.fan_speed == 0
    assert automatic.fan_on is True


def test_shutter_dimension_10_supports_short_and_full_replies() -> None:
    short_reply = OWNAutomationEvent("*#2*21*10*10*75##")
    full_reply = OWNAutomationEvent("*#2*21*10*10*75*1*0##")

    assert short_reply.current_position == 75
    assert full_reply.current_position == 75
    assert str(OWNAutomationCommand.get_shutter_status("21")) == "*#2*21*10##"


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
