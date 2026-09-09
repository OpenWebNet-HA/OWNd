"""Regression tests for OpenWebNet message protocol edge cases."""

from __future__ import annotations

import pytest

from OWNd.message import (
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
    OWNMessage,
    OWNStatusRequest,
)


def test_invalid_message_has_defensive_defaults() -> None:
    message = OWNMessage("not-an-openwebnet-frame")

    assert message.is_valid is False
    assert message.who is None
    assert message.where is None
    assert message.dimension is None


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

    assert isinstance(alarm, OWNStatusRequest)
    assert alarm.where is None
    assert alarm.unique_id == "5"
    assert isinstance(auxiliary, OWNStatusRequest)
    assert auxiliary.where is None
    assert auxiliary.unique_id == "9"
    assert str(OWNStatusRequest.request(9)) == "*#9##"
    assert str(OWNStatusRequest.request(9, "1")) == "*#9*1##"


def test_f454_time_without_timezone_is_parsed_safely() -> None:
    event = OWNGatewayEvent("*#13**0*14*30*45##")
    command = OWNGatewayCommand("*#13**#0*12*00*00##")

    assert event._hour == "14"
    assert event._minute == "30"
    assert event._second == "45"
    assert event._timezone == ""
    assert command._hour == "12"
    assert command._timezone == ""


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
