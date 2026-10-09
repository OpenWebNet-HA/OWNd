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
    assert not zone.is_source_event
    assert not zone.is_routing_event
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
        "*16*3*122##",
    ]

    with pytest.raises(ValueError):
        OWNSoundCommand.set_volume("21", 101)
    with pytest.raises(ValueError):
        OWNSoundCommand.select_source("21", 0)


def test_select_source_uses_environment_of_the_amplifier_address() -> None:
    """Routing is addressed by environment, not by amplifier.

    Amplifier addresses are `EA`: the first digit is the environment, the
    second the amplifier within it. The matrix is routed with `1ES`, so both
    amplifiers 21 and 23 route through environment 2.
    """
    assert [str(command) for command in OWNSoundCommand.select_source("23", 2)] == [
        "*16*3*102##",
        "*16*3*122##",
    ]
    assert [str(command) for command in OWNSoundCommand.select_source("23", 1)] == [
        "*16*3*101##",
        "*16*3*121##",
    ]
    assert [str(command) for command in OWNSoundCommand.select_source("41", 3)] == [
        "*16*3*103##",
        "*16*3*143##",
    ]
    # Single-digit, environment 0, and non-numeric addresses cannot be routed to a matrix source.
    with pytest.raises(ValueError, match="two-digit amplifier address"):
        OWNSoundCommand.select_source("2", 2)
    with pytest.raises(ValueError, match="two-digit amplifier address"):
        OWNSoundCommand.select_source("01", 2)
    with pytest.raises(ValueError, match="two-digit amplifier address"):
        OWNSoundCommand.select_source("#1", 2)
    with pytest.raises(ValueError, match="two-digit amplifier address"):
        OWNSoundCommand.select_source("20", 2)
    # Non-ASCII digits pass str.isdigit() but are not an address
    with pytest.raises(ValueError, match="two-digit amplifier address"):
        OWNSoundCommand.select_source("٢٣", 2)


def test_status_request_uses_dimension_5() -> None:
    """WHO 16 status is `*#16*WHERE*5##`; an MH201 NACKs `*#16*WHERE##`."""
    status = OWNSoundCommand.status("22")

    assert str(status) == "*#16*22*5##"
    assert status._message_type == "DIMENSION_REQUEST"
    assert status.dimension == 5
    assert str(OWNSoundCommand.status("0")) == "*#16*0*5##"


def test_routing_event_exposes_environment_and_source() -> None:
    routing = OWNMessage.parse("*16*3*122##")

    assert isinstance(routing, OWNSoundEvent)
    assert routing.is_routing_event
    assert not routing.is_source_event
    assert routing.environment == "2"
    assert routing.routed_source == "2"
    assert routing.source_id is None
    assert (
        "Routing of environment 2 to source 2 is switched ON"
        in routing.human_readable_log
    )
    assert routing.is_on

    # A routing frame keeps its address as `zone`: MyHOME parses routing from
    # it, and a None there turned every matrix re-broadcast into a zone ON.
    assert routing.zone == "122"


@pytest.mark.parametrize(
    ("frame", "environment", "source", "log"),
    [
        ("*16*3*111##", "1", "1", "is switched ON"),
        ("*16*3*141##", "4", "1", "is switched ON"),
        ("*16*3*181##", "8", "1", "is switched ON"),
        ("*16*3*199##", "9", "9", "is switched ON"),
        ("*16*13*122##", "2", "2", "is switched OFF"),
        # Source 0 is not a matrix input, but the frame is still routing and
        # must not surface as amplifier `1E0`.
        ("*16*3*120##", "2", "0", "is switched ON"),
        ("*16*13*190##", "9", "0", "is switched OFF"),
    ],
)
def test_routing_event_decomposes_every_environment(
    frame: str, environment: str, source: str, log: str
) -> None:
    event = OWNMessage.parse(frame)

    assert isinstance(event, OWNSoundEvent)
    assert event.is_routing_event
    assert event.zone == frame.split("*")[3].rstrip("#")
    assert event.environment == environment
    assert event.routed_source == source
    assert (
        f"Routing of environment {environment} to source {source} {log}"
        in event.human_readable_log
    )


@pytest.mark.parametrize(
    "frame",
    [
        "*16*3*102##",  # source 2 powering on
        "*16*13*21##",  # amplifier 21
        "*16*3*100##",  # general source
        "*16*3*1٢٢##",  # non-ASCII digits
        "*16*3*0##",  # general amplifiers
    ],
)
def test_non_routing_events_have_no_environment(frame: str) -> None:
    event = OWNMessage.parse(frame)

    assert isinstance(event, OWNSoundEvent)
    assert not event.is_routing_event
    assert event.environment is None
    assert event.routed_source is None
    assert event.zone == event.where


def test_who16_sound_source_commands() -> None:
    """Verify WHO 16 sound source command builders and range validation."""
    assert str(OWNSoundCommand.next_track("101")) == "*16*6001*101##"
    assert str(OWNSoundCommand.next_track(102, 5)) == "*16*6005*102##"
    assert str(OWNSoundCommand.previous_track("101")) == "*16*6101*101##"
    assert str(OWNSoundCommand.previous_track(102, 3)) == "*16*6103*102##"
    assert str(OWNSoundCommand.seek_up("101")) == "*16*5000*101##"
    assert str(OWNSoundCommand.seek_down("101")) == "*16*5100*101##"
    assert str(OWNSoundCommand.select_track("101", 4)) == "*#16*101*#7*4##"
    assert str(OWNSoundCommand.request_track("101")) == "*#16*101*7##"
    assert str(OWNSoundCommand.set_frequency("101", 107000)) == "*#16*101*#6*0*107000##"
    # Below 100 MHz the value is not zero-padded (F500N capture, MyHOME#427).
    assert str(OWNSoundCommand.set_frequency("101", 96200)) == "*#16*101*#6*0*96200##"
    assert str(OWNSoundCommand.request_frequency("101")) == "*#16*101*6##"
    assert str(OWNSoundCommand.start_rds("101")) == "*16*101*101##"
    assert str(OWNSoundCommand.stop_rds("101")) == "*16*102*101##"
    assert str(OWNSoundCommand.request_rds("101")) == "*#16*101*8##"

    with pytest.raises(ValueError, match="step must be between 1 and 15"):
        OWNSoundCommand.next_track("101", 0)
    with pytest.raises(ValueError, match="step must be between 1 and 15"):
        OWNSoundCommand.next_track("101", 16)
    with pytest.raises(ValueError, match="step must be between 1 and 15"):
        OWNSoundCommand.previous_track("101", 0)
    with pytest.raises(ValueError, match="step must be between 1 and 15"):
        OWNSoundCommand.previous_track("101", 16)
    with pytest.raises(ValueError, match="track must be greater than or equal to 1"):
        OWNSoundCommand.select_track("101", 0)
    with pytest.raises(ValueError, match="track must be greater than or equal to 1"):
        OWNSoundCommand.select_track("101", -1)
    with pytest.raises(ValueError, match="frequency in kHz must be positive"):
        OWNSoundCommand.set_frequency("101", 0)
    with pytest.raises(ValueError, match="frequency in kHz must be positive"):
        OWNSoundCommand.set_frequency("101", -107000)


def test_who16_sound_source_events() -> None:
    """Verify WHO 16 sound source event parsing and state extraction."""
    # Source busy indicator
    busy = OWNMessage.parse("*16*100*101##")
    assert isinstance(busy, OWNSoundEvent)
    assert busy.is_source_busy is True
    assert busy.source_id == "1"
    assert "BUSY" in busy.human_readable_log

    # Track advance steps
    step_fwd = OWNMessage.parse("*16*6001*101##")
    assert isinstance(step_fwd, OWNSoundEvent)
    assert step_fwd.track_step_forward == 1
    assert "advance track/station by 1 step(s)" in step_fwd.human_readable_log

    step_fwd5 = OWNMessage.parse("*16*6005*101##")
    assert isinstance(step_fwd5, OWNSoundEvent)
    assert step_fwd5.track_step_forward == 5

    # Track return steps
    step_back = OWNMessage.parse("*16*6101*101##")
    assert isinstance(step_back, OWNSoundEvent)
    assert step_back.track_step_backward == 1
    assert "return track/station by 1 step(s)" in step_back.human_readable_log

    # Hardware seek
    seek_up = OWNMessage.parse("*16*5000*101##")
    assert isinstance(seek_up, OWNSoundEvent)
    assert seek_up.is_seek_up is True

    seek_down = OWNMessage.parse("*16*5100*101##")
    assert isinstance(seek_down, OWNSoundEvent)
    assert seek_down.is_seek_down is True

    # Frequency report
    freq = OWNMessage.parse("*#16*101*6*0*107000##")
    assert isinstance(freq, OWNSoundEvent)
    assert freq.frequency_khz == 107000
    assert "frequency is 107000 kHz" in freq.human_readable_log

    # Stored station/track report
    trk = OWNMessage.parse("*#16*101*7*0*3##")
    assert isinstance(trk, OWNSoundEvent)
    assert trk.track == 3
    assert "station/track is 3" in trk.human_readable_log

    # RDS text report
    rds = OWNMessage.parse("*#16*101*8*82*65*68*73*79*32*32*49##")
    assert isinstance(rds, OWNSoundEvent)
    assert rds.rds_text == "RADIO  1"
    assert "RADIO  1" in rds.human_readable_log

    # Malformed dimension error handling
    bad_freq = OWNSoundEvent("*#16*101*6*##")
    assert bad_freq.frequency_khz is None

    bad_freq_neg = OWNSoundEvent("*#16*101*6*0*0##")
    assert bad_freq_neg.frequency_khz is None

    bad_trk = OWNSoundEvent("*#16*101*7*##")
    assert bad_trk.track is None

    bad_trk_zero = OWNSoundEvent("*#16*101*7*0*0##")
    assert bad_trk_zero.track is None

    bad_rds = OWNSoundEvent("*#16*101*8*82*65*68*73*79*32*32*##")
    assert bad_rds.rds_text == "RADIO"

    zero_rds = OWNSoundEvent("*#16*101*8*82*65*68*73*79*32*32*0##")
    assert zero_rds.rds_text == "RADIO"

    # Non-8-code RDS payloads are ignored as malformed frames
    short_rds = OWNSoundEvent("*#16*101*8*82*65*68##")
    assert short_rds.rds_text is None

    long_rds = OWNSoundEvent("*#16*101*8*82*65*68*73*79*32*32*49*50##")
    assert long_rds.rds_text is None

    # Blank RDS payload
    blank_rds = OWNSoundEvent("*#16*101*8*32*32*32*32*32*32*32*32##")
    assert blank_rds.rds_text is None
    assert "RDS text: ''" in blank_rds.human_readable_log
