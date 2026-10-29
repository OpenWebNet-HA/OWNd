"""WHO 13 Dimension 27: gateway model name as ``#``-separated ASCII codes.

Live F461 2.0.11 (2026-10-23): ``*#13**27##`` -> ``*#13**27*70#52#54#49##``
("F461"). Live MyHomeServer1 3.87.13 (2026-10-24):
``*#13**27*77#121#72#111#109#101#83#101#114#118#101#114#49##``
("MyHomeServer1"). Both are in the MyHOME#799 trace fixtures. No oracle suite
sends ``*#13**27##``.
"""

from __future__ import annotations

import pytest

from OWNd.message import OWNEvent, OWNGatewayCommand, OWNGatewayEvent, OWNMessage


@pytest.mark.parametrize(
    ("frame", "value", "name"),
    [
        ("*#13**27*70#52#54#49##", "70#52#54#49", "F461"),
        (
            "*#13**27*77#121#72#111#109#101#83#101#114#118#101#114#49##",
            "77#121#72#111#109#101#83#101#114#118#101#114#49",
            "MyHomeServer1",
        ),
    ],
)
def test_model_name_reply_parses(frame: str, value: str, name: str) -> None:
    message = OWNMessage.parse(frame)

    assert isinstance(message, OWNGatewayEvent)
    assert message.is_dimension_reply
    assert message.dimension == 27
    assert message.dimension_value == [value]
    assert message.dimension_param == []
    assert message.model_name == name
    assert message.human_readable_log == f"Gateway's model name is: {name}."
    assert str(message) == frame


@pytest.mark.parametrize(
    "frame",
    [
        "*#13**27*70#52#54#49##",
        "*#13**27*77#121#72#111#109#101#83#101#114#118#101#114#49##",
        "*#13**27*70#7#300##",
        "*#13**27*70*52*54*49##",
    ],
)
def test_event_parse_matches_message_parse(frame: str) -> None:
    """The event session (``OWNEvent.parse``) decodes the same object as ``OWNMessage.parse``."""
    event = OWNEvent.parse(frame)
    message = OWNMessage.parse(frame)

    assert isinstance(event, OWNGatewayEvent)
    assert type(event) is type(message)
    assert str(event) == str(message) == frame
    assert event.dimension_value == message.dimension_value
    assert event.model_name == message.model_name
    assert event.human_readable_log == message.human_readable_log


def test_model_name_with_non_printable_codes_is_not_decoded() -> None:
    message = OWNMessage.parse("*#13**27*70#7#300##")

    assert isinstance(message, OWNGatewayEvent)
    assert message.model_name is None


@pytest.mark.parametrize(
    "frame",
    [
        "*#13**27*70*52*54*49##",  # the general '*'-separated form is not a name
        "*#13**27*70##",  # a single code without '#' is not a name
    ],
)
def test_other_dimension_27_shapes_are_not_decoded(frame: str) -> None:
    message = OWNMessage.parse(frame)

    assert isinstance(message, OWNGatewayEvent)
    assert message.model_name is None
    assert "model name" not in message.human_readable_log


def test_model_name_request_is_a_gateway_command() -> None:
    message = OWNMessage.parse("*#13**27##")

    assert isinstance(message, OWNGatewayCommand)
    assert message.is_dimension_request


@pytest.mark.parametrize(
    "frame",
    [
        "*#13**27*70#52#54#49*1##",  # a second value after the codes
        "*#13**27*70#1234##",  # a code longer than three digits is no character
        "*#13**27*70#" + "9" * 5000 + "##",  # never reaches int() on a huge string
        "*#13**27*70#52*54#49##",  # mixed separators
        "*#13**12*70#52##",  # another dimension with a '#' value
        "*#1*11*1*#5##",  # not for WHO 1
    ],
)
def test_hash_values_elsewhere_still_do_not_parse(frame: str) -> None:
    assert OWNMessage.parse(frame) is None


def test_model_name_with_unicode_digit_codes_does_not_parse() -> None:
    """``int("٧٠")`` is 70, but non-ASCII digits are not OpenWebNet wire bytes.

    ``OWNMessage.parse`` has no pattern for the frame and returns ``None``;
    the event session's ``OWNEvent.parse`` builds its usual invalid event for
    an unmatched WHO 13 frame (as for any unparsed frame), with no name.
    """
    frame = "*#13**27*\u0667\u0660#\u0665\u0662##"

    assert OWNMessage.parse(frame) is None

    event = OWNEvent.parse(frame)
    assert isinstance(event, OWNGatewayEvent)
    assert not event.is_valid
    assert event.model_name is None
    assert "model name" not in event.human_readable_log
