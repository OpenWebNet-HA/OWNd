"""WHO 3 load control, pinned to the firmware oracle first and the specification second.

Firmware: tests/golden/firmware_oracle.json, suite energy-ts10. F459 020105 and
MH202 010024 have aligned rows and are the reference; F453AV, F454, H4684 and
MH200N lag by one row in that suite, so their per-row replies are not used.

Specification: WHO 3 Load Control v1.0.0 (2006) via the OpenWebNet Encyclopedia
(functional/who-3-load-management). No real-plant capture exists yet, so the
state and measurement replies below come from the specification.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest

from OWNd.message import (
    LOAD_STATE_DISABLED,
    LOAD_STATE_ENABLED,
    LOAD_STATE_FORCED,
    LOAD_STATE_FORCING_REMOVED,
    OWNCommand,
    OWNEvent,
    OWNLoadCommand,
    OWNLoadEvent,
    OWNMessage,
)

ORACLE = json.loads(
    (Path(__file__).parent / "golden" / "firmware_oracle.json").read_text(encoding="utf-8")
)["verdicts"]
ALIGNED_GATEWAYS = ("F459", "MH202")
WHO3_INPUTS = sorted(f for f in ORACLE if f.startswith(("*3*", "*#3*")))


def _aligned(frame: str) -> list[dict[str, Any]]:
    rows = [r for r in ORACLE[frame] if r["product"] in ALIGNED_GATEWAYS]
    assert {r["product"] for r in rows} == set(ALIGNED_GATEWAYS)
    return rows


def _forwarded(frame: str) -> bool:
    """Not NACKed and put on the bus by every aligned gateway."""
    return all(r["reply"] != "nack" and r["verdict"] == "out" for r in _aligned(frame))


def _refused(frame: str) -> bool:
    return all(r["reply"] == "nack" and r["verdict"] == "silent" for r in _aligned(frame))


def _bus_text(row: dict[str, Any]) -> list[str]:
    return [bytes.fromhex(b.replace(" ", "")).decode().strip() for b in row["bus_frames"]]


def _all_builder_frames() -> set[str]:
    frames = {str(OWNLoadCommand.force(p)) for p in range(1, 9)}
    frames |= {str(OWNLoadCommand.status(p)) for p in range(1, 9)}
    frames |= {str(OWNLoadCommand.request_measurement(d)) for d in range(5)}
    return frames


def test_oracle_covers_who3():
    assert len(WHO3_INPUTS) == 15


@pytest.mark.parametrize("frame", WHO3_INPUTS)
def test_every_oracle_input_dispatches_to_load_classes(frame: str):
    parsed = OWNMessage.parse(frame)
    expected = OWNLoadEvent if frame.startswith("*3*") else OWNLoadCommand
    assert isinstance(parsed, expected)
    assert parsed.is_valid
    assert isinstance(OWNCommand.parse(frame), OWNLoadCommand)


@pytest.mark.parametrize("priority", [1, 2])
def test_force_is_forwarded_with_priority_in_the_telegram(priority: int):
    frame = str(OWNLoadCommand.force(priority))
    assert frame == f"*3*2*#{priority}##"
    for row in _aligned(frame):
        assert row["reply"] == "ack"
        assert _bus_text(row) == [f"$04B70{priority}1300"]


def test_force_echo_on_event_session_parses_as_forced():
    echoed = {own for rows in ORACLE.values() for r in rows for own in r["emitted_own"]}
    load_echoes = sorted(e for e in echoed if e.startswith("*3*"))
    assert load_echoes == ["*3*2*#1##", "*3*2*#2##"]
    for frame in load_echoes:
        event = OWNEvent.parse(frame)
        assert isinstance(event, OWNLoadEvent)
        assert event.is_forced is True
        assert event.priority == int(frame[-3])


def test_every_oracle_backed_builder_frame_reaches_the_bus():
    in_oracle = _all_builder_frames() & set(ORACLE)
    assert in_oracle == {
        "*3*2*#1##",
        "*3*2*#2##",
        "*#3*#1##",
        "*#3*#2##",
        "*#3*10*0##",
        "*#3*10*1##",
        "*#3*10*2##",
        "*#3*10*3##",
        "*#3*10*4##",
    }
    assert all(_forwarded(f) for f in in_oracle)


def test_no_builder_emits_a_frame_the_gateways_refuse():
    refused = {f for f in WHO3_INPUTS if _refused(f)}
    assert refused == {
        "*#3*0##",
        "*3*0*#1##",
        "*3*0*0##",
        "*3*1*#1##",
        "*3*1*0##",
        "*3*3*#1##",
    }
    assert not refused & _all_builder_frames()


def test_measurement_requests_read_distinct_registers():
    """Each dimension maps to its own register run; dimension 0 reads the others.

    Run widths 1/1/2/4 fit the specification's voltage/current/power/energy
    order, but the bus telegrams name no quantity, so values stay raw.
    """
    for gateway in ALIGNED_GATEWAYS:
        registers = {
            d: next(
                _bus_text(r) for r in _aligned(f"*#3*10*{d}##") if r["product"] == gateway
            )
            for d in range(5)
        }
        assert registers[1] == ["$03AA001613"]
        assert registers[2] == ["$03AA001612"]
        assert registers[3] == ["$03AA001610", "$03AA001611"]
        assert registers[4] == ["$03AA001606", "$03AA001607", "$03AA001608", "$03AA001609"]
        others = registers[1] + registers[2] + registers[3] + registers[4]
        assert registers[0][:4] == others[:4]
        assert set(registers[0]) <= set(others)


@pytest.mark.parametrize(
    ("frame", "state", "text"),
    [
        ("*3*0*#3##", LOAD_STATE_DISABLED, "Load priority 3 is disabled."),
        ("*3*1*#8##", LOAD_STATE_ENABLED, "Load priority 8 is enabled."),
        ("*3*2*#1##", LOAD_STATE_FORCED, "Load priority 1 is forced."),
        ("*3*3*#5##", LOAD_STATE_FORCING_REMOVED, "Load priority 5 is no longer forced."),
        ("*3*1*0##", LOAD_STATE_ENABLED, "All load priorities are enabled."),
    ],
)
def test_specified_state_frames(frame: str, state: int, text: str):
    event = OWNEvent.parse(frame)
    assert isinstance(event, OWNLoadEvent)
    assert event.state == state
    assert event.is_forced is (state == LOAD_STATE_FORCED)
    assert event.human_readable_log == text


def test_priority_keeps_its_hash_and_rejects_out_of_range():
    assert OWNLoadEvent("*3*2*#4##").where == "#4"
    assert OWNLoadEvent("*3*2*#4##").priority == 4
    assert OWNLoadEvent("*3*2*#9##").priority is None
    assert OWNLoadEvent("*3*2*4##").priority is None
    assert OWNLoadEvent("*3*2*4##").human_readable_log == "Load 4 is forced."


def test_unknown_what_keeps_the_raw_frame():
    event = OWNLoadEvent("*3*7*#1##")
    assert event.state is None
    assert event.is_forced is None
    assert event.priority == 1
    assert event.human_readable_log == "*3*7*#1##"


def test_measurement_reply_stays_raw():
    event = OWNEvent.parse("*#3*10*0*230*12*2760*1520##")
    assert isinstance(event, OWNLoadEvent)
    assert event.is_control_unit
    assert event.dimension == 0
    assert event.measurement_values == ["230", "12", "2760", "1520"]
    assert event.state is None
    assert event.human_readable_log == (
        "Load control unit dimension 0 (all measurements per specification): "
        "raw values ['230', '12', '2760', '1520']."
    )


def test_unnamed_dimension_and_other_where_are_not_measurements():
    assert OWNLoadEvent("*#3*10*9*1##").human_readable_log == (
        "Load control unit dimension 9: raw values ['1']."
    )
    other = OWNLoadEvent("*#3*#1*1*5##")
    assert other.measurement_values == []
    assert not other.is_control_unit


@pytest.mark.parametrize(
    ("command", "frame", "text"),
    [
        (OWNLoadCommand.force(3), "*3*2*#3##", "Forcing load priority 3."),
        (OWNLoadCommand.status(8), "*#3*#8##", "Requesting load priority 8 status."),
        (OWNLoadCommand.request_measurement(), "*#3*10*0##", "Requesting load control unit dimension 0."),
        (OWNLoadCommand.request_measurement(4), "*#3*10*4##", "Requesting load control unit dimension 4."),
    ],
)
def test_builders(command: OWNLoadCommand, frame: str, text: str):
    assert str(command) == frame
    assert command.is_valid
    assert command.human_readable_log == text


@pytest.mark.parametrize("frame", ["*3*2*0##", "*#3*0##", "*#3*#1*1##", "*3*1*#1##"])
def test_parsed_commands_without_a_specific_log_keep_the_raw_frame(frame: str):
    assert OWNLoadCommand(frame).human_readable_log == frame


@pytest.mark.parametrize("priority", [0, 9, -1])
def test_priority_validation(priority: int):
    with pytest.raises(ValueError, match="between 1 and 8"):
        OWNLoadCommand.force(priority)
    with pytest.raises(ValueError, match="between 1 and 8"):
        OWNLoadCommand.status(priority)


@pytest.mark.parametrize("dimension", [-1, 5])
def test_dimension_validation(dimension: int):
    with pytest.raises(ValueError, match="between 0 and 4"):
        OWNLoadCommand.request_measurement(dimension)
