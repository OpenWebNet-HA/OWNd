"""WHO 4 Dimension 14 setpoint replies with a ``#``-prefixed value (MyHOME#139).

``*#4*#1*14*#0230*1##`` is the frame a user's central unit sent in MyHOME#139
("Data received is not a message"); no oracle suite and no live capture of
ours contains it. Only this shape is accepted; a ``#`` in any other value
still does not parse.
"""

from __future__ import annotations

import pytest

from OWNd.message import MESSAGE_TYPE_TARGET_TEMPERATURE, OWNHeatingEvent, OWNMessage


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
    ],
)
def test_hash_values_elsewhere_still_do_not_parse(frame: str) -> None:
    assert OWNMessage.parse(frame) is None
