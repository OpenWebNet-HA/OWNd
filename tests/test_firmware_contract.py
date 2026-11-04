"""OWNd's WHO 4 decoding checked against what gateway firmware puts on the bus.

tests/oracle/who4_facts.json holds, per WHO 4 frame, the serial telegram that
at least two emulated BTicino/Legrand gateways sent to their SCS bus interface
after ACKing the frame (OpenWebNet-HA/own-firmware-oracle, extracted by
scripts/oracle_who4_facts.py; the commit is in the file). The telegram bytes
are the firmware's own reading of the frame, so OWNd must read it the same way.

Telegram grammar (consistent across MH200N, MyHomeServer1, F453AV, F454, F459,
F460, F461, MH202, H4684):

  $06 D1 <addr> 03 02 C1 <op> <a1> <a2>   central-unit command, addr = zone
  $06 D1 <addr> 03 02 C2 <zone> <op> <a1> zone (#Z) command
  $06 D1 <addr> 03 02 0B <speed> 00 00     fan-coil speed, addr = zone (00 and
                                           no zone when written via the central)
  $04 93 <zone> 30 <00|01|0F>             plain zone: heating / cooling / off

  op high nibble: 0 generic, 1 heating, 2 conditioning (F: season frame)
  op low nibble:  0 automatic   1 weekly program (a1 = P-1)
                  2 setpoint (a1 = T*2)   3 scenario (a1 = S-1)
                  4 holiday plan (a1 = return program - 1)
                  5 vacation (a1 = days, a2 = return program - 1)
                  6 off   7 protection   9 timed manual (a1 = T*2)

Every telegram class in the fixture is either checked below or listed in
NOT_DECODED with the reason, and every difference OWNd keeps on purpose is in
KNOWN_DIFFERENCES: a new firmware fact therefore fails this test until someone
decides what OWNd does with it.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest

from OWNd.message import (
    CLIMATE_MODE_OFF,
    MESSAGE_TYPE_SEASON,
    SEASON_CONDITIONING,
    SEASON_HEATING,
    OWNEvent,
    OWNHeatingEvent,
)

FACTS = Path(__file__).resolve().parent / "oracle" / "who4_facts.json"
DOC = json.loads(FACTS.read_text(encoding="utf-8"))

SEASON_NIBBLE = {0x0: None, 0x1: SEASON_HEATING, 0x2: SEASON_CONDITIONING}

# Telegram classes OWNd does not decode, with the reason. Adding decoding for
# one of them means moving it from here into a rule below.
NOT_DECODED = {
    "C3": "central-unit date write (*#4*#0*#30*D*M*Y##): OWNd has no date decoding",
    "C4": "central-unit time write (*#4*#0*#31*H*M##): OWNd has no time decoding",
    "C5": "central-unit holiday end write (*#4*#0*#32*…##): not decoded by OWNd",
}

# Frames whose OWNd decoding differs from the bus on purpose: frame -> (the one
# aspect not compared, why). Everything else about the frame is still checked.
KNOWN_DIFFERENCES = {
    "*4*115*#0##": (
        "program",
        "the frame names no return program; gateways put program 1 (index 0) on "
        "the bus, OWNd reports program None because the frame does not state one",
    ),
    "*#4*1*#11*4##": (
        "fan_speed",
        "speed 4 is outside the specification (0 automatic, 1..3, 15 off); "
        "gateways pass the byte through, OWNd reports no speed",
    ),
    "*4*312#0210#5*#1##": (
        "zone",
        "timed manual is a central-unit operation: gateways address the central "
        "(addr 00) whatever zone the frame names; OWNd reports the zone written",
    ),
}


def _waived(frame: str, aspect: str) -> bool:
    return KNOWN_DIFFERENCES.get(frame, ("", ""))[0] == aspect


def _decode(frame: str) -> OWNHeatingEvent:
    event = OWNEvent.parse(frame)
    assert isinstance(event, OWNHeatingEvent), f"{frame} is not a heating event"
    return event


def _check_operation(frame: str, event: OWNHeatingEvent, op: int, a1: int, a2: int) -> None:
    """The parts of a central/zone command every class shares."""
    what_frame = frame.startswith("*4*")
    if op in (0xF0, 0xF1):
        assert event.message_type == MESSAGE_TYPE_SEASON
        assert event.mode is None
        assert event.season == (SEASON_HEATING if op == 0xF0 else SEASON_CONDITIONING)
        return
    if what_frame:
        # The setpoint write's season (*#4*…*#14*T*M##, M) is not reported by OWNd.
        assert event.season == SEASON_NIBBLE[op >> 4], "season"
    kind = op & 0x0F
    if kind == 0x0:
        assert event.mode not in (None, CLIMATE_MODE_OFF), "automatic"
    elif kind == 0x1:
        assert event.program == a1 + 1, "weekly program"
    elif kind == 0x2:
        assert event.set_temperature == a1 / 2, "setpoint"
    elif kind == 0x3:
        assert event.scenario == a1 + 1, "scenario"
    elif kind == 0x4:
        assert event.set_temperature is None, "holiday plan carries no temperature"
        if not _waived(frame, "program"):
            assert event.program == a1 + 1, "holiday return program"
    elif kind == 0x5:
        assert event.set_temperature is None, "vacation carries no temperature"
        assert event.holiday_days == a1, "vacation days"
        assert event.program == a2 + 1, "vacation return program"
    elif kind in (0x6, 0x7):
        assert event.mode == CLIMATE_MODE_OFF, "off / protection"
    elif kind == 0x9:
        assert event.set_temperature == a1 / 2, "timed manual setpoint"
    else:
        pytest.fail(f"{frame}: operation {op:02X} has no contract rule")


def check(fact: dict[str, Any]) -> None:
    frame, t = fact["frame"], fact["telegram"]
    event = _decode(frame)
    if t[0] == "04":
        _, cls, zone, value = t
        assert cls == "93", f"{frame}: short telegram class {cls} has no contract rule"
        assert event.zone == int(zone, 16), "zone"
        if value == "0F":
            assert event.mode == CLIMATE_MODE_OFF
        else:
            assert event.message_type == MESSAGE_TYPE_SEASON
            assert event.season == {"00": SEASON_HEATING, "01": SEASON_CONDITIONING}[value]
        return
    _, addr, cls, b1, b2, b3 = t
    if cls in NOT_DECODED:
        return
    if cls == "C1":
        if not _waived(frame, "zone"):
            assert event.zone == int(addr, 16), "zone"
        _check_operation(frame, event, int(b1, 16), int(b2, 16), int(b3, 16))
    elif cls == "C2":
        # Zone b1; zone N of a 4-zone central (#0#N) goes out as zone 0, addr N.
        zone = int(addr, 16) if b1 == "00" and "#0#" in frame else int(b1, 16)
        assert event.zone == zone, "zone"
        _check_operation(frame, event, int(b2, 16), int(b3, 16), 0)
    elif cls == "0B":
        # Written through the central (*#4*#Z*#11*S##) the telegram goes to the
        # central (addr 00) and carries no zone: #1 and #99 give the same bytes.
        if not frame.startswith("*#4*#"):
            assert event.zone == int(addr, 16), "zone"
        if not _waived(frame, "fan_speed"):
            assert event.fan_speed == int(b1, 16), "fan speed"
    else:
        pytest.fail(f"{frame}: telegram class {cls} has no contract rule")


@pytest.mark.parametrize(
    "fact", DOC["facts"], ids=[f"{f['frame']} {' '.join(f['telegram'])}" for f in DOC["facts"]]
)
def test_ownd_reads_the_frame_as_the_firmware_does(fact: dict[str, Any]) -> None:
    check(fact)


def test_the_facts_are_pinned_to_an_oracle_commit() -> None:
    source = DOC["source"]
    assert source["repo"] == "OpenWebNet-HA/own-firmware-oracle"
    assert len(source["ref"]) == 40
    assert DOC["facts"], "no WHO 4 facts extracted"


def test_every_exception_is_still_needed() -> None:
    """A stale entry in NOT_DECODED or KNOWN_DIFFERENCES is a silent gap."""
    classes = {f["telegram"][2] for f in DOC["facts"] if f["telegram"][0] == "06"}
    frames = {f["frame"] for f in DOC["facts"]}
    assert set(NOT_DECODED) <= classes
    assert set(KNOWN_DIFFERENCES) <= frames
