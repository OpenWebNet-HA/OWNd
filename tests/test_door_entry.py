"""Tests for WHO 6 and WHO 8 door entry and lock messages."""

from __future__ import annotations

import pytest

from OWNd.message import (
    BROADCAST_WHERE,
    END_ALL_CALLS,
    KIND_EXTERNAL_INTERCOM,
    KIND_INTERNAL_INTERCOM,
    KIND_PAGER,
    KIND_PE1,
    MESSAGE_TYPE_AMPLIFIER_MUTE,
    MESSAGE_TYPE_CALL,
    MESSAGE_TYPE_CAMERA,
    MESSAGE_TYPE_LOCK,
    MESSAGE_TYPE_PTZ,
    MESSAGE_TYPE_SESSION,
    MESSAGE_TYPE_STAIRCASE_LIGHT,
    MESSAGE_TYPE_TELELOOP,
    MESSAGE_TYPE_VCT_INIT,
    MMTYPE_AUDIO,
    MMTYPE_AUDIO_VIDEO,
    OWNCommand,
    OWNDoorEntryCommand,
    OWNDoorEntryEvent,
    OWNIntercomCommand,
    OWNIntercomEvent,
    OWNLockCommand,
    OWNLockEvent,
    OWNMessage,
)


def test_door_entry_event_incoming_call() -> None:
    event = OWNDoorEntryEvent("*6*6*1##")
    assert event.is_incoming_call is True
    assert event.is_call is True
    assert event.is_broadcast_call is False
    assert event.where == "1"
    assert event.human_readable_log == "Incoming door entry call to handset 1."


def test_door_entry_event_broadcast_call() -> None:
    event = OWNDoorEntryEvent("*6*6*4100##")
    assert event.is_incoming_call is True
    assert event.is_call is True
    assert event.is_broadcast_call is True
    assert event.where == "4100"
    assert event.human_readable_log == "Incoming door entry broadcast call."


def test_door_entry_event_chime() -> None:
    event = OWNDoorEntryEvent("*6*20*1##")
    assert event.is_chime is True
    assert event.is_call is True
    assert event.is_incoming_call is False
    assert event.where == "1"
    assert event.human_readable_log == "Door entry chime active at 1."


def test_door_entry_event_lock_open() -> None:
    event1 = OWNDoorEntryEvent("*6*10*4001##")
    assert event1.is_lock_open is True
    assert event1.is_call is False
    assert event1.human_readable_log == "Door lock released at entrance panel 4001."

    event2 = OWNDoorEntryEvent("*6*22*4001##")
    assert event2.is_lock_open is True
    assert (
        event2.human_readable_log
        == "Door lock released during conversation with entrance panel 4001."
    )


def test_door_entry_event_staircase() -> None:
    on_event = OWNDoorEntryEvent("*6*12*1##")
    assert on_event.is_staircase_on is True
    assert on_event.is_staircase_off is False
    assert (
        on_event.human_readable_log
        == "Staircase light switched ON from door entry at 1."
    )

    off_event = OWNDoorEntryEvent("*6*11*1##")
    assert off_event.is_staircase_on is False
    assert off_event.is_staircase_off is True
    assert (
        off_event.human_readable_log
        == "Staircase light switched OFF from door entry at 1."
    )


def test_door_entry_event_camera() -> None:
    cam_on = OWNDoorEntryEvent("*6*0*4001##")
    assert cam_on.is_camera_on is True
    assert cam_on.is_camera_off is False
    assert cam_on.human_readable_log == "Door entry camera switched ON at 4001."

    # All three camera OFF frame forms (standard, double-star, and single-star trailing delimiters)
    for raw, expected_where in (("*6*9##", ""), ("*6*9**##", "*"), ("*6*9*##", "")):
        cam_off = OWNDoorEntryEvent(raw)
        assert cam_off.is_camera_off is True
        assert cam_off.is_camera_on is False
        assert cam_off.where == expected_where
        assert cam_off.human_readable_log == "Door entry camera switched OFF."

        parsed = OWNMessage.parse(raw)
        assert isinstance(parsed, OWNDoorEntryEvent)
        assert parsed.is_camera_off is True
        assert parsed.where == expected_where


def test_door_entry_commands() -> None:
    cmd_lock = OWNDoorEntryCommand.open_lock(4001)
    assert str(cmd_lock) == "*6*10*4001##"
    assert (
        cmd_lock.human_readable_log == "Opening door lock at entrance panel 4001."
    )

    cmd_riser = OWNDoorEntryCommand.open_lock("4001#2")
    assert str(cmd_riser) == "*6*10*4001#2##"

    cmd_light_on = OWNDoorEntryCommand.staircase_light_on(1)
    assert str(cmd_light_on) == "*6*12*1##"

    cmd_light_off = OWNDoorEntryCommand.staircase_light_off(1)
    assert str(cmd_light_off) == "*6*11*1##"

    cmd_cam_on = OWNDoorEntryCommand.camera_on(4001)
    assert str(cmd_cam_on) == "*6*0*4001##"

    cmd_cam_off = OWNDoorEntryCommand.camera_off()
    assert str(cmd_cam_off) == "*6*9##"

    cmd_cam_off_star = OWNDoorEntryCommand.camera_off("*")
    assert str(cmd_cam_off_star) == "*6*9##"


def test_door_entry_event_fallback() -> None:
    event = OWNDoorEntryEvent("*6*99*1##")
    assert event.human_readable_log == "Door entry device 1 received event: 99."

    event_none = OWNDoorEntryEvent("*#6*1##")
    assert event_none.human_readable_log == "*#6*1##"


def test_lock_actuator_event_and_command() -> None:
    evt_unlock = OWNLockEvent("*8*19*20##")
    assert evt_unlock.is_unlocked is True
    assert evt_unlock.is_locked is False
    assert evt_unlock.is_lock_open is True
    assert evt_unlock.message_type == MESSAGE_TYPE_LOCK
    assert evt_unlock.human_readable_log == "Lock actuator 20 unlocked / open."

    evt_lock = OWNLockEvent("*8*20*20##")
    assert evt_lock.is_locked is True
    assert evt_lock.is_unlocked is False
    assert evt_lock.is_lock_open is False
    assert evt_lock.human_readable_log == "Lock actuator 20 locked / released."

    evt_fallback = OWNLockEvent("*8*99*20##")
    assert evt_fallback.human_readable_log == "Lock actuator 20 received event: 99."

    evt_none = OWNLockEvent("*#8*20##")
    assert evt_none.human_readable_log == "*#8*20##"

    cmd_unlock = OWNLockCommand.unlock(20)
    assert str(cmd_unlock) == "*8*19*20##"
    assert str(OWNLockCommand.open_door_lock(20)) == "*8*19*20##"

    cmd_lock = OWNLockCommand.lock(20)
    assert str(cmd_lock) == "*8*20*20##"
    assert str(OWNLockCommand.release_door_lock(20)) == "*8*20*20##"


def test_who8_staircase_light_events_and_commands() -> None:
    ev_on = OWNLockEvent("*8*21*11##")
    assert ev_on.message_type == MESSAGE_TYPE_STAIRCASE_LIGHT
    assert ev_on.is_staircase_on is True
    assert ev_on.is_staircase_off is False
    assert ev_on.is_light_on is True
    assert ev_on.human_readable_log == "Staircase light 11 is switched ON."

    ev_off = OWNLockEvent("*8*22*0##")
    assert ev_off.message_type == MESSAGE_TYPE_STAIRCASE_LIGHT
    assert ev_off.is_staircase_on is False
    assert ev_off.is_staircase_off is True
    assert ev_off.is_light_on is False
    assert ev_off.human_readable_log == "Staircase light 0 is switched OFF."

    cmd_on = OWNLockCommand.turn_on_staircase_light("11")
    assert str(cmd_on) == "*8*21*11##"
    assert str(OWNLockCommand.staircase_light_on("11")) == "*8*21*11##"

    cmd_off = OWNLockCommand.turn_off_staircase_light("0")
    assert str(cmd_off) == "*8*22*0##"
    assert str(OWNLockCommand.staircase_light_off("0")) == "*8*22*0##"


def test_who8_camera_auto_switch_cycling_and_ptz() -> None:
    ev_cam = OWNLockEvent("*8*4#11*20##")
    assert ev_cam.message_type == MESSAGE_TYPE_CAMERA
    assert ev_cam.caller == "11"
    assert ev_cam.camera == "20"
    assert "Camera 20 switched ON by caller 11." in ev_cam.human_readable_log

    ev_cam_nocaller = OWNLockEvent("*8*4*20##")
    assert ev_cam_nocaller.caller is None
    assert ev_cam_nocaller.human_readable_log == "Camera 20 switched ON."

    ev_cycle = OWNLockEvent("*8*6#11*20##")
    assert ev_cycle.message_type == MESSAGE_TYPE_CAMERA
    assert ev_cycle.is_cycle is True
    assert "cycling triggered by caller 11" in ev_cycle.human_readable_log

    ev_cycle_nocaller = OWNLockEvent("*8*6*20##")
    assert ev_cycle_nocaller.caller is None
    assert "cycling triggered (target 20)" in ev_cycle_nocaller.human_readable_log

    ev_ptz_up = OWNLockEvent("*8*59#1*20##")
    assert ev_ptz_up.message_type == MESSAGE_TYPE_PTZ
    assert ev_ptz_up.ptz_direction == "up"
    assert ev_ptz_up.ptz_action == "press"

    ev_ptz_down = OWNLockEvent("*8*60#2*20##")
    assert ev_ptz_down.ptz_direction == "down"
    assert ev_ptz_down.ptz_action == "release"

    ev_ptz_left = OWNLockEvent("*8*61#1*20##")
    assert ev_ptz_left.ptz_direction == "left"
    assert ev_ptz_left.ptz_action == "press"

    ev_ptz_right = OWNLockEvent("*8*62#2*20##")
    assert ev_ptz_right.ptz_direction == "right"
    assert ev_ptz_right.ptz_action == "release"

    cmd_cam = OWNLockCommand.switch_camera(11, 20)
    assert str(cmd_cam) == "*8*4#11*20##"

    cmd_cycle = OWNLockCommand.cycle_camera(11, 20)
    assert str(cmd_cycle) == "*8*6#11*20##"

    cmd_up = OWNLockCommand.ptz_move(20, "up", "press")
    assert str(cmd_up) == "*8*59#1*20##"
    cmd_down = OWNLockCommand.ptz_move(20, "down", "release")
    assert str(cmd_down) == "*8*60#2*20##"
    cmd_left = OWNLockCommand.ptz_move(20, "left", "press")
    assert str(cmd_left) == "*8*61#1*20##"
    cmd_right = OWNLockCommand.ptz_move(20, "right", "release")
    assert str(cmd_right) == "*8*62#2*20##"

    with pytest.raises(ValueError, match="direction must be one of"):
        OWNLockCommand.ptz_move(20, "diagonal", "press")
    with pytest.raises(ValueError, match="action must be"):
        OWNLockCommand.ptz_move(20, "up", "hold")


def test_who8_intercom_calling_and_session() -> None:
    # Real trace from MH200 (#667): *8*1#1#4*74## (PE1, Audio/Video to handset 74)
    ev_mh200_call = OWNLockEvent("*8*1#1#4*74##")
    assert ev_mh200_call.message_type == MESSAGE_TYPE_CALL
    assert ev_mh200_call.is_call is True
    assert ev_mh200_call.is_incoming_call is True
    assert ev_mh200_call.call_kind == KIND_PE1
    assert ev_mh200_call.multimedia_type == MMTYPE_AUDIO_VIDEO
    assert ev_mh200_call.caller is None
    assert ev_mh200_call.callee == "74"
    assert ev_mh200_call.human_readable_log == "Intercom call to 74 (kind 1, mm 4)."

    # Bare call without params: *8*1*74##
    ev_bare_call = OWNLockEvent("*8*1*74##")
    assert ev_bare_call.message_type == MESSAGE_TYPE_CALL
    assert ev_bare_call.is_call is True
    assert ev_bare_call.call_kind is None
    assert ev_bare_call.is_incoming_call is False
    assert ev_bare_call.callee == "74"

    # Internal audio call: *8*1#6#2#11*16## (caller 11, callee 16, kind 6, mm 2)
    ev_call = OWNLockEvent("*8*1#6#2#11*16##")
    assert ev_call.message_type == MESSAGE_TYPE_CALL
    assert ev_call.is_call is True
    # An internal handset call is not a doorbell ring.
    assert ev_call.is_incoming_call is False
    assert ev_call.is_internal_call is True
    assert ev_call.call_kind == KIND_INTERNAL_INTERCOM
    assert ev_call.multimedia_type == MMTYPE_AUDIO
    assert ev_call.caller == "11"
    assert ev_call.callee == "16"
    assert ev_call.is_pager is False
    assert "Intercom call from 11 to 16" in ev_call.human_readable_log

    # Pager call: *8*1#14#2#11*4##
    ev_pager = OWNLockEvent("*8*1#14#2#11*4##")
    assert ev_pager.is_pager is True
    assert ev_pager.is_call is True
    assert ev_pager.is_incoming_call is False
    assert ev_pager.is_internal_call is False
    assert "Pager broadcast from 11 to 4" in ev_pager.human_readable_log

    # Answer call: *8*2#6#2*11##
    ev_ans = OWNLockEvent("*8*2#6#2*11##")
    assert ev_ans.message_type == MESSAGE_TYPE_SESSION
    assert ev_ans.session_action == "answer"
    assert ev_ans.call_kind == KIND_INTERNAL_INTERCOM
    assert ev_ans.multimedia_type == MMTYPE_AUDIO
    assert ev_ans.human_readable_log == "Call answered on 11."

    # Answer without params
    ev_ans_noparams = OWNLockEvent("*8*2*11##")
    assert ev_ans_noparams.session_action == "answer"

    # End call: *8*3#6#2*411##
    ev_end = OWNLockEvent("*8*3#6#2*411##")
    assert ev_end.message_type == MESSAGE_TYPE_SESSION
    assert ev_end.session_action == "end"
    assert ev_end.human_readable_log == "Call ended on 411."

    # End without params
    ev_end_noparams = OWNLockEvent("*8*3*11##")
    assert ev_end_noparams.session_action == "end"

    # Stop video: *8*3#1#3*11##
    ev_stop_vid = OWNLockEvent("*8*3#1#3*11##")
    assert ev_stop_vid.session_action == "stop_video"
    assert ev_stop_vid.human_readable_log == "Video stopped on 11."

    # Real trace from MH200 (#667): *8*9#1#4*73## (caller notification from PE 73)
    ev_notif = OWNLockEvent("*8*9#1#4*73##")
    assert ev_notif.message_type == MESSAGE_TYPE_SESSION
    assert ev_notif.session_action == "caller_notification"
    assert ev_notif.caller == "73"
    assert ev_notif.call_kind == KIND_PE1
    assert ev_notif.multimedia_type == MMTYPE_AUDIO_VIDEO
    assert ev_notif.human_readable_log == "Caller notification: 73."

    # Caller notification without params
    ev_notif_noparams = OWNLockEvent("*8*9*11##")
    assert ev_notif_noparams.session_action == "caller_notification"

    # Session rearm: *8*40*11##
    ev_rearm = OWNLockEvent("*8*40*11##")
    assert ev_rearm.session_action == "rearm"
    assert ev_rearm.caller == "11"
    assert ev_rearm.human_readable_log == "Session rearmed for 11."

    # Builders
    cmd_int_audio = OWNLockCommand.call_internal("11", "16", video=False)
    assert str(cmd_int_audio) == "*8*1#6#2#11*16##"

    cmd_int_video = OWNLockCommand.call_internal("11", "16", video=True)
    assert str(cmd_int_video) == "*8*1#6#4#11*16##"

    cmd_ext_audio = OWNLockCommand.call_external("11", "16", video=False)
    assert str(cmd_ext_audio) == "*8*1#7#2#11*16##"

    cmd_ext_video = OWNLockCommand.call_external("11", "16", video=True)
    assert str(cmd_ext_video) == "*8*1#7#4#11*16##"

    cmd_pager = OWNLockCommand.call_pager("11", BROADCAST_WHERE)
    assert str(cmd_pager) == "*8*1#14#2#11*4##"

    cmd_ans = OWNLockCommand.answer_call(
        "11", kind=KIND_INTERNAL_INTERCOM, mm_type=MMTYPE_AUDIO
    )
    assert str(cmd_ans) == "*8*2#6#2*11##"

    cmd_end = OWNLockCommand.end_call(
        "411", kind=KIND_INTERNAL_INTERCOM, mm_type=MMTYPE_AUDIO
    )
    assert str(cmd_end) == "*8*3#6#2*411##"
    assert str(OWNLockCommand.end_call()) == f"*8*3#6#2*{END_ALL_CALLS}##"

    cmd_stop_vid = OWNLockCommand.stop_video("11", kind=KIND_PE1)
    assert str(cmd_stop_vid) == "*8*3#1#3*11##"


def test_who8_amplifier_mute_teleloop_and_vct() -> None:
    # Mute: *8*63*11##
    ev_mute = OWNLockEvent("*8*63*11##")
    assert ev_mute.message_type == MESSAGE_TYPE_AMPLIFIER_MUTE
    assert ev_mute.is_muted is True
    assert "silenced (muted)" in ev_mute.human_readable_log

    # Unmute: *8*64*11##
    ev_unmute = OWNLockEvent("*8*64*11##")
    assert ev_unmute.is_muted is False
    assert "unmuted" in ev_unmute.human_readable_log

    # Teleloop start: *8*76*11##
    ev_tl0 = OWNLockEvent("*8*76*11##")
    assert ev_tl0.message_type == MESSAGE_TYPE_TELELOOP
    assert ev_tl0.session_action == "teleloop_start"

    # Teleloop assoc: *8*77#5*11##
    ev_tl1 = OWNLockEvent("*8*77#5*11##")
    assert ev_tl1.message_type == MESSAGE_TYPE_TELELOOP
    assert ev_tl1.session_action == "teleloop_association"
    assert ev_tl1.teleloop_mode == 5

    # Teleloop assoc without params
    ev_tl_noparam = OWNLockEvent("*8*77*11##")
    assert ev_tl_noparam.session_action == "teleloop_association"

    # Teleloop timeout: *8*78*11##
    ev_tl2 = OWNLockEvent("*8*78*11##")
    assert ev_tl2.message_type == MESSAGE_TYPE_TELELOOP
    assert ev_tl2.session_action == "teleloop_timeout"

    # Teleloop active: *8*79*11##
    ev_tl_active = OWNLockEvent("*8*79*11##")
    assert ev_tl_active.session_action == "teleloop_active"

    # VCT init: *8*37#1*11##
    ev_vct = OWNLockEvent("*8*37#1*11##")
    assert ev_vct.message_type == MESSAGE_TYPE_VCT_INIT
    assert ev_vct.vct_mode == 1

    # VCT without params
    ev_vct_noparam = OWNLockEvent("*8*37*11##")
    assert ev_vct_noparam.message_type == MESSAGE_TYPE_VCT_INIT

    # Builders
    cmd_mute = OWNLockCommand.mute_amplifier("11")
    assert str(cmd_mute) == "*8*63*11##"

    cmd_unmute = OWNLockCommand.unmute_amplifier("11")
    assert str(cmd_unmute) == "*8*64*11##"

    cmd_status = OWNLockCommand.status("11")
    assert str(cmd_status) == "*#8*11##"
    assert cmd_status.human_readable_log == "Requesting intercom status for 11."

    # *#8*WHERE*19## has no documented meaning; no builder is offered for it.
    assert not hasattr(OWNIntercomCommand, "lock_status")


def test_who8_primary_classes_and_lock_aliases() -> None:
    assert OWNLockEvent is OWNIntercomEvent
    assert OWNLockCommand is OWNIntercomCommand
    assert OWNIntercomEvent.__name__ == "OWNIntercomEvent"


@pytest.mark.parametrize("raw", ["*6*3##", "*6*42##", "*6*6##", "*6*10##", "*6*0*##"])
def test_who6_short_form_only_accepts_camera_off(raw: str) -> None:
    """Only WHAT 9 may omit WHERE; other short WHO 6 frames are not valid."""
    assert not isinstance(OWNMessage.parse(raw), OWNDoorEntryEvent)


def test_message_registry_parsing() -> None:
    msg6_lock = OWNMessage.parse("*6*10*4001##")
    assert isinstance(msg6_lock, OWNDoorEntryEvent)

    msg6_call = OWNMessage.parse("*6*6*1##")
    assert isinstance(msg6_call, OWNDoorEntryEvent)

    msg6_cam_off = OWNMessage.parse("*6*9##")
    assert isinstance(msg6_cam_off, OWNDoorEntryEvent)

    cmd6 = OWNCommand.parse("*6*10*4001##")
    assert isinstance(cmd6, OWNDoorEntryCommand)

    # WHO 8 registry parsing
    msg8_lock = OWNMessage.parse("*8*19*20##")
    assert isinstance(msg8_lock, OWNLockEvent)

    msg8_rel = OWNMessage.parse("*8*20*20##")
    assert isinstance(msg8_rel, OWNLockEvent)

    msg8_call = OWNMessage.parse("*8*1#1#4*74##")
    assert isinstance(msg8_call, OWNLockEvent)

    msg8_notif = OWNMessage.parse("*8*9#1#4*73##")
    assert isinstance(msg8_notif, OWNLockEvent)

    cmd8_unlock = OWNCommand.parse("*8*19*20##")
    assert isinstance(cmd8_unlock, OWNLockCommand)

    cmd8_lock = OWNCommand.parse("*8*20*20##")
    assert isinstance(cmd8_lock, OWNLockCommand)

    # Aliases
    assert OWNIntercomEvent is OWNLockEvent
    assert OWNIntercomCommand is OWNLockCommand
