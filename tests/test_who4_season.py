"""WHAT 1 / 0 on WHO 4 is the season (zone operation mode), not an operating mode.

Legrand WHO 4 v2.0.0 p. 5 (WHAT table: 0 conditioning mode, 1 heating mode), p. 13,
16, 19 and 63 (zone operation mode acquire frame, listed next to the setpoint frames);
libqtdevices TS10_1_0_23 probe_device.cpp:240-253 keeps a zone in automatic on it; the
MyHomeServer1 translator emits it together with the dimension 12 setpoint report
(512 of 534 dimension-12 reports in the emitted corpus).
"""

from __future__ import annotations

import pytest

from OWNd.message import (
    CLIMATE_MODE_AUTO,
    CLIMATE_MODE_COOL,
    CLIMATE_MODE_HEAT,
    CLIMATE_MODE_OFF,
    MESSAGE_TYPE_MODE,
    MESSAGE_TYPE_MODE_TARGET,
    MESSAGE_TYPE_SEASON,
    SEASON_CONDITIONING,
    SEASON_HEATING,
    OWNEvent,
    OWNHeatingEvent,
)


@pytest.mark.parametrize(
    ("frame", "season", "zone"),
    [
        ("*4*1*23##", SEASON_HEATING, 23),
        ("*4*0*23##", SEASON_CONDITIONING, 23),
        ("*4*1*#0##", SEASON_HEATING, 0),
        ("*4*0*#0#1##", SEASON_CONDITIONING, 1),
    ],
)
def test_bare_what_0_and_1_are_season_frames(frame: str, season: str, zone: int) -> None:
    event = OWNEvent.parse(frame)
    assert isinstance(event, OWNHeatingEvent)
    assert event.message_type == MESSAGE_TYPE_SEASON
    assert event.season == season
    assert event.mode is None
    assert event.zone == zone
    assert event.human_readable_log == f"Zone {zone}'s season is {season}."


@pytest.mark.parametrize(
    ("frame", "mode", "season", "message_type"),
    [
        ("*4*110*#1##", CLIMATE_MODE_HEAT, SEASON_HEATING, MESSAGE_TYPE_MODE),
        ("*4*111*#1##", CLIMATE_MODE_HEAT, SEASON_HEATING, MESSAGE_TYPE_MODE),
        ("*4*210*#1##", CLIMATE_MODE_COOL, SEASON_CONDITIONING, MESSAGE_TYPE_MODE),
        ("*4*110#0215*#0##", CLIMATE_MODE_HEAT, SEASON_HEATING, MESSAGE_TYPE_MODE_TARGET),
        ("*4*102*1##", CLIMATE_MODE_OFF, SEASON_HEATING, MESSAGE_TYPE_MODE),
        ("*4*202*1##", CLIMATE_MODE_OFF, SEASON_CONDITIONING, MESSAGE_TYPE_MODE),
        ("*4*103*1##", CLIMATE_MODE_OFF, SEASON_HEATING, MESSAGE_TYPE_MODE),
        ("*4*1102*#0##", CLIMATE_MODE_HEAT, SEASON_HEATING, MESSAGE_TYPE_MODE),
        ("*4*2201*#0##", CLIMATE_MODE_COOL, SEASON_CONDITIONING, MESSAGE_TYPE_MODE),
        ("*4*311*#1##", CLIMATE_MODE_AUTO, None, MESSAGE_TYPE_MODE),
        ("*4*303*1##", CLIMATE_MODE_OFF, None, MESSAGE_TYPE_MODE),
        ("*4*3102*#0##", CLIMATE_MODE_AUTO, None, MESSAGE_TYPE_MODE),
    ],
)
def test_season_of_mode_whats(frame: str, mode: str, season: str | None, message_type: str) -> None:
    event = OWNHeatingEvent(frame)
    assert event.mode == mode
    assert event.season == season
    assert event.message_type == message_type


def test_non_mode_frames_have_no_season() -> None:
    assert OWNHeatingEvent("*#4*1*0*0215##").season is None
    assert OWNHeatingEvent("*4*21*#0##").season is None
