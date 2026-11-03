"""WHO 2 / WHO 3 / WHO 9 audit fixes (review-session automation_load_aux.md rows A1..A9, L1, X1).

Evidence: OpenWebNet Encyclopedia ``who-2-automation/what.md`` (advanced
commands, parameter format, state values are not commands),
``who-2-automation/dimensions.md`` (Dimension 10 payload, Dimension 11 go to
level, resulting state traffic), ``who-2-automation/addressing.md`` (WHERE
forms), ``who-3-load-management/README.md#status-requests`` with the
review-session ``ORACLE_CONFIRM.md`` row L1 verdict, and
``who-9-auxiliaries/README.md#corpus-status``.
"""

from __future__ import annotations

import pytest

from OWNd.message import (
    OWNAutomationCommand,
    OWNAutomationEvent,
    OWNCommand,
    OWNEvent,
    OWNLoadCommand,
    OWNMessage,
)
from OWNd.message.automation import _int_or_none, _priority_bitfield

# ── A1: *2*10#PRIORITY[#SELECTOR]*WHERE## is Advanced Stop, not a state ──────


def test_a1_advanced_stop_ln4660m2_frame_claims_no_level() -> None:
    # what.md#observed-physical-transmitter-frames: *2*10#001#1*0## on the bus.
    event = OWNEvent.parse("*2*10#001#1*0##")
    assert isinstance(event, OWNAutomationEvent)
    assert event.is_advanced_stop is True
    assert event.is_advanced_up is False
    assert event.is_advanced_down is False
    assert event.state is None  # 10 is a DIMENSION 10 value, not a WHAT state
    assert event.current_position is None
    assert event.is_position_unknown is False
    assert event.is_closed is None
    assert event.is_opening is False
    assert event.is_closing is False
    assert event.priority == 1
    assert event.priority_bitfield == "001"
    assert (event.priority_safety, event.priority_high, event.priority_medium) == (False, False, True)
    assert event.selector == 1
    assert event.step is None
    assert event.moves_to_end_point is None
    assert event.is_general is True
    assert event.what == 10 and event.what_param == ["001", "1"]
    assert event.human_readable_log == "Cover 0 advanced stop (priority 001, set)."
    assert "None" not in event.human_readable_log


def test_a1_advanced_stop_command_session_form_and_clear_selector() -> None:
    # what.md#parameter-format: *2*10#PRIORITY*WHERE## (command session).
    cmd_form = OWNEvent.parse("*2*10#100*31##")
    assert isinstance(cmd_form, OWNAutomationEvent)
    assert cmd_form.is_advanced_stop is True
    assert cmd_form.priority_bitfield == "100"
    assert cmd_form.priority_safety is True
    assert cmd_form.selector is None
    assert cmd_form.human_readable_log == "Cover 31 advanced stop (priority 100)."

    clear = OWNEvent.parse("*2*10#010#0*31##")
    assert isinstance(clear, OWNAutomationEvent)
    assert clear.selector == 0
    assert clear.priority_high is True
    assert clear.human_readable_log == "Cover 31 advanced stop (priority 010, clear)."

    bare = OWNEvent.parse("*2*10*31##")
    assert isinstance(bare, OWNAutomationEvent)
    assert bare.is_advanced_stop is True
    assert bare.priority is None
    assert bare.priority_bitfield is None
    assert bare.priority_safety is None
    assert bare.human_readable_log == "Cover 31 advanced stop."


def test_a1_priority_that_is_not_a_bit_field_keeps_the_integer_only() -> None:
    event = OWNEvent.parse("*2*10#7#2*31##")
    assert isinstance(event, OWNAutomationEvent)
    assert event.priority == 7
    assert event.priority_bitfield is None
    assert event.selector is None  # only 0 / 1 are selectors
    assert event.human_readable_log == "Cover 31 advanced stop (priority 7)."


# ── A2: *2*11#STEP#PRIORITY[#SELECTOR]*WHERE## / *2*12#... keep step and priority ──


@pytest.mark.parametrize(
    ("frame", "up", "step", "end_point", "log"),
    [
        ("*2*11#100#001#1*0##", True, 100, True, "Cover 0 advanced up to the end point (priority 001, set)."),
        ("*2*12#100#001#1*0##", False, 100, True, "Cover 0 advanced down to the end point (priority 001, set)."),
        ("*2*11#50#001*31##", True, 50, False, "Cover 31 advanced up by 50% (priority 001)."),
        ("*2*12#1#001#0*31##", False, 1, False, "Cover 31 advanced down by 1% (priority 001, clear)."),
        ("*2*11#99#111*31##", True, 99, False, "Cover 31 advanced up by 99% (priority 111)."),
    ],
)
def test_a2_advanced_up_down_decode_step_priority_selector(
    frame: str, up: bool, step: int, end_point: bool, log: str
) -> None:
    event = OWNEvent.parse(frame)
    assert isinstance(event, OWNAutomationEvent)
    assert event.is_advanced_up is up
    assert event.is_advanced_down is not up
    assert event.is_advanced_stop is False
    assert event.state is None
    assert event.step == step
    assert event.moves_to_end_point is end_point
    assert event.priority_bitfield == frame.split("#")[2].split("*")[0]
    assert event.is_opening is up
    assert event.is_closing is not up
    assert event.is_closed is None  # a relative step claims nothing about closed
    assert event.current_position is None
    assert event.human_readable_log == log


def test_a2_omitted_step_means_end_point_and_single_parameter_is_not_decoded() -> None:
    # what.md#step: "An omitted/null value or 100 means movement to the endpoint".
    omitted = OWNEvent.parse("*2*11*31##")
    assert isinstance(omitted, OWNAutomationEvent)
    assert omitted.is_advanced_up is True
    assert omitted.step is None
    assert omitted.moves_to_end_point is True
    assert omitted.priority is None
    assert omitted.human_readable_log == "Cover 31 advanced up to the end point."

    # A single parameter does not match STEP#PRIORITY: fail closed, keep it raw.
    single = OWNEvent.parse("*2*12#001*31##")
    assert isinstance(single, OWNAutomationEvent)
    assert single.is_advanced_down is True
    assert single.step is None
    assert single.moves_to_end_point is None
    assert single.priority is None
    assert single.what_param == ["001"]
    assert single.human_readable_log == "Cover 31 advanced down (parameters not decoded)."


@pytest.mark.parametrize("frame", ["*2*11#0#001*31##", "*2*11#150#001*31##"])
def test_a2_step_outside_1_100_is_not_a_step(frame: str) -> None:
    event = OWNEvent.parse(frame)
    assert isinstance(event, OWNAutomationEvent)
    assert event.is_advanced_up is True
    assert event.step is None
    assert event.moves_to_end_point is None
    assert event.priority_bitfield == "001"
    assert event.human_readable_log == "Cover 31 advanced up (step not decoded) (priority 001)."


def test_a2_command_translation_wrapper_is_still_not_decoded_as_a_state() -> None:
    event = OWNEvent.parse("*2*1000#11#001#1*31##")
    assert isinstance(event, OWNAutomationEvent)
    assert event.is_translation is True
    assert event.state is None
    assert event.is_advanced_up is False
    assert event.unknown_command_code is None
    assert event.effective_what == 11


def test_a1_a2_event_content_keeps_the_raw_parameters() -> None:
    event = OWNEvent.parse("*2*11#100#001#1*0##")
    assert isinstance(event, OWNAutomationEvent)
    assert event.event_content["what"] == 11
    assert event.event_content["what parameters"] == ["100", "001", "1"]


# ── A3: WHAT 13 / 14 are not commands ──────────────────────────────────────


@pytest.mark.parametrize("what", [13, 14, 3, 9, 15, 99])
def test_a3_non_command_what_fails_closed(what: int) -> None:
    # what.md#state-values-are-not-commands; dimensions.md#shutter-status.
    event = OWNEvent.parse(f"*2*{what}*31##")
    assert isinstance(event, OWNAutomationEvent)
    assert event.state is None
    assert event.is_opening is None
    assert event.is_closing is None
    assert event.is_closed is None
    assert event.current_position is None
    assert event.is_advanced_stop is False
    assert event.unknown_command_code == what
    assert event.human_readable_log == f"Cover 31: unknown command code {what}."


def test_a3_dimension_10_states_13_and_14_still_decode() -> None:
    step_up = OWNEvent.parse("*#2*21*10*13*50*001*0##")
    step_down = OWNEvent.parse("*#2*21*10*14*50*001*0##")
    assert isinstance(step_up, OWNAutomationEvent)
    assert isinstance(step_down, OWNAutomationEvent)
    assert step_up.state == 13 and step_up.is_opening is True
    assert step_down.state == 14 and step_down.is_closing is True
    assert step_up.unknown_command_code is None


def test_base_whats_and_ordinary_states_are_unchanged() -> None:
    assert OWNAutomationEvent("*2*0*31##").state == 0
    assert OWNAutomationEvent("*2*1*31##").state == 1
    assert OWNAutomationEvent("*2*2*31##").state == 2
    closing = OWNAutomationEvent("*2*2*31##")
    assert closing.is_closing is True and closing.is_opening is False
    assert OWNAutomationEvent("*2*1*31##").unknown_command_code is None


# ── A4 / A5: no Dimension 10 write; Dimension 11 is go-to-level, not tilt ───


def test_a4_dimension_10_write_is_not_a_status() -> None:
    # dimensions.md: DIMENSION 10 is request / response / event only.
    event = OWNEvent.parse("*#2*93*#10*75##")
    assert isinstance(event, OWNAutomationEvent)
    assert event.state is None
    assert event.current_position is None
    assert event.human_readable_log == "*#2*93*#10*75##"
    # Dimension 10 status outside 10..14 is not a state either.
    odd = OWNEvent.parse("*#2*93*10*75*50*001*0##")
    assert isinstance(odd, OWNAutomationEvent)
    assert odd.state is None
    assert odd.current_position == 50


def test_a4_a5_golden_corpus_has_no_dimension_10_write_and_no_tilt() -> None:
    import json
    from pathlib import Path

    corpus = json.loads((Path(__file__).parent / "golden" / "corpus.json").read_text())
    frames = corpus["frames"] if isinstance(corpus, dict) else corpus
    records = [f for f in frames if f.get("who") == 2]
    assert records
    assert not any(f["frame"] == "*#2*93*#10*75##" for f in records)
    assert not any("tilt" in (f.get("mcp_notes") or "").lower() for f in records)
    echo = next(f for f in records if f["id"] == "cover.evt.level.50.virtual.25.f461")
    assert echo["direction"] == "event"
    for path in ("README.md", "docs/protocol_conformance_matrix.md", "tests/golden/README.md"):
        text = (Path(__file__).parent.parent / path).read_text().lower()
        assert "tilt" not in text, path


# ── A6: Dimension 11 operations are event traffic ───────────────────────────


def test_a6_f461_echo_routes_to_the_event_decoder_with_target_level() -> None:
    # dimensions.md#resulting-state-traffic; golden cover.evt.level.50.virtual.25.f461.
    echo = OWNMessage.parse("*#2*25*#11#001#1*50##")
    assert isinstance(echo, OWNAutomationEvent)
    assert echo.is_go_to_level is True
    assert echo.target_level == 50
    assert echo.priority == 1
    assert echo.priority_bitfield == "001"
    assert echo.selector == 1
    assert echo.dimension == 11
    assert echo.dimension_param == ["001", "1"]
    assert echo.dimension_value == ["50"]
    assert echo.state is None
    assert echo.current_position is None
    assert echo.is_opening is None and echo.is_closing is None and echo.is_closed is None
    assert echo.human_readable_log == "Cover 25 go to level 50% (priority 001, set)."
    assert str(echo) == "*#2*25*#11#001#1*50##"


def test_a6_write_form_routes_to_the_event_decoder_too() -> None:
    write = OWNMessage.parse("*#2*25*#11#001*50##")
    assert isinstance(write, OWNAutomationEvent)
    assert write.target_level == 50
    assert write.selector is None
    assert write.human_readable_log == "Cover 25 go to level 50% (priority 001)."
    assert write.is_dimension_writing is True
    # The builder and OWNCommand.parse still give the command class.
    assert isinstance(OWNCommand.parse("*#2*25*#11#001*50##"), OWNAutomationCommand)
    assert isinstance(OWNAutomationCommand.set_shutter_level("25", 50), OWNAutomationCommand)


def test_a6_go_to_level_edge_values() -> None:
    no_priority = OWNEvent.parse("*#2*93*#11*30##")
    assert isinstance(no_priority, OWNAutomationEvent)
    assert no_priority.target_level == 30 and no_priority.priority is None
    assert no_priority.human_readable_log == "Cover 93 go to level 30%."
    # dimensions.md#target-level: 255 is not a target position.
    unknown = OWNEvent.parse("*#2*93*#11#001*255##")
    assert isinstance(unknown, OWNAutomationEvent)
    assert unknown.target_level is None
    assert unknown.human_readable_log == "Cover 93 go to an invalid level (priority 001)."
    empty = OWNEvent.parse("*#2*93*#11#001#5*##")
    assert isinstance(empty, OWNAutomationEvent)
    assert empty.target_level is None and empty.selector is None
    # Not a WHO 2 go-to-level: still a command on the message parser.
    assert isinstance(OWNMessage.parse("*#2*93*#10*75##"), OWNAutomationCommand)
    assert isinstance(OWNMessage.parse("*#4*1*#11*2##"), OWNCommand)
    assert OWNMessage.parse("*#2**#11#001*50##").__class__ is OWNAutomationCommand
    plain = OWNAutomationEvent("*#2*25*11##")
    assert plain.is_go_to_level is False and plain.target_level is None


# ── A7: priority and info on Dimension 10 replies ───────────────────────────


@pytest.mark.parametrize(
    ("frame", "info", "name", "not_executed", "log"),
    [
        ("*#2*31*10*10*40*001*0##", 0, "normal", False, "Cover 31 is opened at 40%."),
        ("*#2*31*10*10*40*001*12##", 12, "PUL + disabled", False, "Cover 31 is opened at 40% (PUL + disabled)."),
        ("*#2*31*10*10*40*001*13##", 13, "disabled", False, "Cover 31 is opened at 40% (disabled)."),
        ("*#2*31*10*10*40*001*14##", 14, "command not executed", True, "Cover 31 is opened at 40% (command not executed)."),
        ("*#2*31*10*10*0*001*15##", 15, "PUL", False, "Cover 31 is closed (PUL)."),
        ("*#2*31*10*11*40*001*5##", 5, None, False, "Cover 31 is opening from initial position 40 (info 5)."),
        ("*#2*31*10*12*255*001*14##", 14, "command not executed", True, "Cover 31 is closing from an unknown position (command not executed)."),
        ("*#2*31*10*10*255*001*13##", 13, "disabled", False, "Cover 31 is stopped at an unknown position (disabled)."),
    ],
)
def test_a7_info_is_exposed_with_its_name(
    frame: str, info: int, name: str | None, not_executed: bool, log: str
) -> None:
    event = OWNEvent.parse(frame)
    assert isinstance(event, OWNAutomationEvent)
    assert event.info == info
    assert event.info_name == name
    assert event.is_command_not_executed is not_executed
    assert event.priority == 1
    assert event.priority_bitfield == "001"
    assert event.human_readable_log == log


def test_a7_priority_int_and_bit_field_forms() -> None:
    full = OWNAutomationEvent("*#2*21*10*10*75*001*0##")
    assert full.priority == 1 and full.priority_bitfield == "001"
    assert full._priority == 1  # MyHOME test_issue_445 reads the private int
    short = OWNAutomationEvent("*#2*21*10*10*75*1*0##")
    assert short.priority == 1 and short.priority_bitfield == "001"
    none = OWNAutomationEvent("*#2*21*10*10*75##")
    assert none.priority is None and none.priority_bitfield is None
    assert none.info is None and none.info_name is None
    assert none.is_command_not_executed is None
    assert none.priority_safety is None and none.priority_high is None and none.priority_medium is None
    odd = OWNAutomationEvent("*#2*21*10*10*75*7*0##")
    assert odd.priority == 7 and odd.priority_bitfield is None
    empty = OWNAutomationEvent("*#2*21*10*##")
    assert empty.state is None and empty.current_position is None and empty.priority is None


def test_helpers_fail_closed() -> None:
    assert _int_or_none(None) is None
    assert _int_or_none("") is None
    assert _int_or_none("x") is None
    assert _int_or_none("12") == 12
    assert _priority_bitfield(None) is None
    assert _priority_bitfield("1") == "001"
    assert _priority_bitfield("0011") is None
    assert _priority_bitfield("2") is None


# ── A8: report_shutter_level ────────────────────────────────────────────────


def test_a8_report_shutter_level_states_priority_and_unknown_position() -> None:
    for state in range(10, 15):
        assert str(OWNAutomationCommand.report_shutter_level("31", 40, state=state)) == f"*#2*31*10*{state}*40*000*0##"
    with pytest.raises(ValueError, match="between 10 and 14"):
        OWNAutomationCommand.report_shutter_level("31", 40, state=15)
    assert str(OWNAutomationCommand.report_shutter_level("31", 40, priority="001")) == "*#2*31*10*10*40*001*0##"
    assert str(OWNAutomationCommand.report_shutter_level("31", 40, priority=1)) == "*#2*31*10*10*40*001*0##"
    assert str(OWNAutomationCommand.report_shutter_level("31", 40, priority=7)) == "*#2*31*10*10*40*111*0##"
    assert str(OWNAutomationCommand.report_shutter_level("31", 40, priority="100", info=14)) == "*#2*31*10*10*40*100*14##"
    unknown = OWNAutomationCommand.report_shutter_level("31", 255)
    assert str(unknown) == "*#2*31*10*10*255*000*0##"
    assert unknown.human_readable_log == "Reporting shutter 31 at an unknown position (state 10)."
    assert "255%" not in unknown.human_readable_log
    known = OWNAutomationCommand.report_shutter_level("31", 40, state=12)
    assert known.human_readable_log == "Reporting shutter 31 position at 40% (state 12)."
    for bad in (True, 0.5):
        with pytest.raises(ValueError, match="must be integers"):
            OWNAutomationCommand.report_shutter_level("31", 40, priority=bad)  # type: ignore[arg-type]
    # The reply round-trips through the event decoder with the same fields.
    event = OWNEvent.parse(str(OWNAutomationCommand.report_shutter_level("31", 40, priority="001", info=14)))
    assert isinstance(event, OWNAutomationEvent)
    assert (event.state, event.current_position, event.priority_bitfield, event.info) == (10, 40, "001", 14)


# ── A9: WHO 2 builders validate WHERE ───────────────────────────────────────


@pytest.mark.parametrize(
    "builder",
    [
        OWNAutomationCommand.status,
        OWNAutomationCommand.get_shutter_status,
        OWNAutomationCommand.raise_shutter,
        OWNAutomationCommand.lower_shutter,
        OWNAutomationCommand.stop_shutter,
        lambda where: OWNAutomationCommand.set_shutter_level(where, 50),
        lambda where: OWNAutomationCommand.report_shutter_level(where, 50),
    ],
)
@pytest.mark.parametrize("where", ["", "*", "  ", "31*1"])
def test_a9_builders_reject_empty_or_star_where(builder, where: str) -> None:
    # addressing.md#where-forms: 0, A, APL, #GR or APL#4#INTERFACE only.
    with pytest.raises(ValueError, match="where must be a non-empty address without '\\*'"):
        builder(where)


def test_a9_builders_accept_every_documented_where_form() -> None:
    assert str(OWNAutomationCommand.status(" 0 ")) == "*#2*0##"
    assert str(OWNAutomationCommand.get_shutter_status("#3")) == "*#2*#3*10##"
    assert str(OWNAutomationCommand.raise_shutter(31)) == "*2*1*31##"
    assert str(OWNAutomationCommand.lower_shutter("21#4#01")) == "*2*2*21#4#01##"
    assert str(OWNAutomationCommand.stop_shutter("100")) == "*2*0*100##"
    for frame in ("*#2*0##", "*#2*#3*10##", "*2*1*31##", "*2*2*21#4#01##", "*2*0*100##"):
        assert OWNAutomationCommand(frame).is_valid is True
    assert OWNAutomationCommand.lower_shutter("21#4#01").human_readable_log == "Lowering shutter 21 on interface 01."


# ── L1: *#3*## parses; general_status() builds *#3## ────────────────────────


def test_l1_both_firmware_general_status_spellings_parse() -> None:
    # ORACLE_CONFIRM.md row L1: *#3*0## refused 12/12, *#3## out on 8, *#3*## on F454 / F459.
    star = OWNMessage.parse("*#3*##")
    bare = OWNMessage.parse("*#3##")
    assert isinstance(star, OWNLoadCommand) and isinstance(bare, OWNLoadCommand)
    assert star.is_valid is True and bare.is_valid is True
    assert star.is_status_request is True and bare.is_status_request is True
    assert star.where == "" and bare.where is None
    assert star.where_param == [] and star.priority is None if hasattr(star, "priority") else True
    assert star.human_readable_log == "Requesting general load status."
    assert bare.human_readable_log == "Requesting general load status."
    assert str(star) == "*#3*##"
    assert isinstance(OWNCommand.parse("*#3*##"), OWNLoadCommand)
    # The empty-WHERE spelling is WHO 3 only.
    assert OWNMessage.parse("*#1*##") is None
    assert OWNMessage.parse("*#2*##") is None
    # The documented *#3*0## keeps its raw log (no builder, refused by the firmware).
    documented = OWNMessage.parse("*#3*0##")
    assert isinstance(documented, OWNLoadCommand)
    assert documented.human_readable_log == "*#3*0##"


def test_l1_general_status_builder() -> None:
    command = OWNLoadCommand.general_status()
    assert str(command) == "*#3##"
    assert command.is_valid is True
    assert command.human_readable_log == "Requesting general load status."
    assert str(OWNLoadCommand.status(1)) == "*#3*#1##"
