"""WHO 15 / WHO 25 frames without a WHAT are not events; CEN buttons are integers (OWNd#160 review).

A status request echoed on a monitor session (``*#15*WHERE##``, ``*#25*WHERE##``) or a
dimension form (``*#15*WHERE*1*0##``) has no WHAT. ``OWNAlarmEvent``, ``OWNDoorEntryEvent``
and ``OWNIntercomEvent`` already fail closed on a missing WHAT; ``OWNCENEvent`` read it as a
press of "Button None" and ``OWNDryContactEvent`` as "Sensor N detected OFF". Published
frames decode exactly as before (``tests/test_message_edges.py``
``test_who25_routing_and_bounds_safety`` pins them too).
"""

from __future__ import annotations

import pytest

from OWNd.message import (
    OWNCenCommand,
    OWNCENEvent,
    OWNCenPlusCommand,
    OWNDryContactCommand,
    OWNDryContactEvent,
    OWNEvent,
    OWNMessage,
)


@pytest.mark.parametrize("frame", ["*#15*21##", "*#15*21*1*0##"])
def test_a_what_less_cen_frame_is_not_a_press(frame: str) -> None:
    event = OWNEvent.parse(frame)
    assert isinstance(event, OWNCENEvent)
    assert event.push_button is None
    assert event.is_pressed is False
    assert event.is_held is False
    assert event.is_released_after_short_press is False
    assert event.is_released_after_long_press is False
    assert event.human_readable_log == "CEN object 21 sent no button: the frame carries no WHAT (a *#15*WHERE## status form, not a pushbutton event)."
    assert "Button None" not in event.human_readable_log


def test_an_empty_what_tag_is_no_what_either() -> None:
    """``*15**21##`` / ``*25**339##`` are not valid frames (no WHERE is read); they fail closed too."""
    cen = OWNEvent.parse("*15**21##")
    assert isinstance(cen, OWNCENEvent)
    assert cen.is_valid is False and cen.push_button is None and cen.is_pressed is False
    assert "sent no button" in cen.human_readable_log
    contact = OWNEvent.parse("*25**339##")
    assert isinstance(contact, OWNDryContactEvent)
    assert contact.is_valid is False and contact.is_on is None and contact.is_detection is False
    assert "sent no state" in contact.human_readable_log


@pytest.mark.parametrize(
    ("frame", "pressed", "held", "short", "long", "log"),
    [
        ("*15*1*21##", True, False, False, False, "Button 1 of CEN object 21 has been pressed."),
        ("*15*1#3*21##", False, True, False, False, "Button 1 of CEN object 21 is being held pressed."),
        ("*15*1#1*21##", False, False, True, False, "Button 1 of CEN object 21 has been released after a short press."),
        ("*15*1#2*21##", False, False, False, True, "Button 1 of CEN object 21 has been released after a long press."),
    ],
)
def test_cen_pushbutton_frames_decode_as_before(frame: str, pressed: bool, held: bool, short: bool, long: bool, log: str) -> None:
    event = OWNEvent.parse(frame)
    assert isinstance(event, OWNCENEvent)
    assert (event.is_pressed, event.is_held, event.is_released_after_short_press, event.is_released_after_long_press) == (pressed, held, short, long)
    assert event.human_readable_log == log


@pytest.mark.parametrize(
    ("frame", "parse"),
    [
        ("*#25*339##", OWNEvent.parse),  # the status request seen on a monitor session
        ("*#25*339*1*0##", OWNMessage.parse),  # a dimension form routes to the event parser
        ("*#25*339*1*0##", OWNEvent.parse),
    ],
)
def test_a_what_less_dry_contact_frame_has_no_state(frame: str, parse) -> None:  # type: ignore[no-untyped-def]
    event = parse(frame)
    assert isinstance(event, OWNDryContactEvent)
    assert event.sensor == "39"
    assert event.is_on is None
    assert event.is_detection is False
    assert event.human_readable_log == "Sensor 39 sent no state: the frame carries no WHAT (a *#25*WHERE## status form, not a WHAT 31 / 32 report)."


@pytest.mark.parametrize(
    ("frame", "sensor", "is_on", "detection", "log"),
    [
        ("*25*31#1*339##", "39", True, True, "Sensor 39 detected ON."),  # golden dry_contact.event.on.339
        ("*25*32#1*33##", "3", False, True, "Sensor 3 detected OFF."),
        ("*25*31#0*3100##", "100", True, False, "Sensor 100 reported ON."),
        ("*25*31*21##", "21", True, True, "Sensor 21 detected ON."),  # no parameter: detection, as pinned
        ("*25*32*2##", "2", False, True, "Sensor 2 detected OFF."),
    ],
)
def test_dry_contact_reports_decode_as_before(frame: str, sensor: str, is_on: bool, detection: bool, log: str) -> None:
    event = OWNMessage.parse(frame)
    assert isinstance(event, OWNDryContactEvent)
    assert (event.sensor, event.is_on, event.is_detection, event.human_readable_log) == (sensor, is_on, detection, log)


def test_the_status_request_itself_still_parses_as_a_command() -> None:
    command = OWNMessage.parse("*#25*339##")  # on the command side it stays the status request
    assert isinstance(command, OWNDryContactCommand)
    assert str(OWNDryContactCommand.status("339")) == "*#25*339##"
    assert isinstance(OWNMessage.parse("*#15*21##"), OWNCenCommand)  # command side: the status request


@pytest.mark.parametrize("button", [True, False, 1.9, 0.5, 31.5])
def test_cen_builders_refuse_bool_and_fractional_buttons(button: object) -> None:
    with pytest.raises(ValueError, match="must be an integer between 0 and 31"):
        OWNCenCommand.press("21", button)  # type: ignore[arg-type]
    with pytest.raises(ValueError, match="must be an integer between 0 and 31"):
        OWNCenPlusCommand.press("21", button)  # type: ignore[arg-type]


def test_cen_builders_accept_integers_and_digit_strings() -> None:
    assert str(OWNCenCommand.press("21", 1)) == "*15*01*21##"
    assert str(OWNCenCommand.press("21", "31")) == "*15*31*21##"
    assert str(OWNCenCommand.press("21", 0)) == "*15*00*21##"
    assert str(OWNCenPlusCommand.press("21", 1)) == "*25*21#1*21##"
    assert str(OWNCenPlusCommand.press("21", "31")) == "*25*21#31*21##"
    with pytest.raises(ValueError, match="between 0 and 31"):
        OWNCenCommand.press("21", 32)
    with pytest.raises(ValueError, match="between 0 and 31"):
        OWNCenPlusCommand.press("21", -1)
