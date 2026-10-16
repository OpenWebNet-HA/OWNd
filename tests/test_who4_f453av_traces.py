"""WHO 4: decoding of real F453AV bus captures (central unit #0, BTicino plant).

Captures: OpenWebNet-HA/OWNd#97 comment 6110745254 (@nce2704), F453AV, 2026-10-11, taken
with the MyHOME trace export while the central unit was driven from the Freedompro app:

* ``Holiday ON``      : daily holiday started on the central unit.
* ``Holiday OFF auto``: the holiday expired by itself.
* ``one zone to cool``: one zone switched Heat -> Cool, the whole plant follows.
* ``Antifreeze ON`` / ``Central to OFF``: central unit modes.
* baseline            : plant in winter, zones on the weekly program.

Only the distinct WHO 4 status frames are pinned here, not the raw exports.
"""

import pytest

from OWNd.message import (
    CLIMATE_MODE_HEAT,
    CLIMATE_MODE_OFF,
    MESSAGE_TYPE_MODE,
    MESSAGE_TYPE_SEASON,
    SEASON_CONDITIONING,
    SEASON_HEATING,
    OWNEvent,
    OWNHeatingEvent,
)


def _parse(raw: str) -> OWNHeatingEvent:
    msg = OWNEvent.parse(raw)
    assert isinstance(msg, OWNHeatingEvent)
    return msg


def test_holiday_on_report_carries_the_program_not_a_temperature():
    # Daily holiday ON: the central answers 115#1101 (program 1), not -10.1 °C.
    msg = _parse("*4*115#1101*#0##")
    assert msg.message_type == MESSAGE_TYPE_MODE
    assert msg.mode == CLIMATE_MODE_HEAT
    assert msg.season == SEASON_HEATING
    assert msg.program == 1
    assert msg.set_temperature is None


def test_holiday_expiry_restores_the_weekly_program():
    # Holiday OFF automatically: the central broadcasts 1101, then the zone reports 111.
    msg = _parse("*4*1101*#0##")
    assert msg.message_type == MESSAGE_TYPE_MODE
    assert msg.mode == CLIMATE_MODE_HEAT
    assert msg.program == 1
    assert msg.set_temperature is None
    assert _parse("*4*111*#10##").mode == CLIMATE_MODE_HEAT


@pytest.mark.parametrize("raw", ["*4*1*3##", "*4*1*4##", "*4*1*7##"])
def test_season_frame_next_to_a_programmed_zone_is_not_a_mode(raw):
    # Baseline: *4*1*Z## arrives while the zone reports a weekly program (*4*111*#Z##).
    msg = _parse(raw)
    assert msg.message_type == MESSAGE_TYPE_SEASON
    assert msg.season == SEASON_HEATING
    assert msg.mode is None


def test_central_switching_to_summer_reports_thermal_protection():
    # One zone Heat -> Cool: the plant switches to summer and the central parks in
    # thermal protection (*4*202*#0##), which is "off" in the conditioning season.
    msg = _parse("*4*202*#0##")
    assert msg.mode == CLIMATE_MODE_OFF
    assert msg.season == SEASON_CONDITIONING


@pytest.mark.parametrize("raw", ["*4*102*#0##", "*4*103*#0##"])
def test_central_antifreeze_and_off_in_winter(raw):
    msg = _parse(raw)
    assert msg.mode == CLIMATE_MODE_OFF
    assert msg.season == SEASON_HEATING


@pytest.mark.parametrize("raw", ["*4*21*#0##", "*4*22*#0##"])
def test_central_status_frames_do_not_set_a_mode(raw):
    msg = _parse(raw)
    assert msg.mode is None
    assert msg.season is None


def test_zone_off_report_does_not_claim_a_season():
    msg = _parse("*4*303*1##")
    assert msg.mode == CLIMATE_MODE_OFF
    assert msg.season is None
