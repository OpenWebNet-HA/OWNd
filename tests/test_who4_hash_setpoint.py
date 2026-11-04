"""WHO 4 Dimension 14 setpoint replies with a ``#``-prefixed value (MyHOME#139).

``*#4*#1*14*#0230*1##`` is the frame a user's central unit sent in MyHOME#139
("Data received is not a message"); no oracle suite and no live capture of
ours contains it. Only this shape is accepted; a ``#`` in any other value
still does not parse.
"""

from __future__ import annotations

import pytest

from OWNd.message import MESSAGE_TYPE_TARGET_TEMPERATURE, OWNEvent, OWNHeatingEvent, OWNMessage


def test_hash_prefixed_setpoint_parses_as_dimension_14() -> None:
    message = OWNMessage.parse("*#4*#1*14*#0230*1##")

    assert isinstance(message, OWNHeatingEvent)
    assert message.is_dimension_reply
    assert message.dimension == 14
    assert message.zone == 1
    assert message.message_type == MESSAGE_TYPE_TARGET_TEMPERATURE
    assert message.set_temperature == 23.0
    assert message.dimension_value == ["#0230", "1"]
    assert message.dimension_param == []
    assert str(message) == "*#4*#1*14*#0230*1##"
    # The '#' never leaks into the log line.
    assert message.human_readable_log == "Zone 1's target temperature is set to 23.0°C."


def test_event_parse_matches_message_parse() -> None:
    """``OWNEvent.parse`` (the event session's entry point) gives the same event as
    ``OWNMessage.parse``; on master it returned an invalid event (``zone 0``)."""
    event = OWNEvent.parse("*#4*#1*14*#0230*1##")
    message = OWNMessage.parse("*#4*#1*14*#0230*1##")

    assert isinstance(event, OWNHeatingEvent)
    assert event.is_valid
    assert event.zone == 1
    assert event.message_type == MESSAGE_TYPE_TARGET_TEMPERATURE
    assert event.set_temperature == 23.0
    assert event.human_readable_log == message.human_readable_log
    assert str(event) == str(message)


@pytest.mark.parametrize(
    ("frame", "zone", "setpoint"),
    [
        ("*#4*#1*14*#0230*1##", 1, 23.0),
        ("*#4*1*14*#0215*3##", 1, 21.5),
        ("*#4*#0#2*14*#0200*1##", 2, 20.0),
    ],
)
def test_hash_prefixed_setpoint_zone_forms(frame: str, zone: int, setpoint: float) -> None:
    message = OWNMessage.parse(frame)

    assert isinstance(message, OWNHeatingEvent)
    assert message.zone == zone
    assert message.set_temperature == setpoint


def test_plain_setpoint_is_unchanged() -> None:
    message = OWNMessage.parse("*#4*#1*14*0230*1##")

    assert isinstance(message, OWNHeatingEvent)
    assert message.set_temperature == 23.0
    assert message.dimension_value == ["0230", "1"]


@pytest.mark.parametrize(
    "frame",
    [
        "*#4*#1*12*#0230*1##",  # '#' value accepted for dimension 14 only
        "*#1*11*1*#5##",  # not for WHO 1
        "*#4*#1*14*0230*#1##",  # only the setpoint may carry it
        "*#4*#1*14*##0230*1##",  # one '#', not two
        "*#4*#1*14*#02#30*1##",  # no '#' inside the value
        "*#4*#1*14*#*1##",  # a bare '#' is not a value
        # The dimension 14 shape only: one or two values, a four-digit
        # temperature starting with 0 or 1, ASCII digits.
        "*#4*#1*14*#0230*##",  # empty trailing field
        "*#4*#1*14*#0230*1*2*3##",  # too many values
        "*#4*#1*14*#99999*1##",  # not a temperature
        "*#4*#1*14*#230*1##",  # three digits
        "*#4*#1*14*#\u0660\u0662\u0663\u0660*1##",  # non-ASCII digits are not wire bytes
        "*#4*#\u0661*14*#0230*1##",
    ],
)
def test_hash_values_elsewhere_still_do_not_parse(frame: str) -> None:
    assert OWNMessage.parse(frame) is None
