"""WHO 16 / WHO 22 fixes of the 2026-10-28 Encyclopedia audit (rows D1..D7, S1..S4).

Evidence: Encyclopedia ``who-22-sound-diffusion/README.md`` and
``who-16-sound-system/README.md``; firmware-oracle rows as recorded in
``tests/golden/firmware_oracle.json`` (suite ``sound-who22`` /
``sound-who16-source``) and in the review's ORACLE_CONFIRM.md (S1, S2, D1,
D2, D5, D7); ENCY_CONFIRM.md SD-D1..D7, SD-S1..S4. Nothing here reaches a
gateway.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from OWNd.message import OWNMessage, OWNSoundCommand, OWNSoundDiffusionCommand, OWNSoundDiffusionEvent, OWNSoundEvent
from OWNd.message.sound import _is_who22_preset, _validate_area, _who22_frequency_khz, _who22_target_area

_ORACLE = json.loads((Path(__file__).parent / "golden" / "firmware_oracle.json").read_text(encoding="utf-8"))["verdicts"]
_BT_MULTI_OUT = {"F453", "F453AV", "F454", "F459", "F460", "F461", "MH200N", "MH202", "MyHomeServer1"}


def _who22(frame: str) -> OWNSoundDiffusionEvent:
    event = OWNMessage.parse(frame)
    assert isinstance(event, OWNSoundDiffusionEvent)
    return event


def _who16(frame: str) -> OWNSoundEvent:
    event = OWNMessage.parse(frame)
    assert isinstance(event, OWNSoundEvent)
    return event


def _out_products(frame: str) -> set[str]:
    assert frame in _ORACLE, frame
    return {r["product"] for r in _ORACLE[frame] if r["verdict"] == "out" and r["bus_frames"]}


# ---------------------------------------------------------------------------
# D1: the second WHAT parameter of WHAT 0 / 1 / 2 / 34 is the AREA
# ---------------------------------------------------------------------------


def test_d1_source_activity_carries_the_area_in_what_and_the_source_in_where() -> None:
    # Plant captures (ENCY_CONFIRM SD-D1): area 1 / source 1, area 2 / source 1.
    one = _who22("*22*2#4#1*5#2#1##")
    assert one.target_type == "source"
    assert one.source_id == 1
    assert one.what_area == 1
    assert one.area == 1
    assert one.multimedia_type == 4
    assert one.requested_source is None
    assert one.is_source_active is True
    assert one.is_on is True
    assert one.human_readable_log == "Audio Source 1 is active in area 1."
    two = _who22("*22*2#4#2*5#2#1##")
    assert two.source_id == 1
    assert two.area == 2
    assert two.human_readable_log == "Audio Source 1 is active in area 2."


def test_d1_speaker_where_keeps_its_own_area() -> None:
    event = _who22("*22*1#4#2*3#2#1##")
    assert event.area == 2
    assert event.point == 1
    assert event.what_area == 2
    assert event.requested_source is None
    assert event.human_readable_log == "Speaker 3#2#1 (Zone 21) is switched ON (area 2)."
    # A mismatching WHAT area does not overwrite the WHERE area.
    odd = _who22("*22*1#4#5*3#2#1##")
    assert odd.area == 2
    assert odd.what_area == 5


def test_d1_off_and_follow_me_forms_carry_the_area() -> None:
    off = _who22("*22*0#4#2*3#2#0##")  # firmware oracle `sound-who22`
    assert off.is_atomic_off is True
    assert off.what_area == 2
    assert off.multimedia_type == 4
    assert off.human_readable_log == "Speaker 3#2#0 (Zone 20) is switched OFF (atomic)."
    follow = _who22("*22*34#4#2*3#2#0##")
    assert follow.is_follow_me is True
    assert follow.what_area == 2
    assert follow.human_readable_log == "Speaker 3#2#0 (Zone 20) follow-me."
    # Temporary-off event on `6`: the WHAT area is the only area.
    temp = _who22("*22*0#4#3*6##")
    assert temp.target_type == "all_sources"
    assert temp.area == 3


def test_d1_short_or_malformed_parameters_set_nothing() -> None:
    short = _who22("*22*1#4*3#2#1##")
    assert short.multimedia_type is None
    assert short.what_area is None
    assert short.area == 2
    assert short.human_readable_log == "Speaker 3#2#1 (Zone 21) is switched ON."
    source = _who22("*22*2*5#2#1##")
    assert source.area is None
    assert source.human_readable_log == "Audio Source 1 is switched ON."
    # The frame grammar admits only `#DIGITS` parameters: a letter is not a frame.
    assert OWNMessage.parse("*22*1#x#y*3#2#1##") is None
    assert OWNMessage.parse("*22*1#4#*3#2#1##") is None


@pytest.mark.parametrize(
    ("where", "expected"),
    [
        ("3#2#1", "*22*1#4#2*3#2#1##"),
        ("4#3", "*22*1#4#3*4#3##"),
        ("5#3#7#6", "*22*1#4#7*5#3#7#6##"),
        ("5#3#0#0", "*22*1#4#0*5#3#0#0##"),
    ],
)
def test_d1_turn_on_atomic_derives_the_area_from_the_target(where: str, expected: str) -> None:
    command = OWNSoundDiffusionCommand.turn_on_atomic(where)
    assert str(command) == expected
    assert f"(area {expected.split('#')[2].split('*')[0]})" in command.human_readable_log


def test_d1_turn_on_atomic_explicit_area_and_errors() -> None:
    assert str(OWNSoundDiffusionCommand.turn_on_atomic("2#1", area=3)) == "*22*1#4#3*2#1##"
    assert str(OWNSoundDiffusionCommand.turn_on_atomic("6", "2", multimedia_type=1)) == "*22*1#1#2*6##"
    assert str(OWNSoundDiffusionCommand.turn_on_atomic("3#2#1", area=5)) == "*22*1#4#5*3#2#1##"
    with pytest.raises(ValueError, match="area is required for target '2#1'"):
        OWNSoundDiffusionCommand.turn_on_atomic("2#1")
    with pytest.raises(ValueError, match="area is required for target '6'"):
        OWNSoundDiffusionCommand.turn_on_atomic("6")
    with pytest.raises(ValueError, match="area must be between 0 and 9, got 10"):
        OWNSoundDiffusionCommand.turn_on_atomic("3#1#1", area=10)
    with pytest.raises(ValueError, match="area must be between 0 and 9, got True"):
        OWNSoundDiffusionCommand.turn_on_atomic("3#1#1", area=True)  # type: ignore[arg-type]
    with pytest.raises(ValueError, match="area must be between 0 and 9, got 1.5"):
        OWNSoundDiffusionCommand.turn_on_atomic("3#1#1", area=1.5)  # type: ignore[arg-type]
    with pytest.raises(ValueError, match="multimedia_type must be non-negative"):
        OWNSoundDiffusionCommand.turn_on_atomic("3#1#1", multimedia_type=-1)


def test_d1_turn_on_with_source_is_the_deprecated_spelling_without_the_source() -> None:
    assert str(OWNSoundDiffusionCommand.turn_on_with_source("3#2#1", 1)) == "*22*1#4#2*3#2#1##"
    assert str(OWNSoundDiffusionCommand.turn_on_with_source("2#1", 1, area=4)) == "*22*1#4#4*2#1##"
    with pytest.raises(ValueError, match="source must be positive"):
        OWNSoundDiffusionCommand.turn_on_with_source("3#2#1", 0)


def test_d1_turn_off_atomic_derives_the_area_from_the_target() -> None:
    assert str(OWNSoundDiffusionCommand.turn_off_atomic("3#2#1")) == "*22*0#4#2*3#2#1##"
    assert str(OWNSoundDiffusionCommand.turn_off_atomic("4#5")) == "*22*0#4#5*4#5##"
    assert str(OWNSoundDiffusionCommand.turn_off_atomic("6", area=1)) == "*22*0#4#1*6##"
    assert str(OWNSoundDiffusionCommand.turn_off_atomic("3#2#1", 1, 0)) == "*22*0#1#0*3#2#1##"
    with pytest.raises(ValueError, match="area is required for target '6'"):
        OWNSoundDiffusionCommand.turn_off_atomic("6")


def test_d1_power_frames_with_the_target_area_are_in_the_firmware_oracle() -> None:
    # `*22*0#4#1*3#1#1##` and `*22*1#4#1*3#1#1##` (suite `sound-who22`) are
    # the builders' output for speaker 3#1#1; nine bt_multi gateways put them
    # on the bus.
    off = OWNSoundDiffusionCommand.turn_off_atomic("3#1#1")
    assert str(off) == "*22*0#4#1*3#1#1##"
    assert _out_products(str(off)) >= _BT_MULTI_OUT
    on = OWNSoundDiffusionCommand.turn_on_atomic("3#1#1")
    assert str(on) == "*22*1#4#1*3#1#1##"
    assert _out_products(str(on)) >= _BT_MULTI_OUT


# ---------------------------------------------------------------------------
# D2: route_source derives the area from the target
# ---------------------------------------------------------------------------


def test_d2_route_source_uses_the_target_area() -> None:
    assert str(OWNSoundDiffusionCommand.route_source("3#2#1", 7)) == "*22*35#4#2#7*3#2#1##"
    assert str(OWNSoundDiffusionCommand.route_source("4#2", 7)) == "*22*35#4#2#7*4#2##"
    assert str(OWNSoundDiffusionCommand.route_source("5#3#0#0", 1)) == "*22*35#4#0#1*5#3#0#0##"
    assert str(OWNSoundDiffusionCommand.route_source("3#2#1", 7, area=1)) == "*22*35#4#1#7*3#2#1##"
    assert str(OWNSoundDiffusionCommand.route_source("3#2#1", 7, matrix_area=0)) == "*22*35#4#0#7*3#2#1##"
    # `area=` wins over the older `matrix_area=` spelling.
    assert str(OWNSoundDiffusionCommand.route_source("3#2#1", 7, matrix_area=0, area=3)) == "*22*35#4#3#7*3#2#1##"
    command = OWNSoundDiffusionCommand.route_source("3#2#1", 7)
    assert command.human_readable_log == "Routing sound diffusion device 3#2#1 to source 7 on matrix area 2."
    with pytest.raises(ValueError, match="area is required for target '2#1'"):
        OWNSoundDiffusionCommand.route_source("2#1", 7)
    with pytest.raises(ValueError, match="source must be between 1 and 9"):
        OWNSoundDiffusionCommand.route_source("3#2#1", 10)
    with pytest.raises(ValueError, match="multimedia_type must be non-negative"):
        OWNSoundDiffusionCommand.route_source("3#2#1", 1, multimedia_type=-1)


def test_d2_route_frames_with_the_target_area_are_in_the_firmware_oracle() -> None:
    # `*22*35#4#2#7*3#2#0##` and `*22*35#4#1#1*3#1#1##` (suite `sound-who22`):
    # param area == WHERE area, forwarded by nine gateways.
    for where, source, frame in (("3#2#0", 7, "*22*35#4#2#7*3#2#0##"), ("3#1#1", 1, "*22*35#4#1#1*3#1#1##")):
        assert str(OWNSoundDiffusionCommand.route_source(where, source)) == frame
        assert _out_products(frame) >= _BT_MULTI_OUT


def test_d2_route_event_reports_the_area() -> None:
    event = _who22("*22*35#4#2#7*3#2#0##")
    assert event.matrix_area == 2
    assert event.what_area == 2
    assert event.requested_source == 7
    assert event.human_readable_log == "Speaker 3#2#0 (Zone 20) is routed to source 7 on matrix area 2."
    bare = _who22("*22*35*3#2#0##")
    assert bare.matrix_area is None
    assert bare.what_area is None
    assert bare.requested_source is None
    assert bare.human_readable_log == "Speaker 3#2#0 (Zone 20) received command: 35."


def test_target_area_helper() -> None:
    assert _who22_target_area("3#2#1") == 2
    assert _who22_target_area("4#7") == 7
    assert _who22_target_area("5#3#4#2") == 4
    assert _who22_target_area("5#3#0#0") == 0
    for target in ("2#1", "5#2#1", "6", "3#x#1", "4#", "3#1", "5#3#x#1", "7"):
        assert _who22_target_area(target) is None, target
    assert _validate_area(None, "3#1#1", "3#1#1") == 1
    assert _validate_area("4", "3#1#1", "3#1#1") == 4


# ---------------------------------------------------------------------------
# D3: dimension 5 / 11 frequency decode follows the modulation
# ---------------------------------------------------------------------------


def test_d3_frequency_helper() -> None:
    assert _who22_frequency_khz(1, 10150) == 101500
    assert _who22_frequency_khz(1, 1015) == 101500
    assert _who22_frequency_khz(1, 5000) is None
    assert _who22_frequency_khz(2, 216) == 216
    assert _who22_frequency_khz(3, 999) == 999
    assert _who22_frequency_khz(4, 6000) == 6000
    assert _who22_frequency_khz(3, 0) is None
    assert _who22_frequency_khz(5, 10150) is None
    assert _who22_frequency_khz(0, 10150) is None
    assert _who22_frequency_khz(None, 10150) is None


def test_d3_am_bands_are_kilohertz_not_fm_megahertz() -> None:
    mw = _who22("*#22*2#1*5*3*999##")
    assert mw.frequency_band == 3
    assert mw.frequency_band_name == "AM-MW"
    assert mw.frequency_khz == 999
    assert mw.frequency_mhz == 1.0
    assert mw.human_readable_log == "Audio Source 1 is tuned to 999 kHz AM-MW."
    lw = _who22("*#22*2#1*5*2*216##")
    assert lw.frequency_khz == 216
    assert lw.frequency_mhz == 0.22
    assert lw.human_readable_log == "Audio Source 1 is tuned to 216 kHz AM-LW."
    sw = _who22("*#22*2#1*11*4*6000*2##")
    assert sw.frequency_band_name == "AM-SW"
    assert sw.frequency_khz == 6000
    assert sw.station == 2
    assert sw.human_readable_log == "Audio Source 1 is tuned to 6000 kHz AM-SW (station 2)."
    fm = _who22("*#22*2#1*5*1*10150##")
    assert fm.frequency_band_name == "FM"
    assert fm.human_readable_log == "Audio Source 1 is tuned to 101.50 MHz."


def test_d3_unknown_modulation_fails_closed() -> None:
    for frame in ("*#22*2#1*5*5*10150##", "*#22*2#1*5*0*10150##", "*#22*2#1*5**10150##"):
        event = _who22(frame)
        assert event.frequency_khz is None, frame
        assert event.frequency_mhz is None
        assert event.human_readable_log == "Audio Source 1 reported dimension 5."
    assert _who22("*#22*2#1*5**10150##").frequency_band is None
    assert _who22("*#22*2#1*5**10150##").frequency_band_name is None
    assert _who22("*#22*2#1*5*5*10150##").frequency_band == 5
    assert _who22("*#22*2#1*5*5*10150##").frequency_band_name is None


def test_d3_trailing_empty_field_is_ignored() -> None:
    five = _who22("*#22*2#1*5*1*10150*##")
    assert five.frequency_khz == 101500
    assert five.dimension_value == ["1", "10150", ""]
    eleven = _who22("*#22*2#1*11*1*10150*3*##")
    assert eleven.frequency_khz == 101500
    assert eleven.station == 3
    # Only one trailing empty field is a preserved artefact; more is not a payload.
    assert _who22("*#22*2#1*5*1*10150**##").frequency_khz is None
    assert _who22("*#22*2#1*5*1**##").frequency_khz is None
    # An empty station field after a valid frequency keeps the frequency.
    assert _who22("*#22*2#1*11*1*10150*##").station is None
    assert _who22("*#22*2#1*11*1*10150*##").frequency_khz == 101500
    assert _who22("*#22*2#1*11*1*10150*##").is_station_cleared is False


# ---------------------------------------------------------------------------
# D4: dimension 19 is the preset, dimension 6 the station
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("preset", [2, 11, 16, 25])
def test_d4_dimension_19_is_the_equalizer_preset(preset: int) -> None:
    event = _who22(f"*#22*3#1#1*19*{preset}##")
    assert event.preset == preset
    assert event.equalizer_preset == preset
    assert event.station is None
    assert event.human_readable_log == f"Speaker 3#1#1 (Zone 11) equalizer preset is {preset}."


@pytest.mark.parametrize("value", ["1", "12", "15", "26", "0", ""])
def test_d4_dimension_19_outside_the_published_presets_is_none(value: str) -> None:
    event = _who22(f"*#22*3#1#1*19*{value}##")
    assert event.preset is None
    assert event.equalizer_preset is None
    assert event.human_readable_log == "Speaker 3#1#1 (Zone 11) reported dimension 19."


def test_d4_preset_helper() -> None:
    assert [p for p in range(0, 30) if _is_who22_preset(p)] == list(range(2, 12)) + list(range(16, 26))


def test_d4_station_properties_and_deprecated_preset_alias() -> None:
    six = _who22("*#22*2#1*6*3##")
    assert six.station == 3
    assert six.preset == 3  # deprecated alias on a dimension 6 frame
    assert six.equalizer_preset is None
    eleven = _who22("*#22*5#2#1*11*1*10530*5##")
    assert eleven.station == 5
    assert eleven.preset == 5
    assert eleven.is_station_cleared is False
    cleared = _who22("*#22*5#2#1*11*1*10530*0##")
    assert cleared.station is None
    assert cleared.is_station_cleared is True
    assert cleared.is_preset_cleared is True  # deprecated alias
    stored = _who22("*22*33#4*2#1##")
    assert stored.station == 4
    assert stored.human_readable_log == "Audio Source 1 stored frequency to station 4."
    assert _who22("*22*33*2#1##").station is None


def test_d4_station_and_preset_builders() -> None:
    assert str(OWNSoundDiffusionCommand.select_station("2#1", 3)) == "*#22*2#1*#6*3##"
    assert str(OWNSoundDiffusionCommand.select_station("2#1", 999)) == "*#22*2#1*#6*999##"
    assert OWNSoundDiffusionCommand.select_station("2#1", 3).human_readable_log == (
        "Selecting station 3 on sound diffusion device 2#1."
    )
    for bad in (0, 1000):
        with pytest.raises(ValueError, match="station must be between 1 and 999"):
            OWNSoundDiffusionCommand.select_station("2#1", bad)
    assert str(OWNSoundDiffusionCommand.request_station("2#1")) == "*#22*2#1*6##"
    assert OWNSoundDiffusionCommand.request_station("2#1").human_readable_log == (
        "Requesting station for sound diffusion device 2#1."
    )
    # Deprecated spellings build the same frames.
    assert str(OWNSoundDiffusionCommand.set_preset("2#1", 3)) == "*#22*2#1*#6*3##"
    assert str(OWNSoundDiffusionCommand.request_preset("2#1")) == "*#22*2#1*6##"
    assert str(OWNSoundDiffusionCommand.store_station("2#1", 3)) == "*22*33#3*2#1##"
    assert str(OWNSoundDiffusionCommand.store_preset("2#1", 3)) == "*22*33#3*2#1##"
    assert OWNSoundDiffusionCommand.store_station("2#1", 3).human_readable_log == (
        "Storing current frequency into station 3 on 2#1."
    )
    with pytest.raises(ValueError, match="station must be positive"):
        OWNSoundDiffusionCommand.store_station("2#1", 0)
    # Dimension 19 and WHAT 55 / 56.
    assert str(OWNSoundDiffusionCommand.set_equalizer_preset("3#1#1", 2)) == "*#22*3#1#1*#19*2##"
    assert str(OWNSoundDiffusionCommand.set_equalizer_preset("3#1#1", "25")) == "*#22*3#1#1*#19*25##"
    assert OWNSoundDiffusionCommand.set_equalizer_preset("3#1#1", 5).human_readable_log == (
        "Selecting equalizer preset 5 on sound diffusion device 3#1#1."
    )
    for bad in (1, 12, 15, 26):
        with pytest.raises(ValueError, match="preset must be 2..11 or 16..25"):
            OWNSoundDiffusionCommand.set_equalizer_preset("3#1#1", bad)
    assert str(OWNSoundDiffusionCommand.request_equalizer_preset("3#1#1")) == "*#22*3#1#1*19##"
    assert OWNSoundDiffusionCommand.request_equalizer_preset("3#1#1").human_readable_log == (
        "Requesting equalizer preset for sound diffusion device 3#1#1."
    )
    assert str(OWNSoundDiffusionCommand.next_preset("3#1#1")) == "*22*55*3#1#1##"
    assert str(OWNSoundDiffusionCommand.previous_preset("3#1#1")) == "*22*56*3#1#1##"
    assert OWNSoundDiffusionCommand.next_preset("3#1#1").human_readable_log == (
        "Next equalizer preset on sound diffusion device 3#1#1."
    )
    assert OWNSoundDiffusionCommand.previous_preset("3#1#1").human_readable_log == (
        "Previous equalizer preset on sound diffusion device 3#1#1."
    )


# ---------------------------------------------------------------------------
# D5: the bare single-step form is preserved (#127 / decision D19); the
# multi-step form carries the step. The oracle finding stays a docstring note.
# ---------------------------------------------------------------------------


def test_d5_volume_step_forms_are_both_preserved() -> None:
    up = OWNSoundDiffusionCommand.volume_up("3#1#1")
    down = OWNSoundDiffusionCommand.volume_down("3#1#1")
    assert str(up) == "*22*3*3#1#1##"
    assert str(down) == "*22*4*3#1#1##"
    assert str(OWNSoundDiffusionCommand.volume_up("3#1#1", step=2)) == "*22*3#2*3#1#1##"
    assert str(OWNSoundDiffusionCommand.volume_down("3#1#1", step=2)) == "*22*4#2*3#1#1##"
    assert str(OWNSoundDiffusionCommand.volume_up("3#1#1", step=31)) == "*22*3#31*3#1#1##"
    # `*22*3#1*3#1#1##` is in the firmware oracle (`sound-who22`); the bare
    # `*22*3*3#1#1##` is not (ORACLE_CONFIRM D5, recorded in the docstring).
    assert _out_products("*22*3#1*3#1#1##") >= _BT_MULTI_OUT
    assert "*22*3*3#1#1##" not in _ORACLE
    assert "#127" in (OWNSoundDiffusionCommand.volume_up.__doc__ or "")
    assert "ORACLE_CONFIRM D5" in (OWNSoundDiffusionCommand.volume_up.__doc__ or "")
    event = _who22(str(up))
    assert event.volume_step == 1
    assert event.is_volume_up is True


# ---------------------------------------------------------------------------
# D6: tone, balance, play status, 3D, loudness, equalizer and the related WHATs
# ---------------------------------------------------------------------------


def test_d6_tone_dimensions() -> None:
    high = _who22("*#22*3#1#1*2*30##")
    assert high.high_tones == 30
    assert high.human_readable_log == "Speaker 3#1#1 (Zone 11) high tones are 30."
    mid = _who22("*#22*3#1#1*3*1##")
    assert mid.medium_tones == 1
    assert mid.human_readable_log == "Speaker 3#1#1 (Zone 11) medium tones are 1."
    low = _who22("*#22*3#1#1*4*63##")
    assert low.low_tones == 63
    assert low.human_readable_log == "Speaker 3#1#1 (Zone 11) low tones are 63."
    for frame in ("*#22*3#1#1*2*0##", "*#22*3#1#1*2*64##", "*#22*3#1#1*2*##", "*#22*3#1#1*2*30*1##"):
        event = _who22(frame)
        assert event.high_tones is None, frame
        assert event.human_readable_log == "Speaker 3#1#1 (Zone 11) reported dimension 2."
    assert _who22("*#22*3#1#1*3*##").medium_tones is None
    assert _who22("*#22*3#1#1*4*##").low_tones is None


def test_d6_play_status_3d_loudness() -> None:
    play = _who22("*#22*2#1*7*1##")
    assert play.play_status == 1
    assert play.human_readable_log == "Audio Source 1 play status is 1."
    assert _who22("*#22*2#1*7*##").play_status is None
    three_d = _who22("*#22*3#1#1*18*10##")
    assert three_d.sound_3d == 10
    assert three_d.human_readable_log == "Speaker 3#1#1 (Zone 11) 3D level is 10."
    assert _who22("*#22*3#1#1*18*0##").sound_3d == 0
    assert _who22("*#22*3#1#1*18*11##").sound_3d is None
    assert _who22("*#22*3#1#1*18*##").sound_3d is None
    loud = _who22("*#22*3#1#1*20*1##")
    assert loud.loudness is True
    assert loud.human_readable_log == "Speaker 3#1#1 (Zone 11) loudness is ON."
    quiet = _who22("*#22*3#1#1*20*0##")
    assert quiet.loudness is False
    assert quiet.human_readable_log == "Speaker 3#1#1 (Zone 11) loudness is OFF."
    assert _who22("*#22*3#1#1*20*2##").loudness is None
    assert _who22("*#22*3#1#1*20*2##").human_readable_log == "Speaker 3#1#1 (Zone 11) reported dimension 20."


def test_d6_balance_is_textual() -> None:
    left = _who22("*#22*3#1#1*17*030##")
    assert left.balance == "030"
    assert left.balance_side == "left"
    assert left.balance_level == 30
    assert left.dimension_value == ["030"]
    assert left.human_readable_log == "Speaker 3#1#1 (Zone 11) balance is 030 (left 30)."
    right = _who22("*#22*3#1#1*17*115##")
    assert right.balance == "115"
    assert right.balance_side == "right"
    assert right.balance_level == 15
    centre = _who22("*#22*3#1#1*17*0##")
    assert centre.balance == "0"
    assert centre.balance_side == "left"
    assert centre.balance_level == 0
    none = _who22("*#22*3#1#1*17*##")
    assert none.balance is None
    assert none.balance_side is None
    assert none.balance_level is None
    assert none.human_readable_log == "Speaker 3#1#1 (Zone 11) reported dimension 17."


def test_d6_equalizer_reports() -> None:
    event = _who22("*#22*3#1#1*21#1*10*20*30##")
    assert event.equalizer_group == 1
    assert event.equalizer_values == [10, 20, 30]
    assert event.human_readable_log == "Speaker 3#1#1 (Zone 11) equalizer group 1 is 10, 20, 30."
    assert _who22("*#22*3#1#1*21#3*5*6##").equalizer_group == 3
    for frame in ("*#22*3#1#1*21#4*1*2##", "*#22*3#1#1*21*1*2##", "*#22*3#1#1*21#1*1*##", "*#22*3#1#1*21#1#2*1*2##"):
        other = _who22(frame)
        assert other.equalizer_group is None, frame
        assert other.equalizer_values is None
        assert other.human_readable_log == "Speaker 3#1#1 (Zone 11) reported dimension 21."
    values = event.equalizer_values
    assert values is not None
    values.append(99)
    assert event.equalizer_values == [10, 20, 30]


@pytest.mark.parametrize(
    ("frame", "band", "step", "log"),
    [
        ("*22*36#1*3#1#1##", "low", 1, "low tones increased by 1."),
        ("*22*37#2*3#1#1##", "low", -2, "low tones decreased by 2."),
        ("*22*38*3#1#1##", "mid", 1, "mid tones increased by 1."),
        ("*22*39*3#1#1##", "mid", -1, "mid tones decreased by 1."),
        ("*22*40#3*3#1#1##", "high", 3, "high tones increased by 3."),
        ("*22*41#1*3#1#1##", "high", -1, "high tones decreased by 1."),
    ],
)
def test_d6_tone_whats(frame: str, band: str, step: int, log: str) -> None:
    event = _who22(frame)
    assert event.tone_band == band
    assert event.tone_step == step
    assert event.balance_step is None
    assert event.human_readable_log == f"Speaker 3#1#1 (Zone 11) {log}"


def test_d6_balance_whats_and_presets() -> None:
    right = _who22("*22*42#1*3#1#1##")
    assert right.balance_step == 1
    assert right.tone_step is None
    assert right.human_readable_log == "Speaker 3#1#1 (Zone 11) balance moved right by 1."
    left = _who22("*22*43*3#1#1##")
    assert left.balance_step == -1
    assert left.human_readable_log == "Speaker 3#1#1 (Zone 11) balance moved left by 1."
    assert _who22("*22*43#2*3#1#1##").balance_step == -2
    sliding = _who22("*22*22#4#1*5#3#1#1##")
    assert sliding.is_sliding_request is True
    assert sliding.what_area is None  # WHAT 22 is not a power / activity frame
    assert sliding.human_readable_log == "Sound diffusion device 5#3#1#1 sliding request."
    nxt = _who22("*22*55*3#1#1##")
    assert nxt.is_next_preset is True
    assert nxt.is_previous_preset is False
    assert nxt.human_readable_log == "Speaker 3#1#1 (Zone 11) next preset."
    prev = _who22("*22*56*3#1#1##")
    assert prev.is_previous_preset is True
    assert prev.human_readable_log == "Speaker 3#1#1 (Zone 11) previous preset."
    other = _who22("*22*1*3#1#1##")
    assert other.is_sliding_request is False
    assert other.is_next_preset is False
    assert other.is_source_active is False


# ---------------------------------------------------------------------------
# D7: builders outside the published grammar
# ---------------------------------------------------------------------------


def test_d7_source_address_is_limited_to_the_published_domain() -> None:
    assert OWNSoundDiffusionCommand.source_address(1) == "2#1"
    assert OWNSoundDiffusionCommand.source_address("4") == "2#4"
    for bad in (0, 5, 9):
        with pytest.raises(ValueError, match="between 1 and 4"):
            OWNSoundDiffusionCommand.source_address(bad)


def test_d7_undocumented_builders_say_so() -> None:
    assert "Not in the published grammar" in (OWNSoundDiffusionCommand.send_rds_text.__doc__ or "")
    assert "not in the published grammar" in (OWNSoundDiffusionCommand.set_preset.__doc__ or "")
    assert "Not in the published grammar" in (OWNSoundDiffusionCommand.open_paging.__doc__ or "")
    assert "not in the published grammar" in (OWNSoundDiffusionCommand.start_paging_voice.__doc__ or "")
    assert "Deprecated" in (OWNSoundDiffusionCommand.turn_on_with_source.__doc__ or "")
    assert "Deprecated" in (OWNSoundDiffusionCommand.request_preset.__doc__ or "")
    assert "Deprecated" in (OWNSoundDiffusionCommand.store_preset.__doc__ or "")
    assert "Deprecated alias" in (OWNSoundDiffusionEvent.preset.__doc__ or "")
    assert "Deprecated alias" in (OWNSoundDiffusionEvent.is_preset_cleared.__doc__ or "")
    # They still build their frames for callers that depend on them.
    assert str(OWNSoundDiffusionCommand.set_preset("2#1", 3, frequency_khz=101500)) == "*#22*2#1*#11*1*10150*3##"
    assert str(OWNSoundDiffusionCommand.open_paging()) == "*22*19#1*5#3#0#0##"


# ---------------------------------------------------------------------------
# S1 / S2 / S3 / S4: WHO 16
# ---------------------------------------------------------------------------


def test_s1_who16_volume_is_0_to_31() -> None:
    assert str(OWNSoundCommand.set_volume("21", 0)) == "*#16*21*#1*0##"
    assert str(OWNSoundCommand.set_volume("21", 31)) == "*#16*21*#1*31##"
    for bad in (32, 50, 100, -1):
        with pytest.raises(ValueError, match="volume must be between 0 and 31"):
            OWNSoundCommand.set_volume("21", bad)
    assert _who16("*#16*21*1*31##").volume == 31
    assert _who16("*#16*21*1*0##").volume == 0
    for value in ("32", "40", "50", ""):
        event = _who16(f"*#16*21*1*{value}##")
        assert event.volume is None, value
        assert event.human_readable_log == f"*#16*21*1*{value}##"


def test_s2_who16_amplifier_addresses_ending_in_zero_route() -> None:
    assert [str(c) for c in OWNSoundCommand.select_source("20", 1)] == ["*16*3*101##", "*16*3*121##"]
    assert [str(c) for c in OWNSoundCommand.select_source("90", 9)] == ["*16*3*109##", "*16*3*199##"]
    assert [str(c) for c in OWNSoundCommand.select_source(21, 2)] == ["*16*3*102##", "*16*3*122##"]
    for bad in ("00", "05", "0", "100", "2a", "٢٠"):
        with pytest.raises(ValueError, match="two-digit amplifier address"):
            OWNSoundCommand.select_source(bad, 1)
    with pytest.raises(ValueError, match="where must identify an audio zone"):
        OWNSoundCommand.select_source(" ", 1)


def test_s3_where_100_is_every_source() -> None:
    event = _who16("*16*3*100##")
    assert event.is_source_event is True
    assert event.is_all_sources is True
    assert event.source_id is None
    assert event.zone == "100"
    assert event.is_on is True
    assert event.human_readable_log == "All audio sources is switched ON."
    source = _who16("*16*3*101##")
    assert source.is_all_sources is False
    assert source.source_id == "1"
    amplifier = _who16("*16*3*10##")
    assert amplifier.is_source_event is False
    assert amplifier.is_all_sources is False


def test_s3_module_docstring_names_the_dialects() -> None:
    from OWNd.message import sound

    assert sound.__doc__ is not None
    assert sound.__doc__.startswith("WHO 16 Sound System and WHO 22 Sound Diffusion")
    assert "door entry" not in sound.__doc__


@pytest.mark.parametrize(
    ("frame", "attribute", "stereo", "log"),
    [
        ("*16*20*100##", "is_source_cycle", False, "All audio sources cycles to the next source."),
        ("*16*23*100##", "is_source_cycle", True, "All audio sources cycles to the next source."),
        ("*16*30*21##", "is_sleep", False, "Audio Zone 21 sleep is ON."),
        ("*16*33*21##", "is_sleep", True, "Audio Zone 21 sleep is ON."),
        ("*16*40*21##", "is_sleep_off", None, "Audio Zone 21 sleep is OFF."),
        ("*16*50*21##", "is_follow_me", False, "Audio Zone 21 is switched ON with Follow Me."),
        ("*16*53*21##", "is_follow_me", True, "Audio Zone 21 is switched ON with Follow Me."),
        ("*16*101*101##", "is_rds_start", None, "Audio Source 1 starts RDS transmission."),
        ("*16*102*101##", "is_rds_stop", None, "Audio Source 1 stops RDS transmission."),
    ],
)
def test_s4_who16_named_whats(frame: str, attribute: str, stereo: bool | None, log: str) -> None:
    event = _who16(frame)
    assert getattr(event, attribute) is True
    assert event.is_stereo_channel is stereo
    assert event.human_readable_log == log
    for other in ("is_source_cycle", "is_sleep", "is_sleep_off", "is_follow_me", "is_rds_start", "is_rds_stop"):
        if other != attribute:
            assert getattr(event, other) is False, other


def test_s4_who16_stereo_flag_on_power_whats() -> None:
    assert _who16("*16*0*21##").is_stereo_channel is False
    assert _who16("*16*3*21##").is_stereo_channel is True
    assert _who16("*16*10*21##").is_stereo_channel is False
    assert _who16("*16*13*21##").is_stereo_channel is True
    assert _who16("*16*1001*21##").is_stereo_channel is None
    assert _who16("*#16*21*1*5##").is_stereo_channel is None


@pytest.mark.parametrize(
    ("frame", "delta", "log"),
    [
        ("*16*2001*21##", 1, "Audio Zone 21 increase high tones by 1 step(s)."),
        ("*16*2015*21##", 15, "Audio Zone 21 increase high tones by 15 step(s)."),
        ("*16*2101*21##", -1, "Audio Zone 21 decrease high tones by 1 step(s)."),
        ("*16*2115*21##", -15, "Audio Zone 21 decrease high tones by 15 step(s)."),
    ],
)
def test_s4_who16_high_tone_steps(frame: str, delta: int, log: str) -> None:
    event = _who16(frame)
    assert event.high_tone_step_delta == delta
    assert event.human_readable_log == log


@pytest.mark.parametrize("frame", ["*16*2000*21##", "*16*2016*21##", "*16*2100*21##", "*16*2116*21##", "*16*60*21##"])
def test_s4_who16_values_outside_the_tables_stay_unknown(frame: str) -> None:
    event = _who16(frame)
    assert event.high_tone_step_delta is None
    assert event.is_source_cycle is False
    assert event.is_sleep is False
    assert event.human_readable_log.endswith(f"received command: {event.what}.")
