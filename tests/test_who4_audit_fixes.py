"""WHO 4 parser crash guards (Encyclopedia audit of OWNd master, WHO 4 group).

Only crash prevention is pinned here: a frame the grammar accepts but the
decoder could not read (an empty tag where the parser used to call ``int()``
/ ``float()``, a missing value it used to index, the wildcard WHERE ``*``, or
a non-ASCII digit the tokenizer's ``\\d`` lets through) must not raise out of
``OWNMessage.parse`` / ``OWNEvent.parse`` and stays untyped. Every decoded
value, log line and builder keeps its master behaviour; the address-class,
operating-mode, DIMENSION 15 / 19 / 22 and builder-domain findings of the
audit are documentation only (no committed plant trace carries them).
"""

from __future__ import annotations

import pytest

from OWNd.message import (
    CLIMATE_MODE_AUTO,
    CLIMATE_MODE_HEAT,
    CLIMATE_MODE_OFF,
    MESSAGE_TYPE_ACTION,
    MESSAGE_TYPE_FAN_SPEED,
    MESSAGE_TYPE_MAIN_HUMIDITY,
    MESSAGE_TYPE_MAIN_TEMPERATURE,
    MESSAGE_TYPE_MODE,
    MESSAGE_TYPE_MODE_TARGET,
    MESSAGE_TYPE_SEASON,
    MESSAGE_TYPE_TARGET_TEMPERATURE,
    OWNEvent,
    OWNHeatingCommand,
    OWNHeatingEvent,
    OWNMessage,
)


def _event(frame: str) -> OWNHeatingEvent:
    message = OWNMessage.parse(frame)
    assert isinstance(message, OWNHeatingEvent), frame
    return message


def _no_reading(value: object) -> bool:
    """``secondary_temperature`` is a ``[sensor, temperature]`` pair: no reading is ``[None, None]``."""
    return value is None or (isinstance(value, list) and all(v is None for v in value))


# ---------------------------------------------------------------- empty values do not raise


@pytest.mark.parametrize("frame", ["*#4*1*11*##", "*#4*1*60*##"])
def test_empty_fan_speed_and_humidity_values_do_not_raise(frame: str) -> None:
    """``*#4*1*11*##`` raised ``ValueError`` out of the parser; ``*#4*1*60*##`` likewise."""
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


@pytest.mark.parametrize("frame", ["*#4*1*11##", "*#4*1*13##", "*#4*1*60##"])
def test_missing_dimension_values_do_not_raise(frame: str) -> None:
    """``OWNMessage.parse`` reads these as dimension requests; constructing the
    event directly (the event-session path) used to raise ``IndexError``."""
    event = OWNHeatingEvent(frame)
    assert event.is_valid is True and event.dimension in (11, 13, 60)
    assert event.message_type is None
    assert event.fan_speed is None and event.main_humidity is None and event.local_offset is None


@pytest.mark.parametrize(
    ("frame", "message_type"),
    [
        ("*#4*1*12*##", "local_target_temperature"),
        ("*#4*1*13*##", "local_offset"),
        ("*#4*1*14*##", "target_temperature"),
        ("*#4*1*15*##", "secondary_temperature"),
        ("*#4*1*15**##", "secondary_temperature"),
        ("*#4*1*15**0215##", "secondary_temperature"),
        ("*#4*1*15#1**0215##", "secondary_temperature"),
        ("*#4*1*19*##", None),
        ("*#4*1*19*5*##", None),
        ("*#4*1*19**5##", None),
        ("*#4*1*20*##", None),
        ("*#4*1*30*##", None),
    ],
)
def test_empty_tag_dimension_values_parse_without_raising(frame: str, message_type: str | None) -> None:
    """Grammar-accepted empty tags (protocol/frame-syntax.md "Delimiters and empty
    tags") through both parse entry points. The DIMENSION 15 empty sensor slot
    (``*#4*1*15**##``, ``*#4*1*15**0215##``) raised ``ValueError`` from ``int('')``;
    the others stay as on master: typed where master typed them, every value ``None``."""
    for parsed in (OWNMessage.parse(frame), OWNEvent.parse(frame)):
        assert isinstance(parsed, OWNHeatingEvent), frame
        assert parsed.is_valid is True
        assert parsed.zone == 1
        assert parsed.message_type == message_type
        assert _no_reading(parsed.secondary_temperature)  # the property is a [sensor, value] pair
        assert parsed.local_set_temperature is None and parsed.set_temperature is None
        assert parsed.fan_speed is None and parsed.main_humidity is None


@pytest.mark.parametrize("frame", ["*4*1**##", "*4*303**##"])
def test_wildcard_where_does_not_raise(frame: str) -> None:
    """``base.py``'s grammar admits the wildcard WHERE ``*`` for every WHO; it is no
    zone, so the event is zone 0 (as a frame without a WHERE already was) instead
    of ``ValueError`` from ``int('*')``."""
    for parsed in (OWNMessage.parse(frame), OWNEvent.parse(frame)):
        assert isinstance(parsed, OWNHeatingEvent), frame
        assert parsed.zone == 0
        assert parsed.unique_id == "4-#0"  # zone 0 is the central unit's id, as for a missing WHERE


def test_rejected_frames_are_not_a_crash_test() -> None:
    """``*#4*1*12*x##`` fails the frame grammar entirely: no dimension, nothing
    decoded, ``OWNMessage.parse`` returns ``None``. Kept only to say so."""
    event = OWNHeatingEvent("*#4*1*12*x##")
    assert event.is_valid is False and event.dimension is None and event.message_type is None
    assert OWNMessage.parse("*#4*1*12*x##") is None


# ---------------------------------------------------------------- ASCII digits only


@pytest.mark.parametrize(
    ("frame", "attribute"),
    [
        ("*#4*1*11*\uff13*##", "fan_speed"),
        ("*#4*1*15*\uff11*0215##", "secondary_temperature"),
        ("*#4*1*19*\uff15*\uff10##", "is_heating"),
        ("*#4*1*20*\uff11##", "is_active"),
        ("*#4*#0*30*\uff10\uff11*\uff10\uff12*\uff12\uff10\uff12\uff16##", "holiday_end_date"),
        ("*#4*#0*31*\uff11\uff12*\uff13\uff10##", "holiday_end_time"),
        ("*#4*#0*32*\uff10\uff11*\uff13\uff10##", "manual_timed_duration"),
        ("*#4*1*60*\uff14\uff15##", "main_humidity"),
    ],
)
def test_fullwidth_digits_fail_closed(frame: str, attribute: str) -> None:
    """``str.isdigit()`` accepts fullwidth digits and ``base.py``'s ``\\d`` lets them
    through; ``*#4*1*11*３*##`` decoded ``fan_speed`` 3. Every integer field now
    needs ASCII digits, as the DIMENSION 60 humidity value already did."""
    parsed = OWNMessage.parse(frame)
    assert isinstance(parsed, OWNHeatingEvent)
    value = getattr(parsed, attribute)
    value = value() if callable(value) else value
    assert value in (None, False) or _no_reading(value)
    assert parsed.message_type in (None, "secondary_temperature")
    assert parsed.human_readable_log == frame


def test_ascii_frames_still_decode_the_same_values() -> None:
    assert _event("*#4*1*15*1*0215##").secondary_temperature == [1, 21.5]
    assert _event("*#4*2*19*5*1##").is_heating() is True
    assert _event("*#4*2#1*20*1##").is_active() is True
    assert _event("*#4*#0*30*01*02*2026##").holiday_end_date == (1, 2, 2026)
    assert _event("*#4*#0*31*12*30##").holiday_end_time == (12, 30)
    assert _event("*#4*#0*32*01*30##").manual_timed_duration == (1, 30)


def test_filled_values_still_decode() -> None:
    fan = _event("*#4*1*11*3*##")
    assert (fan.message_type, fan.fan_speed, fan.fan_on) == (MESSAGE_TYPE_FAN_SPEED, 3, True)
    off = _event("*#4*1*11*15*##")
    assert (off.message_type, off.fan_speed, off.fan_on) == (MESSAGE_TYPE_FAN_SPEED, None, False)
    humidity = _event("*#4*1*60*45##")
    assert (humidity.message_type, humidity.main_humidity) == (MESSAGE_TYPE_MAIN_HUMIDITY, 45.0)
    offset = _event("*#4*1*13*02##")
    assert (offset.message_type, offset.local_offset) == ("local_offset", 2)


# ---------------------------------------------------------------- builder clamp (master behaviour, pinned)


@pytest.mark.parametrize(
    ("temperature", "code"),
    [(4.9, "0050"), (4.0, "0050"), (-3.0, "0050"), (0.0, "0050"), (40.2, "0400"), (40.5, "0400"), (50.0, "0400")],
)
def test_set_temperature_clamps_out_of_range_values(temperature: float, code: str) -> None:
    # MyHOME relies on the clamp (its ``test_set_temperature_clamp_low`` / ``_high``).
    assert str(OWNHeatingCommand.set_temperature("1", temperature, CLIMATE_MODE_HEAT)) == f"*#4*#1*#14*{code}*1##"


def test_set_temperature_in_range_rounds_to_half_degrees() -> None:
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
        ("*#4*2#1*20*1##", 2, "4-2", MESSAGE_TYPE_ACTION, None),
        ("*#4*2*19*5*1##", 2, "4-2", MESSAGE_TYPE_ACTION, None),
        ("*#4*2*11*0##", 2, "4-2", MESSAGE_TYPE_FAN_SPEED, None),
        ("*4*110#0215*#0##", 0, "4-#0", MESSAGE_TYPE_MODE_TARGET, CLIMATE_MODE_HEAT),
        ("*4*202*#0##", 0, "4-#0", MESSAGE_TYPE_MODE, CLIMATE_MODE_OFF),
        ("*4*0*#0#1##", 1, "4-1", MESSAGE_TYPE_SEASON, None),
        ("*#4*#0#1*20*0##", 1, "4-1", MESSAGE_TYPE_ACTION, None),
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
