"""Tests for bt_termo P2 protocol refinements (own-firmware-oracle findings/bt-termo.md)."""

from __future__ import annotations

import pytest

from OWNd.message import (
    LOCAL_CONTROL_UNKNOWN,
    MESSAGE_TYPE_LOCAL_OFFSET,
    MESSAGE_TYPE_LOCAL_OFFSET_RELEASE,
    MESSAGE_TYPE_PUMP_CALL,
    MESSAGE_TYPE_SECONDARY_TEMPERATURE,
    OWNEvent,
    OWNHeatingCommand,
    OWNHeatingEvent,
)


# ── P2-13: Circulation-pump demand calls (4001 / 4002) ──


@pytest.mark.parametrize(
    ("frame", "active", "calling_zone", "pump", "zone", "unique_id", "log"),
    [
        (
            "*4*4001#1*0#3##",
            True,
            1,
            3,
            0,
            "4-#0",
            "Zone 1 calls pump 3 on.",
        ),
        (
            "*4*4001#55*0#3##",
            True,
            55,
            3,
            0,
            "4-#0",
            "Zone 55 calls pump 3 on.",
        ),
        (
            "*4*4002#64*0#2##",
            False,
            64,
            2,
            0,
            "4-#0",
            "Zone 64 releases pump 2.",
        ),
        (
            "*4*4002*2##",
            False,
            2,
            None,
            2,
            "4-2",
            "Zone 2 releases its pump call.",
        ),
        (
            "*4*4001*2##",
            True,
            2,
            None,
            2,
            "4-2",
            "Zone 2 calls pump on.",
        ),
        (
            "*4*4002*0#1##",
            False,
            None,
            1,
            0,
            "4-#0",
            "Pump 1 call is released.",
        ),
        (
            "*4*4001*0#1##",
            True,
            None,
            1,
            0,
            "4-#0",
            "Pump 1 call is on.",
        ),
        (
            "*4*4001#0*0#3##",
            True,
            None,
            3,
            0,
            "4-#0",
            "Pump 3 call is on.",
        ),
        (
            "*4*4001#1*0#0##",
            True,
            1,
            None,
            0,
            "4-#0",
            "Zone 1 calls pump on.",
        ),
        (
            "*4*4001*0##",
            True,
            None,
            None,
            0,
            "4-#0",
            "Pump call is on.",
        ),
        (
            "*4*4002*0##",
            False,
            None,
            None,
            0,
            "4-#0",
            "Pump call is released.",
        ),
        (
            "*4*4001#1*0#3#4#01##",
            True,
            1,
            3,
            0,
            "4-#0",
            "Zone 1 calls pump 3 on.",
        ),
        (
            "*4*4001#1*0#4#01##",
            True,
            1,
            None,
            0,
            "4-#0",
            "Zone 1 calls pump on.",
        ),
        (
            "*4*4002*0#4#01##",
            False,
            None,
            None,
            0,
            "4-#0",
            "Pump call is released.",
        ),
        (
            "*4*4002*105##",
            False,
            None,
            None,
            5,
            "4-105",
            "Pump call is released.",
        ),
        (
            "*4*4002*#0#3##",
            False,
            None,
            None,
            3,
            "4-3",
            "Pump call is released.",
        ),
    ],
)
def test_p2_13_pump_call_events(
    frame: str,
    active: bool,
    calling_zone: int | None,
    pump: int | None,
    zone: int,
    unique_id: str,
    log: str,
) -> None:
    event = OWNEvent.parse(frame)
    assert isinstance(event, OWNHeatingEvent)
    assert event.message_type == MESSAGE_TYPE_PUMP_CALL
    assert event.mode is None
    assert event.pump_call_active is active
    assert event.calling_zone == calling_zone
    assert event.pump == pump
    assert event.zone == zone
    assert event.unique_id == unique_id
    assert event.human_readable_log == log


def test_p2_13_non_pump_event_leaves_pump_properties_none() -> None:
    event = OWNEvent.parse("*4*1*2##")
    assert isinstance(event, OWNHeatingEvent)
    assert event.pump_call_active is None
    assert event.calling_zone is None
    assert event.pump is None


# ── P2-14: WHAT 40 release local offset, WHAT 39/41..45, DIM 13 codes 7/8 ──


def test_p2_14_what_40_release_local_offset_event() -> None:
    event = OWNEvent.parse("*4*40*2##")
    assert isinstance(event, OWNHeatingEvent)
    assert event.message_type == MESSAGE_TYPE_LOCAL_OFFSET_RELEASE
    assert event.mode is None
    assert event.zone == 2
    assert event.unique_id == "4-2"
    assert event.human_readable_log == "Zone 2's local offset is released."

    # Malformed parameterized WHAT 40#1 stays untyped
    malformed = OWNEvent.parse("*4*40#1*2##")
    assert isinstance(malformed, OWNHeatingEvent)
    assert malformed.message_type is None


@pytest.mark.parametrize("what", [39, 41, 42, 43, 44, 45])
def test_p2_14_undocumented_gen_d_whats_stay_untyped_with_clear_log(what: int) -> None:
    event = OWNEvent.parse(f"*4*{what}*2##")
    assert isinstance(event, OWNHeatingEvent)
    assert event.message_type is None
    assert event.mode is None
    assert event.zone == 2
    assert event.human_readable_log == f"Zone 2 reported undocumented WHO 4 event {what}."


@pytest.mark.parametrize(
    ("where", "expected_frame", "expected_zone"),
    [
        (1, "*4*40*1##", 1),
        (2, "*4*40*2##", 2),
        ("2", "*4*40*2##", 2),
        ("02", "*4*40*2##", 2),
        ("99", "*4*40*99##", 99),
        (99, "*4*40*99##", 99),
    ],
)
def test_p2_14_release_local_offset_builder_valid(
    where: str | int, expected_frame: str, expected_zone: int
) -> None:
    cmd = OWNHeatingCommand.release_local_offset(where)
    assert str(cmd) == expected_frame
    assert cmd.human_readable_log == f"Releasing local offset for zone {expected_zone}."


@pytest.mark.parametrize(
    "bad_where",
    [
        True,
        False,
        0,
        -1,
        100,
        "",
        "0",
        "00",
        "001",
        "100",
        "#0",
        "#0#1",
        "#2",
        "2#1",
        "2#4#01",
        " 2 ",
        "2\n",
        "abc",
        "\uff12",  # fullwidth digit 2
        None,
    ],
)
def test_p2_14_release_local_offset_builder_rejects_invalid(bad_where: object) -> None:
    with pytest.raises(ValueError):
        OWNHeatingCommand.release_local_offset(bad_where)  # type: ignore[arg-type]


@pytest.mark.parametrize("raw", ["7", "8"])
def test_p2_14_dim13_undocumented_codes_preserve_raw(raw: str) -> None:
    event = OWNEvent.parse(f"*#4*2*13*{raw}##")
    assert isinstance(event, OWNHeatingEvent)
    assert event.message_type == MESSAGE_TYPE_LOCAL_OFFSET
    assert event.local_offset is None
    assert event.local_control_state == LOCAL_CONTROL_UNKNOWN
    assert event.local_offset_raw == raw
    assert f"raw value {raw}" in event.human_readable_log


# ── P2-15: DIM 15 4-bit status mask & DIM 0 leading-zero guard (QUIRK-05) ──


@pytest.mark.parametrize(
    ("frame", "expected_sec", "expected_raw", "expected_mask"),
    [
        ("*#4*105*15*0*0000*0000##", [0, 0.0], "0000", 0),
        ("*#4*100*15*1*0200*0001##", [1, 20.0], "0001", 1),
        ("*#4*100*15*1*0253*1010##", [1, 25.3], "1010", 10),
        ("*#4*11*15*1*0123*1111##", [1, 12.3], "1111", 15),
        ("*#4*2*15*1*0215##", [1, 21.5], None, None),
        ("*#4*2*15*0215##", [None, 21.5], None, None),
        ("*#4*2*15*1*0215*##", [1, 21.5], None, None),
        ("*#4*2*15*1*0215*1234##", [1, 21.5], None, None),
        ("*#4*2*15*1*0215*001##", [1, 21.5], None, None),
        ("*#4*2*15*1*0215*00001##", [1, 21.5], None, None),
        ("*#4*1*15**0215*0001##", [None, None], None, None),
    ],
)
def test_p2_15_dim15_probe_status_mask(
    frame: str,
    expected_sec: list[int | float | None],
    expected_raw: str | None,
    expected_mask: int | None,
) -> None:
    event = OWNEvent.parse(frame)
    assert isinstance(event, OWNHeatingEvent)
    assert event.message_type == MESSAGE_TYPE_SECONDARY_TEMPERATURE
    assert event.secondary_temperature == expected_sec
    assert event.probe_status_raw == expected_raw
    assert event.probe_status_mask == expected_mask


@pytest.mark.parametrize(
    ("where", "expected_frame"),
    [
        # Accidental 2-digit leading-zero plain zones normalized to avoid QUIRK-05
        ("01", "*#4*1*0##"),
        ("02", "*#4*2*0##"),
        ("09", "*#4*9*0##"),
        ("01#4#01", "*#4*1#4#01*0##"),
        ("01#4#1", "*#4*1#4#1*0##"),
        ("09#4#12", "*#4*9#4#12*0##"),
        # Normal plain zones, ints, general, and intentional 3-digit 0ZZ all-probes preserved
        (1, "*#4*1*0##"),
        ("1", "*#4*1*0##"),
        ("10", "*#4*10*0##"),
        ("99", "*#4*99*0##"),
        ("0", "*#4*0*0##"),
        ("001", "*#4*001*0##"),
        ("099", "*#4*099*0##"),
        ("100", "*#4*100*0##"),
        ("105", "*#4*105*0##"),
        ("#0", "*#4*#0*0##"),
    ],
)
def test_p2_15_get_temperature_leading_zero_guard(
    where: str | int, expected_frame: str
) -> None:
    cmd = OWNHeatingCommand.get_temperature(where)
    assert str(cmd) == expected_frame
