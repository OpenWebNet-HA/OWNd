"""WHO 6 and WHO 8: Door entry, lock, and video intercom events and commands."""

from __future__ import annotations

from .base import OWNCommand, OWNEvent, register_command_parser, register_event_parser

# Call kinds
KIND_PE1 = 1
KIND_PE2 = 2
KIND_PE3 = 3
KIND_PE4 = 4
KIND_AUTOSWITCH = 5
KIND_INTERNAL_INTERCOM = 6
KIND_EXTERNAL_INTERCOM = 7
KIND_FLOOR = 13
KIND_PAGER = 14

# Multimedia types
MMTYPE_AUDIO = 2
MMTYPE_VIDEO = 3
MMTYPE_AUDIO_VIDEO = 4

# Special values
END_ALL_CALLS = 4
BROADCAST_WHERE = "4"

# PTZ opcodes and actions
PTZ_MOVE_UP = 59
PTZ_MOVE_DOWN = 60
PTZ_MOVE_LEFT = 61
PTZ_MOVE_RIGHT = 62

PTZ_ACTION_PRESS = 1
PTZ_ACTION_RELEASE = 2

# Message types for WHO 8
MESSAGE_TYPE_LOCK = "door_lock"
MESSAGE_TYPE_STAIRCASE_LIGHT = "staircase_light"
MESSAGE_TYPE_CAMERA = "camera"
MESSAGE_TYPE_PTZ = "ptz"
MESSAGE_TYPE_CALL = "intercom_call"
MESSAGE_TYPE_SESSION = "session"
MESSAGE_TYPE_AMPLIFIER_MUTE = "amplifier_mute"
MESSAGE_TYPE_TELELOOP = "teleloop"
MESSAGE_TYPE_VCT_INIT = "vct_init"

_PTZ_DIRECTIONS: dict[str, int] = {
    "up": PTZ_MOVE_UP,
    "down": PTZ_MOVE_DOWN,
    "left": PTZ_MOVE_LEFT,
    "right": PTZ_MOVE_RIGHT,
}
_PTZ_OPCODE_NAMES: dict[int, str] = {v: k for k, v in _PTZ_DIRECTIONS.items()}


class OWNDoorEntryEvent(OWNEvent):
    """Event reported by a WHO 6 door entry system or lock."""

    def __init__(self, data: str) -> None:
        super().__init__(data)

        self._where = self._where or ""
        self._is_incoming_call = self._what == 6
        self._is_broadcast_call = self._what == 6 and self._where == "4100"
        self._is_chime = self._what == 20
        self._is_call = self._is_incoming_call or self._is_chime
        self._is_lock_open = self._what in (10, 22)
        self._is_staircase_on = self._what == 12
        self._is_staircase_off = self._what == 11
        self._is_camera_on = self._what == 0
        self._is_camera_off = self._what == 9

        if self._is_broadcast_call:
            self._human_readable_log = "Incoming door entry broadcast call."
        elif self._is_incoming_call:
            self._human_readable_log = (
                f"Incoming door entry call to handset {self._where}."
            )
        elif self._is_chime:
            self._human_readable_log = f"Door entry chime active at {self._where}."
        elif self._what == 10:
            self._human_readable_log = (
                f"Door lock released at entrance panel {self._where}."
            )
        elif self._what == 22:
            self._human_readable_log = (
                f"Door lock released during conversation with entrance panel {self._where}."
            )
        elif self._is_staircase_on:
            self._human_readable_log = (
                f"Staircase light switched ON from door entry at {self._where}."
            )
        elif self._is_staircase_off:
            self._human_readable_log = (
                f"Staircase light switched OFF from door entry at {self._where}."
            )
        elif self._is_camera_on:
            self._human_readable_log = (
                f"Door entry camera switched ON at {self._where}."
            )
        elif self._is_camera_off:
            self._human_readable_log = "Door entry camera switched OFF."
        elif self._what is not None:
            self._human_readable_log = (
                f"Door entry device {self._where} received event: {self._what}."
            )

    @property
    def is_call(self) -> bool:
        """True if the event represents an incoming call or active chime."""
        return self._is_call

    @property
    def is_incoming_call(self) -> bool:
        """True if an incoming call frame (*6*6*WHERE##) was received."""
        return self._is_incoming_call

    @property
    def is_broadcast_call(self) -> bool:
        """True if a broadcast call frame (*6*6*4100##) was received."""
        return self._is_broadcast_call

    @property
    def is_chime(self) -> bool:
        """True if a chime event (*6*20*WHERE##) was received.

        WHAT 20 is not in the published WHO 6 table (WHAT 0, 6, 9, 10, 11, 12,
        18, 22) and no capture of it exists in this repository, so treat it as
        unverified.
        """
        return self._is_chime

    @property
    def is_lock_open(self) -> bool:
        """True if a door lock open event (*6*10*WHERE## or *6*22*WHERE##) was received."""
        return self._is_lock_open

    @property
    def is_staircase_on(self) -> bool:
        """True if a staircase light ON event (*6*12*WHERE##) was received."""
        return self._is_staircase_on

    @property
    def is_staircase_off(self) -> bool:
        """True if a staircase light OFF event (*6*11*WHERE##) was received."""
        return self._is_staircase_off

    @property
    def is_camera_on(self) -> bool:
        """True if a camera ON event (*6*0*WHERE##) was received."""
        return self._is_camera_on

    @property
    def is_camera_off(self) -> bool:
        """True if a camera OFF event (*6*9##) was received."""
        return self._is_camera_off


class OWNDoorEntryCommand(OWNCommand):
    """WHO 6 commands for door locks, staircase lighting, and cameras."""

    @classmethod
    def open_lock(cls, where: str | int = 0) -> OWNDoorEntryCommand:
        """Open / release door lock at the specified entrance panel address."""
        ep = str(where).strip()
        message = cls(f"*6*10*{ep}##")
        message._human_readable_log = (
            f"Opening door lock at entrance panel {ep}."
        )
        return message

    @classmethod
    def staircase_light_on(cls, where: str | int = 0) -> OWNDoorEntryCommand:
        """Switch ON the staircase light from the door entry system."""
        ep = str(where).strip()
        message = cls(f"*6*12*{ep}##")
        message._human_readable_log = (
            f"Switching ON staircase light from door entry at {ep}."
        )
        return message

    @classmethod
    def staircase_light_off(cls, where: str | int = 0) -> OWNDoorEntryCommand:
        """Switch OFF the staircase light from the door entry system."""
        ep = str(where).strip()
        message = cls(f"*6*11*{ep}##")
        message._human_readable_log = (
            f"Switching OFF staircase light from door entry at {ep}."
        )
        return message

    @classmethod
    def camera_on(cls, where: str | int) -> OWNDoorEntryCommand:
        """Switch ON video door entry camera at entrance panel."""
        ep = str(where).strip()
        message = cls(f"*6*0*{ep}##")
        message._human_readable_log = (
            f"Switching ON camera at entrance panel {ep}."
        )
        return message

    @classmethod
    def camera_off(cls, where: str | int | None = None) -> OWNDoorEntryCommand:
        """Switch OFF video door entry camera."""
        del where
        message = cls("*6*9##")
        message._human_readable_log = "Switching OFF video door entry camera."
        return message


class OWNIntercomEvent(OWNEvent):
    """Event reported by a WHO 8 video door entry / lock actuator or intercom device."""

    def __init__(self, data: str) -> None:
        super().__init__(data)

        self._where = self._where or ""
        what = self._what
        params = self._what_param

        self._type: str | None = None
        self._is_unlocked: bool = what == 19
        self._is_locked: bool = what == 20
        self._is_lock_open: bool | None = (
            True if what == 19 else (False if what == 20 else None)
        )
        self._is_staircase_on: bool = what == 21
        self._is_staircase_off: bool = what == 22
        self._is_light_on: bool | None = (
            True if what == 21 else (False if what == 22 else None)
        )
        # WHAT 1 is any call session; the kind (first WHAT parameter) tells a
        # door-panel ring (1..4) from an internal handset call (6) or a pager (14).
        self._is_call: bool = what == 1
        self._is_incoming_call: bool = False
        self._is_internal_call: bool = False
        self._is_muted: bool | None = (
            True if what == 63 else (False if what == 64 else None)
        )
        self._call_kind: int | None = None
        self._multimedia_type: int | None = None
        self._caller: str | None = None
        self._callee: str | None = None
        self._is_pager: bool = False
        self._camera: str | None = None
        self._is_cycle: bool = False
        self._ptz_direction: str | None = None
        self._ptz_action: str | None = None
        self._session_action: str | None = None
        self._teleloop_mode: int | None = None
        self._vct_mode: int | None = None

        if what is None:
            return

        if what in (19, 20):
            self._type = MESSAGE_TYPE_LOCK
            action = "unlocked / open" if self._is_unlocked else "locked / released"
            self._human_readable_log = f"Lock actuator {self._where} {action}."
        elif what in (21, 22):
            self._type = MESSAGE_TYPE_STAIRCASE_LIGHT
            action = "switched ON" if self._is_staircase_on else "switched OFF"
            self._human_readable_log = f"Staircase light {self._where} is {action}."
        elif what in (63, 64):
            self._type = MESSAGE_TYPE_AMPLIFIER_MUTE
            action = "silenced (muted)" if self._is_muted else "restored (unmuted)"
            self._human_readable_log = f"Multimedia amplifier {self._where} is {action}."
        elif what == 4:
            self._type = MESSAGE_TYPE_CAMERA
            self._caller = params[0] if params else None
            self._camera = self._where
            self._human_readable_log = (
                f"Camera {self._camera} switched ON by caller {self._caller}."
                if self._caller
                else f"Camera {self._camera} switched ON."
            )
        elif what == 6:
            self._type = MESSAGE_TYPE_CAMERA
            self._is_cycle = True
            self._caller = params[0] if params else None
            self._camera = self._where
            self._human_readable_log = (
                f"External camera cycling triggered by caller {self._caller} (target {self._camera})."
                if self._caller
                else f"External camera cycling triggered (target {self._camera})."
            )
        elif what in (59, 60, 61, 62):
            self._type = MESSAGE_TYPE_PTZ
            self._camera = self._where
            self._ptz_direction = _PTZ_OPCODE_NAMES.get(what)
            action_code = (
                int(params[0]) if params and params[0].isdigit() else PTZ_ACTION_PRESS
            )
            self._ptz_action = "press" if action_code == PTZ_ACTION_PRESS else "release"
            self._human_readable_log = (
                f"Camera {self._camera} PTZ move {self._ptz_direction} ({self._ptz_action})."
            )
        elif what == 1:
            self._type = MESSAGE_TYPE_CALL
            if len(params) >= 2:
                self._call_kind = int(params[0]) if params[0].isdigit() else None
                self._multimedia_type = int(params[1]) if params[1].isdigit() else None
                if len(params) >= 3:
                    self._caller = params[2]
            self._callee = self._where
            self._is_pager = (
                self._call_kind == KIND_PAGER or self._callee == BROADCAST_WHERE
            )
            self._is_incoming_call = self._call_kind in (
                KIND_PE1,
                KIND_PE2,
                KIND_PE3,
                KIND_PE4,
            )
            self._is_internal_call = (
                self._call_kind == KIND_INTERNAL_INTERCOM and not self._is_pager
            )
            desc = "Pager broadcast" if self._is_pager else "Intercom call"
            if self._caller:
                self._human_readable_log = (
                    f"{desc} from {self._caller} to {self._callee} "
                    f"(kind {self._call_kind}, mm {self._multimedia_type})."
                )
            else:
                self._human_readable_log = (
                    f"{desc} to {self._callee} (kind {self._call_kind}, mm {self._multimedia_type})."
                )
        elif what == 2:
            self._type = MESSAGE_TYPE_SESSION
            self._session_action = "answer"
            if len(params) >= 2:
                self._call_kind = int(params[0]) if params[0].isdigit() else None
                self._multimedia_type = int(params[1]) if params[1].isdigit() else None
            self._human_readable_log = f"Call answered on {self._where}."
        elif what == 3:
            self._type = MESSAGE_TYPE_SESSION
            if len(params) >= 2 and params[1] == "3":
                self._session_action = "stop_video"
                self._human_readable_log = f"Video stopped on {self._where}."
            else:
                self._session_action = "end"
                self._human_readable_log = f"Call ended on {self._where}."
            if len(params) >= 2:
                self._call_kind = int(params[0]) if params[0].isdigit() else None
                self._multimedia_type = int(params[1]) if params[1].isdigit() else None
        elif what == 9:
            self._type = MESSAGE_TYPE_SESSION
            self._session_action = "caller_notification"
            self._caller = self._where
            if len(params) >= 2:
                self._call_kind = int(params[0]) if params[0].isdigit() else None
                self._multimedia_type = int(params[1]) if params[1].isdigit() else None
            self._human_readable_log = f"Caller notification: {self._caller}."
        elif what == 37:
            self._type = MESSAGE_TYPE_VCT_INIT
            if params and params[0].isdigit():
                self._vct_mode = int(params[0])
            self._human_readable_log = (
                f"VCT initialized on {self._where} (mode {self._vct_mode})."
            )
        elif what == 40:
            self._type = MESSAGE_TYPE_SESSION
            self._session_action = "rearm"
            self._caller = self._where
            self._human_readable_log = f"Session rearmed for {self._caller}."
        elif what in (76, 77, 78, 79):
            self._type = MESSAGE_TYPE_TELELOOP
            if what == 76:
                self._session_action = "teleloop_start"
            elif what == 77:
                self._session_action = "teleloop_association"
                if params and params[0].isdigit():
                    self._teleloop_mode = int(params[0])
            elif what == 78:
                self._session_action = "teleloop_timeout"
            else:
                self._session_action = "teleloop_active"
            self._human_readable_log = (
                f"Teleloop event {self._session_action} on {self._where}."
            )
        else:
            self._human_readable_log = (
                f"Lock actuator {self._where} received event: {what}."
            )

    @property
    def message_type(self) -> str | None:
        """Subsystem message type category."""
        return self._type

    @property
    def is_unlocked(self) -> bool:
        """True if lock actuator is unlocked (*8*19*WHERE##)."""
        return self._is_unlocked

    @property
    def is_locked(self) -> bool:
        """True if lock actuator is locked (*8*20*WHERE##)."""
        return self._is_locked

    @property
    def is_lock_open(self) -> bool | None:
        """True if lock is open, False if locked, None for non-lock frames."""
        return self._is_lock_open

    @property
    def is_call(self) -> bool:
        """True for any call session start (*8*1#...), doorbell or not.

        Use ``is_incoming_call`` to react to an entrance panel ringing.
        """
        return self._is_call

    @property
    def is_incoming_call(self) -> bool:
        """True if an entrance panel (PE1..PE4, call kind 1..4) is calling.

        Internal handset calls (kind 6) and pager broadcasts (kind 14) are not
        doorbell rings; see ``is_internal_call`` and ``is_pager``.
        """
        return self._is_incoming_call

    @property
    def is_internal_call(self) -> bool:
        """True if the call is between two handsets (call kind 6)."""
        return self._is_internal_call

    @property
    def is_staircase_on(self) -> bool:
        """True if staircase light is ON (*8*21*WHERE##)."""
        return self._is_staircase_on

    @property
    def is_staircase_off(self) -> bool:
        """True if staircase light is OFF (*8*22*WHERE##)."""
        return self._is_staircase_off

    @property
    def is_light_on(self) -> bool | None:
        """True if staircase light is ON, False if OFF, None if not lighting."""
        return self._is_light_on

    @property
    def is_muted(self) -> bool | None:
        """True if amplifier is muted, False if restored, None if not mute frame."""
        return self._is_muted

    @property
    def call_kind(self) -> int | None:
        """Intercom call kind (KIND_PE1..PE4, KIND_INTERNAL_INTERCOM, etc.)."""
        return self._call_kind

    @property
    def multimedia_type(self) -> int | None:
        """Call multimedia type (MMTYPE_AUDIO, MMTYPE_VIDEO, MMTYPE_AUDIO_VIDEO)."""
        return self._multimedia_type

    @property
    def caller(self) -> str | None:
        """Calling unit address."""
        return self._caller

    @property
    def callee(self) -> str | None:
        """Target handset or device address."""
        return self._callee

    @property
    def is_pager(self) -> bool:
        """True if call is a pager / broadcast call."""
        return self._is_pager

    @property
    def camera(self) -> str | None:
        """Target camera address."""
        return self._camera

    @property
    def is_cycle(self) -> bool:
        """True if camera cycling was triggered."""
        return self._is_cycle

    @property
    def ptz_direction(self) -> str | None:
        """PTZ movement direction ('up', 'down', 'left', 'right')."""
        return self._ptz_direction

    @property
    def ptz_action(self) -> str | None:
        """PTZ action ('press', 'release')."""
        return self._ptz_action

    @property
    def session_action(self) -> str | None:
        """Session control action ('answer', 'end', 'stop_video', 'caller_notification', etc.)."""
        return self._session_action

    @property
    def teleloop_mode(self) -> int | None:
        """Teleloop mode parameter."""
        return self._teleloop_mode

    @property
    def vct_mode(self) -> int | None:
        """VCT process mode parameter."""
        return self._vct_mode


class OWNIntercomCommand(OWNCommand):
    """WHO 8 commands for video door entry, intercoms, and lock actuators."""

    def __init__(self, data: str) -> None:
        super().__init__(data)
        if self._message_type == "STATUS_REQUEST":
            self._human_readable_log = (
                f"Requesting intercom status for {self._where}."
            )

    @classmethod
    def unlock(cls, where: str | int) -> OWNIntercomCommand:
        """Activate / unlock door lock actuator at address WHERE."""
        target = str(where).strip()
        message = cls(f"*8*19*{target}##")
        message._human_readable_log = (
            f"Unlocking lock actuator at address {target}."
        )
        return message

    @classmethod
    def lock(cls, where: str | int) -> OWNIntercomCommand:
        """Release / lock door lock actuator at address WHERE."""
        target = str(where).strip()
        message = cls(f"*8*20*{target}##")
        message._human_readable_log = (
            f"Releasing lock actuator at address {target}."
        )
        return message

    @classmethod
    def open_door_lock(cls, where: str | int) -> OWNIntercomCommand:
        """Activate/open door lock actuator."""
        return cls.unlock(where)

    @classmethod
    def release_door_lock(cls, where: str | int) -> OWNIntercomCommand:
        """Release/close door lock actuator."""
        return cls.lock(where)

    @classmethod
    def staircase_light_on(cls, where: str | int) -> OWNIntercomCommand:
        """Turn ON staircase light actuator."""
        target = str(where).strip()
        message = cls(f"*8*21*{target}##")
        message._human_readable_log = f"Turning ON staircase light {target}."
        return message

    @classmethod
    def staircase_light_off(cls, where: str | int) -> OWNIntercomCommand:
        """Turn OFF staircase light actuator."""
        target = str(where).strip()
        message = cls(f"*8*22*{target}##")
        message._human_readable_log = f"Turning OFF staircase light {target}."
        return message

    @classmethod
    def turn_on_staircase_light(cls, where: str | int) -> OWNIntercomCommand:
        return cls.staircase_light_on(where)

    @classmethod
    def turn_off_staircase_light(cls, where: str | int) -> OWNIntercomCommand:
        return cls.staircase_light_off(where)

    @classmethod
    def switch_camera(cls, caller: str | int, camera: str | int) -> OWNIntercomCommand:
        """Auto-switch / turn on a camera from a caller console."""
        caller_str = str(caller).strip()
        cam_str = str(camera).strip()
        message = cls(f"*8*4#{caller_str}*{cam_str}##")
        message._human_readable_log = (
            f"Auto-switching camera {cam_str} from console {caller_str}."
        )
        return message

    @classmethod
    def cycle_camera(
        cls, caller: str | int, master_caller: str | int
    ) -> OWNIntercomCommand:
        """Cycle to the next external unit / camera."""
        caller_str = str(caller).strip()
        master_str = str(master_caller).strip()
        message = cls(f"*8*6#{caller_str}*{master_str}##")
        message._human_readable_log = (
            f"Cycling camera from console {caller_str} (master {master_str})."
        )
        return message

    @classmethod
    def ptz_move(
        cls, camera: str | int, direction: str, action: str = "press"
    ) -> OWNIntercomCommand:
        """Send PTZ movement press or release to a camera."""
        direction_lower = direction.strip().lower()
        if direction_lower not in _PTZ_DIRECTIONS:
            raise ValueError(
                f"direction must be one of {list(_PTZ_DIRECTIONS.keys())}, got '{direction}'"
            )
        opcode = _PTZ_DIRECTIONS[direction_lower]
        action_lower = action.strip().lower()
        if action_lower not in ("press", "release"):
            raise ValueError("action must be 'press' or 'release'")
        action_code = (
            PTZ_ACTION_PRESS if action_lower == "press" else PTZ_ACTION_RELEASE
        )
        cam_str = str(camera).strip()
        message = cls(f"*8*{opcode}#{action_code}*{cam_str}##")
        message._human_readable_log = (
            f"PTZ move {direction_lower} ({action_lower}) on camera {cam_str}."
        )
        return message

    @classmethod
    def call_internal(
        cls, caller: str | int, callee: str | int, video: bool = False
    ) -> OWNIntercomCommand:
        """Initiate internal intercom call."""
        mm = MMTYPE_AUDIO_VIDEO if video else MMTYPE_AUDIO
        caller_str = str(caller).strip()
        callee_str = str(callee).strip()
        message = cls(
            f"*8*1#{KIND_INTERNAL_INTERCOM}#{mm}#{caller_str}*{callee_str}##"
        )
        message._human_readable_log = (
            f"Initiating internal {'audio/video' if video else 'audio'} call "
            f"from {caller_str} to {callee_str}."
        )
        return message

    @classmethod
    def call_external(
        cls, caller: str | int, callee: str | int, video: bool = False
    ) -> OWNIntercomCommand:
        """Initiate external intercom call."""
        mm = MMTYPE_AUDIO_VIDEO if video else MMTYPE_AUDIO
        caller_str = str(caller).strip()
        callee_str = str(callee).strip()
        message = cls(
            f"*8*1#{KIND_EXTERNAL_INTERCOM}#{mm}#{caller_str}*{callee_str}##"
        )
        message._human_readable_log = (
            f"Initiating external {'audio/video' if video else 'audio'} call "
            f"from {caller_str} to {callee_str}."
        )
        return message

    @classmethod
    def call_pager(
        cls, caller: str | int, broadcast_where: str | int = BROADCAST_WHERE
    ) -> OWNIntercomCommand:
        """Initiate pager broadcast call."""
        caller_str = str(caller).strip()
        bc_str = str(broadcast_where).strip()
        message = cls(f"*8*1#{KIND_PAGER}#{MMTYPE_AUDIO}#{caller_str}*{bc_str}##")
        message._human_readable_log = (
            f"Initiating pager broadcast from {caller_str} to {bc_str}."
        )
        return message

    @classmethod
    def answer_call(
        cls,
        where: str | int,
        kind: int = KIND_INTERNAL_INTERCOM,
        mm_type: int = MMTYPE_AUDIO,
    ) -> OWNIntercomCommand:
        """Answer an incoming call."""
        target = str(where).strip()
        message = cls(f"*8*2#{kind}#{mm_type}*{target}##")
        message._human_readable_log = f"Answering call on {target}."
        return message

    @classmethod
    def end_call(
        cls,
        where: str | int = END_ALL_CALLS,
        kind: int = KIND_INTERNAL_INTERCOM,
        mm_type: int = MMTYPE_AUDIO,
    ) -> OWNIntercomCommand:
        """Terminate call session."""
        target = str(where).strip()
        message = cls(f"*8*3#{kind}#{mm_type}*{target}##")
        message._human_readable_log = f"Ending call session on {target}."
        return message

    @classmethod
    def stop_video(
        cls, where: str | int, kind: int = KIND_INTERNAL_INTERCOM
    ) -> OWNIntercomCommand:
        """Stop video stream for active call."""
        target = str(where).strip()
        message = cls(f"*8*3#{kind}#3*{target}##")
        message._human_readable_log = f"Stopping video feed on {target}."
        return message

    @classmethod
    def mute_amplifier(cls, where: str | int) -> OWNIntercomCommand:
        """Silence multimedia amplifier."""
        target = str(where).strip()
        message = cls(f"*8*63*{target}##")
        message._human_readable_log = (
            f"Silencing multimedia amplifier {target}."
        )
        return message

    @classmethod
    def unmute_amplifier(cls, where: str | int) -> OWNIntercomCommand:
        """Restore multimedia amplifier audio."""
        target = str(where).strip()
        message = cls(f"*8*64*{target}##")
        message._human_readable_log = (
            f"Restoring multimedia amplifier {target}."
        )
        return message

    @classmethod
    def status(cls, where: str | int) -> OWNIntercomCommand:
        """Request device/intercom status."""
        target = str(where).strip()
        message = cls(f"*#8*{target}##")
        message._human_readable_log = f"Requesting intercom status for {target}."
        return message


# Backwards-compatible names: WHO 8 is mostly call routing, locks are one part.
OWNLockEvent = OWNIntercomEvent
OWNLockCommand = OWNIntercomCommand

register_event_parser(6, OWNDoorEntryEvent)
register_command_parser(6, OWNDoorEntryCommand)
register_event_parser(8, OWNIntercomEvent)
register_command_parser(8, OWNIntercomCommand)
