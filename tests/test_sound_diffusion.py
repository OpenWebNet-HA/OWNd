"""Tests for WHO 22 advanced sound diffusion messages."""

import pytest

from OWNd.message import (
    OWNCommand,
    OWNMessage,
    OWNSoundDiffusionCommand,
    OWNSoundDiffusionEvent,
)


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
    src_dim = OWNMessage.parse("*#22*5#2#1*10*82##")
    assert isinstance(src_dim, OWNSoundDiffusionEvent)
    assert src_dim.target_type == "source"
    assert src_dim.source_id == 1
    assert "Audio Source 1 reported dimension 10." in src_dim.human_readable_log

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
