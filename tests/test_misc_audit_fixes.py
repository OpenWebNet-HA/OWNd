"""Report 21 fixes for WHO 25 (T1..T4), WHO 6 (E1), WHO 8 (I1..I3) and WHO 5 (A1..A5).

Evidence: Encyclopedia ``functional/who-25-transversal/{dry-contact-ir,cen-plus}.md``,
``who-6-basic-video-door-entry/README.md``, ``who-8-video-door-entry-telephony/README.md``,
``who-5-alarm/{protocol,what,addressing}.md``; oracle rows as recorded in
``work/review-session/audit_ency/ORACLE_CONFIRM.md`` (T1, E1-door, I1, I3, A1).
"""

from __future__ import annotations

import pytest

from OWNd.message import (
    END_ALL_CALLS,
    END_CALL_PREFIX,
    KIND_PE1,
    MMTYPE_AUDIO,
    MMTYPE_AUDIO_VIDEO,
    MMTYPE_STOP_VIDEO,
    MMTYPE_VIDEO,
    OWNAlarmCommand,
    OWNAlarmEvent,
    OWNCENPlusEvent,
    OWNCommand,
    OWNDoorEntryCommand,
    OWNDoorEntryEvent,
    OWNDryContactCommand,
    OWNDryContactEvent,
    OWNEvent,
    OWNIntercomCommand,
    OWNIntercomEvent,
    OWNMessage,
)

# ── T1: dry contact 3 prefix ─────────────────────────────────────────────────


@pytest.mark.parametrize(
    ("frame", "where", "sensor"),
    [
        ("*25*31#1*339##", "339", "39"),  # golden dry_contact.event.on.339
        ("*25*31#1*35##", "35", "5"),  # oracle: *#25*35## polls sensor 05
        ("*25*31#1*39##", "39", "9"),  # oracle: *#25*39## polls sensor 09
        ("*25*32#1*33##", "33", "3"),  # MH200 capture probe (dry-contact-ir.md)
        ("*25*31#0*3100##", "3100", "100"),
    ],
)
def test_t1_parser_strips_the_prefix_the_firmware_reads(frame: str, where: str, sensor: str) -> None:
    event = OWNMessage.parse(frame)
    assert isinstance(event, OWNDryContactEvent)
    assert event.where == where
    assert event.sensor == sensor


def test_t1_status_sends_the_bus_where_verbatim() -> None:
    """MyHOME polls with the configured bus WHERE (33, 339 in the captures)."""
    assert str(OWNDryContactCommand.status("339")) == "*#25*339##"
    assert str(OWNDryContactCommand.status("33")) == "*#25*33##"
    assert str(OWNDryContactCommand.status(21)) == "*#25*21##"


@pytest.mark.parametrize(
    ("sensor", "frame"),
    [
        (39, "*#25*339##"),  # oracle: sensor 39
        ("39", "*#25*339##"),
        (5, "*#25*35##"),  # oracle: sensor 05; *#25*5## is refused 12/12
        (9, "*#25*39##"),
        (100, "*#25*3100##"),
    ],
)
def test_t1_status_for_sensor_is_the_inverse_of_sensor(sensor: int | str, frame: str) -> None:
    command = OWNDryContactCommand.status_for_sensor(sensor)
    assert str(command) == frame
    assert command.human_readable_log == f"Requesting dry contact sensor {sensor} status (WHERE 3{sensor})."
    # Round trip through the parser's reading of the same WHERE.
    event = OWNDryContactEvent(f"*25*31#0*{frame[5:-2]}##")
    assert event.sensor == str(sensor)


@pytest.mark.parametrize("bad", ["", " ", "3#9", "a1", "*"])
def test_t1_status_for_sensor_rejects_non_numbers(bad: str) -> None:
    with pytest.raises(ValueError, match="dry contact sensor must be a number"):
        OWNDryContactCommand.status_for_sensor(bad)


def test_t1_status_request_round_trips_through_the_command_parser() -> None:
    parsed = OWNCommand.parse("*#25*339##")
    assert isinstance(parsed, OWNDryContactCommand)
    assert parsed.where == "339"


# ── T4: parameter-less dry contact and bare CEN+ WHERE 2 ────────────────────


@pytest.mark.parametrize(
    ("frame", "is_on", "has_parameter", "detection", "state_reply", "log"),
    [
        ("*25*31#1*339##", True, True, True, False, "Sensor 39 detected ON."),
        ("*25*32#1*339##", False, True, True, False, "Sensor 39 detected OFF."),
        ("*25*31#0*339##", True, True, False, True, "Sensor 39 reported ON."),
        ("*25*32#0*33##", False, True, False, True, "Sensor 3 reported OFF."),
        (
            # is_detection keeps the historical True for the missing parameter
            # (MyHOME pins it); has_detection_parameter tells it apart.
            "*25*31*33##",
            True,
            False,
            True,
            False,
            "Sensor 3 sent ON without the WHAT parameter (not a published WHO 25 form: dry-contact-ir.md#what).",
        ),
    ],
)
def test_t4_dry_contact_parameter_is_required_for_a_detection(
    frame: str, is_on: bool, has_parameter: bool, detection: bool, state_reply: bool, log: str
) -> None:
    event = OWNDryContactEvent(frame)
    assert event.is_on is is_on
    assert event.has_detection_parameter is has_parameter
    assert event.is_detection is detection
    assert event.is_state_reply is state_reply
    assert event.human_readable_log == log


def test_t4_cen_plus_bare_where_2_has_no_object() -> None:
    event = OWNMessage.parse("*25*21#1*2##")
    assert isinstance(event, OWNCENPlusEvent)
    assert event.object is None
    assert event.push_button == 1
    assert event.human_readable_log == (
        "CEN+ WHAT 21 on bare WHERE 2 carries no Object (WHERE is 2 + OBJECT: cen-plus.md#where---virtual-object)."
    )


@pytest.mark.parametrize(
    ("frame", "obj"),
    [("*25*21#1*21##", "1"), ("*25*21#1*20##", "0"), ("*25*22#2*22047##", "2047"), ("*25*21#1*5##", "5")],
)
def test_t4_cen_plus_object_forms_still_decode(frame: str, obj: str) -> None:
    event = OWNCENPlusEvent(frame)
    assert event.object == obj


# ── T2: CEN+ pushbutton range ────────────────────────────────────────────────


@pytest.mark.parametrize(
    ("frame", "button"),
    [
        ("*25*21#0*21##", 0),  # 0 is a real button
        ("*25*21#31*21##", 31),
        ("*25*21#32*21##", None),
        ("*25*21#40*21##", None),
        ("*25*21#-1*21##", None),
        ("*25*21#x*21##", None),
        ("*25*21*21##", None),
    ],
)
def test_t2_pushbutton_outside_0_31_is_none(frame: str, button: int | None) -> None:
    event = OWNCENPlusEvent(frame)
    assert event.valid_push_button == button
    # push_button keeps the historical 0 fallback (MyHOME pins it).
    assert event.push_button == (0 if button is None else button)
    if button is None:
        assert "outside the published 0..31" in event.human_readable_log
    else:
        assert event.human_readable_log == f"Button {button} of CEN+ object 1 has been pressed"


def test_t2_out_of_range_log_names_the_parameter() -> None:
    assert OWNCENPlusEvent("*25*21#40*21##").human_readable_log == (
        "CEN+ object 1 sent WHAT 21 with pushbutton 40 (outside the published 0..31: cen-plus.md#pushbutton-parameter)."
    )
    assert OWNCENPlusEvent("*25*24*21##").human_readable_log == (
        "CEN+ object 1 sent WHAT 24 with pushbutton missing (outside the published 0..31: cen-plus.md#pushbutton-parameter)."
    )


# ── T3: no rotary builder ────────────────────────────────────────────────────


def test_t3_rotary_whats_are_events_only() -> None:
    from OWNd.message import OWNCenPlusCommand

    builders = {m for m in dir(OWNCenPlusCommand) if not m.startswith("_")} - set(dir(OWNCommand))
    assert builders == {"press", "start_long_press", "still_held", "release"}
    event = OWNMessage.parse("*25*26#3*21##")
    assert isinstance(event, OWNCENPlusEvent)
    assert event.is_quickly_turned_cw is True


# ── E1: WHO 6 builders need a WHERE; WHAT 18 ─────────────────────────────────


@pytest.mark.parametrize(
    ("builder", "frame"),
    [
        (OWNDoorEntryCommand.open_lock, "*6*10*4001##"),
        (OWNDoorEntryCommand.staircase_light_on, "*6*12*4001##"),
        (OWNDoorEntryCommand.staircase_light_off, "*6*11*4001##"),
        (OWNDoorEntryCommand.camera_on, "*6*0*4001##"),
        (OWNDoorEntryCommand.camera_cycle, "*6*18*4001##"),
    ],
)
def test_e1_who6_builders_require_an_explicit_where(builder, frame: str) -> None:  # type: ignore[no-untyped-def]
    assert str(builder(4001)) == frame
    assert str(builder("4001#2")) == frame.replace("4001", "4001#2")
    with pytest.raises(TypeError):
        builder()  # no where=0 default: *6*10*0## is nack/silent on 12/12
    for empty in ("", "  ", "40*01"):
        with pytest.raises(ValueError, match="where must be a non-empty address"):
            builder(empty)


def test_e1_camera_cycle_log_and_event() -> None:
    command = OWNDoorEntryCommand.camera_cycle("4001")
    assert command.human_readable_log == "Cycling camera at entrance panel 4001."
    event = OWNMessage.parse("*6*18*4001##")
    assert isinstance(event, OWNDoorEntryEvent)
    assert event.is_camera_cycle is True
    assert event.is_camera_on is False
    assert event.human_readable_log == "Door entry camera cycling at entrance panel 4001."
    assert OWNDoorEntryEvent("*6*0*4001##").is_camera_cycle is False


# ── I1: end call 4LOCAL ──────────────────────────────────────────────────────


def test_i1_end_call_concatenates_the_literal_4() -> None:
    assert str(OWNIntercomCommand.end_call("11")) == "*8*3#6#2*411##"
    assert str(OWNIntercomCommand.end_call(20, kind=KIND_PE1, mm_type=MMTYPE_AUDIO_VIDEO)) == "*8*3#1#4*420##"
    assert OWNIntercomCommand.end_call("11").human_readable_log == "Ending call session of 11."
    assert END_CALL_PREFIX == "4"
    assert END_ALL_CALLS == END_CALL_PREFIX
    with pytest.raises(TypeError):
        OWNIntercomCommand.end_call()  # type: ignore[call-arg]
    with pytest.raises(ValueError, match="where must be a non-empty address"):
        OWNIntercomCommand.end_call("")


def test_i1_end_call_frame_parses_as_an_end_session() -> None:
    event = OWNIntercomEvent("*8*3#6#2*411##")
    assert event.session_action == "end"
    assert event.where == "411"


# ── I2: constants and WHAT 6 / 40 / 77 ───────────────────────────────────────


def test_i2_multimedia_type_constants() -> None:
    assert MMTYPE_AUDIO == 2
    assert MMTYPE_AUDIO_VIDEO == 4
    assert MMTYPE_VIDEO == 4  # deprecated alias; 3 is not a media type
    assert MMTYPE_STOP_VIDEO == 3
    assert str(OWNIntercomCommand.stop_video("11")) == "*8*3#6#3*11##"
    assert str(OWNIntercomCommand.call_internal("11", "16", video=True)) == "*8*1#6#4#11*16##"


def test_i2_cycle_event_where_is_the_original_caller() -> None:
    event = OWNMessage.parse("*8*6#11*21##")
    assert isinstance(event, OWNIntercomEvent)
    assert event.is_cycle is True
    assert event.caller == "11"
    assert event.original_caller == "21"
    assert event.camera is None
    assert event.human_readable_log == "External unit cycling requested by 11 for the call from 21."
    assert str(OWNIntercomCommand.cycle_camera("11", "21")) == "*8*6#11*21##"
    # Autoswitch keeps camera as the WHERE and no original caller.
    autoswitch = OWNIntercomEvent("*8*4#11*20##")
    assert autoswitch.camera == "20"
    assert autoswitch.original_caller is None


def test_i2_rearm_carries_kind_and_multimedia_type() -> None:
    event = OWNMessage.parse("*8*40#1#4*21##")
    assert isinstance(event, OWNIntercomEvent)
    assert event.session_action == "rearm"
    assert event.caller == "21"
    assert event.call_kind == 1
    assert event.multimedia_type == MMTYPE_AUDIO_VIDEO
    assert event.human_readable_log == "Session rearmed for 21 (kind 1, mm 4)."
    odd = OWNIntercomEvent("*8*40#x#y*21##")
    assert odd.call_kind is None
    assert odd.multimedia_type is None


def test_i2_teleloop_association_id() -> None:
    event = OWNIntercomEvent("*8*77#5*11##")
    assert event.teleloop_id == 5
    assert event.teleloop_mode == 5  # deprecated alias
    assert OWNIntercomEvent("*8*77*11##").teleloop_id is None


# ── I3: undocumented builders stay, marked ───────────────────────────────────


@pytest.mark.parametrize(
    ("method", "frame"),
    [("mute_amplifier", "*8*63*11##"), ("unmute_amplifier", "*8*64*11##"), ("status", "*#8*11##")],
)
def test_i3_undocumented_who8_builders_keep_their_frames(method: str, frame: str) -> None:
    assert str(getattr(OWNIntercomCommand, method)("11")) == frame


# ── A1: documented controls only ─────────────────────────────────────────────


def test_a1_arm_and_set_zones_build_the_documented_frames() -> None:
    arm = OWNAlarmCommand.arm("12345")
    assert str(arm) == "*5*36#12345*0##"
    assert "12345" not in arm.human_readable_log
    assert arm.human_readable_log == "Toggling burglar alarm armed state on 0 (password redacted)."
    assert str(OWNAlarmCommand.arm(1234, where="1")) == "*5*36#1234*1##"

    zones = OWNAlarmCommand.set_zones("12345", "11000001")
    assert str(zones) == "*5*50#12345#11000001*0##"
    assert "12345" not in zones.human_readable_log
    assert str(OWNAlarmCommand.set_zones("12345", {1, 2, 8})) == "*5*50#12345#11000001*0##"
    assert str(OWNAlarmCommand.set_zones("12345", [8, 2, 1])) == "*5*50#12345#11000001*0##"
    assert str(OWNAlarmCommand.set_zones("12345", ())) == "*5*50#12345#00000000*0##"
    assert str(OWNAlarmCommand.set_zones("12345", " 00000000 ")) == "*5*50#12345#00000000*0##"
    assert isinstance(OWNCommand.parse("*5*36#12345*0##"), OWNAlarmCommand)
    assert isinstance(OWNCommand.parse("*5*50#12345#11000001*0##"), OWNAlarmCommand)


@pytest.mark.parametrize("password", ["", "  ", "12*45", "12#45"])
def test_a1_password_is_validated(password: str) -> None:
    with pytest.raises(ValueError, match="alarm password"):
        OWNAlarmCommand.arm(password)
    with pytest.raises(ValueError, match="alarm password"):
        OWNAlarmCommand.set_zones(password, "11000001")


@pytest.mark.parametrize("mask", ["1100000", "110000011", "1100000x", "", {0}, {9}, [1, 2, 10]])
def test_a1_mask_is_validated(mask: str | set[int] | list[int]) -> None:
    with pytest.raises(ValueError, match="alarm zone"):
        OWNAlarmCommand.set_zones("12345", mask)


def test_a1_where_is_validated() -> None:
    with pytest.raises(ValueError, match="where must be a non-empty address"):
        OWNAlarmCommand.arm("12345", where="")
    with pytest.raises(ValueError, match="where must be a non-empty address"):
        OWNAlarmCommand.set_zones("12345", "11000001", where="")


@pytest.mark.parametrize(
    ("method", "what", "role"),
    [
        ("disarm", 2, "state/event"),
        ("arm_away", 1, "central-unit state"),
        ("arm_home", 1, "central-unit state"),
        ("trigger", 17, "alarm event"),
        ("panic", 17, "alarm event"),
        ("engage", 8, "system state"),
        ("disengage", 9, "system state"),
    ],
)
def test_a1_state_whats_are_not_built_as_controls(method: str, what: int, role: str) -> None:
    builder = getattr(OWNAlarmCommand, method)
    with pytest.raises(NotImplementedError) as info:
        builder()
    text = str(info.value)
    assert f"WHO 5 WHAT {what} is a {role}" in text
    assert "functional/who-5-alarm/what.md" in text
    assert "protocol.md#write-support" in text
    assert f"*5*{what}*0## is refused on 9 of the 12 emulated gateways" in text
    assert "OWNAlarmCommand.arm(password)" in text
    with pytest.raises(NotImplementedError):
        builder("1")


# ── A2 / A3: zone_number is an int for both forms, #9 is the auxiliary ───────
# ``zone`` keeps the str form of the #Z selector: MyHOME pins it
# (tests/test_issue_466_mh200_trace.py, precedent gate).


@pytest.mark.parametrize(
    ("frame", "zone", "zone_number", "sensor", "auxiliary", "log"),
    [
        ("*5*15*#2##", "2", 2, None, False, "Zone 2 is reporting: 'intrusion alarm'."),
        ("*5*15*21##", 2, 2, 1, False, "Sensor 1 in zone 2 is reporting: 'intrusion alarm'."),
        ("*5*11*#0##", "0", 0, None, False, "Zone 0 is reporting: 'active zone'."),
        ("*5*18*#8##", "8", 8, None, False, "Zone 8 is reporting: 'non-active zone'."),
        ("*5*17*#9##", "9", 9, None, True, "Auxiliary 9 (anti-panic) is reporting: 'anti-panic alarm'."),
        ("*5*12*#12##", "c", None, None, False, "Zone c is reporting: 'technical alarm'."),
        ("*5*12*#15##", "f", None, None, False, "Zone f is reporting: 'technical alarm'."),
        ("*5*1*01##", 0, 0, 1, False, "Device 1 in input zone is reporting: 'activation'."),
    ],
)
def test_a2_a3_zone_forms(
    frame: str,
    zone: int | str | None,
    zone_number: int | None,
    sensor: int | None,
    auxiliary: bool,
    log: str,
) -> None:
    event = OWNEvent.parse(frame)
    assert isinstance(event, OWNAlarmEvent)
    assert event.zone == zone
    assert type(event.zone) is type(zone)
    assert event.zone_number == zone_number
    assert event.sensor == sensor
    assert event.is_auxiliary is auxiliary
    assert event.general is False
    assert event.human_readable_log == log


def test_a2_zone_number_equality_across_forms() -> None:
    assert OWNAlarmEvent("*5*15*#2##").zone_number == OWNAlarmEvent("*5*15*21##").zone_number == 2


# ── A4: WHAT 0 and 11 semantics ──────────────────────────────────────────────


@pytest.mark.parametrize(
    ("frame", "active", "disarmed", "maintenance", "zone_active"),
    [
        ("*5*1*0##", True, False, False, False),
        ("*5*1*##", True, False, False, False),
        ("*5*0*0##", False, False, True, False),
        ("*5*0*##", False, False, True, False),
        ("*5*2*0##", False, True, False, False),
        ("*5*9*0##", False, True, False, False),
        ("*5*11*0##", False, False, False, False),  # zone state on the panel address
        ("*5*11*#1##", False, False, False, True),
        ("*5*0*#1##", False, False, False, False),
        ("*5*1*#1##", False, False, False, False),
    ],
)
def test_a4_central_unit_states(frame: str, active: bool, disarmed: bool, maintenance: bool, zone_active: bool) -> None:
    event = OWNAlarmEvent(frame)
    assert event.is_active is active
    assert event.is_disarmed is disarmed
    assert event.is_maintenance is maintenance
    assert event.is_zone_active is zone_active


# ── A5: golden labels ────────────────────────────────────────────────────────


def test_a5_golden_alarm_labels_follow_the_page() -> None:
    import json
    from pathlib import Path

    corpus = json.loads((Path(__file__).parent / "golden" / "corpus.json").read_text(encoding="utf-8"))
    by_id = {record["id"]: record for record in corpus}
    assert "alarm.event.silent.zone0" not in by_id
    disactivation = by_id["alarm.event.disactivation.central"]
    assert disactivation["frame"] == "*5*2*0##"
    assert "Disactivation" in disactivation["mcp_notes"]
    assert "Silent alarm event" not in disactivation["mcp_notes"].split("The earlier label")[0]
    activation = by_id["alarm.event.arm_total.mh202"]
    assert activation["frame"] == "*5*1*0##"
    assert "Not an arm" in activation["mcp_notes"]
    zone2 = by_id["alarm.req.status.zone2"]
    assert zone2["frame"] == "*#5*2##"
    assert "*#5*#2##" in zone2["mcp_notes"]
    parsed = OWNMessage.parse("*5*2*0##")
    assert isinstance(parsed, OWNAlarmEvent)
    assert parsed.state_name == "deactivation"
    assert parsed.is_silent is False
    assert OWNAlarmEvent("*5*31*0##").is_silent is True
