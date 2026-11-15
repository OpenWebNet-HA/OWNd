"""WHO 4 DIMENSION 19 / 20 codes 14, 15, 16 and 100 are not a running fan.

The published table for DIMENSION 19 / 20 stops at ``8`` (``9`` on DIMENSION
20). Two more groups are known (MyHOME#908):

* ``100``: proportional 0-10 V output at 0 %, stopped. A MyHomeServer1
  2.87.13 with 0-10 V Sabiana fan coils on actuator 3 sends
  ``*#4*1#3*20*100##`` and ``*#4*2#3*20*100##`` (live capture, MyHOME
  ``tests/fixtures/traces/issue_908/myhome_trace_MyHomeServer1_fancoil_dim20_100_2026-11-14.json``;
  golden records ``thermo.capture.dim20.status.fancoil_0pct.z1.act3`` and
  ``...z2.act3``).
* ``14`` / ``15`` / ``16``: fan coil OFF at speed 1 / 2 / 3 (MyHOME#908
  reads them from the MyHomeServer1 firmware table). Encyclopedia ``who-4-temperature-control/dimensions.md``:
  "additional fan-coil OFF-speed states `14`, `15`, and `16`". Golden records
  ``thermo.resp.valves.extended_fancoil_off_speed1.zone1``,
  ``thermo.resp.dim20.extended_fancoil_off_speed2.zone1.act2`` and
  ``thermo.resp.dim20.extended_fancoil_off_speed3.zone1.act2`` (source
  ``encyclopedia``). The frames used here are stored only in a synthetic
  MyHOME trace built from the firmware table, not in a plant capture.

``OWNHeatingEvent`` read every value above 5 as "value - 5 = fan speed":
``*#4*1#2*20*15##`` and ``*#4*1#3*20*100##`` came out as ``fan_on = True``
("fan is on at 'Auto' speed", ``is_active() = True``) and
``*#4*1*19*0*14##`` as a heating fan running at speed 9. MyHOME decodes the
value itself (``where_grammar.py``); a plain consumer of this library got a
running fan for a stopped one.

DIMENSION 19 with ``100`` and the cooling side with ``14..16`` have no stored
frame: they follow the same table.
"""

from __future__ import annotations

import pytest

from OWNd.message import OWNEvent, OWNHeatingEvent


def _parse(frame: str) -> OWNHeatingEvent:
    event = OWNEvent.parse(frame)
    assert isinstance(event, OWNHeatingEvent)
    assert event.is_valid
    assert str(event) == frame
    return event


@pytest.mark.parametrize(
    ("frame", "off_speed"),
    [
        ("*#4*1#2*20*14##", 1),
        ("*#4*1#2*20*15##", 2),
        ("*#4*1#2*20*16##", 3),
    ],
)
def test_dimension_20_fancoil_off_speed_is_a_stopped_fan(
    frame: str, off_speed: int
) -> None:
    event = _parse(frame)
    assert event.fan_on is False
    assert event.fan_speed is None
    assert event.is_active() is False
    assert event.actuator == "2"
    assert event.human_readable_log == f"Zone 1's fan is off (OFF speed {off_speed})."


@pytest.mark.parametrize(
    ("frame", "zone", "actuator"),
    [
        ("*#4*1#3*20*100##", 1, "3"),
        ("*#4*2#3*20*100##", 2, "3"),
    ],
)
def test_dimension_20_proportional_zero_is_inactive_and_claims_no_fan(
    frame: str, zone: int, actuator: str
) -> None:
    event = _parse(frame)
    assert event.is_active() is False
    assert event.fan_on is None
    assert event.fan_speed is None
    assert event.actuator == actuator
    assert (
        event.human_readable_log
        == f"Zone {zone}'s actuator {actuator} output is at 0%."
    )


def test_dimension_19_heating_fancoil_off_speed() -> None:
    """``*#4*1*19*0*14##`` is the frame of the synthetic MyHOME#908 trace."""
    event = _parse("*#4*1*19*0*14##")
    assert event.fan_on is False
    assert event.fan_speed is None
    assert event.cooling_fan_on is None
    assert event.is_heating() is False
    assert event.is_cooling() is False
    assert event.is_active() is False
    assert (
        event.human_readable_log
        == "Zone 1's cooling valve is off; heating fan is off (OFF speed 1)."
    )


@pytest.mark.parametrize(
    ("frame", "off_speed"),
    [
        ("*#4*1*19*14*0##", 1),
        ("*#4*1*19*15*0##", 2),
        ("*#4*1*19*16*0##", 3),
    ],
)
def test_dimension_19_cooling_fancoil_off_speed(frame: str, off_speed: int) -> None:
    event = _parse(frame)
    assert event.cooling_fan_on is False
    assert event.cooling_fan_speed is None
    assert event.fan_on is None
    assert event.is_cooling() is False
    assert event.is_active() is False
    assert (
        event.human_readable_log
        == f"Zone 1's cooling fan is off (OFF speed {off_speed}); heating valve is off."
    )


def test_dimension_19_proportional_zero_on_both_sides() -> None:
    event = _parse("*#4*1*19*100*100##")
    assert event.fan_on is None
    assert event.fan_speed is None
    assert event.cooling_fan_on is None
    assert event.cooling_fan_speed is None
    assert event.is_cooling() is False
    assert event.is_heating() is False
    assert event.is_active() is False
    assert (
        event.human_readable_log
        == "Zone 1's cooling output is at 0%; heating output is at 0%."
    )


def test_dimension_19_stopped_side_does_not_hide_the_running_side() -> None:
    """A stopped fan coil on one side leaves the other side as it was."""
    event = _parse("*#4*1*19*14*7##")
    assert event.cooling_fan_on is False
    assert event.fan_on is True
    assert event.fan_speed == 2
    assert event.is_active() is True

    event = _parse("*#4*1*19*100*1##")
    assert event.cooling_fan_on is None
    assert event.is_heating() is True
    assert event.is_active() is True


@pytest.mark.parametrize(
    ("frame", "fan_on", "fan_speed", "active"),
    [
        ("*#4*1#2*20*5##", False, None, False),
        ("*#4*1#2*20*6##", True, 1, True),
        ("*#4*1#2*20*8##", True, 3, True),
        ("*#4*1#2*20*9##", True, None, True),
    ],
)
def test_dimension_20_published_fan_values_are_unchanged(
    frame: str, fan_on: bool, fan_speed: int | None, active: bool
) -> None:
    event = _parse(frame)
    assert event.fan_on is fan_on
    assert event.fan_speed == fan_speed
    assert event.is_active() is active
