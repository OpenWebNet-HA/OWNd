"""Tests for WHO 14 Special Commands (Actuator Lock / Unlock).

Evidence sources:
- ``OPEN.db`` (``EN_SYSTEM.id_system = 35``): ``WHO = 14`` ``"Special commands"``.
- ``ScenarioDevices`` (``miniScenarioSuite.specialCommands.actionLockUnlockActuator``):
  ``WHAT = 0`` (``*14*0*WHERE##``, lock) and ``WHAT = 1`` (``*14*1*WHERE##``, unlock).
- ``tests/golden/firmware_oracle.json`` (suites ``trace-corpus`` and ``interface-routing``):
  11 emulated gateways with ``bt_luci`` or ``coso`` forward all 4 WHO 14 frames
  onto the SCS bus (``verdict == "out"``), while F450 (BACnet gateway without
  ``bt_luci`` or ``coso``) refuses all 4 (``reply == "nack"``, ``verdict == "silent"``).
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest

from OWNd.message import (
    ACTUATOR_LOCK_STATE_NAMES,
    ACTUATOR_STATE_LOCKED,
    ACTUATOR_STATE_UNLOCKED,
    OWNActuatorLockCommand,
    OWNActuatorLockEvent,
    OWNCommand,
    OWNEvent,
    OWNMessage,
    OWNSpecialCommand,
    OWNSpecialEvent,
)

ORACLE = json.loads(
    (Path(__file__).parent / "golden" / "firmware_oracle.json").read_text(
        encoding="utf-8"
    )
)["verdicts"]

FORWARDING_GATEWAYS = (
    "F453",
    "F453AV",
    "F454",
    "F459",
    "F460",
    "F461",
    "H4684",
    "MH200",
    "MH200N",
    "MH202",
    "MyHomeServer1",
)
REFUSING_GATEWAYS = ("F450",)
WHO14_INPUTS = sorted(f for f in ORACLE if f.startswith(("*14*", "*#14*")))


def _bus_text(row: dict[str, Any]) -> list[str]:
    return [
        bytes.fromhex(b.replace(" ", "")).decode("ascii").strip()
        for b in row["bus_frames"]
    ]


def test_who14_oracle_inputs_inventory() -> None:
    assert WHO14_INPUTS == [
        "*14*0*31#4#01##",
        "*14*0*31#4#02##",
        "*14*0*32##",
        "*14*1*32##",
    ]


@pytest.mark.parametrize("frame", WHO14_INPUTS)
def test_every_oracle_input_dispatches_to_actuator_lock_classes(frame: str) -> None:
    cmd = OWNCommand.parse(frame)
    assert isinstance(cmd, OWNActuatorLockCommand)
    assert cmd.is_valid
    assert cmd.who == 14
    assert str(cmd) == frame

    evt = OWNMessage.parse(frame)
    assert isinstance(evt, OWNActuatorLockEvent)
    assert isinstance(OWNEvent.parse(frame), OWNActuatorLockEvent)
    assert evt.is_valid
    assert evt.who == 14
    assert evt.effective_what == cmd.effective_what
    assert str(evt) == frame


def test_f450_refuses_all_who14_frames_while_11_gateways_forward() -> None:
    for frame in WHO14_INPUTS:
        rows = {r["product"]: r for r in ORACLE[frame]}
        assert set(rows) == set(FORWARDING_GATEWAYS) | set(REFUSING_GATEWAYS)
        for gw in REFUSING_GATEWAYS:
            assert rows[gw]["reply"] == "nack"
            assert rows[gw]["verdict"] == "silent"
            assert rows[gw]["bus_frames"] == []
        for gw in FORWARDING_GATEWAYS:
            assert rows[gw]["verdict"] == "out"
            assert bool(rows[gw]["bus_frames"])


@pytest.mark.parametrize(
    ("builder_fn", "expected_frame", "expected_opcode", "expected_locked"),
    [
        (
            lambda: OWNActuatorLockCommand.lock(32),
            "*14*0*32##",
            "1100",
            True,
        ),
        (
            lambda: OWNActuatorLockCommand.unlock(32),
            "*14*1*32##",
            "1000",
            False,
        ),
    ],
)
def test_lock_and_unlock_oracle_bus_telegrams_and_mh202_echo(
    builder_fn: Any,
    expected_frame: str,
    expected_opcode: str,
    expected_locked: bool,
) -> None:
    cmd = builder_fn()
    assert str(cmd) == expected_frame
    assert cmd.is_locked is expected_locked
    assert cmd.is_unlocked is (not expected_locked)

    rows = {r["product"]: r for r in ORACLE[expected_frame]}
    for gw in (
        "F453",
        "F453AV",
        "F454",
        "F459",
        "H4684",
        "MH200",
        "MH200N",
        "MyHomeServer1",
    ):
        assert _bus_text(rows[gw]) == [f"$033200{expected_opcode}"]
    for gw in ("F460", "F461"):
        assert _bus_text(rows[gw]) == [f"$0033200{expected_opcode}"]
    assert _bus_text(rows["MH202"]) == [f"$043200{expected_opcode}"]

    # MH202 echoes the WHO 14 frame on the event session.
    echoed = rows["MH202"]["emitted_own"]
    assert echoed == [expected_frame]
    evt = OWNEvent.parse(echoed[0])
    assert isinstance(evt, OWNActuatorLockEvent)
    assert evt.is_locked is expected_locked
    assert evt.is_unlocked is (not expected_locked)

    # Command-session ACK vs NACK-while-forwarding split in the oracle fixture:
    ack_gateways = {p for p in FORWARDING_GATEWAYS if rows[p]["reply"] == "ack"}
    nack_out_gateways = {p for p in FORWARDING_GATEWAYS if rows[p]["reply"] == "nack"}
    assert ack_gateways == {
        "F453",
        "F453AV",
        "F454",
        "F459",
        "H4684",
        "MH200",
        "MH200N",
        "MH202",
    }
    assert nack_out_gateways == {"F460", "F461", "MyHomeServer1"}


@pytest.mark.parametrize("iface", ["01", "02"])
def test_interface_routing_oracle_bus_telegrams(iface: str) -> None:
    cmd = OWNActuatorLockCommand.lock(31, interface=iface)
    frame = str(cmd)
    assert frame == f"*14*0*31#4#{iface}##"
    assert cmd.where == "31"
    assert cmd.interface == iface
    assert cmd.unique_id == f"14-31#4#{iface}"
    assert (
        cmd.human_readable_log
        == f"Locking actuator 31 on interface {iface}."
    )

    rows = {r["product"]: r for r in ORACLE[frame]}
    for gw in (
        "F453",
        "F453AV",
        "F454",
        "F459",
        "MH200",
        "MH200N",
        "MH202",
        "MyHomeServer1",
    ):
        assert _bus_text(rows[gw]) == [f"$06EC{iface}000031001100"]
    for gw in ("F460", "F461"):
        assert _bus_text(rows[gw]) == [f"$006EC{iface}000031001100"]
    assert _bus_text(rows["H4684"]) == [f"$06E4{iface}000031001100"]


def test_command_builders_and_aliases() -> None:
    assert OWNSpecialCommand is OWNActuatorLockCommand
    assert OWNSpecialEvent is OWNActuatorLockEvent
    assert ACTUATOR_STATE_LOCKED == 0
    assert ACTUATOR_STATE_UNLOCKED == 1
    assert ACTUATOR_LOCK_STATE_NAMES == {0: "locked", 1: "unlocked"}

    # Exact 2-digit Area 0 and 4-digit APL preservation (02 != 2, 0015 != 15)
    lock_02 = OWNActuatorLockCommand.lock("02")
    assert str(lock_02) == "*14*0*02##"
    assert lock_02.where == "02"
    assert lock_02.state == ACTUATOR_STATE_LOCKED
    assert lock_02.state_name == "locked"

    lock_0015 = OWNActuatorLockCommand.lock("0015")
    assert str(lock_0015) == "*14*0*0015##"
    assert lock_0015.where == "0015"
    assert lock_0015.interface is None
    assert lock_0015.is_locked is True
    assert lock_0015.is_unlocked is False
    assert lock_0015.human_readable_log == "Locking actuator 0015."

    unlock_0015 = OWNActuatorLockCommand.unlock("0015")
    assert str(unlock_0015) == "*14*1*0015##"
    assert unlock_0015.where == "0015"
    assert unlock_0015.state == ACTUATOR_STATE_UNLOCKED
    assert unlock_0015.state_name == "unlocked"
    assert unlock_0015.is_locked is False
    assert unlock_0015.is_unlocked is True
    assert unlock_0015.human_readable_log == "Unlocking actuator 0015."

    # set_locked helper
    assert str(OWNActuatorLockCommand.set_locked(32, True)) == "*14*0*32##"
    assert str(OWNActuatorLockCommand.set_locked(32, False)) == "*14*1*32##"
    assert (
        str(OWNActuatorLockCommand.set_locked("0115", True, interface=1))
        == "*14*0*0115#4#01##"
    )
    for bad_locked in (0, 1, "true", None):
        with pytest.raises(ValueError, match="boolean"):
            OWNActuatorLockCommand.set_locked(32, bad_locked)  # type: ignore[arg-type]

    # disable / enable aliases normalize #4#I to 2-digit #4#01..09 per bt_luci flex DFA
    dis = OWNActuatorLockCommand.disable("13", interface=2)
    assert str(dis) == "*14*0*13#4#02##"
    assert dis.where == "13"
    assert dis.interface == "02"
    assert dis.human_readable_log == "Locking actuator 13 on interface 02."

    en = OWNActuatorLockCommand.enable("13#4#2")
    assert str(en) == "*14*1*13#4#02##"
    assert en.where == "13"
    assert en.interface == "02"
    assert en.human_readable_log == "Unlocking actuator 13 on interface 02."

    # Command translation (*14*1000#0*32## and *14*1000#1*32##)
    tr_lock = OWNCommand.parse("*14*1000#0*32##")
    assert isinstance(tr_lock, OWNActuatorLockCommand)
    assert tr_lock.is_translation is True
    assert tr_lock.effective_what == 0
    assert tr_lock.state == 0
    assert tr_lock.state_name == "locked"
    assert tr_lock.is_locked is True
    assert tr_lock.is_unlocked is False
    assert tr_lock.human_readable_log == "Locking actuator 32."

    tr_unlock = OWNCommand.parse("*14*1000#1*32##")
    assert isinstance(tr_unlock, OWNActuatorLockCommand)
    assert tr_unlock.is_locked is False
    assert tr_unlock.is_unlocked is True
    assert tr_unlock.human_readable_log == "Unlocking actuator 32."

    # Status request and unknown command WHAT parsing
    req = OWNCommand.parse("*#14*32##")
    assert isinstance(req, OWNActuatorLockCommand)
    assert req.is_status_request is True
    assert req.state is None
    assert req.state_name is None
    assert req.is_locked is False
    assert req.is_unlocked is False
    assert req.human_readable_log == "Requesting lock status for actuator 32."

    req_iface = OWNCommand.parse("*#14*31#4#01##")
    assert isinstance(req_iface, OWNActuatorLockCommand)
    assert (
        req_iface.human_readable_log
        == "Requesting lock status for actuator 31 on interface 01."
    )

    unknown_cmd = OWNCommand.parse("*14*9*32##")
    assert isinstance(unknown_cmd, OWNActuatorLockCommand)
    assert unknown_cmd.state is None
    assert unknown_cmd.state_name is None
    assert unknown_cmd.is_locked is False
    assert unknown_cmd.is_unlocked is False
    assert unknown_cmd.human_readable_log == "*14*9*32##"


@pytest.mark.parametrize(
    ("where", "interface"),
    [
        ("", None),
        ("   ", None),
        ("*", None),
        (True, None),
        (False, None),
        ("0", None),
        (0, None),
        ("00", None),
        ("2", None),
        (2, None),
        ("100", None),
        (100, None),
        ("10", None),
        (10, None),
        ("20", None),
        ("111", None),
        ("115", None),
        (115, None),
        ("210", None),
        ("0000", None),
        ("0100", None),
        ("1000", None),
        ("0105", None),
        ("0016", None),
        ("0116", None),
        ("1016", None),
        ("0021", None),
        ("1101", None),
        ("99999", None),
        ("32*1", None),
        ("#1", None),
        ("abc", None),
        ("-1", None),
        ("31#5#01", None),
        ("31#4#01#2", None),
        ("31#4#0", None),
        ("31#4#00", None),
        ("31#4#10", None),
        ("31#4#99", None),
        ("31#4#001", None),
        ("31", ""),
        ("31", "*"),
        ("31", "abc"),
        ("31", True),
        ("31", False),
        ("31", 0),
        ("31", "0"),
        ("31", "00"),
        ("31", 10),
        ("31", "10"),
        ("31", "99"),
        ("31", "001"),
        ("31#4#01", "02"),
        ("١٢", None),
        ("31", "١"),
    ],
)
def test_command_builders_reject_invalid_where_and_interface(
    where: Any, interface: Any
) -> None:
    with pytest.raises(ValueError):
        OWNActuatorLockCommand.lock(where, interface=interface)
    with pytest.raises(ValueError):
        OWNActuatorLockCommand.unlock(where, interface=interface)


def test_event_states_and_logs() -> None:
    locked = OWNActuatorLockEvent("*14*0*11##")
    assert locked.who == 14
    assert locked.what == 0
    assert locked.where == "11"
    assert locked.interface is None
    assert locked.state == ACTUATOR_STATE_LOCKED
    assert locked.state_name == "locked"
    assert locked.is_locked is True
    assert locked.is_unlocked is False
    assert locked.human_readable_log == "Actuator 11 is locked."

    unlocked = OWNActuatorLockEvent("*14*1*11#4#02##")
    assert unlocked.who == 14
    assert unlocked.what == 1
    assert unlocked.where == "11"
    assert unlocked.interface == "02"
    assert unlocked.unique_id == "14-11#4#02"
    assert unlocked.state == ACTUATOR_STATE_UNLOCKED
    assert unlocked.state_name == "unlocked"
    assert unlocked.is_locked is False
    assert unlocked.is_unlocked is True
    assert (
        unlocked.human_readable_log
        == "Actuator 11 on interface 02 is unlocked."
    )

    unknown = OWNActuatorLockEvent("*14*9*11#4#02##")
    assert unknown.state is None
    assert unknown.state_name is None
    assert unknown.is_locked is False
    assert unknown.is_unlocked is False
    assert (
        unknown.human_readable_log
        == "Actuator 11 on interface 02 received unknown lock state: 9."
    )

    translation_evt = OWNActuatorLockEvent("*14*1000#0*11##")
    assert translation_evt.is_translation is True
    assert translation_evt.effective_what == 0
    assert translation_evt.state is None
    assert translation_evt.state_name is None
    assert translation_evt.is_locked is False
    assert translation_evt.is_unlocked is False
    assert translation_evt.human_readable_log == "*14*1000#0*11##"

    dim_reply = OWNActuatorLockEvent("*#14*11*1*0##")
    assert dim_reply.what is None
    assert dim_reply.state is None
    assert dim_reply.state_name is None
    assert dim_reply.is_locked is False
    assert dim_reply.is_unlocked is False
    assert dim_reply.human_readable_log == "*#14*11*1*0##"


