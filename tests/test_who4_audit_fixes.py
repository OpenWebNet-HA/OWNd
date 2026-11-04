"""WHO 4 parser crash guards from the Encyclopedia audit (report 21, row H9).

Only crash prevention is pinned here: a malformed or truncated dimension
reply (an empty or missing value where the parser used to call ``int()`` /
``float()`` or index the value list) must not raise out of
``OWNHeatingEvent``. Every decoded value, log line and builder keeps its
master behaviour; the address-class, operating-mode, DIMENSION 15 / 19 / 22
and builder-domain findings of the audit are documentation only (no
committed plant trace carries them).
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


# ---------------------------------------------------------------- H9: empty values do not raise


@pytest.mark.parametrize("frame", ["*#4*1*11*##", "*#4*1*60*##"])
def test_h9_empty_values_do_not_raise(frame: str) -> None:
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


@pytest.mark.parametrize(
    "frame",
    [
        "*#4*1*11##",
        "*#4*1*13##",
        "*#4*1*60##",
        "*#4*1*11*##",
        "*#4*1*20*##",
        "*#4*1*30*##",
        "*#4*1*60*##",
        "*#4*1*12*x##",
        "*#4*1*13*x##",
        "*#4*1*14*x##",
        "*#4*1*19*x*0##",
        "*#4*1*20*x##",
    ],
)
def test_h9_truncated_or_non_digit_dimension_values_do_not_raise(frame: str) -> None:
    """Constructing the event directly must not raise ``IndexError`` / ``ValueError``."""
    event = OWNHeatingEvent(frame)  # a frame the grammar rejects has no WHERE: zone 0 (master behaviour)
    assert event.fan_speed is None
    assert event.main_humidity is None
    assert event.message_type in (None, "local_offset", "local_target_temperature", "target_temperature")


def test_h9_filled_values_still_decode() -> None:
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
