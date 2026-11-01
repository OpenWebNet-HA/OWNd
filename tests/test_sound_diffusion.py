"""Tests for WHO 22 advanced sound diffusion messages."""

import json
from pathlib import Path

import pytest

from OWNd.message import (
    OWNCommand,
    OWNEvent,
    OWNMessage,
    OWNSoundDiffusionCommand,
    OWNSoundDiffusionEvent,
)

GOLDEN_PATH = Path(__file__).parent / "golden" / "firmware_oracle.json"
ORACLE = json.loads(GOLDEN_PATH.read_text(encoding="utf-8"))["verdicts"]


def test_who22_speaker_volume_event() -> None:
    """Verify decoding of empirical MH202 speaker volume event frames."""
    event = OWNMessage.parse("*#22*3#4#1*1*1##")
    assert isinstance(event, OWNSoundDiffusionEvent)
    assert event.target_type == "speaker"
    assert event.area == 4
    assert event.point == 1
    assert event.where == "3"
    assert event.target_address == "3#4#1"
    assert event.equivalent_who16_where == "41"
    assert event.volume == 1
    assert event.human_readable_log == "Speaker 3#4#1 (Zone 41) volume is set to 1."

    event61 = OWNMessage.parse("*#22*3#6#1*1*7##")
    assert isinstance(event61, OWNSoundDiffusionEvent)
    assert event61.target_type == "speaker"
    assert event61.area == 6
    assert event61.point == 1
    assert event61.where == "3"
    assert event61.target_address == "3#6#1"
    assert event61.equivalent_who16_where == "61"
    assert event61.volume == 7
    assert event61.human_readable_log == "Speaker 3#6#1 (Zone 61) volume is set to 7."


def test_who22_device_state_event() -> None:
    """Verify decoding of dimension 12 device state frames."""
    event_on = OWNMessage.parse("*#22*3#1#1*12*1*4##")
    assert isinstance(event_on, OWNSoundDiffusionEvent)
    assert event_on.target_type == "speaker"
    assert event_on.area == 1
    assert event_on.point == 1
    assert event_on.device_state == 1
    assert event_on.multimedia_type == 4
    assert event_on.is_on is True
    assert event_on.is_off is False
    assert event_on.human_readable_log == "Speaker 3#1#1 (Zone 11) is ON, audio channel 4."

    event_off = OWNMessage.parse("*#22*3#1#1*12*0*4##")
    assert isinstance(event_off, OWNSoundDiffusionEvent)
    assert event_off.device_state == 0
    assert event_off.multimedia_type == 4
    assert event_off.is_on is False
    assert event_off.is_off is True
    assert event_off.human_readable_log == "Speaker 3#1#1 (Zone 11) device state is OFF."


def test_who22_power_and_status_events() -> None:
    """Verify WHAT=0, 1, 2 on area, source, and all sources."""
    # Area ON
    area_on = OWNMessage.parse("*22*1*4#2##")
    assert isinstance(area_on, OWNSoundDiffusionEvent)
    assert area_on.target_type == "area"
    assert area_on.area == 2
    assert area_on.point is None
    assert area_on.equivalent_who16_where is None
    assert area_on.is_on is True
    assert area_on.is_off is False
    assert "Sound diffusion device 4#2 is switched ON." in area_on.human_readable_log

    # Source ON
    src_on = OWNMessage.parse("*22*2*2#3##")
    assert isinstance(src_on, OWNSoundDiffusionEvent)
    assert src_on.target_type == "source"
    assert src_on.source_id == 3
    assert src_on.is_on is True
    assert src_on.is_off is False
    assert "Audio Source 3 is switched ON." in src_on.human_readable_log

    # Source dimension report with 5#2#S target
    src_dim = OWNMessage.parse("*#22*5#2#1*9*82##")
    assert isinstance(src_dim, OWNSoundDiffusionEvent)
    assert src_dim.target_type == "source"
    assert src_dim.source_id == 1
    assert "Audio Source 1 reported dimension 9." in src_dim.human_readable_log

    # All sources OFF
    all_off = OWNMessage.parse("*22*0*6##")
    assert isinstance(all_off, OWNSoundDiffusionEvent)
    assert all_off.target_type == "all_sources"
    assert all_off.is_off is True
    assert all_off.is_on is False
    assert "Sound diffusion device 6 is switched OFF." in all_off.human_readable_log


def test_who22_volume_and_media_transport_events() -> None:
    """Verify relative volume adjustments and media transport WHAT events."""
    vol_up = OWNMessage.parse("*22*3*3#4#1##")
    assert isinstance(vol_up, OWNSoundDiffusionEvent)
    assert vol_up.is_volume_up is True
    assert vol_up.volume_step == 1
    assert "volume increased." in vol_up.human_readable_log

    vol_up_step = OWNMessage.parse("*22*3#3*3#4#1##")
    assert isinstance(vol_up_step, OWNSoundDiffusionEvent)
    assert vol_up_step.is_volume_up is True
    assert vol_up_step.volume_step == 3
    assert "volume increased by 3." in vol_up_step.human_readable_log

    vol_down = OWNMessage.parse("*22*4*3#4#1##")
    assert isinstance(vol_down, OWNSoundDiffusionEvent)
    assert vol_down.is_volume_down is True
    assert vol_down.volume_step == 1
    assert "volume decreased." in vol_down.human_readable_log

    vol_down_step = OWNMessage.parse("*22*4#2*3#4#1##")
    assert isinstance(vol_down_step, OWNSoundDiffusionEvent)
    assert vol_down_step.is_volume_down is True
    assert vol_down_step.volume_step == 2
    assert "volume decreased by 2." in vol_down_step.human_readable_log

    # Transport controls
    assert OWNMessage.parse("*22*9*6##").is_next_station is True
    assert OWNMessage.parse("*22*10*6##").is_previous_station is True
    assert OWNMessage.parse("*22*11*6##").is_next_track is True
    assert OWNMessage.parse("*22*12*6##").is_previous_track is True

    # Custom / unknown command
    unknown = OWNMessage.parse("*22*99*3#4#1##")
    assert isinstance(unknown, OWNSoundDiffusionEvent)
    assert "received command: 99" in unknown.human_readable_log


def test_who22_edge_cases_and_malformed() -> None:
    """Verify edge case parsing resilience."""
    # Unknown structured address kind
    event = OWNSoundDiffusionEvent("*22*1*9#1#2##")
    assert event.target_type == "unknown"
    assert event.area is None
    assert event.point is None
    assert event.equivalent_who16_where is None

    # Incomplete structured speaker (3#1 without point)
    incomplete_speaker = OWNSoundDiffusionEvent("*22*1*3#1##")
    assert incomplete_speaker.target_type == "unknown"

    # General target with non-source kind 5#3#1
    non_source_gen = OWNSoundDiffusionEvent("*#22*5#3#1*10*1##")
    assert non_source_gen.target_type == "unknown"

    # General target without structured prefix
    general_target = OWNSoundDiffusionEvent("*22*1*0##")
    assert general_target.target_type == "unknown"
    assert "Sound diffusion device 0 is switched ON." in general_target.human_readable_log

    # Empty / truncated dimension values
    bad_vol = OWNSoundDiffusionEvent("*#22*3#4#1*1*##")
    assert bad_vol.volume is None

    bad_state = OWNSoundDiffusionEvent("*#22*3#4#1*12*##")
    assert bad_state.device_state is None
    assert bad_state.multimedia_type is None


def test_who22_command_builders() -> None:
    """Verify WHO 22 command factory methods and range validation."""
    speaker = OWNSoundDiffusionCommand.speaker_address(4, 1)
    assert speaker == "3#4#1"
    assert OWNSoundDiffusionCommand.area_address(2) == "4#2"
    assert OWNSoundDiffusionCommand.source_address(3) == "2#3"
    assert OWNSoundDiffusionCommand.all_sources_address() == "6"

    # Address validation
    with pytest.raises(ValueError, match="must both be between 1 and 9"):
        OWNSoundDiffusionCommand.speaker_address(0, 1)
    with pytest.raises(ValueError, match="must both be between 1 and 9"):
        OWNSoundDiffusionCommand.speaker_address(10, 1)
    with pytest.raises(ValueError, match="must both be between 1 and 9"):
        OWNSoundDiffusionCommand.speaker_address(1, 0)
    with pytest.raises(ValueError, match="must both be between 1 and 9"):
        OWNSoundDiffusionCommand.speaker_address(1, 10)
    with pytest.raises(ValueError, match="Area .* must be between 1 and 9"):
        OWNSoundDiffusionCommand.area_address(0)
    with pytest.raises(ValueError, match="Area .* must be between 1 and 9"):
        OWNSoundDiffusionCommand.area_address(10)
    with pytest.raises(ValueError, match="Source ID .* must be positive"):
        OWNSoundDiffusionCommand.source_address(0)

    # Power and status
    assert str(OWNSoundDiffusionCommand.turn_on(speaker)) == "*22*1*3#4#1##"
    assert str(OWNSoundDiffusionCommand.turn_off(speaker)) == "*22*0*3#4#1##"
    assert str(OWNSoundDiffusionCommand.status(speaker)) == "*#22*3#4#1##"
    assert str(OWNSoundDiffusionCommand.request_volume(speaker)) == "*#22*3#4#1*1##"
    assert str(OWNSoundDiffusionCommand.request_device_state(speaker)) == "*#22*3#4#1*12##"

    # Volume controls
    assert str(OWNSoundDiffusionCommand.volume_up(speaker)) == "*22*3*3#4#1##"
    assert str(OWNSoundDiffusionCommand.volume_up(speaker, step=3)) == "*22*3#3*3#4#1##"
    assert str(OWNSoundDiffusionCommand.volume_down(speaker)) == "*22*4*3#4#1##"
    assert str(OWNSoundDiffusionCommand.volume_down(speaker, step=2)) == "*22*4#2*3#4#1##"
    assert str(OWNSoundDiffusionCommand.set_volume(speaker, 20)) == "*#22*3#4#1*#1*20##"

    with pytest.raises(ValueError, match="step must be positive"):
        OWNSoundDiffusionCommand.volume_up(speaker, step=0)
    with pytest.raises(ValueError, match="step must be positive"):
        OWNSoundDiffusionCommand.volume_up(speaker, step=-1)
    with pytest.raises(ValueError, match="step must be positive"):
        OWNSoundDiffusionCommand.volume_down(speaker, step=0)
    with pytest.raises(ValueError, match="step must be positive"):
        OWNSoundDiffusionCommand.volume_down(speaker, step=-1)
    with pytest.raises(ValueError, match="volume must be between 0 and 31"):
        OWNSoundDiffusionCommand.set_volume(speaker, -1)
    with pytest.raises(ValueError, match="volume must be between 0 and 31"):
        OWNSoundDiffusionCommand.set_volume(speaker, 32)

    # Media transport
    assert str(OWNSoundDiffusionCommand.next_track()) == "*22*11*6##"
    assert str(OWNSoundDiffusionCommand.previous_track()) == "*22*12*6##"
    assert str(OWNSoundDiffusionCommand.next_station()) == "*22*9*6##"
    assert str(OWNSoundDiffusionCommand.previous_station()) == "*22*10*6##"


def test_who22_command_parser_dispatch() -> None:
    """Verify OWNCommand.parse dispatches WHO 22 frames to OWNSoundDiffusionCommand."""
    cmd = OWNCommand.parse("*22*1*3#4#1##")
    assert isinstance(cmd, OWNSoundDiffusionCommand)
    assert isinstance(cmd, OWNCommand)
    assert cmd.who == 22
    assert cmd.where == "3"
    assert cmd.target_address == "3#4#1"

    req = OWNCommand.parse("*#22*3#4#1##")
    assert isinstance(req, OWNSoundDiffusionCommand)
    assert isinstance(req, OWNCommand)
    assert req.who == 22
    assert req.is_request is True
    assert req.where == "3"
    assert req.target_address == "3#4#1"

    cmd_all = OWNSoundDiffusionCommand.turn_off("6")
    assert cmd_all.where == "6"
    assert cmd_all.target_address == "6"


@pytest.mark.parametrize(
    ("frame", "khz"),
    [
        ("*#22*5#2#1*5*1*8880##", 88800),
        ("*#22*5#2#1*5*1*9620##", 96200),
        ("*#22*5#2#1*5*1*10350##", 103500),
    ],
)
def test_who22_tuner_frequency_event(frame: str, khz: int) -> None:
    """Dimension 5 reports the F500 frequency in 10 kHz units (live MH200N frames)."""
    event = OWNMessage.parse(frame)
    assert isinstance(event, OWNSoundDiffusionEvent)
    assert event.target_type == "source"
    assert event.source_id == 1
    assert event.frequency_khz == khz
    assert event.preset is None
    assert f"{khz / 1000:.2f} MHz" in event.human_readable_log


@pytest.mark.parametrize(
    ("frame", "khz", "preset"),
    [
        ("*#22*5#2#1*11*1*8880*1##", 88800, 1),
        ("*#22*5#2#1*11*1*9620*2##", 96200, 2),
        ("*#22*5#2#1*11*1*10350*4##", 103500, 4),
    ],
)
def test_who22_tuner_frequency_and_preset_event(frame: str, khz: int, preset: int) -> None:
    event = OWNMessage.parse(frame)
    assert isinstance(event, OWNSoundDiffusionEvent)
    assert event.frequency_khz == khz
    assert event.preset == preset


def test_who22_tuner_preset_zero_is_not_a_stored_station() -> None:
    event = OWNMessage.parse("*#22*5#2#1*11*1*8950*0##")
    assert isinstance(event, OWNSoundDiffusionEvent)
    assert event.frequency_khz == 89500
    assert event.preset is None


def test_who22_tuner_station_report() -> None:
    event = OWNMessage.parse("*#22*2#1*6*3##")
    assert isinstance(event, OWNSoundDiffusionEvent)
    assert event.target_type == "source"
    assert event.source_id == 1
    assert event.preset == 3
    assert event.frequency_khz is None


def test_who22_rds_text_event() -> None:
    event = OWNMessage.parse("*#22*5#2#1*10*75*82*79*78*69*72*73*84##")
    assert isinstance(event, OWNSoundDiffusionEvent)
    assert event.rds_text == "KRONEHIT"
    assert event.is_rds_blank is False
    assert event.human_readable_log == "Audio Source 1 RDS text: 'KRONEHIT'."


def test_who22_rds_blank_while_retuning() -> None:
    event = OWNMessage.parse("*#22*5#2#1*10*32*32*32*32*32*32*32*32##")
    assert isinstance(event, OWNSoundDiffusionEvent)
    assert event.rds_text is None
    assert event.is_rds_blank is True


def test_who22_rds_keeps_asterisk_padding() -> None:
    event = OWNMessage.parse("*#22*5#2#1*10*42*82*65*68*73*79*42*32##")
    assert isinstance(event, OWNSoundDiffusionEvent)
    assert event.rds_text == "*RADIO*"


@pytest.mark.parametrize(
    "frame",
    [
        "*#22*5#2#1*10*42*42*79*79*69*42*79*79*69*42*42*32##",  # 12-code glitch
        "*#22*5#2#1*5*1*96200##",  # kHz where 10 kHz units belong
        "*#22*5#2#1*5*1##",  # frequency missing
        "*#22*5#2#1*11*1*9620##",  # preset missing
        "*#22*2#1*6*0##",  # station numbers start at 1
    ],
)
def test_who22_tuner_malformed_frames_set_nothing(frame: str) -> None:
    event = OWNMessage.parse(frame)
    assert isinstance(event, OWNSoundDiffusionEvent)
    assert event.frequency_khz is None
    assert event.preset is None
    assert event.rds_text is None
    assert event.is_rds_blank is False
# ---------------------------------------------------------------------------
# MyHomeServer1 + F500 + F441 + H4562, contributed by @bboykaos in OWNd#103
# (frames are literal; MyHOME tests/fixtures/traces/who22_myhomeserver1_f500_h4562)
# ---------------------------------------------------------------------------


def test_dimension_12_state_on_carries_the_audio_channel() -> None:
    on = OWNMessage.parse("*#22*3#7#5*12*1*2##")
    assert isinstance(on, OWNSoundDiffusionEvent)
    assert on.is_on is True
    assert on.audio_channel == 2
    assert on.is_standby is False
    assert on.human_readable_log == "Speaker 3#7#5 (Zone 75) is ON, audio channel 2."
    assert OWNMessage.parse("*#22*3#7#6*12*1*1##").audio_channel == 1


def test_dimension_12_state_0_type_10_is_standby() -> None:
    """After an atomic OFF and while paging mutes the house, the zone reports ``12*0*10``."""
    standby = OWNMessage.parse("*#22*3#7#5*12*0*10##")
    assert isinstance(standby, OWNSoundDiffusionEvent)
    assert standby.is_standby is True
    assert standby.is_off is True
    assert standby.audio_channel is None
    assert standby.multimedia_type == 10
    assert standby.human_readable_log == "Speaker 3#7#5 (Zone 75) is in standby (OFF or muted by a priority call)."
    # A state 0 with another type is a plain OFF, not standby.
    plain = OWNMessage.parse("*#22*3#1#1*12*0*4##")
    assert plain.is_standby is False
    assert plain.human_readable_log == "Speaker 3#1#1 (Zone 11) device state is OFF."


def test_power_on_with_source() -> None:
    event = OWNMessage.parse("*22*1#4#1*3#7#5##")
    assert isinstance(event, OWNSoundDiffusionEvent)
    assert event.is_on is True
    assert event.requested_source == 1
    assert event.is_atomic_off is False
    assert event.human_readable_log == "Speaker 3#7#5 (Zone 75) is switched ON with source 1."
    assert OWNMessage.parse("*22*1*3#7#5##").requested_source is None


def test_atomic_off() -> None:
    event = OWNMessage.parse("*22*0#4#0*3#7#5##")
    assert isinstance(event, OWNSoundDiffusionEvent)
    assert event.is_off is True
    assert event.is_atomic_off is True
    assert event.human_readable_log == "Speaker 3#7#5 (Zone 75) is switched OFF (atomic)."
    plain = OWNMessage.parse("*22*0*3#7#5##")
    assert plain.is_off is True
    assert plain.is_atomic_off is False


def test_matrix_route_to_source() -> None:
    event = OWNMessage.parse("*22*35#4#1#2*3#7#5##")
    assert isinstance(event, OWNSoundDiffusionEvent)
    assert event.is_route_source is True
    assert event.requested_source == 2
    assert event.target_type == "speaker"
    assert event.human_readable_log == "Speaker 3#7#5 (Zone 75) is routed to source 2."
    assert OWNMessage.parse("*22*35#4#1#1*3#7#6##").requested_source == 1
    # Too few parameters name no source.
    assert OWNMessage.parse("*22*35*3#7#6##").requested_source is None


def test_whole_house_paging() -> None:
    opened = OWNMessage.parse("*22*19#1*5#3#0#0##")
    assert isinstance(opened, OWNSoundDiffusionEvent)
    assert opened.target_type == "zone_control"
    assert opened.is_all_zones is True
    assert (opened.area, opened.point) == (0, 0)
    assert opened.equivalent_who16_where is None
    assert opened.is_paging_open is True
    assert opened.paging_channel == 1
    assert opened.human_readable_log == "Sound diffusion device 5#3#0#0 opens paging channel 1."

    voice = OWNMessage.parse("*22*20#1*5#3#0#0##")
    assert voice.is_paging_voice is True
    assert voice.paging_channel == 1
    assert voice.human_readable_log == "Sound diffusion device 5#3#0#0 starts paging voice on channel 1."
    assert OWNMessage.parse("*22*19*5#3#0#0##").paging_channel is None
    assert OWNMessage.parse("*22*9*2#1##").paging_channel is None


def test_wall_unit_keypress_is_not_a_station_change() -> None:
    press = OWNMessage.parse("*22*9*5#3#7#6##")
    assert isinstance(press, OWNSoundDiffusionEvent)
    assert press.target_type == "zone_control"
    assert (press.area, press.point) == (7, 6)
    assert press.is_all_zones is False
    assert press.is_keypress is True
    assert press.is_next_station is False
    assert press.human_readable_log == "Sound diffusion device 5#3#7#6 keypad pressed."
    # The same WHAT on a tuner source is still next station.
    station = OWNMessage.parse("*22*9*2#1##")
    assert station.is_next_station is True
    assert station.is_keypress is False


def test_paging_ducking_and_volume_restore_replay() -> None:
    for zone in ("3#5#1", "3#7#2", "3#1#8"):
        ducked = OWNMessage.parse(f"*#22*{zone}*12*0*10##")
        assert ducked.is_standby is True
    restored = OWNMessage.parse("*#22*3#5#1*1*1##")
    assert restored.volume == 1 and restored.is_standby is False


def test_new_command_builders_match_the_traces() -> None:
    assert str(OWNSoundDiffusionCommand.turn_on_with_source("3#7#5", 1)) == "*22*1#4#1*3#7#5##"
    assert str(OWNSoundDiffusionCommand.turn_on_with_source("3#7#6", 2, multimedia_type=4)) == "*22*1#4#2*3#7#6##"
    assert str(OWNSoundDiffusionCommand.turn_off_atomic("3#7#5")) == "*22*0#4#0*3#7#5##"
    assert str(OWNSoundDiffusionCommand.route_source("3#7#5", 2)) == "*22*35#4#1#2*3#7#5##"
    assert str(OWNSoundDiffusionCommand.open_paging()) == "*22*19#1*5#3#0#0##"
    assert str(OWNSoundDiffusionCommand.start_paging_voice()) == "*22*20#1*5#3#0#0##"
    assert str(OWNSoundDiffusionCommand.open_paging("5#3#7#6", 2)) == "*22*19#2*5#3#7#6##"
    assert str(OWNSoundDiffusionCommand.start_paging_voice("5#3#7#6", 2)) == "*22*20#2*5#3#7#6##"
    cmd = OWNSoundDiffusionCommand.route_source("3#7#5", 2)
    assert cmd.human_readable_log == "Routing sound diffusion device 3#7#5 to source 2."
    assert OWNSoundDiffusionCommand.turn_on_with_source("3#7#5", 1).human_readable_log == (
        "Turning ON sound diffusion device 3#7#5 with source 1."
    )
    assert OWNSoundDiffusionCommand.turn_off_atomic("3#7#5").human_readable_log == (
        "Turning OFF sound diffusion device 3#7#5 (atomic)."
    )
    assert OWNSoundDiffusionCommand.open_paging().human_readable_log == "Opening paging channel 1 on 5#3#0#0."
    assert OWNSoundDiffusionCommand.start_paging_voice().human_readable_log == (
        "Starting paging voice on channel 1 on 5#3#0#0."
    )


def test_builder_inputs_are_validated() -> None:
    with pytest.raises(ValueError):
        OWNSoundDiffusionCommand.turn_on_with_source("3#7#5", 0)
    with pytest.raises(ValueError):
        OWNSoundDiffusionCommand.route_source("3#7#5", 0)
    assert OWNSoundDiffusionCommand.zone_control_address(0, 0) == "5#3#0#0"
    assert OWNSoundDiffusionCommand.zone_control_address(7, 6) == "5#3#7#6"
    with pytest.raises(ValueError):
        OWNSoundDiffusionCommand.zone_control_address(10, 0)
    with pytest.raises(ValueError):
        OWNSoundDiffusionCommand.zone_control_address(0, -1)


@pytest.mark.parametrize(
    ("frame", "khz", "preset"),
    [
        ("*#22*5#2#1*11*1*1015*5##", 101500, 5),
        ("*#22*5#2#1*11*1*933*1##", 93300, 1),
        ("*#22*5#2#1*11*1*911*2##", 91100, 2),
        ("*#22*5#2#1*11*1*995*3##", 99500, 3),
        ("*#22*5#2#1*11*1*10150*5##", 101500, 5),
    ],
)
def test_who22_tuner_frequency_unit_follows_the_value(frame: str, khz: int, preset: int) -> None:
    """A MyHomeServer1 reports 101.5 MHz as 1015 (100 kHz), an MH200N as 10150 (10 kHz)."""
    event = OWNMessage.parse(frame)
    assert isinstance(event, OWNSoundDiffusionEvent)
    assert event.frequency_khz == khz
    assert event.preset == preset


@pytest.mark.parametrize("raw", ["874", "1081", "8749", "10801"])
def test_who22_tuner_frequency_outside_both_fm_ranges(raw: str) -> None:
    event = OWNMessage.parse(f"*#22*5#2#1*5*1*{raw}##")
    assert event.frequency_khz is None


def test_who22_rds_chunks_of_five_codes_are_text() -> None:
    event = OWNMessage.parse("*#22*5#2#1*10*82*65*68*73*79##")
    assert isinstance(event, OWNSoundDiffusionEvent)
    assert event.rds_text == "RADIO"
    assert OWNMessage.parse("*#22*5#2#1*10*68*69*69*74*65##").rds_text == "DEEJA"


def test_who22_frequency_and_presets() -> None:
    """Verify decoding of dimension 5, 6, and 11 frequency and preset frames."""
    # Dimension 5: Tuner frequency report from bus (10 kHz resolution: 10150 -> 101.50 MHz)
    freq_event = OWNMessage.parse("*#22*5#2#1*5*1*10150##")
    assert isinstance(freq_event, OWNSoundDiffusionEvent)
    assert freq_event.target_type == "source"
    assert freq_event.source_id == 1
    assert freq_event.frequency_band == 1
    assert freq_event.frequency_khz == 101500
    assert freq_event.frequency_mhz == 101.5
    assert "101.50 MHz" in freq_event.human_readable_log

    # Dimension 5 fallback: 100 kHz units (1015 -> 101.50 MHz)
    freq_fallback = OWNMessage.parse("*#22*2#1*5*1*1015##")
    assert isinstance(freq_fallback, OWNSoundDiffusionEvent)
    assert freq_fallback.frequency_khz == 101500
    assert freq_fallback.frequency_mhz == 101.5

    # Dimension 6: Active preset slot
    preset_event = OWNMessage.parse("*#22*2#1*6*3##")
    assert isinstance(preset_event, OWNSoundDiffusionEvent)
    assert preset_event.preset == 3
    assert "station is 3" in preset_event.human_readable_log

    # Dimension 11: Preset station memory frequency (P5 on 101.50 MHz)
    mem_event = OWNMessage.parse("*#22*5#2#1*11*1*10150*5##")
    assert isinstance(mem_event, OWNSoundDiffusionEvent)
    assert mem_event.preset == 5
    assert mem_event.frequency_mhz == 101.5
    assert mem_event.frequency_khz == 101500
    assert "101.50 MHz (station 5)" in mem_event.human_readable_log


def test_who22_rds_reporting() -> None:
    """Verify decoding of dimension 10 RDS frames and WHAT 31/32 control."""
    # 8-character Program Service name (RADIO   )
    rds_event = OWNMessage.parse("*#22*5#2#1*10*82*65*68*73*79*32*32*32##")
    assert isinstance(rds_event, OWNSoundDiffusionEvent)
    assert rds_event.rds_text == "RADIO"
    assert "RDS text: 'RADIO'" in rds_event.human_readable_log

    # RDS DEEJAY
    deejay = OWNMessage.parse("*#22*2#1*10*68*69*69*74*65*89*32*32##")
    assert isinstance(deejay, OWNSoundDiffusionEvent)
    assert deejay.rds_text == "DEEJAY"

    # Start RDS (WHAT 31) & Stop RDS (WHAT 32)
    start_rds = OWNMessage.parse("*22*31*2#1##")
    assert isinstance(start_rds, OWNSoundDiffusionEvent)
    assert start_rds.is_rds_start is True
    assert "started RDS reporting" in start_rds.human_readable_log

    stop_rds = OWNMessage.parse("*22*32*2#1##")
    assert isinstance(stop_rds, OWNSoundDiffusionEvent)
    assert stop_rds.is_rds_stop is True
    assert "stopped RDS reporting" in stop_rds.human_readable_log

    # Store preset (WHAT 33)
    store = OWNMessage.parse("*22*33#4*2#1##")
    assert isinstance(store, OWNSoundDiffusionEvent)
    assert store.preset == 4
    assert "stored frequency to preset 4" in store.human_readable_log

    # Follow-me (WHAT 34)
    follow_me = OWNMessage.parse("*22*34*3#1#1##")
    assert isinstance(follow_me, OWNSoundDiffusionEvent)
    assert follow_me.is_follow_me is True
    assert "follow-me" in follow_me.human_readable_log


def test_who22_matrix_route_parameters() -> None:
    """Verify full matrix area and source parameter extraction in WHAT 35."""
    route_area2 = OWNMessage.parse("*22*35#4#2#7*3#2#0##")
    assert isinstance(route_area2, OWNSoundDiffusionEvent)
    assert route_area2.multimedia_type == 4
    assert route_area2.matrix_area == 2
    assert route_area2.requested_source == 7
    assert "routed to source 7 on matrix area 2" in route_area2.human_readable_log


def test_who22_tuner_command_builders() -> None:
    """Verify new WHO 22 tuner and RDS command builders."""
    assert str(OWNSoundDiffusionCommand.set_frequency("2#1", 101500)) == "*#22*2#1*#5*1*10150##"
    assert str(OWNSoundDiffusionCommand.request_frequency("2#1")) == "*#22*2#1*5##"
    assert str(OWNSoundDiffusionCommand.set_preset("2#1", 3)) == "*#22*2#1*#6*3##"
    assert str(OWNSoundDiffusionCommand.set_preset("2#1", 5, frequency_khz=101500)) == "*#22*2#1*#11*1*10150*5##"
    assert str(OWNSoundDiffusionCommand.request_preset("2#1")) == "*#22*2#1*6##"
    assert str(OWNSoundDiffusionCommand.start_rds("2#1")) == "*22*31*2#1##"
    assert str(OWNSoundDiffusionCommand.stop_rds("2#1")) == "*22*32*2#1##"
    assert str(OWNSoundDiffusionCommand.store_preset("2#1", 4)) == "*22*33#4*2#1##"
    assert str(OWNSoundDiffusionCommand.send_rds_text("2#1", "RADIO")) == "*#22*2#1*#10*82*65*68*73*79*32*32*32##"
    assert str(OWNSoundDiffusionCommand.request_rds("2#1")) == "*#22*2#1*10##"
    assert str(OWNSoundDiffusionCommand.route_source("3#1#1", 7, matrix_area=2)) == "*22*35#4#2#7*3#1#1##"

    with pytest.raises(ValueError, match="frequency must be positive"):
        OWNSoundDiffusionCommand.set_frequency("2#1", 0)
    with pytest.raises(ValueError, match="frequency must be positive"):
        OWNSoundDiffusionCommand.set_frequency("2#1", -10)
    with pytest.raises(ValueError, match="preset must be positive"):
        OWNSoundDiffusionCommand.set_preset("2#1", 0)
    with pytest.raises(ValueError, match="preset must be positive"):
        OWNSoundDiffusionCommand.set_preset("2#1", -5)


def _decoded_bus_frames(row: dict[str, object]) -> list[str]:
    bus_frames = row.get("bus_frames", [])
    assert isinstance(bus_frames, list)
    decoded: list[str] = []
    for bf in bus_frames:
        assert isinstance(bf, str)
        text = bytes.fromhex(bf.replace(" ", "")).decode("ascii").strip()
        if text.startswith("$00"):
            text = "$" + text[2:]
        decoded.append(text)
    return decoded


@pytest.mark.parametrize(
    ("builder", "expected_frame", "expected_bus"),
    [
        (
            OWNSoundDiffusionCommand.turn_on_with_source("3#1#1", 1),
            "*22*1#4#1*3#1#1##",
            ["$0490018113"],
        ),
        (
            OWNSoundDiffusionCommand.turn_off_atomic("3#0#6"),
            "*22*0#4#0*3#0#6##",
            ["$0491068003"],
        ),
        (
            OWNSoundDiffusionCommand.turn_off_atomic("5#3#0#0"),
            "*22*0#4#0*5#3#0#0##",
            ["$04B1008003"],
        ),
        (
            OWNSoundDiffusionCommand.volume_up("3#1#1", step=5),
            "*22*3#5*3#1#1##",
            ["$0494018105"],
        ),
        (
            OWNSoundDiffusionCommand.set_volume("3#1#1", 20),
            "*#22*3#1#1*#1*20##",
            ["$0493018114"],
        ),
        (
            OWNSoundDiffusionCommand.request_volume("3#1#1"),
            "*#22*3#1#1*1##",
            ["$0495018100"],
        ),
        (
            OWNSoundDiffusionCommand.request_device_state("3#1#1"),
            "*#22*3#1#1*12##",
            ["$049501818F"],
        ),
        (
            OWNSoundDiffusionCommand.request_frequency("2#1"),
            "*#22*2#1*5##",
            ["$0495018FA0"],
        ),
        (
            OWNSoundDiffusionCommand.set_preset("2#1", 7),
            "*#22*2#1*#6*7##",
            ["$0493018FC6"],
        ),
        (
            OWNSoundDiffusionCommand.request_preset("2#1"),
            "*#22*2#1*6##",
            ["$0495018FC0"],
        ),
        (
            OWNSoundDiffusionCommand.next_station("2#1"),
            "*22*9*2#1##",
            ["$0494018FC1"],
        ),
        (
            OWNSoundDiffusionCommand.previous_station("2#1"),
            "*22*10*2#1##",
            ["$0494018FD1"],
        ),
        (
            OWNSoundDiffusionCommand.seek_up("2#1"),
            "*22*5*2#1##",
            ["$0494018FA0"],
        ),
        (
            OWNSoundDiffusionCommand.seek_down("2#1"),
            "*22*6*2#1##",
            ["$0494018FB0"],
        ),
        (
            OWNSoundDiffusionCommand.start_rds("2#1"),
            "*22*31*2#1##",
            ["$06D101F83501410400"],
        ),
        (
            OWNSoundDiffusionCommand.stop_rds("2#1"),
            "*22*32*2#1##",
            ["$06D101F83501420400"],
        ),
        (
            OWNSoundDiffusionCommand.store_preset("2#1", 3),
            "*22*33#3*2#1##",
            ["$0493018FD2"],
        ),
        (
            OWNSoundDiffusionCommand.route_source("3#1#1", 2, matrix_area=1),
            "*22*35#4#1#2*3#1#1##",
            ["$04A10F8113", "$0490028F13", "$0490018113"],
        ),
        (
            OWNSoundDiffusionCommand.route_source("3#2#0", 7, matrix_area=2),
            "*22*35#4#2#7*3#2#0##",
            ["$04A10F8123", "$0490078F23", "$0490008223"],
        ),
    ],
)
def test_who22_firmware_oracle_conformance(
    builder: OWNSoundDiffusionCommand,
    expected_frame: str,
    expected_bus: list[str],
) -> None:
    """Verify WHO 22 command builders against bt_multi firmware oracle bus output."""
    assert str(builder) == expected_frame
    parsed = OWNCommand.parse(expected_frame)
    assert isinstance(parsed, OWNSoundDiffusionCommand)
    assert expected_frame in ORACLE
    rows = ORACLE[expected_frame]
    out_products = {
        r["product"] for r in rows if r["verdict"] == "out" and r["bus_frames"]
    }
    assert out_products >= {
        "F453AV",
        "F454",
        "F459",
        "F461",
        "MyHomeServer1",
    }
    mhs_row = next(r for r in rows if r["product"] == "MyHomeServer1")
    assert _decoded_bus_frames(mhs_row) == expected_bus


def test_who22_infeasible_input_validation() -> None:
    """Verify WHO 22 command builders reject infeasible parameters."""
    with pytest.raises(ValueError, match="multimedia_type must be non-negative"):
        OWNSoundDiffusionCommand.turn_on_with_source("3#1#1", 1, multimedia_type=-1)
    with pytest.raises(ValueError, match="multimedia_type must be non-negative"):
        OWNSoundDiffusionCommand.turn_off_atomic("3#1#1", multimedia_type=-1)
    with pytest.raises(ValueError, match="matrix_area must be non-negative"):
        OWNSoundDiffusionCommand.route_source("3#1#1", 1, matrix_area=-1)
    with pytest.raises(ValueError, match="multimedia_type must be non-negative"):
        OWNSoundDiffusionCommand.route_source("3#1#1", 1, multimedia_type=-1)

    with pytest.raises(ValueError, match="frequency must be finite"):
        OWNSoundDiffusionCommand.set_frequency("2#1", float("nan"))
    with pytest.raises(ValueError, match="frequency must be at least 10 kHz"):
        OWNSoundDiffusionCommand.set_frequency("2#1", 5)
    with pytest.raises(ValueError, match="band must be between 1 and 4"):
        OWNSoundDiffusionCommand.set_frequency("2#1", 101500, band=0)
    with pytest.raises(ValueError, match="band must be between 1 and 4"):
        OWNSoundDiffusionCommand.set_frequency("2#1", 101500, band=5)

    with pytest.raises(ValueError, match="frequency must be finite"):
        OWNSoundDiffusionCommand.set_preset("2#1", 1, frequency_khz=float("inf"))
    with pytest.raises(ValueError, match="frequency must be positive"):
        OWNSoundDiffusionCommand.set_preset("2#1", 1, frequency_khz=0)
    with pytest.raises(ValueError, match="frequency must be at least 10 kHz"):
        OWNSoundDiffusionCommand.set_preset("2#1", 1, frequency_khz=5)
    with pytest.raises(ValueError, match="band must be between 1 and 4"):
        OWNSoundDiffusionCommand.set_preset("2#1", 1, frequency_khz=101500, band=0)

    with pytest.raises(ValueError, match="preset must be positive"):
        OWNSoundDiffusionCommand.store_preset("2#1", 0)
    with pytest.raises(ValueError, match="channel must be positive"):
        OWNSoundDiffusionCommand.open_paging("5#3#0#0", channel=0)
    with pytest.raises(ValueError, match="channel must be positive"):
        OWNSoundDiffusionCommand.start_paging_voice("5#3#0#0", channel=0)

    for bad_step in (0, -1, 32):
        with pytest.raises(ValueError, match="step must be positive and between 1 and 31"):
            OWNSoundDiffusionCommand.volume_up("3#1#1", step=bad_step)
        with pytest.raises(ValueError, match="step must be positive and between 1 and 31"):
            OWNSoundDiffusionCommand.volume_down("3#1#1", step=bad_step)
    assert str(OWNSoundDiffusionCommand.volume_down("3#1#1", step=5)) == "*22*4#5*3#1#1##"

    # Dimension 1 volume reports outside 0..31 are ignored
    assert OWNSoundDiffusionEvent("*#22*3#4#1*1*0##").volume == 0
    assert OWNSoundDiffusionEvent("*#22*3#4#1*1*31##").volume == 31
    assert OWNSoundDiffusionEvent("*#22*3#4#1*1*32##").volume is None
    assert OWNSoundDiffusionEvent("*#22*3#4#1*1*-1##").volume is None




# WHO 22 tuner seek / step builders and the cleared-preset flag. The physical
# F500 frames come from an H/L4684 6.0.11 (MyHOME#839, fixture issue_466
# myhome_trace_HL4684_all_2026-11-01T11-48-15.json): *#22*5#2#1*5*1*10530##
# and *#22*5#2#1*11*1*10530*5## (105.30 MHz, station 5). *22*5*2#1## and
# *22*6*2#1## are in the firmware oracle (sound-who22); *22*7*2#1## and
# *22*8*2#1## are not in its index. Nothing here reaches a gateway.


def test_who22_seek_and_step_builders() -> None:
    assert str(OWNSoundDiffusionCommand.seek_up()) == "*22*5*6##"
    assert str(OWNSoundDiffusionCommand.seek_up("2#1")) == "*22*5*2#1##"
    assert str(OWNSoundDiffusionCommand.seek_down()) == "*22*6*6##"
    assert str(OWNSoundDiffusionCommand.seek_down("2#1")) == "*22*6*2#1##"
    assert str(OWNSoundDiffusionCommand.step_frequency_up()) == "*22*7*6##"
    assert str(OWNSoundDiffusionCommand.step_frequency_up("2#1")) == "*22*7*2#1##"
    assert str(OWNSoundDiffusionCommand.step_frequency_down()) == "*22*8*6##"
    assert str(OWNSoundDiffusionCommand.step_frequency_down(6)) == "*22*8*6##"
    assert OWNSoundDiffusionCommand.seek_up("2#1").human_readable_log == (
        "Seeking the next station up on sound diffusion device 2#1."
    )
    assert OWNSoundDiffusionCommand.seek_down("2#1").human_readable_log == (
        "Seeking the next station down on sound diffusion device 2#1."
    )
    assert OWNSoundDiffusionCommand.step_frequency_up("2#1").human_readable_log == (
        "Stepping the frequency up on sound diffusion device 2#1."
    )
    assert OWNSoundDiffusionCommand.step_frequency_down("2#1").human_readable_log == (
        "Stepping the frequency down on sound diffusion device 2#1."
    )
    for builder in (
        OWNSoundDiffusionCommand.seek_up,
        OWNSoundDiffusionCommand.seek_down,
        OWNSoundDiffusionCommand.step_frequency_up,
        OWNSoundDiffusionCommand.step_frequency_down,
    ):
        command = builder("2#1")
        assert isinstance(command, OWNSoundDiffusionCommand)
        assert command.target_address == "2#1"
        assert OWNCommand.parse(str(command)).__class__ is OWNSoundDiffusionCommand
        for bad_where in ("", "   ", "2*1"):
            with pytest.raises(ValueError, match="where must be a non-empty address without '\\*'"):
                builder(bad_where)
    # Not in the oracle index: pinned so a replay gets noticed.
    assert "*22*7*2#1##" not in ORACLE
    assert "*22*8*2#1##" not in ORACLE


@pytest.mark.parametrize(
    ("frame", "flag", "log"),
    [
        ("*22*5*2#1##", "is_seek_up", "Audio Source 1 seeks the next station up."),
        ("*22*6*2#1##", "is_seek_down", "Audio Source 1 seeks the next station down."),
        ("*22*7*2#1##", "is_step_frequency_up", "Audio Source 1 steps the frequency up."),
        ("*22*8*2#1##", "is_step_frequency_down", "Audio Source 1 steps the frequency down."),
        ("*22*6*6##", "is_seek_down", "Sound diffusion device 6 seeks the next station down."),
    ],
)
def test_who22_seek_and_step_events(frame: str, flag: str, log: str) -> None:
    event = OWNMessage.parse(frame)
    assert isinstance(event, OWNSoundDiffusionEvent)
    assert type(OWNEvent.parse(frame)) is OWNSoundDiffusionEvent
    flags = ("is_seek_up", "is_seek_down", "is_step_frequency_up", "is_step_frequency_down")
    assert {name: getattr(event, name) for name in flags} == {name: name == flag for name in flags}
    assert event.is_next_station is False
    assert event.is_previous_station is False
    assert event.is_next_track is False
    assert event.is_volume_up is False
    assert event.human_readable_log == log


def test_who22_manual_tuning_with_a_step_is_not_a_seek() -> None:
    # The published manual-tuning form ``*22*5#STEP*2#S##`` / ``*22*6#STEP*2#S##``
    # carries a step parameter: not an automatic seek, not WHAT 7 / 8 either.
    for frame, log in (
        ("*22*5#3*2#1##", "Audio Source 1 tunes the frequency up by 3 step(s)."),
        ("*22*6#10*2#1##", "Audio Source 1 tunes the frequency down by 10 step(s)."),
    ):
        event = OWNMessage.parse(frame)
        assert isinstance(event, OWNSoundDiffusionEvent)
        assert event.is_seek_up is False
        assert event.is_seek_down is False
        assert event.is_step_frequency_up is False
        assert event.is_step_frequency_down is False
        assert event.human_readable_log == log


def test_who22_other_whats_set_no_seek_or_step_flag() -> None:
    for frame in ("*22*9*2#1##", "*22*3*3#1#1##", "*22*1#4#1*3#1#1##", "*#22*5#2#1*11*1*10530*5##"):
        event = OWNMessage.parse(frame)
        assert isinstance(event, OWNSoundDiffusionEvent)
        assert event.is_seek_up is False
        assert event.is_seek_down is False
        assert event.is_step_frequency_up is False
        assert event.is_step_frequency_down is False


def test_who22_dimension_11_preset_zero_sets_is_preset_cleared() -> None:
    # Tuned off every stored station (manually tuned, or before a station is selected).
    cleared = OWNMessage.parse("*#22*5#2#1*11*1*10530*0##")
    assert isinstance(cleared, OWNSoundDiffusionEvent)
    assert cleared.frequency_khz == 105300
    assert cleared.preset is None
    assert cleared.is_preset_cleared is True
    assert cleared.human_readable_log == "Audio Source 1 is tuned to 105.30 MHz (no stored station)."
    # Physical H/L4684 F500 frame: station 5 selected at the same frequency.
    stored = OWNMessage.parse("*#22*5#2#1*11*1*10530*5##")
    assert isinstance(stored, OWNSoundDiffusionEvent)
    assert stored.preset == 5
    assert stored.is_preset_cleared is False
    assert stored.human_readable_log == "Audio Source 1 is tuned to 105.30 MHz (station 5)."
    # Physical dimension 5 report: no preset field at all, so not "cleared".
    no_field = OWNMessage.parse("*#22*5#2#1*5*1*10530##")
    assert isinstance(no_field, OWNSoundDiffusionEvent)
    assert no_field.preset is None
    assert no_field.is_preset_cleared is False
    assert no_field.human_readable_log == "Audio Source 1 is tuned to 105.30 MHz."


@pytest.mark.parametrize(
    "frame",
    [
        "*#22*5#2#1*11*1*10530*##",  # empty preset field
        "*#22*5#2#1*11*1*0*0##",  # frequency outside the FM band
        "*#22*5#2#1*11*1*10530##",  # a dimension 11 frame without the preset field
        "*#22*2#1*6*0##",  # dimension 6 preset 0 is not a dimension 11 report
    ],
)
def test_who22_is_preset_cleared_needs_a_decoded_dimension_11_frequency(frame: str) -> None:
    event = OWNMessage.parse(frame)
    assert isinstance(event, OWNSoundDiffusionEvent)
    assert event.is_preset_cleared is False
    assert event.preset is None
