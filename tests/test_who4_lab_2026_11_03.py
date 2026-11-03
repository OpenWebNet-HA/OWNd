"""WHO 4 fixes from the lab audit of 2026-11-03 (rows L-A1, L-A2, L-A3).

Evidence: the live F461 2.0.11 test plant (``reports/data/live_f418_0010_2026-11-03/
lab_probe_output.txt``: ``*#4*2*2##`` -> ``*#4*2*2*0350##``, ``*#4*2*3##`` ->
``*#4*2*3*0070##``, ``*#4*2*19##`` -> ``*#4*2*19*5*0##`` on zone 2, a KW4691),
the Encyclopedia ``who-4-temperature-control/dimensions.md`` ("DIMENSION 14":
``T`` ``0050..0400``, page 18; "DIMENSION 19": values ``0..8`` plus the
MyHOME-team ``14``, ``15``, ``16``; no Dimension 2 or 3 is published) and the
``lab-2026-11-03`` firmware-oracle suite on the 12 emulated gateways.

- L-A1: Dimensions 2 and 3 decode as ``protection_setpoint`` / ``antifreeze_setpoint``.
- L-A2: a Dimension 14 value outside ``5.0..40.0`` is kept but the log says so;
  the ``set_temperature`` builder keeps clamping (MyHOME relies on the clamp,
  ``test_h19_set_temperature_clamps_out_of_range_values``).
- L-A3: Dimension 19 values outside ``0..8`` and ``14..16`` are not fan speeds.
"""

from __future__ import annotations

import pytest

from OWNd.message import (
    CLIMATE_MODE_HEAT,
    MESSAGE_TYPE_ACTION,
    MESSAGE_TYPE_ANTIFREEZE_SETPOINT,
    MESSAGE_TYPE_PROTECTION_SETPOINT,
    MESSAGE_TYPE_TARGET_TEMPERATURE,
    OWNEvent,
    OWNHeatingCommand,
    OWNHeatingEvent,
    OWNMessage,
)


def _event(frame: str) -> OWNHeatingEvent:
    """Parse through both entry points (D13: ``OWNEvent.parse`` symmetry) and return the event."""
    message = OWNMessage.parse(frame)
    assert isinstance(message, OWNHeatingEvent), frame
    event = OWNEvent.parse(frame)
    assert isinstance(event, OWNHeatingEvent), frame
    assert event.message_type == message.message_type
    assert event.human_readable_log == message.human_readable_log
    return message


# ---------------------------------------------------------------- L-A1: Dimensions 2 and 3


def test_la1_dimension_2_is_the_thermal_protection_setpoint() -> None:
    event = _event("*#4*2*2*0350##")
    assert event.message_type == MESSAGE_TYPE_PROTECTION_SETPOINT
    assert event.protection_setpoint == 35.0
    assert event.antifreeze_setpoint is None
    assert event.set_temperature is None
    assert event.human_readable_log == "Zone 2's thermal protection setpoint is 35.0°C."
    assert event.unique_id == "4-2"
    assert event.zone == 2


def test_la1_dimension_3_is_the_antifreeze_setpoint() -> None:
    event = _event("*#4*2*3*0070##")
    assert event.message_type == MESSAGE_TYPE_ANTIFREEZE_SETPOINT
    assert event.antifreeze_setpoint == 7.0
    assert event.protection_setpoint is None
    assert event.set_temperature is None
    assert event.human_readable_log == "Zone 2's antifreeze setpoint is 7.0°C."


@pytest.mark.parametrize(
    ("frame", "dimension", "expected"),
    [
        ("*#4*1*2*1050##", 2, -5.0),  # SXXX sign like Dimension 14
        ("*#4*1*3*0000##", 3, 0.0),
        ("*#4*#1*2*0350##", 2, 35.0),  # via the central unit
        ("*#4*1#4#01*3*0070##", 3, 7.0),  # bus-interface suffix
    ],
)
def test_la1_values_use_the_who4_temperature_decoding(
    frame: str, dimension: int, expected: float
) -> None:
    event = _event(frame)
    value = event.protection_setpoint if dimension == 2 else event.antifreeze_setpoint
    assert value == expected
    assert f"{expected}°C" in event.human_readable_log


@pytest.mark.parametrize("frame", ["*#4*2*2*##", "*#4*2*3*##"])
def test_la1_an_empty_value_keeps_the_type_without_a_setpoint(frame: str) -> None:
    event = _event(frame)
    expected_type = (
        MESSAGE_TYPE_PROTECTION_SETPOINT
        if frame.startswith("*#4*2*2")
        else MESSAGE_TYPE_ANTIFREEZE_SETPOINT
    )
    assert event.message_type == expected_type
    assert event.protection_setpoint is None
    assert event.antifreeze_setpoint is None
    assert event.human_readable_log == frame  # the raw frame, as for Dimension 12


@pytest.mark.parametrize("frame", ["*#4*2*2*035##", "*#4*2*3*20350##"])
def test_la1_a_value_of_another_shape_keeps_the_type_without_a_setpoint(
    frame: str,
) -> None:
    event = _event(frame)
    assert event.message_type in (
        MESSAGE_TYPE_PROTECTION_SETPOINT,
        MESSAGE_TYPE_ANTIFREEZE_SETPOINT,
    )
    assert event.protection_setpoint is None
    assert event.antifreeze_setpoint is None
    assert event.human_readable_log == frame


@pytest.mark.parametrize(
    "frame", ["*#4*2*#2*0350##", "*#4*2*#3*0070##", "*#4*2*2##", "*#4*2*3##"]
)
def test_la1_reads_and_writes_stay_raw_commands(frame: str) -> None:
    """No builder: the read and the write forms parse as commands, as before."""
    message = OWNMessage.parse(frame)
    assert isinstance(message, OWNHeatingCommand), frame
    assert not hasattr(OWNHeatingCommand, "set_protection_setpoint")
    assert not hasattr(OWNHeatingCommand, "set_antifreeze_setpoint")


def test_la1_other_dimensions_leave_the_new_properties_none() -> None:
    for frame in (
        "*#4*2*14*0230*3##",
        "*#4*2*12*0230*3##",
        "*#4*2*0*0238##",
        "*#4*2*19*5*0##",
        "*4*1*2##",
    ):
        event = _event(frame)
        assert event.protection_setpoint is None, frame
        assert event.antifreeze_setpoint is None, frame


# ---------------------------------------------------------------- L-A2: Dimension 14 range


@pytest.mark.parametrize(
    ("frame", "temperature"),
    [
        ("*#4*1*14*0999*3##", 99.9),
        ("*#4*1*14*0040*3##", 4.0),
        ("*#4*1*14*0401*3##", 40.1),
        ("*#4*1*14*1050*3##", -5.0),
        ("*#4*#1*14*#0999*1##", 99.9),  # '#'-prefixed value
    ],
)
def test_la2_dimension_14_outside_the_published_range_is_kept_and_flagged(
    frame: str, temperature: float
) -> None:
    event = _event(frame)
    assert event.message_type == MESSAGE_TYPE_TARGET_TEMPERATURE
    assert event.set_temperature == temperature
    assert event.human_readable_log == (
        f"Zone 1's target temperature is set to {temperature}°C (outside the published 5.0..40.0 °C range)."
    )


@pytest.mark.parametrize(
    ("frame", "temperature"),
    [
        ("*#4*1*14*0050*3##", 5.0),
        ("*#4*1*14*0400*3##", 40.0),
        ("*#4*2*14*0230*3##", 23.0),  # live F461 2.0.11
        ("*#4*#1*14*#0230*1##", 23.0),
    ],
)
def test_la2_dimension_14_inside_the_published_range_logs_as_before(
    frame: str, temperature: float
) -> None:
    event = _event(frame)
    assert event.set_temperature == temperature
    assert (
        event.human_readable_log
        == f"Zone {event.zone}'s target temperature is set to {temperature}°C."
    )


def test_la2_dimension_14_write_echo_on_the_event_path_is_flagged_too() -> None:
    """``*#4*#1*#14*...##`` is a command for ``OWNMessage.parse``; MyHOME replays the echo through ``OWNEvent.parse``."""
    assert isinstance(OWNMessage.parse("*#4*#1*#14*0999*1##"), OWNHeatingCommand)
    event = OWNEvent.parse("*#4*#1*#14*0999*1##")
    assert isinstance(event, OWNHeatingEvent)
    assert event.message_type == MESSAGE_TYPE_TARGET_TEMPERATURE
    assert event.set_temperature == 99.9
    assert (
        event.human_readable_log
        == "Zone 1's target temperature is set to 99.9°C (outside the published 5.0..40.0 °C range)."
    )


def test_la2_dimension_14_without_a_value_stays_untyped_text() -> None:
    event = _event("*#4*1*14*##")
    assert event.message_type == MESSAGE_TYPE_TARGET_TEMPERATURE
    assert event.set_temperature is None
    assert "outside" not in event.human_readable_log


def test_la2_set_temperature_keeps_the_clamp_myhome_relies_on() -> None:
    """D20/D21 would raise, but the register and MyHOME pin the clamp (``test_h19_...``)."""
    assert (
        str(OWNHeatingCommand.set_temperature("1", 99.9, CLIMATE_MODE_HEAT))
        == "*#4*#1*#14*0400*1##"
    )
    assert (
        str(OWNHeatingCommand.set_temperature("1", 4.0, CLIMATE_MODE_HEAT))
        == "*#4*#1*#14*0050*1##"
    )


# ---------------------------------------------------------------- L-A3: Dimension 19 unpublished values


@pytest.mark.parametrize("value", [9, 10, 13, 17, 99])
def test_la3_unpublished_cooling_valve_value_is_not_a_fan_speed(value: int) -> None:
    event = _event(f"*#4*1*19*{value}*0##")
    assert event.message_type == MESSAGE_TYPE_ACTION
    assert event.is_cooling() is None
    assert event.is_heating() is False
    assert event.cooling_fan_on is None
    assert event.cooling_fan_speed is None
    assert event.fan_on is None
    assert event.is_active() is None
    assert event.human_readable_log == (
        f"Zone 1's cooling valve reports the unpublished valve value {value}; heating valve is off."
    )


@pytest.mark.parametrize("value", [9, 10, 13, 17, 99])
def test_la3_unpublished_heating_valve_value_is_not_a_fan_speed(value: int) -> None:
    event = _event(f"*#4*1*19*0*{value}##")
    assert event.message_type == MESSAGE_TYPE_ACTION
    assert event.is_heating() is None
    assert event.is_cooling() is False
    assert event.fan_on is None
    assert event.fan_speed is None
    assert event.cooling_fan_on is None
    assert event.is_active() is None
    assert event.human_readable_log == (
        f"Zone 1's cooling valve is off; heating valve reports the unpublished valve value {value}."
    )


def test_la3_both_sides_unpublished() -> None:
    event = _event("*#4*1*19*9*9##")
    assert (event.is_cooling(), event.is_heating(), event.is_active()) == (
        None,
        None,
        None,
    )
    assert event.human_readable_log == (
        "Zone 1's cooling valve reports the unpublished valve value 9; "
        "heating valve reports the unpublished valve value 9."
    )


@pytest.mark.parametrize(
    ("frame", "heating", "cooling", "cooling_fan_on", "fan_on"),
    [
        ("*#4*1*19*9*1##", True, None, None, None),  # heating valve on
        ("*#4*1*19*1*9##", None, True, None, None),  # cooling valve on
        ("*#4*1*19*9*6##", True, None, None, True),  # heating fan coil at speed 1
        ("*#4*1*19*8*9##", None, True, True, None),  # cooling fan coil at speed 3
    ],
)
def test_la3_an_active_published_side_keeps_the_zone_active(
    frame: str,
    heating: bool | None,
    cooling: bool | None,
    cooling_fan_on: bool | None,
    fan_on: bool | None,
) -> None:
    event = _event(frame)
    assert event.is_active() is True
    assert event.is_heating() is heating
    assert event.is_cooling() is cooling
    assert event.cooling_fan_on is cooling_fan_on
    assert event.fan_on is fan_on


@pytest.mark.parametrize(
    ("frame", "cooling_fan_on", "fan_on", "active"),
    [
        (
            "*#4*1*19*9*5##",
            None,
            False,
            None,
        ),  # heating fan coil off, cooling unpublished
        ("*#4*1*19*5*9##", False, None, None),
        ("*#4*1*19*9*14##", None, False, None),
        ("*#4*1*19*16*9##", False, None, None),
    ],
)
def test_la3_an_idle_published_side_leaves_the_zone_undecided(
    frame: str, cooling_fan_on: bool | None, fan_on: bool | None, active: bool | None
) -> None:
    event = _event(frame)
    assert event.cooling_fan_on is cooling_fan_on
    assert event.fan_on is fan_on
    assert event.is_active() is active


@pytest.mark.parametrize(
    ("frame", "active", "heating", "cooling", "cooling_fan_on", "fan_on", "log"),
    [
        (
            "*#4*2*19*5*0##",
            False,
            False,
            False,
            False,
            None,
            "Zone 2's cooling fan is off; heating valve is off.",
        ),  # live F461
        (
            "*#4*1*19*8*6##",
            True,
            True,
            True,
            True,
            True,
            "Zone 1's cooling fan is on at speed 3; heating fan is on at speed 1.",
        ),
        (
            "*#4*1*19*0*5##",
            False,
            False,
            False,
            None,
            False,
            "Zone 1's cooling valve is off; heating fan is off.",
        ),
        (
            "*#4*1*19*14*16##",
            False,
            False,
            False,
            False,
            False,
            "Zone 1's cooling fan-coil is off (state 14); heating fan-coil is off (state 16).",
        ),
        (
            "*#4*1*19*0*0##",
            False,
            False,
            False,
            None,
            None,
            "Zone 1's cooling valve is off; heating valve is off.",
        ),
        (
            "*#4*1*19*2*3##",
            True,
            False,
            True,
            None,
            None,
            "Zone 1's cooling valve is opened; heating valve is closed.",
        ),
        (
            "*#4*1*19*4*1##",
            True,
            True,
            False,
            None,
            None,
            "Zone 1's cooling valve is stopped; heating valve is on.",
        ),
        (
            "*#4*1*19*3*4##",
            False,
            False,
            False,
            None,
            None,
            "Zone 1's cooling valve is closed; heating valve is stopped.",
        ),
        (
            "*#4*1*19*1*2##",
            True,
            True,
            True,
            None,
            None,
            "Zone 1's cooling valve is on; heating valve is opened.",
        ),
        (
            "*#4*1*19*6*7##",
            True,
            True,
            True,
            True,
            True,
            "Zone 1's cooling fan is on at speed 1; heating fan is on at speed 2.",
        ),
        (
            "*#4*1*19*7*8##",
            True,
            True,
            True,
            True,
            True,
            "Zone 1's cooling fan is on at speed 2; heating fan is on at speed 3.",
        ),
    ],
)
def test_la3_published_values_decode_as_before(
    frame: str,
    active: bool,
    heating: bool,
    cooling: bool,
    cooling_fan_on: bool | None,
    fan_on: bool | None,
    log: str,
) -> None:
    event = _event(frame)
    assert event.is_active() is active
    assert event.is_heating() is heating
    assert event.is_cooling() is cooling
    assert event.cooling_fan_on is cooling_fan_on
    assert event.fan_on is fan_on
    assert event.human_readable_log == log


# ---------------------------------------------------------------- live F461 2.0.11 write session (2026-11-03 17:25 UTC)


@pytest.mark.parametrize(
    ("frame", "attribute", "value", "log"),
    [
        # *#4*2*#3*0060## ACKed and read back; *#4*2*#2*0340## likewise; *#4*2*#3*0999## NACKed
        (
            "*#4*2*3*0060##",
            "antifreeze_setpoint",
            6.0,
            "Zone 2's antifreeze setpoint is 6.0°C.",
        ),
        (
            "*#4*2*2*0340##",
            "protection_setpoint",
            34.0,
            "Zone 2's thermal protection setpoint is 34.0°C.",
        ),
        # *#4*2*#14*0049*3## ACKed and stored as 0045: a real value below the published bound
        (
            "*#4*2*14*0045*3##",
            "set_temperature",
            4.5,
            "Zone 2's target temperature is set to 4.5°C (outside the published 5.0..40.0 °C range).",
        ),
        (
            "*#4*2*12*0045*3##",
            "local_set_temperature",
            4.5,
            "Zone 2's local target temperature is set to 4.5°C.",
        ),
        # *#4*2*#14*0400*3## ACKed and applied
        (
            "*#4*2*14*0400*3##",
            "set_temperature",
            40.0,
            "Zone 2's target temperature is set to 40.0°C.",
        ),
    ],
)
def test_live_f461_write_readbacks(
    frame: str, attribute: str, value: float, log: str
) -> None:
    event = _event(frame)
    assert getattr(event, attribute) == value
    assert event.human_readable_log == log
