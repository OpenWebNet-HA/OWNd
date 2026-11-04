"""Tests for WHO 18 Stop&Go automatic reset breakers (F16EB).

Firmware provenance: findings/MyHomeServer1/energy-ts10.md
Empirical verification across MyHomeServer1 (028206), MH202 (010024), and F454 (020051).
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from OWNd.message import (
    MESSAGE_TYPE_STOP_AND_GO,
    STOP_AND_GO_AUTORESET_DISABLE,
    STOP_AND_GO_AUTORESET_ENABLE,
    STOP_AND_GO_CLOSE,
    STOP_AND_GO_DIM_AUTORESET_OFF,
    STOP_AND_GO_DIM_BLOCKED,
    STOP_AND_GO_DIM_CHECK_OFF,
    STOP_AND_GO_DIM_DOWNSTREAM_POWER_FAILURE,
    STOP_AND_GO_DIM_FAILURE,
    STOP_AND_GO_DIM_FIRST_24H_OPENING,
    STOP_AND_GO_DIM_GROUND_FAULT,
    STOP_AND_GO_DIM_MAX_VOLTAGE,
    STOP_AND_GO_DIM_NEUTRAL_SHORT_CIRCUIT,
    STOP_AND_GO_DIM_OPEN,
    STOP_AND_GO_DIM_SELF_TEST_DISABLED,
    STOP_AND_GO_DIM_STATUS_MASK,
    STOP_AND_GO_DIM_TEST_FREQUENCY,
    STOP_AND_GO_DIM_UPSTREAM_POWER_FAILURE,
    STOP_AND_GO_DIM_WAITING_CLOSING,
    STOP_AND_GO_FLAG_DIMENSIONS,
    STOP_AND_GO_OPEN,
    STOP_AND_GO_TEST_NEGATIVE,
    STOP_AND_GO_TEST_POSITIVE,
    STOP_AND_GO_TRACKING_DISABLE,
    STOP_AND_GO_TRACKING_ENABLE,
    OWNCommand,
    OWNEnergyCommand,
    OWNEnergyEvent,
    OWNEvent,
    OWNMessage,
    OWNStopAndGoCommand,
    OWNStopAndGoEvent,
)

GOLDEN_PATH = Path(__file__).parent / "golden" / "firmware_oracle.json"
ORACLE = json.loads(GOLDEN_PATH.read_text(encoding="utf-8"))["verdicts"]


@pytest.mark.parametrize(
    ("frame", "what", "is_open", "is_closed", "log_phrase"),
    [
        ("*18*21*11##", STOP_AND_GO_OPEN, True, False, "is open"),
        ("*18*22*11##", STOP_AND_GO_CLOSE, False, True, "is closed"),
    ],
)
def test_stop_and_go_breaker_open_close_status(
    frame: str, what: int, is_open: bool, is_closed: bool, log_phrase: str
) -> None:
    event = OWNEvent.parse(frame)
    assert isinstance(event, OWNStopAndGoEvent)
    assert event.who == 18
    assert event.where == "11"
    assert event.line == 1
    assert event.state == what
    assert event.is_open is is_open
    assert event.is_closed is is_closed
    assert event.message_type == MESSAGE_TYPE_STOP_AND_GO
    assert log_phrase in event.human_readable_log


@pytest.mark.parametrize(
    ("frame", "passed", "result"),
    [
        ("*18*23*11##", True, "positive"),
        ("*18*24*11##", False, "negative"),
    ],
)
def test_stop_and_go_differential_test_events(
    frame: str, passed: bool, result: str
) -> None:
    event = OWNEvent.parse(frame)
    assert isinstance(event, OWNStopAndGoEvent)
    assert event.differential_test_passed is passed
    assert event.differential_test_result == result
    assert "differential test" in event.human_readable_log


@pytest.mark.parametrize(
    ("frame", "active"),
    [
        ("*18*26*12##", True),
        ("*18*27*12##", False),
    ],
)
def test_stop_and_go_autoreset_events(frame: str, active: bool) -> None:
    event = OWNEvent.parse(frame)
    assert isinstance(event, OWNStopAndGoEvent)
    assert event.line == 2
    assert event.is_auto_reset_active is active
    assert "auto-reset" in event.human_readable_log


@pytest.mark.parametrize(
    ("frame", "active"),
    [
        ("*18*28*19##", True),
        ("*18*29*19##", False),
    ],
)
def test_stop_and_go_tracking_events(frame: str, active: bool) -> None:
    event = OWNEvent.parse(frame)
    assert isinstance(event, OWNStopAndGoEvent)
    assert event.line == 9
    assert event.is_tracking_active is active
    assert "tracking" in event.human_readable_log


def test_stop_and_go_dimension_test_frequency_event() -> None:
    event = OWNEvent.parse("*#18*11*212*10##")
    assert isinstance(event, OWNStopAndGoEvent)
    assert event.line == 1
    assert event.test_frequency_days == 10
    assert "test frequency is 10 days" in event.human_readable_log


def test_stop_and_go_dimension_status_mask_event() -> None:
    event = OWNEvent.parse("*#18*11*250*1##")
    assert isinstance(event, OWNStopAndGoEvent)
    assert event.line == 1
    assert event.status_mask == "1"
    assert event.flag_dimension is None
    assert event.flag_active is None
    assert "status mask is 1" in event.human_readable_log


@pytest.mark.parametrize(
    (
        "dimension",
        "bit",
        "expected_active",
        "expected_open",
        "expected_closed",
        "expected_autoreset",
        "expected_tracking",
    ),
    [
        (STOP_AND_GO_DIM_OPEN, 1, True, True, False, None, None),
        (STOP_AND_GO_DIM_OPEN, 0, False, False, True, None, None),
        (STOP_AND_GO_DIM_FAILURE, 1, True, None, None, None, None),
        (STOP_AND_GO_DIM_BLOCKED, 0, False, None, None, None, None),
        (STOP_AND_GO_DIM_NEUTRAL_SHORT_CIRCUIT, 1, True, None, None, None, None),
        (STOP_AND_GO_DIM_GROUND_FAULT, 1, True, None, None, None, None),
        (STOP_AND_GO_DIM_MAX_VOLTAGE, 1, True, None, None, None, None),
        (STOP_AND_GO_DIM_SELF_TEST_DISABLED, 1, True, None, None, None, None),
        (STOP_AND_GO_DIM_AUTORESET_OFF, 1, True, None, None, False, None),
        (STOP_AND_GO_DIM_AUTORESET_OFF, 0, False, None, None, True, None),
        (STOP_AND_GO_DIM_CHECK_OFF, 1, True, None, None, None, False),
        (STOP_AND_GO_DIM_CHECK_OFF, 0, False, None, None, None, True),
        (STOP_AND_GO_DIM_WAITING_CLOSING, 1, True, None, None, None, None),
        (STOP_AND_GO_DIM_FIRST_24H_OPENING, 1, True, None, None, None, None),
        (STOP_AND_GO_DIM_DOWNSTREAM_POWER_FAILURE, 1, True, None, None, None, None),
        (STOP_AND_GO_DIM_UPSTREAM_POWER_FAILURE, 0, False, None, None, None, None),
    ],
)
def test_stop_and_go_individual_flag_dimension_events(
    dimension: int,
    bit: int,
    expected_active: bool,
    expected_open: bool | None,
    expected_closed: bool | None,
    expected_autoreset: bool | None,
    expected_tracking: bool | None,
) -> None:
    event = OWNEvent.parse(f"*#18*11*{dimension}*{bit}##")
    assert isinstance(event, OWNStopAndGoEvent)
    assert event.line == 1
    assert event.flag_dimension == dimension
    assert event.flag_active is expected_active
    assert event.is_open is expected_open
    assert event.is_closed is expected_closed
    assert event.is_auto_reset_active is expected_autoreset
    assert event.is_tracking_active is expected_tracking
    assert f"status flag {dimension} is {bit}" in event.human_readable_log


@pytest.mark.parametrize(
    ("builder", "expected_frame"),
    [
        (OWNStopAndGoCommand.open_breaker(11), "*18*21*11##"),
        (OWNStopAndGoCommand.open_breaker(1), "*18*21*11##"),
        (OWNStopAndGoCommand.close_breaker("12"), "*18*22*12##"),
        (OWNStopAndGoCommand.close_breaker(2), "*18*22*12##"),
        (OWNStopAndGoCommand.test_differential_positive(11), "*18*23*11##"),
        (OWNStopAndGoCommand.test_differential_negative(11), "*18*24*11##"),
        (OWNStopAndGoCommand.enable_auto_reset(11), "*18*26*11##"),
        (OWNStopAndGoCommand.disable_auto_reset(11), "*18*27*11##"),
        (OWNStopAndGoCommand.set_auto_reset(11, True), "*18*26*11##"),
        (OWNStopAndGoCommand.set_auto_reset(11, False), "*18*27*11##"),
        (OWNStopAndGoCommand.enable_tracking(11), "*18*28*11##"),
        (OWNStopAndGoCommand.disable_tracking(11), "*18*29*11##"),
        (OWNStopAndGoCommand.set_tracking(11, True), "*18*28*11##"),
        (OWNStopAndGoCommand.set_tracking(11, False), "*18*29*11##"),
        (OWNStopAndGoCommand.set_test_frequency(11, 10), "*#18*11*#212*10##"),
        (OWNStopAndGoCommand.request_test_frequency(11), "*#18*11*212##"),
        (OWNStopAndGoCommand.request_status_mask(11), "*#18*11*250##"),
        (
            OWNStopAndGoCommand.request_status_flag(11, STOP_AND_GO_DIM_OPEN),
            "*#18*11*251##",
        ),
        (
            OWNStopAndGoCommand.request_status_flag(11, STOP_AND_GO_DIM_AUTORESET_OFF),
            "*#18*11*258##",
        ),
    ],
)
def test_stop_and_go_command_builders(
    builder: OWNStopAndGoCommand, expected_frame: str
) -> None:
    assert str(builder) == expected_frame
    parsed = OWNCommand.parse(expected_frame)
    assert isinstance(parsed, OWNStopAndGoCommand)
    assert parsed.human_readable_log


def test_stop_and_go_address_validation() -> None:
    with pytest.raises(ValueError, match="Stop&Go line address"):
        OWNStopAndGoCommand.open_breaker(0)
    with pytest.raises(ValueError, match="Stop&Go line address"):
        OWNStopAndGoCommand.open_breaker(10)
    with pytest.raises(ValueError, match="Stop&Go line address"):
        OWNStopAndGoCommand.open_breaker(20)
    with pytest.raises(ValueError, match="Stop&Go line address"):
        OWNStopAndGoCommand.open_breaker("invalid")


def test_stop_and_go_test_frequency_validation() -> None:
    with pytest.raises(ValueError, match="between 1 and 255"):
        OWNStopAndGoCommand.set_test_frequency(11, 0)
    with pytest.raises(ValueError, match="between 1 and 255"):
        OWNStopAndGoCommand.set_test_frequency(11, 256)


def test_stop_and_go_status_flag_validation() -> None:
    assert len(STOP_AND_GO_FLAG_DIMENSIONS) == 13
    with pytest.raises(ValueError, match="between 251 and 263"):
        OWNStopAndGoCommand.request_status_flag(11, 250)
    with pytest.raises(ValueError, match="between 251 and 263"):
        OWNStopAndGoCommand.request_status_flag(11, 264)


def test_energy_meter_events_not_diverted() -> None:
    """Ensure standard WHO 18 power and totalizer frames still parse as OWNEnergyEvent."""
    power_event = OWNEvent.parse("*#18*51*113*1500##")
    assert isinstance(power_event, OWNEnergyEvent)
    assert not isinstance(power_event, OWNStopAndGoEvent)
    assert power_event.active_power == 1500

    total_event = OWNEvent.parse("*#18*11*51*2500##")
    assert isinstance(total_event, OWNEnergyEvent)
    assert not isinstance(total_event, OWNStopAndGoEvent)
    assert total_event.total_consumption == 2500

    auto_event = OWNEvent.parse("*#18*51*1200#1*60##")
    assert isinstance(auto_event, OWNEnergyEvent)
    assert not isinstance(auto_event, OWNStopAndGoEvent)
    assert auto_event.stream_duration == 60


def test_energy_commands_not_diverted() -> None:
    """Ensure standard WHO 18 power commands still parse as OWNEnergyCommand."""
    cmd = OWNCommand.parse("*#18*51*113##")
    assert isinstance(cmd, OWNEnergyCommand)
    assert not isinstance(cmd, OWNStopAndGoCommand)


def _decoded_bus_frames(row: dict[str, object]) -> list[str]:
    bus_frames = row.get("bus_frames", [])
    assert isinstance(bus_frames, list)
    decoded: list[str] = []
    for bf in bus_frames:
        assert isinstance(bf, str)
        text = bytes.fromhex(bf.replace(" ", "")).decode("ascii").strip()
        if text.startswith("$006"):
            text = "$" + text[2:]
        decoded.append(text)
    return decoded


@pytest.mark.parametrize(
    ("builder", "expected_frame", "expected_bus"),
    [
        (OWNStopAndGoCommand.open_breaker(11), "*18*21*11##", "$06D101023210010200"),
        (OWNStopAndGoCommand.close_breaker(11), "*18*22*11##", "$06D101023210010100"),
        (
            OWNStopAndGoCommand.test_differential_positive(11),
            "*18*23*11##",
            "$06D101023210010601",
        ),
        (
            OWNStopAndGoCommand.test_differential_negative(11),
            "*18*24*11##",
            "$06D101023210010600",
        ),
        (
            OWNStopAndGoCommand.enable_auto_reset(11),
            "*18*26*11##",
            "$06D101023210010401",
        ),
        (
            OWNStopAndGoCommand.disable_auto_reset(11),
            "*18*27*11##",
            "$06D101023210010400",
        ),
        (
            OWNStopAndGoCommand.enable_tracking(11),
            "*18*28*11##",
            "$06D101023210010501",
        ),
        (
            OWNStopAndGoCommand.disable_tracking(11),
            "*18*29*11##",
            "$06D101023210010500",
        ),
        (
            OWNStopAndGoCommand.set_test_frequency(11, 10),
            "*#18*11*#212*10##",
            "$06D1010232101C000A",
        ),
        (
            OWNStopAndGoCommand.request_test_frequency(11),
            "*#18*11*212##",
            "$06D1010233101C0000",
        ),
        (
            OWNStopAndGoCommand.request_status_mask(11),
            "*#18*11*250##",
            "$06D101023310100000",
        ),
        (
            OWNStopAndGoCommand.request_status_flag(11, STOP_AND_GO_DIM_OPEN),
            "*#18*11*251##",
            "$06D101023310100000",
        ),
        (
            OWNStopAndGoCommand.request_status_flag(11, STOP_AND_GO_DIM_AUTORESET_OFF),
            "*#18*11*258##",
            "$06D101023310100000",
        ),
    ],
)
def test_stop_and_go_firmware_oracle_conformance(
    builder: OWNStopAndGoCommand, expected_frame: str, expected_bus: str
) -> None:
    """Verify all 13 Stop&Go oracle frames match bt_supervisione firmware behavior."""
    assert str(builder) == expected_frame
    parsed = OWNCommand.parse(expected_frame)
    assert isinstance(parsed, OWNStopAndGoCommand)

    assert expected_frame in ORACLE
    rows = ORACLE[expected_frame]
    supervisione_rows = [
        r
        for r in rows
        if r["verdict"] == "out" and _decoded_bus_frames(r) == [expected_bus]
    ]
    supervisione_products = {r["product"] for r in supervisione_rows}
    expected_products = {
        "F453AV",
        "F454",
        "F459",
        "F460",
        "F461",
        "MH200N",
        "MH202",
        "MyHomeServer1",
    }
    if expected_frame not in {"*#18*11*251##", "*#18*11*258##"}:
        expected_products.add("F453")
    assert supervisione_products == expected_products
    is_status_request = (
        expected_frame.startswith("*#18*11*") and "*#212*" not in expected_frame
    )
    for r in supervisione_rows:
        if is_status_request or r["product"] not in {
            "F460",
            "F461",
            "MyHomeServer1",
        }:
            assert r["reply"] == "ack"
        else:
            assert r["reply"] == "nack"


def test_stop_and_go_unrecognized_and_nonstandard_address_branches() -> None:
    """Cover non-1N line addresses and unrecognized WHAT/dimension fallbacks."""
    non_standard_where = OWNEvent.parse("*18*21*51##")
    assert isinstance(non_standard_where, OWNStopAndGoEvent)
    assert non_standard_where.line is None
    assert non_standard_where.is_open is True

    unknown_event_what = OWNStopAndGoEvent("*18*99*11##")
    assert unknown_event_what.line == 1
    assert unknown_event_what.state == 99
    assert unknown_event_what.is_open is None

    empty_dim_event = OWNStopAndGoEvent("*#18*11*250##")
    assert empty_dim_event.status_mask is None

    unknown_cmd_what = OWNStopAndGoCommand("*18*99*11##")
    assert unknown_cmd_what.who == 18
    assert str(unknown_cmd_what) == "*18*99*11##"

    unknown_cmd_dim = OWNStopAndGoCommand("*#18*11*999##")
    assert unknown_cmd_dim.who == 18
    assert str(unknown_cmd_dim) == "*#18*11*999##"

    status_req_cmd = OWNStopAndGoCommand("*#18*11##")
    assert status_req_cmd.who == 18
    assert str(status_req_cmd) == "*#18*11##"

