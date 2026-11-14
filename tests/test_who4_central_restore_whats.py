"""WHO 4 WHAT 3100 / 3200 / 3000 decode as automatic, like the frames around them.

``OWNHeatingCommand.set_central_mode("#0", "auto")`` builds ``*4*3100*#0##``
(OWNd#169), and ``OWNHeatingEvent`` has to read back what the builder sends:
3100 fell between 311 and 3101..3116 and came out as "Zone 0's mode is
unknown." with no message type (review of OWNd#169). Test plant, 2026-11-12
17:55:13.734 and 17:55:53.159 UTC: an F455 1.0.76 handed the command Home
Assistant had just sent through it back on its own event session, and the
monitor logged exactly that line. The F461 2.0.11 event session of the same
capture never showed the frame.

Sources, Legrand "Open Web Net Language, WHO = 4" (WHO_4 2.pdf):

* 1.6.8 p. 33 "Last set up weekly program activation command": ``*4*3100*#0##``.
* 1.6.12 p. 39 "Last set up scenario activation command": ``*4*3200*#0##``.
* 1.6.19 p. 51 "Holiday mode deactivation command with weekly "N" program
  return": ``*4*3000#what*#0##``, ``what = [3101 - 3103]``.
* 1.6.20 p. 52 "Holiday mode deactivation command with last weekly program
  return": ``*4*3000*#0##``.

Only 3100 has a plant capture (golden record
``thermo.capture.central.restore_last_program.cu99``); 3200 and 3000 are read
from the document alone.
"""

from __future__ import annotations

import pytest

from OWNd.message import (
    CLIMATE_MODE_AUTO,
    MESSAGE_TYPE_MODE,
    MESSAGE_TYPE_SEASON,
    OWNEvent,
    OWNHeatingCommand,
    OWNHeatingEvent,
)


@pytest.mark.parametrize("where", ["#0", "#0#2"])
@pytest.mark.parametrize("what", [3100, 3200, 3000])
def test_restore_whats_decode_as_auto_without_a_number(where: str, what: int) -> None:
    """The frame names no program and no scenario: both stay ``None``."""
    frame = f"*4*{what}*{where}##"

    for event in (OWNEvent.parse(frame), OWNHeatingEvent(frame)):
        assert isinstance(event, OWNHeatingEvent)
        assert event.message_type == MESSAGE_TYPE_MODE
        assert event.mode == CLIMATE_MODE_AUTO
        assert event.program is None
        assert event.scenario is None
        assert event.season is None
        assert event.holiday_days is None
        assert event.set_temperature is None
        assert "unknown" not in event.human_readable_log


def test_the_frame_built_for_auto_on_the_99_zone_unit_reads_back_as_auto() -> None:
    command = OWNHeatingCommand.set_central_mode("#0", CLIMATE_MODE_AUTO)
    assert str(command) == "*4*3100*#0##"

    event = OWNEvent.parse(str(command))

    assert isinstance(event, OWNHeatingEvent)
    assert event.message_type == MESSAGE_TYPE_MODE
    assert event.mode == CLIMATE_MODE_AUTO
    assert event.program is None
    assert event.human_readable_log == "Zone 0's mode is set to 'auto'."


@pytest.mark.parametrize("program", [1, 2, 3])
def test_holiday_deactivation_names_the_program_in_its_parameter(program: int) -> None:
    """1.6.19: the parameter is the weekly program 31PP, not a temperature."""
    event = OWNEvent.parse(f"*4*3000#{3100 + program}*#0##")

    assert isinstance(event, OWNHeatingEvent)
    assert event.message_type == MESSAGE_TYPE_MODE
    assert event.mode == CLIMATE_MODE_AUTO
    assert event.program == program
    assert event.scenario is None
    assert event.set_temperature is None
    assert event.human_readable_log == (
        f"Zone 0's mode is set to 'auto' (program {program})."
    )


def test_numbered_programs_and_scenarios_are_unchanged() -> None:
    program = OWNEvent.parse("*4*3101*#0##")
    assert (program.mode, program.program, program.scenario) == (CLIMATE_MODE_AUTO, 1, None)
    last_program = OWNEvent.parse("*4*3116*#0##")
    assert (last_program.program, last_program.scenario) == (16, None)
    scenario = OWNEvent.parse("*4*3201*#0##")
    assert (scenario.mode, scenario.program, scenario.scenario) == (CLIMATE_MODE_AUTO, None, 1)
    last_scenario = OWNEvent.parse("*4*3216*#0##")
    assert (last_scenario.program, last_scenario.scenario) == (None, 16)


@pytest.mark.parametrize("what", [3001, 3099, 3117, 3199, 3217])
def test_neighbouring_whats_stay_unknown(what: int) -> None:
    """Only the three published codes were added, not the ranges between them."""
    event = OWNEvent.parse(f"*4*{what}*#0##")

    assert isinstance(event, OWNHeatingEvent)
    assert event.message_type is None
    assert event.mode is None
    assert event.human_readable_log == "Zone 0's mode is unknown."


@pytest.mark.parametrize("where", ["#0", "#0#1", "#0#2", "#0#99"])
@pytest.mark.parametrize(
    "mode", ["off", "heat", "cool", "auto", "antifreeze", "protection"]
)
def test_every_frame_set_central_mode_builds_is_read_back_by_the_event_parser(
    where: str, mode: str
) -> None:
    """Guard for the gap closed here: a builder must not emit a frame the parser cannot type."""
    command = OWNHeatingCommand.set_central_mode(where, mode)

    event = OWNEvent.parse(str(command))

    assert isinstance(event, OWNHeatingEvent)
    assert event.message_type in (MESSAGE_TYPE_MODE, MESSAGE_TYPE_SEASON)
    assert "unknown" not in event.human_readable_log
