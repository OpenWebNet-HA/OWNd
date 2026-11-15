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

Review of the fix (OWNd#174) added the rest of that table:

* ``101..200``: the same proportional output at 1 %..100 %, running, with no
  fan claim (a 0-10 V output can be a plain valve). ``*#4*1#3*20*155##`` is
  golden record ``thermo.resp.dim20.proportional_55pct.zone1.act3`` (source
  ``encyclopedia``); no plant capture carries a value above ``100``. Read
  as "value - 5" it was a fan at 'Auto' speed on DIMENSION 20 and a fan at
  speed 150 with ``is_heating() = False`` on DIMENSION 19.
* ``9`` on DIMENSION 19: the PDF table of DIMENSION 19 ends at ``8`` and ``9``
  ("ON Fan Coil") is in the DIMENSION 20 table; it is read the same way on
  both (fan on, no speed), where DIMENSION 19 gave "speed 4" and an inactive
  side.
* every other value (``10..13``, ``17..99``, ``201`` and above) is in no
  source: the event keeps its type and its actuator, the state accessors stay
  ``None`` and the log names the value. MyHOME reads such a frame the same
  way (``where_grammar._decode_thermo_output_code`` returns ``None``) and its
  tests send ``*#4*1#3*20*999##``, ``*#4*7#1*20*250##`` and
  ``*#4*1*19*0*999##`` as typed events.
"""

from __future__ import annotations

import pytest

from OWNd.message import MESSAGE_TYPE_ACTION, OWNEvent, OWNHeatingEvent


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

    assert event.is_heating() is True
    assert event.is_cooling() is False

    event = _parse("*#4*1*19*100*1##")
    assert event.cooling_fan_on is None
    assert event.is_heating() is True
    assert event.is_cooling() is False
    assert event.is_active() is True


def test_dimension_19_stopped_heating_side_does_not_hide_the_running_cooling_side() -> None:
    """The mirror of the test above: cooling runs, heating is stopped."""
    event = _parse("*#4*1*19*7*14##")
    assert event.cooling_fan_on is True
    assert event.cooling_fan_speed == 2
    assert event.fan_on is False
    assert event.fan_speed is None
    assert event.is_cooling() is True
    assert event.is_heating() is False
    assert event.is_active() is True

    event = _parse("*#4*1*19*1*100##")
    assert event.fan_on is None
    assert event.cooling_fan_on is None
    assert event.is_cooling() is True
    assert event.is_heating() is False
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


# (is_active, fan_on, fan_speed) for every code a source defines, written out
# here by hand so the test does not read the library's own table.
_KNOWN_CODES: dict[int, tuple[bool, bool | None, int | None]] = {
    0: (False, None, None),
    1: (True, None, None),
    2: (True, None, None),
    3: (False, None, None),
    4: (False, None, None),
    5: (False, False, None),
    6: (True, True, 1),
    7: (True, True, 2),
    8: (True, True, 3),
    9: (True, True, None),
    14: (False, False, None),
    15: (False, False, None),
    16: (False, False, None),
    100: (False, None, None),
    **{code: (True, None, None) for code in range(101, 201)},
}
_ALL_CODES = [*range(0, 260), 994, 999]


@pytest.mark.parametrize("code", _ALL_CODES)
def test_dimension_20_every_code(code: int) -> None:
    event = _parse(f"*#4*1#3*20*{code}##")
    assert event.message_type == MESSAGE_TYPE_ACTION
    assert event.actuator == "3"
    expected = _KNOWN_CODES.get(code, (None, None, None))
    assert (event.is_active(), event.fan_on, event.fan_speed) == expected
    assert event.is_heating() is None
    assert event.is_cooling() is None
    assert event.cooling_fan_on is None
    assert event.cooling_fan_speed is None
    if code not in _KNOWN_CODES:
        assert (
            event.human_readable_log
            == f"Zone 1's actuator 3 reports an unknown status {code}."
        )


@pytest.mark.parametrize("code", _ALL_CODES)
def test_dimension_19_every_code_on_either_side(code: int) -> None:
    """The other side is ``0`` (valve off), so the frame is as active as the tested side."""
    heating = _parse(f"*#4*1*19*0*{code}##")
    cooling = _parse(f"*#4*1*19*{code}*0##")
    assert heating.message_type == MESSAGE_TYPE_ACTION
    assert cooling.message_type == MESSAGE_TYPE_ACTION
    assert heating.actuator is None
    if code in _KNOWN_CODES:
        active, fan_on, fan_speed = _KNOWN_CODES[code]
        assert (heating.is_heating(), heating.fan_on, heating.fan_speed) == (
            active,
            fan_on,
            fan_speed,
        )
        assert (heating.is_cooling(), heating.cooling_fan_on) == (False, None)
        assert heating.cooling_fan_speed is None
        assert heating.is_active() is active
        assert (
            cooling.is_cooling(),
            cooling.cooling_fan_on,
            cooling.cooling_fan_speed,
        ) == (active, fan_on, fan_speed)
        assert (cooling.is_heating(), cooling.fan_on, cooling.fan_speed) == (
            False,
            None,
            None,
        )
        assert cooling.is_active() is active
    else:
        for event in (heating, cooling):
            assert event.is_active() is None
            assert event.is_heating() is None
            assert event.is_cooling() is None
            assert event.fan_on is None
            assert event.fan_speed is None
            assert event.cooling_fan_on is None
            assert event.cooling_fan_speed is None
        assert (
            heating.human_readable_log
            == f"Zone 1's cooling valve is off; heating valve reports an unknown status {code}."
        )
        assert (
            cooling.human_readable_log
            == f"Zone 1's cooling valve reports an unknown status {code}; heating valve is off."
        )


@pytest.mark.parametrize(
    ("frame", "zone", "actuator", "percent"),
    [
        ("*#4*1#3*20*101##", 1, "3", 1),
        ("*#4*1#3*20*155##", 1, "3", 55),
        ("*#4*7#1*20*200##", 7, "1", 100),
    ],
)
def test_dimension_20_proportional_output_is_active_and_claims_no_fan(
    frame: str, zone: int, actuator: str, percent: int
) -> None:
    """``*#4*1#3*20*155##`` is golden record ``thermo.resp.dim20.proportional_55pct.zone1.act3``."""
    event = _parse(frame)
    assert event.is_active() is True
    assert event.fan_on is None
    assert event.fan_speed is None
    assert event.actuator == actuator
    assert (
        event.human_readable_log
        == f"Zone {zone}'s actuator {actuator} output is at {percent}%."
    )


def test_dimension_19_proportional_output_runs_its_own_side() -> None:
    event = _parse("*#4*1*19*0*155##")
    assert event.is_heating() is True
    assert event.is_cooling() is False
    assert event.is_active() is True
    assert event.fan_on is None
    assert event.fan_speed is None
    assert (
        event.human_readable_log
        == "Zone 1's cooling valve is off; heating output is at 55%."
    )

    event = _parse("*#4*1*19*200*100##")
    assert event.is_cooling() is True
    assert event.is_heating() is False
    assert event.is_active() is True
    assert event.cooling_fan_on is None
    assert event.cooling_fan_speed is None
    assert (
        event.human_readable_log
        == "Zone 1's cooling output is at 100%; heating output is at 0%."
    )


def test_dimension_19_fan_coil_on_without_a_speed() -> None:
    """``9`` is "ON Fan Coil" in the DIMENSION 20 table; DIMENSION 19 gave "speed 4"."""
    event = _parse("*#4*1*19*0*9##")
    assert event.is_heating() is True
    assert event.fan_on is True
    assert event.fan_speed is None
    assert event.is_active() is True
    assert (
        event.human_readable_log
        == "Zone 1's cooling valve is off; heating fan is on at 'Auto' speed."
    )

    event = _parse("*#4*1*19*9*0##")
    assert event.is_cooling() is True
    assert event.cooling_fan_on is True
    assert event.cooling_fan_speed is None
    assert event.is_active() is True
    assert (
        event.human_readable_log
        == "Zone 1's cooling fan is on at 'Auto' speed; heating valve is off."
    )


@pytest.mark.parametrize(
    ("frame", "actuator", "log"),
    [
        ("*#4*1#3*20*999##", "3", "Zone 1's actuator 3 reports an unknown status 999."),
        ("*#4*7#1*20*250##", "1", "Zone 7's actuator 1 reports an unknown status 250."),
        (
            "*#4*1*19*0*999##",
            None,
            "Zone 1's cooling valve is off; heating valve reports an unknown status 999.",
        ),
        (
            "*#4*8*19*0*999##",
            None,
            "Zone 8's cooling valve is off; heating valve reports an unknown status 999.",
        ),
    ],
)
def test_unknown_code_keeps_the_event_typed_and_claims_nothing(
    frame: str, actuator: str | None, log: str
) -> None:
    """The four frames MyHOME ``tests/test_issue_908_fancoil_dim20_100.py`` sends as typed events."""
    event = _parse(frame)
    assert event.message_type == MESSAGE_TYPE_ACTION
    assert event.actuator == actuator
    assert event.is_active() is None
    assert event.is_heating() is None
    assert event.is_cooling() is None
    assert event.fan_on is None
    assert event.fan_speed is None
    assert event.cooling_fan_on is None
    assert event.cooling_fan_speed is None
    assert event.human_readable_log == log


def test_dimension_19_unknown_code_on_one_side_leaves_the_running_side_unclaimed() -> None:
    """One unknown side makes the whole status unknown, as MyHOME reads it."""
    event = _parse("*#4*1*19*7*999##")
    assert event.is_active() is None
    assert event.is_cooling() is None
    assert event.cooling_fan_on is None
    assert event.cooling_fan_speed is None
    assert (
        event.human_readable_log
        == "Zone 1's cooling fan is on at speed 2; heating valve reports an unknown status 999."
    )


@pytest.mark.parametrize(
    ("frame", "active"),
    [
        ("*#4*1*20*01##", True),
        ("*#4*1*20*00##", False),
        ("*#4*1*20*06##", True),
    ],
)
def test_dimension_20_zero_padded_value_is_read_as_its_number(
    frame: str, active: bool
) -> None:
    """The state was a string comparison (``"01"`` inactive) next to an ``int`` log ("is on")."""
    event = _parse(frame)
    assert event.is_active() is active


def test_dimension_19_zero_padded_value_is_read_as_its_number() -> None:
    event = _parse("*#4*1*19*01*0##")
    assert event.is_cooling() is True
    assert event.is_active() is True
    assert event.human_readable_log == "Zone 1's cooling valve is on; heating valve is off."

    event = _parse("*#4*1*19*0*01##")
    assert event.is_heating() is True
    assert event.is_active() is True
