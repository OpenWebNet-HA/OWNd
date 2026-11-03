"""Report 21 (OWNd master vs Encyclopedia functional pages) fixes for WHO 1, 0, 17, 14.

Rows L1..L12, S1, S2, M1, M2, A1, A2 of
work/review-session/audit_ency/lighting_scenarios.md, with the confirmation
verdicts of ENCY_CONFIRM.md (LS-*) and ORACLE_CONFIRM.md (L10 crash row, M2).

Encyclopedia pages: who-1-lighting/{what,dimensions,addressing}.md,
who-0-scenarios/README.md, who-17-scenario-management/README.md,
who-14-special-commands/README.md.
"""

from __future__ import annotations

import datetime

import pytest

from OWNd.message import (
    OWNActuatorLockCommand,
    OWNActuatorLockEvent,
    OWNCommand,
    OWNEvent,
    OWNLightingCommand,
    OWNLightingEvent,
    OWNMessage,
    OWNScenarioEvent,
    OWNSceneCommand,
    clear_coarse_dimmer_wheres,
    is_coarse_dimmer_where,
)
from OWNd.message import actuator_lock
from OWNd.message.lighting import (
    BLINK_PERIOD_MAX,
    BLINK_PERIOD_MIN,
    LEVEL100_MAX,
    LEVEL100_MIN,
    SPEED_MAX,
    SPEED_MIN,
    _check_speed,
    _int_field,
)
from OWNd.message.scenario import (
    SCENARIO_AVAILABILITY_3456,
    SCENARIO_AVAILABILITY_F420_AND_3456,
    SCENARIO_MAX_3456,
    SCENARIO_MAX_F420,
)


@pytest.fixture(autouse=True)
def _clean_coarse_registry():
    clear_coarse_dimmer_wheres()
    yield
    clear_coarse_dimmer_wheres()


# --- L1 / L2: empty or short DIMENSION values must not raise -----------------


@pytest.mark.parametrize(
    ("frame", "log_fragment"),
    [
        ("*#1*12*1*##", "DIMENSION 1 level value is missing"),
        ("*#1*12*4*##", "DIMENSION 4 level value is missing"),
        ("*#1*12*2*##", "timer report '' is incomplete"),
        ("*#1*12*2*1*2##", "timer report '1*2' is incomplete"),
        ("*#1*12*5*##", "PIR sensitivity value is missing"),
        ("*#1*12*6*##", "illuminance value is missing"),
        ("*#1*12*7*0*1##", "timeout report '0*1' is incomplete"),
        ("*#1*12*8*##", "working time value is missing"),
        ("*#1*12*9*##", "maximum working time value is missing"),
        ("*#1*12*14*##", "color temperature value is missing"),
    ],
)
def test_empty_or_short_dimension_values_parse_without_raising(frame: str, log_fragment: str) -> None:
    """L1 / L2 (ENCY_CONFIRM LS-L1: "Tags can be empty ... A tokenizer must
    preserve that empty field"; LS-L2: HOURS*MINUTES*SECONDS are three fields)."""
    msg = OWNMessage.parse(frame)
    assert isinstance(msg, OWNLightingEvent)
    assert msg.brightness is None
    assert msg.is_on is None
    assert msg.transition is None
    assert msg.timer is None
    assert msg.pir_sensitivity is None
    assert msg.illuminance is None
    assert msg.motion_timeout is None
    assert msg.working_time is None
    assert msg.max_working_time is None
    assert msg.color_temp is None
    assert msg.supports_color_temp is None
    assert log_fragment in msg.human_readable_log
    assert OWNEvent.parse(frame) is not None


def test_int_field_helper_edges() -> None:
    assert _int_field([], 0) is None
    assert _int_field([""], 0) is None
    assert _int_field(["12"], 1) is None
    assert _int_field(["12"], 0) == 12
    assert _int_field(["#12"], 0) is None


def test_sensor_dimensions_keep_message_type_when_value_is_missing() -> None:
    assert OWNLightingEvent("*#1*12*5*##").message_type == "pir_sensitivity"
    assert OWNLightingEvent("*#1*12*6*##").message_type == "illuminance_value"
    assert OWNLightingEvent("*#1*12*7*0*1##").message_type == "motion_timeout"
    assert OWNLightingEvent("*#1*12*7*0*1##").is_sensor is True


def test_complete_dimension_2_and_7_still_decode() -> None:
    assert OWNLightingEvent("*#1*21*2*1*30*0##").timer == 5400
    assert OWNLightingEvent("*#1*21*7*0*1*0##").motion_timeout == datetime.timedelta(minutes=1)
    pir = OWNLightingEvent("*#1*21*5*9##")
    assert pir.pir_sensitivity == 9
    assert "unknown (9)" in pir.human_readable_log


# --- L3: LEVEL100 outside 100..200 is not a percentage ----------------------


@pytest.mark.parametrize("level", [0, 1, 50, 99, 201, 220, 999])
@pytest.mark.parametrize("dimension", [1, 4])
def test_level100_outside_100_200_is_not_a_level(level: int, dimension: int) -> None:
    """L3 (dimensions.md "Value fields": 100 = OFF, 101..199, 200 = max; "must not
    be decoded as 100%..200%"; ENCY_CONFIRM LS-L3: every captured LEVEL100 is
    100..200). The MH202 forwards such a write (oracle *#1*31*#1*220*0##)."""
    msg = OWNMessage.parse(f"*#1*12*{dimension}*{level}*5##")
    assert isinstance(msg, OWNLightingEvent)
    assert msg.brightness is None
    assert msg.is_on is None
    assert msg.transition is None
    assert msg.status_level is None
    assert msg.status_speed is None
    assert msg.is_coarse_dimmer is False
    assert (
        msg.human_readable_log
        == f"Light 12 reported level {level} outside 100..200 in DIMENSION {dimension}; not a LEVEL100 percentage."
    )
    assert LEVEL100_MIN == 100 and LEVEL100_MAX == 200


def test_out_of_range_level_does_not_learn_a_coarse_dimmer() -> None:
    OWNMessage.parse("*#1*12*1*50*240##")
    assert is_coarse_dimmer_where("12") is False


@pytest.mark.parametrize(
    ("frame", "brightness", "is_on"),
    [
        ("*#1*12*1*100*0##", 0, False),
        ("*#1*12*1*101*0##", 1, True),
        ("*#1*12*1*134*5##", 34, True),
        ("*#1*12*1*200*5##", 100, True),
        ("*#1*13*4*100*2##", 0, False),
        ("*#1*0714*4*200*2##", 100, True),
    ],
)
def test_level100_inside_100_200_is_unchanged(frame: str, brightness: int, is_on: bool) -> None:
    msg = OWNMessage.parse(frame)
    assert isinstance(msg, OWNLightingEvent)
    assert msg.brightness == brightness
    assert msg.is_on is is_on


def test_command_builder_keeps_its_100_200_check() -> None:
    assert OWNLightingCommand("*#1*12*#1*150*5##").brightness == 50
    assert OWNLightingCommand("*#1*12*#1*50*5##").brightness is None
    assert OWNLightingCommand("*#1*12*#1*220*5##").brightness is None


# --- L4: DIMENSION 1 and DIMENSION 4 are distinct ---------------------------


def test_dimension_4_has_its_own_properties_and_no_transition() -> None:
    """L4 (dimensions.md "DIMENSION 4 - 100-level status": "do not collapse the
    secondary values of DIMENSION 1 and DIMENSION 4 into one field"; an
    F418U2 through an MH202 reports trailing 5 in DIM 1 and 2 in DIM 4 at
    LEVEL100 130; ENCY_CONFIRM LS-L4: relationship-register.md line 107 keeps
    DIM 1 / DIM 4 distinct, the MH200 capture shows DIM 4 requests get no
    reply, so DIM 4 availability is gateway-path dependent)."""
    dim1 = OWNMessage.parse("*#1*32*1*130*5##")
    dim4 = OWNMessage.parse("*#1*32*4*130*2##")
    assert isinstance(dim1, OWNLightingEvent) and isinstance(dim4, OWNLightingEvent)
    # Same published LEVEL100 field in both.
    assert dim1.brightness == dim4.brightness == 30
    assert dim1.is_on is True and dim4.is_on is True
    # Secondary values stay apart: status_speed is DIMENSION 4 only, while
    # transition keeps the DIMENSION 4 trailing value too (MyHOME reads it there).
    assert dim1.transition == 5
    assert dim1.status_level is None
    assert dim1.status_speed is None
    assert dim4.transition == 2
    assert dim4.status_level == 30
    assert dim4.status_speed == 2
    assert dim4.human_readable_log == "Light 32 is switched on at 30%."


def test_dimension_4_reply_to_a_dimension_1_request_still_reports_off() -> None:
    """Golden light.dim.reply.level_transition.13 (MyHOME#466): an F454 answers
    a DIMENSION 1 request while OFF with DIMENSION 4 (dimensions.md consequence
    2: "do not require a response to use the same DIMENSION identifier")."""
    msg = OWNMessage.parse("*#1*13*4*100*2##")
    assert isinstance(msg, OWNLightingEvent)
    assert msg.brightness == 0
    assert msg.is_on is False
    assert msg.status_level == 0
    assert msg.status_speed == 2
    assert msg.human_readable_log == "Light 13 is switched off."


def test_dimension_4_without_trailing_value() -> None:
    msg = OWNLightingEvent("*#1*32*4*130##")
    assert msg.brightness == 30
    assert msg.status_level == 30
    assert msg.status_speed is None


def test_coarse_dimmer_is_learned_from_dimension_1_only() -> None:
    """The F414 coarse sentinel 240 is a DIMENSION 1 observation (golden
    light.dim.reply.level.30.speed240.61, MyHOME#767) and the page records a
    DIMENSION 4 request to a classic F414 ending in NACK (dimensions.md
    "DIMENSION 4", F414 paragraph)."""
    dim4 = OWNMessage.parse("*#1*12*4*130*240##")
    assert isinstance(dim4, OWNLightingEvent)
    assert dim4.is_coarse_dimmer is False
    assert dim4.status_speed == 240
    assert dim4.transition == 240  # exposed, but not learned from
    assert is_coarse_dimmer_where("12") is False

    dim1 = OWNMessage.parse("*#1*61*1*130*240##")
    assert isinstance(dim1, OWNLightingEvent)
    assert dim1.is_coarse_dimmer is True
    assert dim1.transition == 240
    assert is_coarse_dimmer_where("61") is True

    # A later DIMENSION 1 reply with a real speed clears the learning.
    dim1_again = OWNMessage.parse("*#1*61*1*130*5##")
    assert isinstance(dim1_again, OWNLightingEvent)
    assert dim1_again.is_coarse_dimmer is False
    assert is_coarse_dimmer_where("61") is False

    # A DIMENSION 1 reply without a speed field neither learns nor clears.
    OWNMessage.parse("*#1*61*1*130*240##")
    OWNMessage.parse("*#1*61*1*130##")
    assert is_coarse_dimmer_where("61") is True


def test_is_brightness_query_covers_both_level_dimensions() -> None:
    assert OWNLightingCommand("*#1*12*1##").is_brightness_query is True
    assert OWNLightingCommand("*#1*12*4##").is_brightness_query is True


# --- L5: DIMENSION 8 / 9 ------------------------------------------------------


def test_dimension_8_working_time() -> None:
    """L5 (dimensions.md "DIMENSION 8 - working time": *#1*WHERE*8*WORKING_TIME##,
    hours; "The response can also appear on the event session")."""
    msg = OWNMessage.parse("*#1*12*8*500##")
    assert isinstance(msg, OWNLightingEvent)
    assert msg.working_time == 500
    assert msg.max_working_time is None
    assert msg.is_on is None
    assert msg.human_readable_log == "Light 12 has been working for 500 hours."
    assert "unknown dimension" not in msg.human_readable_log


def test_dimension_9_max_working_time() -> None:
    """L5 (dimensions.md "DIMENSION 9 - maximum working time": value in hours)."""
    msg = OWNMessage.parse("*#1*12*9*1000##")
    assert isinstance(msg, OWNLightingEvent)
    assert msg.max_working_time == 1000
    assert msg.working_time is None
    assert msg.human_readable_log == "Light 12 maximum working time is 1000 hours."
    write = OWNMessage.parse("*#1*12*#9*1000##")
    assert isinstance(write, OWNLightingCommand)
    assert write.dimension == 9


def test_unknown_dimension_is_still_reported() -> None:
    assert "unknown dimension 99" in OWNLightingEvent("*#1*12*99*1##").human_readable_log


# --- L6 / L12: parameterised WHAT -------------------------------------------


@pytest.mark.parametrize(
    ("frame", "levels", "transition", "log"),
    [
        ("*1*30#5#10*12##", 5, 10, "Light 12 is dimmed up by 5 levels at speed 10."),
        ("*1*31#2#3*12##", 2, 3, "Light 12 is dimmed down by 2 levels at speed 3."),
        ("*1*30#5*12##", 5, None, "Light 12 is dimmed up by 5 levels."),
        ("*1*30*12##", None, None, "Light 12 is dimmed up one level."),
        ("*1*31*12##", None, None, "Light 12 is dimmed down one level."),
    ],
)
def test_step_with_levels_and_speed(frame: str, levels: int | None, transition: int | None, log: str) -> None:
    """L6 (what.md "Switching and levels": 30#LEVELS#SPEED / 31#LEVELS#SPEED
    "change several levels at the specified speed. These forms must not be
    reduced to their leading numeric WHAT")."""
    msg = OWNMessage.parse(frame)
    assert isinstance(msg, OWNLightingEvent)
    assert msg.levels == levels
    assert msg.transition == transition
    assert msg.is_on is None  # L-B1 (lab 2026-11-03): a step is a command, not a state
    assert msg.is_step is True
    assert msg.human_readable_log == log


# --- Lab 2026-11-03 L-B1 / L-B2: WHAT 30 / 31 steps are relative ---------------
#
# Live F461 2.0.11 + F418 at 0010 (reports/data/live_f418_0010_2026-11-03/
# lab_probe_output.txt): *1*30*0010## moved 53 % -> 63 % and the gateway echoed
# *1*8*0010##; *1*31*0010## moved 63 % -> 47 % with echo *1*7*0010##;
# *1*30#5#0*0010## moved 47 % -> 52 %; *1*30#50#0*0010## moved 52 % -> 100 %.


@pytest.mark.parametrize(
    ("frame", "levels", "log"),
    [
        ("*1*30*0010##", None, "Light 0010 is dimmed up one level."),
        ("*1*31*0010##", None, "Light 0010 is dimmed down one level."),
        ("*1*30#5#0*0010##", 5, "Light 0010 is dimmed up by 5 levels at speed 0."),
        ("*1*30#50#0*0010##", 50, "Light 0010 is dimmed up by 50 levels at speed 0."),
        ("*1*31#5#0*0010##", 5, "Light 0010 is dimmed down by 5 levels at speed 0."),
    ],
)
def test_step_frames_of_the_live_run_carry_no_state(frame: str, levels: int | None, log: str) -> None:
    """L-B1: the step itself carries no on/off state; the F461 reports the
    resulting preset in a separate frame (*1*8*0010## after *1*30*0010##)."""
    msg = OWNMessage.parse(frame)
    assert isinstance(msg, OWNLightingEvent)
    assert msg.is_step is True
    assert msg.is_on is None
    assert msg.brightness is None
    assert msg.levels == levels
    assert msg.unknown_state is None
    assert msg.is_sensor is False
    assert msg.human_readable_log == log


@pytest.mark.parametrize(
    ("frame", "preset", "is_on"),
    [
        ("*1*8*0010##", 8, True),  # preset echo after *1*30*0010## (dim 1 readback 163)
        ("*1*7*0010##", 7, True),  # preset echo after *1*31*0010## (dim 1 readback 147)
        ("*1*10*0010##", 10, True),  # echo after *1*1*0010## at 100 %
        ("*1*1*0010##", None, True),
        ("*1*0*0010##", None, False),
    ],
)
def test_preset_echo_after_a_step_still_carries_the_state(frame: str, preset: int | None, is_on: bool) -> None:
    """L-B1: only the preset / switch frames the gateway sends after a step
    carry is_on; they are not steps."""
    msg = OWNMessage.parse(frame)
    assert isinstance(msg, OWNLightingEvent)
    assert msg.is_step is False
    assert msg.is_on is is_on
    assert msg.brightness_preset == preset


def test_step_builders_emit_the_live_run_frames() -> None:
    """L-B2: delta stays 1..100 (the F461 + F418 took #5 and #50 as percent
    levels: 47 -> 52 %, 52 -> 100 %); the PDF lists dimmerLevel10 2..10, the wider
    range is libqtdevices' dimmer100 use, kept because the gateway applied it."""
    assert str(OWNLightingCommand.step_up("0010")) == "*1*30*0010##"
    assert str(OWNLightingCommand.step_down("0010")) == "*1*31*0010##"
    assert str(OWNLightingCommand.step_up("0010", 5, 0)) == "*1*30#5#0*0010##"
    assert str(OWNLightingCommand.step_up("0010", 50, 0)) == "*1*30#50#0*0010##"
    assert str(OWNLightingCommand.step_up("0010", 100)) == "*1*30#100#0*0010##"
    assert str(OWNLightingCommand.step_down("0010", 1, 255)) == "*1*31#1#255*0010##"
    for delta in (0, 101):
        with pytest.raises(ValueError):
            OWNLightingCommand.step_up("0010", delta)
        with pytest.raises(ValueError):
            OWNLightingCommand.step_down("0010", delta)
    with pytest.raises(ValueError):
        OWNLightingCommand.step_up("0010", 5, 256)


@pytest.mark.parametrize(
    ("frame", "is_on", "transition", "log"),
    [
        ("*1*1#255*12##", True, 255, "Light 12 is switched on with transition speed 255."),
        ("*1*0#3*12##", False, 3, "Light 12 is switched off with transition speed 3."),
        ("*1*1*12##", True, None, "Light 12 is switched on."),
        ("*1*0*12##", False, None, "Light 12 is switched off."),
    ],
)
def test_on_off_with_speed(frame: str, is_on: bool, transition: int | None, log: str) -> None:
    """L12 (what.md: 0#SPEED / 1#SPEED "must not be reduced to their leading
    numeric WHAT"; ENCY_CONFIRM LS-L12: a real client emits 1#SPEED)."""
    msg = OWNMessage.parse(frame)
    assert isinstance(msg, OWNLightingEvent)
    assert msg.is_on is is_on
    assert msg.transition == transition
    assert msg.levels is None
    assert msg.human_readable_log == log


def test_translation_wrapper_is_untouched() -> None:
    msg = OWNLightingEvent("*1*1000#1*12##")
    assert msg.is_on is None
    assert msg.transition is None
    assert msg.human_readable_log == "*1*1000#1*12##"


# --- L7 / L8 / L9: builders validate the type, keep the pinned fallbacks ------
# Precedent gate: MyHOME (tests/test_message_edges.py) pins switch_on('21', 300)
# -> *1*1*21##, switch_off('21', -1) -> *1*0*21##, set_brightness(50, -5) ->
# speed 0 and flash(-1) -> *1*20*21##, and light.py passes Home Assistant
# transition seconds straight through, so out-of-range values keep the
# pre-existing fallback; only bool / fractional values raise (OWNd#129).


@pytest.mark.parametrize("speed", [-1, 256, 300, 1000])
def test_switch_on_off_drop_out_of_range_speed(speed: int) -> None:
    """L7 (what.md "Switching and levels": speed 0 last, 1..254 explicit, 255
    default): an out-of-range speed is not a speed; the plain frame goes out."""
    assert str(OWNLightingCommand.switch_on("12", speed)) == "*1*1*12##"
    assert str(OWNLightingCommand.switch_off("12", speed)) == "*1*0*12##"
    assert _check_speed(speed) is None


@pytest.mark.parametrize("speed", [True, 2.5])
def test_switch_on_rejects_non_integer_speed(speed: object) -> None:
    with pytest.raises(ValueError, match="must be an integer"):
        OWNLightingCommand.switch_on("12", speed)  # type: ignore[arg-type]
    with pytest.raises(ValueError, match="must be an integer"):
        OWNLightingCommand.switch_off("12", speed)  # type: ignore[arg-type]


def test_switch_on_off_accept_the_published_speed_range() -> None:
    assert str(OWNLightingCommand.switch_on("12", 0)) == "*1*1#0*12##"
    assert str(OWNLightingCommand.switch_on("12", 255)) == "*1*1#255*12##"
    assert str(OWNLightingCommand.switch_off("12", 0)) == "*1*0#0*12##"
    assert str(OWNLightingCommand.switch_on("12")) == "*1*1*12##"
    assert str(OWNLightingCommand.switch_off("12", None)) == "*1*0*12##"
    assert str(OWNLightingCommand.switch_on("12", 5.0)) == "*1*1#5*12##"
    assert SPEED_MIN == 0 and SPEED_MAX == 255
    assert _check_speed(None) is None


@pytest.mark.parametrize("speed", [-1, 300])
def test_set_brightness_sends_last_speed_for_out_of_range_transition(speed: int) -> None:
    """L8 (dimensions.md "Value fields": SPEED 0 = "last speed used"): the
    pre-existing fallback MyHOME pins."""
    assert str(OWNLightingCommand.set_brightness("12", 50, speed)) == "*#1*12*#1*150*0##"
    assert str(OWNLightingCommand.set_brightness("12", 0, speed)) == "*1*0*12##"


@pytest.mark.parametrize("speed", [True, 2.5])
def test_set_brightness_rejects_non_integer_transition(speed: object) -> None:
    with pytest.raises(ValueError, match="must be integers"):
        OWNLightingCommand.set_brightness("12", 50, speed)  # type: ignore[arg-type]


def test_set_brightness_keeps_valid_transitions() -> None:
    assert str(OWNLightingCommand.set_brightness("12", 50, 0)) == "*#1*12*#1*150*0##"
    assert str(OWNLightingCommand.set_brightness("12", 50, 255)) == "*#1*12*#1*150*255##"
    assert str(OWNLightingCommand.set_brightness("12", 0, 5)) == "*1*0#5*12##"
    assert str(OWNLightingCommand.set_brightness("12", 0, 0)) == "*1*0*12##"


@pytest.mark.parametrize("period", [0, 0.2, 0.49, 5.01, 7, -1, True])
def test_flash_falls_back_to_half_a_second_outside_the_range(period: object) -> None:
    """L9 (what.md "Blinking operations": WHAT 20..29 = 0.5..5 s in 0.5 s steps):
    an out-of-range period is the 0.5 s default, as MyHOME pins."""
    assert str(OWNLightingCommand.flash("12", period)) == "*1*20*12##"  # type: ignore[arg-type]


def test_flash_accepts_the_published_range() -> None:
    assert str(OWNLightingCommand.flash("12")) == "*1*20*12##"
    assert str(OWNLightingCommand.flash("12", None)) == "*1*20*12##"
    assert str(OWNLightingCommand.flash("12", 0.5)) == "*1*20*12##"
    assert str(OWNLightingCommand.flash("12", 1.5)) == "*1*22*12##"
    assert str(OWNLightingCommand.flash("12", 5)) == "*1*29*12##"
    assert str(OWNLightingCommand.flash("12", 0.7)) == "*1*20*12##"  # nearest 0.5 s step
    assert str(OWNLightingCommand.flash("12", _freqency=1.0)) == "*1*21*12##"
    assert BLINK_PERIOD_MIN == 0.5 and BLINK_PERIOD_MAX == 5.0


# --- L10: WHO 1 builders require a usable WHERE -----------------------------


@pytest.mark.parametrize("where", ["", " ", "*", "12*1", "*12"])
@pytest.mark.parametrize(
    "build",
    [
        lambda w: OWNLightingCommand.status(w),
        lambda w: OWNLightingCommand.get_brightness(w),
        lambda w: OWNLightingCommand.get_pir_sensitivity(w),
        lambda w: OWNLightingCommand.get_illuminance(w),
        lambda w: OWNLightingCommand.get_motion_timeout(w),
        lambda w: OWNLightingCommand.get_color_temperature(w),
        lambda w: OWNLightingCommand.set_color_temperature(w, 300),
        lambda w: OWNLightingCommand.get_hsv_color(w),
        lambda w: OWNLightingCommand.set_hsv_color(w, 1, 2, 3),
        lambda w: OWNLightingCommand.set_rgb_color(w, 1, 2, 3),
        lambda w: OWNLightingCommand.flash(w),
        lambda w: OWNLightingCommand.switch_on(w),
        lambda w: OWNLightingCommand.switch_on(w, 5),
        lambda w: OWNLightingCommand.switch_off(w),
        lambda w: OWNLightingCommand.switch_off(w, 5),
        lambda w: OWNLightingCommand.set_brightness_preset(w, 5),
        lambda w: OWNLightingCommand.step_up(w),
        lambda w: OWNLightingCommand.step_down(w, 5, 1),
        lambda w: OWNLightingCommand.switch_on_timed(w, 11),
        lambda w: OWNLightingCommand.set_variable_timer(w, 0, 1, 0),
        lambda w: OWNLightingCommand.get_variable_timer(w),
        lambda w: OWNLightingCommand.set_brightness(w, 50),
        lambda w: OWNLightingCommand.set_brightness(w, 50, coarse=True),
        lambda w: OWNLightingCommand.set_brightness(w, 0),
        lambda w: OWNLightingCommand.report_brightness(w, 50),
    ],
)
def test_who1_builders_reject_empty_or_star_where(where: str, build) -> None:
    """L10 (addressing.md: WHERE is protocol syntax, "*" a separator;
    ENCY_CONFIRM LS-L10: the A/PL grammar admits no empty or *-bearing WHERE).
    ORACLE_CONFIRM.md row L10: ``*#1*##`` is refused on 11 emulated gateways
    and crashes the MH202 010024 (crash table: "nack, crash ... empty WHERE in
    a WHO 1 status request"); ``*#1*12*1##`` goes out as a DIMENSION 1 read."""
    with pytest.raises(ValueError, match="where must be a non-empty address without"):
        build(where)


def test_who1_builders_strip_and_accept_int_where() -> None:
    assert str(OWNLightingCommand.status(" 12 ")) == "*#1*12##"
    assert str(OWNLightingCommand.status(12)) == "*#1*12##"
    assert str(OWNLightingCommand.status("0311#4#01")) == "*#1*0311#4#01##"
    assert str(OWNLightingCommand.status("#25")) == "*#1*#25##"
    assert str(OWNLightingCommand.status("0")) == "*#1*0##"
    assert OWNLightingCommand.status("12").human_readable_log == "Requesting light or switch 12 status."


# --- L11: 255*255*255 timer -------------------------------------------------


def test_unusable_timer_report_decodes_to_none() -> None:
    """L11 (dimensions.md "Historical timer handling": the TS10_1_0_23 touchscreen
    ignores 255*255*255 as unusable timer state; ENCY_CONFIRM LS-L11)."""
    msg = OWNMessage.parse("*#1*12*2*255*255*255##")
    assert isinstance(msg, OWNLightingEvent)
    assert msg.timer is None
    assert msg.is_on is None
    assert msg.human_readable_log == "Light 12 reports no usable timer (255*255*255)."
    zero = OWNMessage.parse("*#1*12*2*0*0*0##")
    assert isinstance(zero, OWNLightingEvent)
    assert zero.timer == 0


# --- S1 / S2: WHO 0 WHAT ranges and central-unit states ----------------------


@pytest.mark.parametrize(
    ("what", "availability", "note"),
    [(1, SCENARIO_AVAILABILITY_F420_AND_3456, ""), (16, SCENARIO_AVAILABILITY_F420_AND_3456, ""),
     (17, SCENARIO_AVAILABILITY_3456, " (3456 IR interface only)"), (20, SCENARIO_AVAILABILITY_3456, " (3456 IR interface only)")],
)
def test_scenario_activation_ranges(what: int, availability: str, note: str) -> None:
    """S1 (who-0-scenarios/README.md "WHAT reference": 1..16 F420 and 3456,
    17..20 3456 only; ENCY_CONFIRM LS-S1: the 1..31 API assertions do not
    extend the published capacities)."""
    msg = OWNEvent.parse(f"*0*{what}*11##")
    assert isinstance(msg, OWNScenarioEvent)
    assert msg.scenario == what
    assert msg.event == "launched"
    assert msg.scenario_availability == availability
    assert msg.unknown_what is None
    assert msg.human_readable_log == f"Scenario {what} from control panel 11 has been launched{note}."
    assert SCENARIO_MAX_F420 == 16 and SCENARIO_MAX_3456 == 20


@pytest.mark.parametrize("what", [0, 21, 31, 32, 39, 47, 99])
def test_scenario_what_outside_the_page_is_unknown_not_launched(what: int) -> None:
    msg = OWNEvent.parse(f"*0*{what}*01##")
    assert isinstance(msg, OWNScenarioEvent)
    assert msg.scenario is None
    assert msg.event is None
    assert msg.scenario_availability is None
    assert msg.unknown_what == what
    assert msg.human_readable_log == f"Scenario module 01 reports unknown WHAT {what}."
    assert "launched" not in msg.human_readable_log


@pytest.mark.parametrize(
    ("frame", "event", "target", "log"),
    [
        ("*0*40#1*11##", "programming started", 1, "Scenario module 11: recording of scenario 1 started."),
        ("*0*40*11##", "programming started", None, "Scenario module 11: recording started (no scenario selected)."),
        ("*0*41#2*11##", "programming stopped", 2, "Scenario module 11: recording of scenario 2 ended."),
        ("*0*41*11##", "programming stopped", None, "Scenario module 11: recording ended (no scenario selected)."),
        ("*0*42#1*11##", "deleted", 1, "Scenario module 11: scenario 1 erased."),
        ("*0*42*31##", "deleted", None, "Scenario module 31: all scenarios erased."),
        ("*0*43*01##", "locked", None, "Scenario central unit 01 is locked."),
        ("*0*44*01##", "unlocked", None, "Scenario central unit 01 is unlocked."),
        ("*0*45*99##", "unavailable", None, "Scenario central unit 99 is unavailable."),
        ("*0*46*01##", "memory full", None, "Scenario central unit 01 memory is full."),
        ("*0*46#9*99##", "memory full", 9, "Scenario central unit 99 memory is full (scenario 9)."),
    ],
)
def test_programming_and_central_unit_states_use_the_page_wording(frame: str, event: str, target: int | None, log: str) -> None:
    """S2 (who-0-scenarios/README.md "Lock and unlock - WHAT 43 / 44": 43 / 44
    lock / unlock "the addressed scenario central unit"; 45 / 46 "describe
    central-unit state rather than a stored scenario number"; "Erase
    operations - WHAT 42": bare 42 erases all; ENCY_CONFIRM LS-S2). The
    ``event`` values stay as before."""
    msg = OWNEvent.parse(frame)
    assert isinstance(msg, OWNScenarioEvent)
    assert msg.event == event
    assert msg.programming_scenario == target
    assert msg.scenario is None
    assert msg.unknown_what is None
    assert msg.human_readable_log == log


def test_scenario_status_request_has_no_event() -> None:
    msg = OWNEvent.parse("*#0*11##")
    assert isinstance(msg, OWNScenarioEvent)
    assert msg.scenario is None and msg.event is None and msg.unknown_what is None


# --- M1 / M2: WHO 17 ----------------------------------------------------------


def test_dimension_40_frames_are_not_status_requests() -> None:
    """M1 (who-17-scenario-management/README.md "Status request": the request is
    *#17*WHERE##; DIMENSION 40 is a MyHOME_Suite "Set, request and report
    scenario state" operation)."""
    write = OWNCommand.parse("*#17*5*#40*1##")
    assert isinstance(write, OWNSceneCommand)
    assert write.is_dimension_writing is True
    assert write.human_readable_log == "Writing scene 5 dimension 40."
    read = OWNCommand.parse("*#17*5*40##")
    assert isinstance(read, OWNSceneCommand)
    assert read.human_readable_log == "Requesting scene 5 dimension 40."
    report = OWNSceneCommand("*#17*5*40*1##")
    assert report.human_readable_log == "Scene 5 dimension 40 report."
    status = OWNCommand.parse("*#17*5##")
    assert isinstance(status, OWNSceneCommand)
    assert status.human_readable_log == "Requesting status of scene 5."


@pytest.mark.parametrize("where", ["", " ", "*", "1*2", None])
def test_scene_builders_reject_empty_where(where: str | None) -> None:
    """M1 (start('') built *17*1*## with the log "Requesting global scene
    status") and M2 (status(None) emitted *#17##: not on the page, NACKed
    on all 12 emulated gateways, ORACLE_CONFIRM.md row M2 "UNDECIDED": both
    *#17## and *#17*0## nack, silent on 12/12)."""
    for build in (
        OWNSceneCommand.start,
        OWNSceneCommand.stop,
        OWNSceneCommand.enable,
        OWNSceneCommand.disable,
        OWNSceneCommand.status,
    ):
        with pytest.raises(ValueError, match="where must be a non-empty address without"):
            build(where)  # type: ignore[arg-type]


def test_scene_builders_documented_forms() -> None:
    assert str(OWNSceneCommand.start(" 5 ")) == "*17*1*5##"
    assert str(OWNSceneCommand.status()) == "*#17*0##"
    assert str(OWNSceneCommand.status(0)) == "*#17*0##"
    assert str(OWNSceneCommand.status("12")) == "*#17*12##"
    bare = OWNSceneCommand("*#17##")
    assert bare.human_readable_log == "Requesting global scene status (undocumented *#17## form)."


# --- A1 / A2: WHO 14 ------------------------------------------------------------


def test_who14_status_request_is_parsed_but_undocumented_and_not_built() -> None:
    """A1 (who-14-special-commands/README.md "Scope of the semantics": only the
    two lock / unlock command frames exist; ENCY_CONFIRM LS-A1: no status
    request in any source)."""
    req = OWNCommand.parse("*#14*32##")
    assert isinstance(req, OWNActuatorLockCommand)
    assert req.is_status_request is True
    assert "Undocumented" in (OWNActuatorLockCommand.is_status_request.__doc__ or "")
    assert not any(
        name.startswith(("status", "get", "request"))
        for name in vars(OWNActuatorLockCommand)
        if not name.startswith("_") and callable(getattr(OWNActuatorLockCommand, name))
    )


@pytest.mark.parametrize("interface", [11, "11", 15, "15"])
def test_who14_interfaces_11_15_parse_but_are_not_built(interface: int | str) -> None:
    """A2 (who-1-lighting/addressing.md "Address scopes": Int is 01..09 or 11..15;
    ENCY_CONFIRM LS-A2: "Implementations should preserve that discrepancy").
    The builders refuse 11..15 on bt_luci evidence; the parser keeps them."""
    evt = OWNActuatorLockEvent(f"*14*0*12#4#{interface}##")
    assert evt.interface == str(interface)
    assert evt.is_locked is True
    with pytest.raises(ValueError, match="between 1 and 9"):
        OWNActuatorLockCommand.lock("12", interface=interface)
    assert "11..15" in (actuator_lock.__doc__ or "")
