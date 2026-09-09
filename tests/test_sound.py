"""Tests for WHO 16 sound messages."""

import pytest

from OWNd.message import OWNMessage, OWNSoundCommand, OWNSoundEvent


def test_sound_source_and_zone_events_are_distinct() -> None:
    source = OWNMessage.parse("*16*3*102##")
    zone = OWNMessage.parse("*16*13*21##")
    volume = OWNMessage.parse("*#16*21*1*37##")

    assert isinstance(source, OWNSoundEvent)
    assert source.is_source_event
    assert source.source_id == "2"
    assert source.is_on
    assert "Audio Source 2 is switched ON" in source.human_readable_log
    assert isinstance(zone, OWNSoundEvent)
    assert zone.is_off
    assert "Audio Zone 21 is switched OFF" in zone.human_readable_log
    assert isinstance(volume, OWNSoundEvent)
    assert volume.volume == 37


def test_unknown_sound_command_has_diagnostic_log() -> None:
    message = OWNMessage.parse("*16*30*22##")

    assert isinstance(message, OWNSoundEvent)
    assert "received command: 30" in message.human_readable_log


def test_sound_commands_validate_ranges() -> None:
    assert str(OWNSoundCommand.set_volume("21", 40)) == "*#16*21*#1*40##"
    assert [str(command) for command in OWNSoundCommand.select_source("21", 2)] == [
        "*16*3*102##",
        "*16*3*121##",
    ]

    with pytest.raises(ValueError):
        OWNSoundCommand.set_volume("21", 101)
    with pytest.raises(ValueError):
        OWNSoundCommand.select_source("21", 0)
