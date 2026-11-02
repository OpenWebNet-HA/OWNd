"""Tests for WHO 16 sound messages."""

import json
from pathlib import Path

import pytest

from OWNd.message import OWNCommand, OWNEvent, OWNMessage, OWNSoundCommand, OWNSoundEvent


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


def test_who16_volume_step_delta_events() -> None:
    """Verify WHO 16 stepped volume WHAT 1001..1015 and 1101..1115 decode volume_step_delta."""
    vol_up_1 = OWNMessage.parse("*16*1001*21##")
    assert isinstance(vol_up_1, OWNSoundEvent)
    assert vol_up_1.volume_step_delta == 1
    assert "increase volume by 1 step(s)" in vol_up_1.human_readable_log

    vol_up_15 = OWNMessage.parse("*16*1015*21##")
    assert isinstance(vol_up_15, OWNSoundEvent)
    assert vol_up_15.volume_step_delta == 15

    vol_down_1 = OWNMessage.parse("*16*1101*21##")
    assert isinstance(vol_down_1, OWNSoundEvent)
    assert vol_down_1.volume_step_delta == -1
    assert "decrease volume by 1 step(s)" in vol_down_1.human_readable_log

    vol_down_15 = OWNMessage.parse("*16*1115*21##")
    assert isinstance(vol_down_15, OWNSoundEvent)
    assert vol_down_15.volume_step_delta == -15


def test_who16_infeasible_input_validation() -> None:
    """Verify WHO 16 command builders reject empty/wildcard where and non-finite frequency."""
    for bad_where in ("", "   ", "21*1"):
        with pytest.raises(ValueError, match="where must be a non-empty address without '\\*'"):
            OWNSoundCommand.turn_on(bad_where)
        with pytest.raises(ValueError, match="where must be a non-empty address without '\\*'"):
            OWNSoundCommand.set_frequency(bad_where, 107000)

    for bad_freq in (float("nan"), float("inf"), float("-inf")):
        with pytest.raises(ValueError, match="frequency in kHz must be finite"):
            OWNSoundCommand.set_frequency("101", bad_freq)


# WHO 16 FM tuner manual frequency steps (WHAT 5001..5015 / 5101..5115,
# Encyclopedia ownkb:chunk:r000371, ownkb:claim:c002096 / c002098) and the
# write-only DIMENSION 10 station store (ownkb:chunk:r000376,
# ownkb:claim:c002128 / c002135). *16*5001*101##, *16*5101*101## and
# *#16*101*#10*5## are in the firmware oracle (sound-who16-source). The
# physical F500 frames *#16*101*6*0*105300## and *#16*101*7*0*5## (105.30 MHz,
# station 5) come from an H/L4684 6.0.11 (MyHOME#839, fixture issue_466
# myhome_trace_HL4684_all_2026-11-01T11-48-15.json). Nothing here reaches a
# gateway.

_ORACLE_PATH = Path(__file__).parent / "golden" / "firmware_oracle.json"
_ORACLE = json.loads(_ORACLE_PATH.read_text(encoding="utf-8"))["verdicts"]
_BT_DIFSON_ACK = ("F453", "F453AV", "F454", "H4684", "MH200", "MH200N")
_BT_DIFSON_NACK = ("F450", "F459", "F460", "F461", "MH202", "MyHomeServer1")


def _oracle_rows(frame: str) -> dict[str, dict[str, object]]:
    assert frame in _ORACLE, frame
    rows = {row["product"]: row for row in _ORACLE[frame]}
    assert set(rows) == set(_BT_DIFSON_ACK) | set(_BT_DIFSON_NACK)
    return rows


def _bus_frame(row: dict[str, object]) -> str:
    bus_frames = row["bus_frames"]
    assert isinstance(bus_frames, list) and len(bus_frames) == 1
    return bytes.fromhex(bus_frames[0].replace(" ", "")).decode("ascii").strip()


def test_who16_frequency_step_builders() -> None:
    assert str(OWNSoundCommand.step_frequency_up("101")) == "*16*5001*101##"
    assert str(OWNSoundCommand.step_frequency_up(102, 15)) == "*16*5015*102##"
    assert str(OWNSoundCommand.step_frequency_up("101", step=3)) == "*16*5003*101##"
    assert str(OWNSoundCommand.step_frequency_down("101")) == "*16*5101*101##"
    assert str(OWNSoundCommand.step_frequency_down(102, 15)) == "*16*5115*102##"
    assert str(OWNSoundCommand.step_frequency_down("101", step="7")) == "*16*5107*101##"
    assert OWNSoundCommand.step_frequency_up("101", 2).human_readable_log == (
        "Increasing frequency on 101 by 2 step(s)."
    )
    assert OWNSoundCommand.step_frequency_down("101").human_readable_log == (
        "Decreasing frequency on 101 by 1 step(s)."
    )
    # A step of 0 would be the automatic seek (5000 / 5100): refused here.
    assert str(OWNSoundCommand.seek_up("101")) == "*16*5000*101##"
    assert str(OWNSoundCommand.seek_down("101")) == "*16*5100*101##"
    for builder in (OWNSoundCommand.step_frequency_up, OWNSoundCommand.step_frequency_down):
        assert isinstance(builder("101"), OWNSoundCommand)
        assert OWNCommand.parse(str(builder("101"))).__class__ is OWNSoundCommand
        for step in (0, 16, -1, 100):
            with pytest.raises(ValueError, match=f"step must be between 1 and 15, got {step}"):
                builder("101", step)
        for bad_step in (True, False, 1.5, None, [1]):
            with pytest.raises(ValueError, match="step must be between 1 and 15"):
                builder("101", bad_step)  # type: ignore[arg-type]
        with pytest.raises(ValueError):
            builder("101", "x")
        for bad_where in ("", "   ", "21*1"):
            with pytest.raises(ValueError, match="where must be a non-empty address without '\\*'"):
                builder(bad_where)


@pytest.mark.parametrize(
    ("frame", "bus"),
    [
        ("*16*5001*101##", "$0494018FA1"),
        ("*16*5101*101##", "$0494018FB1"),
    ],
)
def test_who16_frequency_steps_match_the_firmware_oracle(frame: str, bus: str) -> None:
    """``*16*5001*101##`` / ``*16*5101*101##`` are ACKed and put on the bus by the bt_difson gateways."""
    builder = OWNSoundCommand.step_frequency_up if "5001" in frame else OWNSoundCommand.step_frequency_down
    assert str(builder("101", 1)) == frame
    rows = _oracle_rows(frame)
    for product in _BT_DIFSON_ACK:
        assert (rows[product]["reply"], rows[product]["verdict"]) == ("ack", "out"), product
        assert _bus_frame(rows[product]) == bus, product
    for product in _BT_DIFSON_NACK:
        assert (rows[product]["reply"], rows[product]["verdict"]) == ("nack", "silent"), product
        assert rows[product]["bus_frames"] == [], product
    # The old WHAT 4001 / 4101 spelling is not what bt_difson answers: not in the index.
    assert frame.replace("*5", "*4", 1) not in _ORACLE


def test_who16_store_station_builder() -> None:
    assert str(OWNSoundCommand.store_station("101", 5)) == "*#16*101*#10*5##"
    assert str(OWNSoundCommand.store_station(101, 1)) == "*#16*101*#10*1##"
    assert str(OWNSoundCommand.store_station("101", "3")) == "*#16*101*#10*3##"
    assert OWNSoundCommand.store_station("101", 5).human_readable_log == (
        "Storing current frequency into station 5 on 101."
    )
    assert OWNCommand.parse("*#16*101*#10*5##").__class__ is OWNSoundCommand
    assert OWNMessage.parse("*#16*101*#10*5##").is_dimension_writing
    # bt_difson: cmp r0, #5; bgt NACK. Stations 6..15 go through WHO 22 store_preset.
    for station in (0, 6, 15, 16, -1):
        with pytest.raises(ValueError, match=f"station must be between 1 and 5, got {station}"):
            OWNSoundCommand.store_station("101", station)
    for bad_station in (True, False, 2.5, None):
        with pytest.raises(ValueError, match="station must be between 1 and 5"):
            OWNSoundCommand.store_station("101", bad_station)  # type: ignore[arg-type]
    for bad_where in ("", "   ", "21*1"):
        with pytest.raises(ValueError, match="where must be a non-empty address without '\\*'"):
            OWNSoundCommand.store_station(bad_where, 5)


def test_who16_store_station_matches_the_firmware_oracle() -> None:
    """``*#16*101*#10*5##`` is ACKed and put on the bus (``$0493018FD4``) by the bt_difson gateways."""
    frame = str(OWNSoundCommand.store_station("101", 5))
    rows = _oracle_rows(frame)
    for product in _BT_DIFSON_ACK:
        assert (rows[product]["reply"], rows[product]["verdict"]) == ("ack", "out"), product
        assert _bus_frame(rows[product]) == "$0493018FD4", product
    for product in _BT_DIFSON_NACK:
        assert (rows[product]["reply"], rows[product]["verdict"]) == ("nack", "silent"), product


@pytest.mark.parametrize(
    ("frame", "forward", "backward", "log"),
    [
        ("*16*5001*101##", 1, None, "Audio Source 1 increase frequency by 1 step(s)."),
        ("*16*5015*101##", 15, None, "Audio Source 1 increase frequency by 15 step(s)."),
        ("*16*5101*101##", None, 1, "Audio Source 1 decrease frequency by 1 step(s)."),
        ("*16*5115*101##", None, 15, "Audio Source 1 decrease frequency by 15 step(s)."),
        ("*16*5003*21##", 3, None, "Audio Zone 21 increase frequency by 3 step(s)."),
    ],
)
def test_who16_frequency_step_events(frame: str, forward: int | None, backward: int | None, log: str) -> None:
    event = OWNMessage.parse(frame)
    assert isinstance(event, OWNSoundEvent)
    assert type(OWNEvent.parse(frame)) is OWNSoundEvent
    assert event.frequency_step_forward == forward
    assert event.frequency_step_backward == backward
    assert event.track_step_forward is None
    assert event.track_step_backward is None
    assert event.is_seek_up is False
    assert event.is_seek_down is False
    assert event.volume_step_delta is None
    assert event.human_readable_log == log


def test_who16_seek_events_are_not_frequency_steps() -> None:
    up = OWNMessage.parse("*16*5000*101##")
    assert isinstance(up, OWNSoundEvent)
    assert up.is_seek_up is True
    assert up.frequency_step_forward is None
    down = OWNMessage.parse("*16*5100*101##")
    assert isinstance(down, OWNSoundEvent)
    assert down.is_seek_down is True
    assert down.frequency_step_backward is None


@pytest.mark.parametrize(
    "frame",
    ["*16*5016*101##", "*16*5116*101##", "*16*4001*101##", "*16*4101*101##", "*16*4015*101##", "*16*4115*101##"],
)
def test_who16_values_outside_the_frequency_step_ranges_are_not_steps(frame: str) -> None:
    event = OWNMessage.parse(frame)
    assert isinstance(event, OWNSoundEvent)
    assert event.frequency_step_forward is None
    assert event.frequency_step_backward is None
    assert event.is_seek_up is False
    assert event.is_seek_down is False
    assert "received command" in event.human_readable_log


def test_who16_dimension_10_is_write_only() -> None:
    """bt_difson never formats DIMENSION 10 (``ownkb:claim:c002135``): only DIMENSION 7 reads into ``track``."""
    # Physical H/L4684 F500 DIMENSION 7 report (105.30 MHz, station 5).
    physical = OWNMessage.parse("*#16*101*7*0*5##")
    assert isinstance(physical, OWNSoundEvent)
    assert physical.track == 5
    assert physical.human_readable_log == "Audio Source 1 station/track is 5."
    frequency = OWNMessage.parse("*#16*101*6*0*105300##")
    assert isinstance(frequency, OWNSoundEvent)
    assert frequency.frequency_khz == 105300
    # A DIMENSION 10 value frame still parses as a WHO 16 event, with nothing decoded.
    stored = OWNMessage.parse("*#16*101*10*0*5##")
    assert isinstance(stored, OWNSoundEvent)
    assert stored.track is None
    assert stored.frequency_khz is None
    assert stored.human_readable_log == "*#16*101*10*0*5##"
