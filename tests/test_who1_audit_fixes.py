"""WHO 1, 0, 17 and 14 against the Encyclopedia functional pages: crash guards and builder WHERE guards.

Evidence: the Encyclopedia pages below and the own-firmware-oracle suites
``ownd-audit-frames`` (WHO 1 empty WHERE: refused on eleven emulated gateways,
crash on the MH202 010024) and ``scenario-who17`` (bare ``*#17##``: NACKed
with a silent bus on all twelve).

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
    OWNSceneCommand,
    clear_coarse_dimmer_wheres,
)
from OWNd.message import actuator_lock
from OWNd.message.lighting import (
    BLINK_PERIOD_MAX,
    BLINK_PERIOD_MIN,
    SPEED_MAX,
    SPEED_MIN,
    _check_speed,
    _int_field,
)


@pytest.fixture(autouse=True)
def _clean_coarse_registry():
    clear_coarse_dimmer_wheres()
    yield
    clear_coarse_dimmer_wheres()


# --- Empty or short DIMENSION values must not raise ---------------------------


@pytest.mark.parametrize(
    ("frame", "log_fragment"),
    [
        ("*#1*12*1*##", "DIMENSION 1 level value is missing"),
        ("*#1*12*4*##", "DIMENSION 4 level value is missing"),
        ("*#1*12*2*##", "timer report '' is incomplete"),
        ("*#1*12*2*1*2##", "timer report '1*2' is incomplete"),
        ("*#1*12*5*##", "PIR sensitivity value is missing"),
        ("*#1*12*6*##", "illuminance value is missing"),
        ("*#1*12*7*##", "timeout report '' is incomplete"),
        ("*#1*12*7*0*1##", "timeout report '0*1' is incomplete"),
        ("*#1*12*14*##", "color temperature value is missing"),
    ],
)
def test_empty_or_short_dimension_values_parse_without_raising(frame: str, log_fragment: str) -> None:
    """protocol/frame-syntax.md "Delimiters and empty tags": "Tags can be empty ...
    A tokenizer must preserve that empty field"; dimensions.md "DIMENSION 2 -
    temporization": HOURS*MINUTES*SECONDS are three fields."""
    msg = OWNMessage.parse(frame)
    assert isinstance(msg, OWNLightingEvent)
    assert msg.brightness is None
    assert msg.is_on is None
    assert msg.transition is None
    assert msg.timer is None
    assert msg.pir_sensitivity is None
    assert msg.illuminance is None
    assert msg.motion_timeout is None
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


@pytest.mark.parametrize("value", ["\uff11\uff15\uff10", "\u00b2", "\u2460", "1\u0663"])
def test_int_field_reads_ascii_digits_only(value: str) -> None:
    """``str.isdigit`` is True for fullwidth, superscript, circled and Arabic-Indic
    digits; none is on the wire, and ``int`` raises on the superscript and circled
    ones, so the field fails closed instead."""
    assert value.isdigit()
    assert _int_field([value], 0) is None


@pytest.mark.parametrize("frame", ["*#1*12*1*150*##", "*#1*12*4*150*##"])
def test_a_level_with_an_empty_trailing_speed_keeps_the_level(frame: str) -> None:
    """The second field can be empty too (``*#1*12*1*150*##`` raised on master)."""
    msg = OWNMessage.parse(frame)
    assert isinstance(msg, OWNLightingEvent)
    assert msg.brightness == 50 and msg.is_on is True
    assert msg.transition is None
    assert OWNEvent.parse(frame) is not None


def test_fullwidth_digits_in_an_hsv_reply_fail_closed() -> None:
    """DIMENSION 12 reads its three values through ``_int_field`` too: fullwidth
    ``100 50 50`` is not a colour, the frame keeps its raw log, and the ASCII
    form still decodes."""
    frame = "*#1*12*12*\uff11\uff10\uff10*\uff15\uff10*\uff15\uff10##"
    msg = OWNMessage.parse(frame)
    assert isinstance(msg, OWNLightingEvent)
    assert msg.hsv is None and msg.hs is None and msg.rgb is None
    assert msg.supports_hsv is None and msg.supports_rgb is None
    assert msg.human_readable_log == frame
    ascii_msg = OWNMessage.parse("*#1*12*12*100*50*50##")
    assert isinstance(ascii_msg, OWNLightingEvent) and ascii_msg.hsv == (100, 50, 50)


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


# --- LEVEL100: the published field, decoded as before -------------------------


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


# --- DIMENSION 1 and DIMENSION 4 are distinct -----------------------------------


def test_dimension_4_has_its_own_properties() -> None:
    """dimensions.md "DIMENSION 4 - 100-level status": "do not collapse the
    secondary values of DIMENSION 1 and DIMENSION 4 into one field". An F418U2
    through an MH202 reports trailing 5 in DIM 1 and 2 in DIM 4 at LEVEL100 130;
    the MH200 capture shows DIM 4 requests get no reply, so DIM 4 availability
    is gateway-path dependent."""
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


def test_is_brightness_query_covers_both_level_dimensions() -> None:
    assert OWNLightingCommand("*#1*12*1##").is_brightness_query is True
    assert OWNLightingCommand("*#1*12*4##").is_brightness_query is True


# --- Unknown dimensions -----------------------------------------------------------


def test_unknown_dimension_is_still_reported() -> None:
    assert "unknown dimension 99" in OWNLightingEvent("*#1*12*99*1##").human_readable_log


# --- Parameterised WHAT -----------------------------------------------------------


def test_translation_wrapper_is_untouched() -> None:
    msg = OWNLightingEvent("*1*1000#1*12##")
    assert msg.is_on is None
    assert msg.transition is None
    assert msg.human_readable_log == "*1*1000#1*12##"


# --- Builders keep the pinned speed and period fallbacks -----------------------
# OWNd's own tests/test_message_edges.py pins switch_on('21', 300) -> *1*1*21##,
# switch_off('21', -1) -> *1*0*21##, set_brightness(50, -5) -> speed 0 and
# flash(-1) -> *1*20*21##, and MyHOME's light.py passes Home Assistant
# transition seconds straight through, so out-of-range values keep the
# pre-existing fallback. switch_on / switch_off and flash use the value as
# given; only set_brightness and report_brightness keep master's bool /
# fractional check.


@pytest.mark.parametrize("speed", [-1, 256, 300, 1000])
def test_switch_on_off_drop_out_of_range_speed(speed: int) -> None:
    """what.md "Switching and levels": speed 0 last, 1..254 explicit, 255
    default; an out-of-range speed is not a speed, the plain frame goes out."""
    assert str(OWNLightingCommand.switch_on("12", speed)) == "*1*1*12##"
    assert str(OWNLightingCommand.switch_off("12", speed)) == "*1*0*12##"
    assert _check_speed(speed) is None


def test_switch_on_off_accept_the_published_speed_range() -> None:
    assert str(OWNLightingCommand.switch_on("12", 0)) == "*1*1#0*12##"
    assert str(OWNLightingCommand.switch_on("12", 255)) == "*1*1#255*12##"
    assert str(OWNLightingCommand.switch_off("12", 0)) == "*1*0#0*12##"
    assert str(OWNLightingCommand.switch_on("12")) == "*1*1*12##"
    assert str(OWNLightingCommand.switch_off("12", None)) == "*1*0*12##"
    assert SPEED_MIN == 0 and SPEED_MAX == 255
    assert _check_speed(None) is None


@pytest.mark.parametrize("speed", [-1, 300])
def test_set_brightness_sends_last_speed_for_out_of_range_transition(speed: int) -> None:
    """dimensions.md "Value fields": SPEED 0 = "last speed used"; the
    pre-existing fallback MyHOME pins."""
    assert str(OWNLightingCommand.set_brightness("12", 50, speed)) == "*#1*12*#1*150*0##"
    assert str(OWNLightingCommand.set_brightness("12", 0, speed)) == "*1*0*12##"


@pytest.mark.parametrize("speed", [True, 2.5])
def test_set_brightness_rejects_non_integer_transition(speed: object) -> None:
    with pytest.raises(ValueError, match="must be integers"):
        OWNLightingCommand.set_brightness("12", 50, speed)  # type: ignore[arg-type]


def test_set_brightness_converts_the_transition_as_master_did() -> None:
    """``int(_transition)``: a numeric string is accepted and ``None`` raises, as on master."""
    assert str(OWNLightingCommand.set_brightness("12", 50, "5")) == "*#1*12*#1*150*5##"  # type: ignore[arg-type]
    with pytest.raises(TypeError):
        OWNLightingCommand.set_brightness("12", 50, None)  # type: ignore[arg-type]


def test_set_brightness_keeps_valid_transitions() -> None:
    assert str(OWNLightingCommand.set_brightness("12", 50, 0)) == "*#1*12*#1*150*0##"
    assert str(OWNLightingCommand.set_brightness("12", 50, 255)) == "*#1*12*#1*150*255##"
    assert str(OWNLightingCommand.set_brightness("12", 0, 5)) == "*1*0#5*12##"
    assert str(OWNLightingCommand.set_brightness("12", 0, 0)) == "*1*0*12##"


@pytest.mark.parametrize("period", [0, 0.2, 0.49, 5.01, 7, -1])
def test_flash_falls_back_to_half_a_second_outside_the_range(period: object) -> None:
    """what.md "Blinking operations": WHAT 20..29 = 0.5..5 s in 0.5 s steps;
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


# --- WHO 1 builders require a usable WHERE ------------------------------------------


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
    """addressing.md: WHERE is protocol syntax and "*" a separator; the A/PL
    grammar admits no empty or *-bearing WHERE. own-firmware-oracle
    ``ownd-audit-frames``: ``*#1*##`` is refused on 11 emulated gateways and
    crashes the MH202 010024 ("nack, crash ... empty WHERE in a WHO 1 status
    request"); ``*#1*12*1##`` goes out as a DIMENSION 1 read."""
    with pytest.raises(ValueError, match="where must be a non-empty address without"):
        build(where)


@pytest.mark.parametrize("where", [True, False, None, 12.5, b"12", ["12"], "12##", "1 2", "1\t2"])
@pytest.mark.parametrize(
    "build",
    [
        lambda w: OWNLightingCommand.status(w),
        lambda w: OWNLightingCommand.switch_on(w),
        lambda w: OWNLightingCommand.switch_off(w, 5),
        lambda w: OWNLightingCommand.get_brightness(w),
        lambda w: OWNLightingCommand.set_brightness(w, 50),
        lambda w: OWNLightingCommand.flash(w),
    ],
)
def test_who1_builders_reject_bool_none_and_malformed_where(where: object, build) -> None:
    """``issubclass(bool, int)`` lets ``status(True)`` through a ``str | int`` check and
    ``str(None)`` is a string: on 62014a9 they built ``*#1*True##`` and ``*#1*None##``
    (``is_valid`` False), ``"12##"`` built ``*#1*12####``. All raise now."""
    with pytest.raises(ValueError, match="where must be a non-empty address without"):
        build(where)


def test_who1_builders_strip_and_accept_int_where() -> None:
    assert str(OWNLightingCommand.status(" 12 ")) == "*#1*12##"
    assert str(OWNLightingCommand.status(12)) == "*#1*12##"
    assert str(OWNLightingCommand.status("0311#4#01")) == "*#1*0311#4#01##"
    assert str(OWNLightingCommand.status("#25")) == "*#1*#25##"
    assert str(OWNLightingCommand.status("0")) == "*#1*0##"
    assert OWNLightingCommand.status("12").human_readable_log == "Requesting light or switch 12 status."


# --- WHO 17 -------------------------------------------------------------------------


@pytest.mark.parametrize("where", ["", " ", "*", "1*2", None, True, False, 1.5, "5##", "1 2"])
def test_scene_builders_reject_empty_where(where: object) -> None:
    """start('') built *17*1*## with the log "Requesting global scene status";
    status(None) emitted *#17##, which is not on the page and is NACKed with a
    silent bus on all 12 emulated gateways (own-firmware-oracle
    ``scenario-who17``; *#17*0## likewise)."""
    for build in (
        OWNSceneCommand.start,
        OWNSceneCommand.stop,
        OWNSceneCommand.enable,
        OWNSceneCommand.disable,
        OWNSceneCommand.status,
    ):
        with pytest.raises(ValueError, match="where must be a non-empty address without"):
            build(where)  # type: ignore[arg-type]


def test_scene_start_true_no_longer_builds_the_global_status_log() -> None:
    """On 62014a9 ``start(True)`` built ``*17*1*True##`` and logged "Requesting
    global scene status", the fallback the WHERE guard is meant to end."""
    with pytest.raises(ValueError):
        OWNSceneCommand.start(True)  # type: ignore[arg-type]
    with pytest.raises(ValueError):
        OWNSceneCommand.status(False)  # type: ignore[arg-type]


def test_scene_builders_documented_forms() -> None:
    assert str(OWNSceneCommand.start(" 5 ")) == "*17*1*5##"
    assert str(OWNSceneCommand.status()) == "*#17*0##"
    assert str(OWNSceneCommand.status(0)) == "*#17*0##"
    assert str(OWNSceneCommand.status("12")) == "*#17*12##"
    bare = OWNSceneCommand("*#17##")
    assert bare.human_readable_log == "Requesting global scene status."


# --- WHO 14 -------------------------------------------------------------------------


def test_who14_status_request_is_parsed_but_undocumented_and_not_built() -> None:
    """who-14-special-commands/README.md "Scope of the semantics": only the two
    lock / unlock command frames exist; no status request in any source."""
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
    """who-1-lighting/addressing.md "Address scopes" publishes the interface as
    01..09 or 11..15. The builders refuse 11..15 on bt_luci evidence (the flex
    DFA accepts #4#0[1-9] only); the parser keeps them."""
    evt = OWNActuatorLockEvent(f"*14*0*12#4#{interface}##")
    assert evt.interface == str(interface)
    assert evt.is_locked is True
    with pytest.raises(ValueError, match="between 1 and 9"):
        OWNActuatorLockCommand.lock("12", interface=interface)
    assert "11..15" in (actuator_lock.__doc__ or "")
