"""WHO 16 Sound System and WHO 22 Sound Diffusion events and commands, plus the WHO 7 video stream commands.

WHO 16 is the earlier Sound System dialect (Encyclopedia
``who-16-sound-system``: amplifiers ``01..99``, sources ``101..109``, all
sources ``100``); WHO 22 is the later Sound Diffusion / Multimedia dialect
(``who-22-sound-diffusion``: tagged targets ``2#S``, ``3#A#P``, ``4#A``,
``5#...``, ``6``). They are separate dialects and are not translated by
numeric coincidence. ``OWNAVCommand`` opens and closes a WHO 7 video stream.
"""

from __future__ import annotations

import math
import re

from .base import (
    OWNCommand,
    OWNEvent,
    register_command_parser,
    register_event_parser,
    require_non_empty_where,
)


_require_non_empty_where = require_non_empty_where

# WHO 22 manual tuner step as published: 1..15, no leading zero, ASCII digits.
_WHO22_FREQUENCY_STEP_REGEX = re.compile(r"[1-9]|1[0-5]", re.ASCII)


def _validate_frequency_step(step: object) -> int:
    """Return ``step`` as an integer 1..15 (a WHO 16 / WHO 22 manual tuner step), else raise ``ValueError``."""
    if isinstance(step, bool) or not isinstance(step, (int, str)):
        raise ValueError(f"step must be between 1 and 15, got {step!r}")
    s = int(step)
    if not 1 <= s <= 15:
        raise ValueError(f"step must be between 1 and 15, got {step}")
    return s


# WHO 22 modulation (Encyclopedia who-22-sound-diffusion#core-parameters).
_WHO22_BAND_NAMES = {1: "FM", 2: "AM-LW", 3: "AM-MW", 4: "AM-SW"}


def _who22_frequency_khz(band: int | None, raw: int) -> int | None:
    """Return the kHz value of a WHO 22 dimension 5 / 11 `FREQUENCY` field, or ``None``.

    FM (modulation 1) is reported in 10 kHz units by an MH200N / F454 and in
    100 kHz units by a MyHomeServer1; the two FM ranges (8750..10800 and
    875..1080) do not overlap, so the value selects the unit, and a value in
    neither range is not a frequency. AM-LW / AM-MW / AM-SW (modulation 2 /
    3 / 4) are taken as kHz: an inference, the page publishes the bands but
    no AM unit. Any other modulation fails closed.
    """
    if band in (2, 3, 4):
        return raw if raw > 0 else None
    if band == 1:
        return next((v for v in (raw * 10, raw * 100) if 87500 <= v <= 108000), None)
    return None


def _is_who22_preset(preset: int) -> bool:
    """True for a published WHO 22 equalizer preset: 2..11 built in, 16..25 user defined."""
    return 2 <= preset <= 11 or 16 <= preset <= 25


def _who22_target_area(target: str) -> int | None:
    """Area of a WHO 22 target: `3#AREA#POINT`, `4#AREA` or `5#3#AREA#POINT`; ``None`` for a source / `6`."""
    parts = target.split("#")
    if parts[0] == "3" and len(parts) == 3 and parts[1].isdigit():
        return int(parts[1])
    if parts[0] == "4" and len(parts) == 2 and parts[1].isdigit():
        return int(parts[1])
    if parts[0] == "5" and len(parts) == 4 and parts[1] == "3" and parts[2].isdigit():
        return int(parts[2])
    return None


def _validate_area(area: object, where: str, target: str) -> int:
    """Return the area of a WHO 22 power / route frame: ``area`` if given, else the area of ``target``."""
    if area is None:
        derived = _who22_target_area(target)
        if derived is None:
            raise ValueError(f"area is required for target '{where}': it carries no area (give area=)")
        return derived
    if isinstance(area, bool) or not isinstance(area, (int, str)):
        raise ValueError(f"area must be between 0 and 9, got {area!r}")
    a = int(area)
    if not 0 <= a <= 9:
        raise ValueError(f"area must be between 0 and 9, got {area}")
    return a



class OWNSoundEvent(OWNEvent):
    """State reported by a WHO 16 sound source or amplifier zone."""

    def __init__(self, data: str) -> None:
        super().__init__(data)

        self._state = self._what
        self._zone = self._where or ""
        # WHERE 101..109 is source 1..9 and 100 every source (Encyclopedia
        # who-16-sound-system#where); `100` has no source number.
        self._is_all_sources = self._zone == "100"
        self._is_source_event = bool(re.fullmatch(r"10[0-9]", self._zone))
        self._source_id = (
            str(int(self._zone) - 100)
            if self._is_source_event and not self._is_all_sources
            else None
        )
        # `1ES` routes the amplifiers of environment E to matrix source S.
        # Environment 0 would be `10S`, the source itself, so E starts at 1.
        # S is kept as sent, `0` included: whatever it names, `1E0` is not
        # amplifier 1E0 either. A routing frame keeps its address as `zone`:
        # consumers parse routing from it, so only is_routing_event tells it
        # apart from an amplifier.
        self._is_routing_event = bool(re.fullmatch(r"1[1-9][0-9]", self._zone))
        self._environment = self._zone[1] if self._is_routing_event else None
        self._routed_source = self._zone[2] if self._is_routing_event else None
        self._volume: int | None = None
        self._volume_step_delta: int | None = None
        self._frequency_khz: int | None = None
        self._track: int | None = None
        self._rds_text: str | None = None
        self._is_source_busy: bool = False
        self._track_step_forward: int | None = None
        self._track_step_backward: int | None = None
        self._frequency_step_forward: int | None = None
        self._frequency_step_backward: int | None = None
        self._is_seek_up: bool = False
        self._is_seek_down: bool = False
        self._is_source_cycle: bool = False
        self._is_sleep: bool = False
        self._is_sleep_off: bool = False
        self._is_follow_me: bool = False
        self._is_rds_start: bool = False
        self._is_rds_stop: bool = False
        self._high_tone_step_delta: int | None = None

        if self._is_all_sources:
            subject = "All audio sources"
        elif self._is_source_event:
            subject = f"Audio Source {self._source_id}"
        elif self._is_routing_event:
            subject = (
                f"Routing of environment {self._environment} "
                f"to source {self._routed_source}"
            )
        else:
            subject = f"Audio Zone {self._zone}"
        if self._state in (0, 3):
            self._human_readable_log = f"{subject} is switched ON."
        elif self._state in (10, 13):
            self._human_readable_log = f"{subject} is switched OFF."
        elif self._state == 100:
            self._is_source_busy = True
            self._human_readable_log = f"{subject} is BUSY."
        elif self._state is not None and 1001 <= self._state <= 1015:
            self._volume_step_delta = self._state - 1000
            self._human_readable_log = (
                f"{subject} increase volume by {self._volume_step_delta} step(s)."
            )
        elif self._state is not None and 1101 <= self._state <= 1115:
            self._volume_step_delta = -(self._state - 1100)
            self._human_readable_log = (
                f"{subject} decrease volume by {abs(self._volume_step_delta)} step(s)."
            )
        elif self._state == 5000:
            self._is_seek_up = True
            self._human_readable_log = f"{subject} seek forward."
        elif self._state == 5100:
            self._is_seek_down = True
            self._human_readable_log = f"{subject} seek backward."
        elif self._state is not None and 6001 <= self._state <= 6015:
            self._track_step_forward = self._state - 6000
            self._human_readable_log = (
                f"{subject} advance track/station by {self._track_step_forward} step(s)."
            )
        elif self._state is not None and 6101 <= self._state <= 6115:
            self._track_step_backward = self._state - 6100
            self._human_readable_log = (
                f"{subject} return track/station by {self._track_step_backward} step(s)."
            )
        elif self._state is not None and 5001 <= self._state <= 5015:
            # Manual tuner steps (Encyclopedia ownkb:chunk:r000371,
            # ownkb:claim:c002096 / c002098): 5001..5015 up, 5101..5115 down;
            # 5000 / 5100 are the automatic seeks above.
            self._frequency_step_forward = self._state - 5000
            self._human_readable_log = (
                f"{subject} increase frequency by {self._frequency_step_forward} step(s)."
            )
        elif self._state is not None and 5101 <= self._state <= 5115:
            self._frequency_step_backward = self._state - 5100
            self._human_readable_log = (
                f"{subject} decrease frequency by {self._frequency_step_backward} step(s)."
            )
        # WHATs of the who-16-sound-system#what-values table that carry no
        # magnitude: 20 / 23 source cycle, 30 / 33 sleep, 40 sleep off,
        # 50 / 53 Follow Me, 101 / 102 RDS start / stop (base band / stereo
        # channel as ``is_stereo_channel``). `*16*20*100##` / `*16*23*100##`
        # cycle the sources on the plant of reverse-engineering
        # sound-matrix-routing.md (ENCY_CONFIRM SD-S4). The log keeps the
        # generic "received command: N" text these WHATs had before (MyHOME
        # tests/test_message.py pins it for `*16*30*22##`) and adds the name.
        elif self._state in (20, 23):
            self._is_source_cycle = True
            self._human_readable_log = (
                f"{subject} received command: {self._state} (cycle to the next source)."
            )
        elif self._state in (30, 33):
            self._is_sleep = True
            self._human_readable_log = f"{subject} received command: {self._state} (sleep ON)."
        elif self._state == 40:
            self._is_sleep_off = True
            self._human_readable_log = f"{subject} received command: {self._state} (sleep OFF)."
        elif self._state in (50, 53):
            self._is_follow_me = True
            self._human_readable_log = (
                f"{subject} received command: {self._state} (switched ON with Follow Me)."
            )
        elif self._state == 101:
            self._is_rds_start = True
            self._human_readable_log = (
                f"{subject} received command: {self._state} (start RDS transmission)."
            )
        elif self._state == 102:
            self._is_rds_stop = True
            self._human_readable_log = (
                f"{subject} received command: {self._state} (stop RDS transmission)."
            )
        elif self._state is not None and 2001 <= self._state <= 2015:
            self._high_tone_step_delta = self._state - 2000
            self._human_readable_log = (
                f"{subject} increase high tones by {self._high_tone_step_delta} step(s)."
            )
        elif self._state is not None and 2101 <= self._state <= 2115:
            self._high_tone_step_delta = -(self._state - 2100)
            self._human_readable_log = (
                f"{subject} decrease high tones by {abs(self._high_tone_step_delta)} step(s)."
            )
        elif self._state is not None:
            self._human_readable_log = f"{subject} received command: {self._state}."
        elif self._dimension == 1 and self._dimension_value:
            # Volume is 0..31 (who-16-sound-system#dimension-values); the
            # firmware oracle NACKs a write of 50 on 12/12 gateways and
            # forwards 31 (ORACLE_CONFIRM S1), so a report outside 0..31 is
            # not a volume.
            try:
                level = int(self._dimension_value[0])
            except ValueError:
                return
            if not 0 <= level <= 31:
                return
            self._volume = level
            self._human_readable_log = (
                f"Audio zone {self._zone} volume is set to {self._volume}."
            )
        elif self._dimension == 6 and self._dimension_value:
            try:
                self._frequency_khz = int(self._dimension_value[-1])
            except ValueError:
                return
            if self._frequency_khz <= 0:
                self._frequency_khz = None
                return
            self._human_readable_log = (
                f"{subject} frequency is {self._frequency_khz} kHz."
            )
        elif self._dimension == 7 and self._dimension_value:
            try:
                self._track = int(self._dimension_value[-1])
            except ValueError:
                return
            if self._track < 1:
                self._track = None
                return
            self._human_readable_log = (
                f"{subject} station/track is {self._track}."
            )
        elif self._dimension == 8 and self._dimension_value:
            # Dimension 8 carries the RDS PS (Program Service) name as exactly 8 decimal
            # ASCII character codes per the WHO 16 specification. Frames with other
            # lengths are ignored as malformed bus artifacts.
            if len(self._dimension_value) != 8:
                return
            chars = []
            for code in self._dimension_value:
                try:
                    val = int(code)
                    if 32 <= val <= 126:
                        chars.append(chr(val))
                except ValueError:
                    continue
            text = "".join(chars).strip()
            self._rds_text = text if text else None
            self._human_readable_log = (
                f"{subject} RDS text: '{self._rds_text or ''}'."
            )

    @property
    def is_on(self) -> bool:
        return self._state in (0, 3)

    @property
    def is_off(self) -> bool:
        return self._state in (10, 13)

    @property
    def is_source_event(self) -> bool:
        """True for a source address: ``101..109`` (source 1..9) or ``100`` (all sources)."""
        return self._is_source_event

    @property
    def is_all_sources(self) -> bool:
        """True for WHERE ``100``, every source (who-16-sound-system#where); ``source_id`` is ``None``."""
        return self._is_all_sources

    @property
    def source_id(self) -> str | None:
        return self._source_id

    @property
    def is_stereo_channel(self) -> bool | None:
        """``True`` for the stereo-channel WHATs 3 / 13 / 23 / 33 / 53, ``False`` for the base-band 0 / 10 / 20 / 30 / 50, else ``None``."""
        if self._state in (3, 13, 23, 33, 53):
            return True
        if self._state in (0, 10, 20, 30, 50):
            return False
        return None

    @property
    def is_source_cycle(self) -> bool:
        """True for WHAT 20 / 23, cycle to the next source (``*16*23*100##``)."""
        return self._is_source_cycle

    @property
    def is_sleep(self) -> bool:
        """True for WHAT 30 / 33, sleep on the base band / stereo channel."""
        return self._is_sleep

    @property
    def is_sleep_off(self) -> bool:
        """True for WHAT 40, sleep OFF."""
        return self._is_sleep_off

    @property
    def is_follow_me(self) -> bool:
        """True for WHAT 50 / 53, Follow Me on the base band / stereo channel."""
        return self._is_follow_me

    @property
    def is_rds_start(self) -> bool:
        """True for WHAT 101, start RDS transmission."""
        return self._is_rds_start

    @property
    def is_rds_stop(self) -> bool:
        """True for WHAT 102, stop RDS transmission."""
        return self._is_rds_stop

    @property
    def high_tone_step_delta(self) -> int | None:
        """Signed high-tone step (+1..+15 for WHAT 2001..2015, -1..-15 for WHAT 2101..2115)."""
        return self._high_tone_step_delta

    @property
    def is_routing_event(self) -> bool:
        """True for a `1ES` matrix routing frame."""
        return self._is_routing_event

    @property
    def environment(self) -> str | None:
        """Environment `E` of a `1ES` routing frame, otherwise None."""
        return self._environment

    @property
    def routed_source(self) -> str | None:
        """Matrix source `S` of a `1ES` routing frame, otherwise None."""
        return self._routed_source

    @property
    def zone(self) -> str:
        """The frame's address; a `1ES` routing address for routing frames."""
        return self._zone

    @property
    def volume(self) -> int | None:
        return self._volume

    @property
    def volume_step_delta(self) -> int | None:
        """Signed volume step delta (+1..+15 for WHAT 1001..1015, -1..-15 for WHAT 1101..1115)."""
        return self._volume_step_delta

    @property
    def frequency_khz(self) -> int | None:
        return self._frequency_khz

    @property
    def track(self) -> int | None:
        return self._track

    @property
    def rds_text(self) -> str | None:
        return self._rds_text

    @property
    def is_source_busy(self) -> bool:
        return self._is_source_busy

    @property
    def track_step_forward(self) -> int | None:
        return self._track_step_forward

    @property
    def track_step_backward(self) -> int | None:
        return self._track_step_backward

    @property
    def frequency_step_forward(self) -> int | None:
        """Steps of a WHAT 5001..5015 frequency increase (1..15), else ``None``."""
        return self._frequency_step_forward

    @property
    def frequency_step_backward(self) -> int | None:
        """Steps of a WHAT 5101..5115 frequency decrease (1..15), else ``None``."""
        return self._frequency_step_backward

    @property
    def is_seek_up(self) -> bool:
        return self._is_seek_up

    @property
    def is_seek_down(self) -> bool:
        return self._is_seek_down



class OWNAVCommand(OWNCommand):
    @classmethod
    def receive_video(cls, where: str | int) -> OWNAVCommand | None:
        camera_id: str | int = where
        where_str = str(where)
        try:
            val = int(where)
        except (ValueError, TypeError):
            return None
        if 0 <= val < 100:
            where_str = f"40{camera_id}"
        elif 4000 <= val < 5000:
            camera_id = where_str[2:]
        else:
            return None

        message = cls(f"*7*0*{where_str}##")
        message._human_readable_log = f"Opening video stream for camera {camera_id}."
        return message

    @classmethod
    def close_video(cls) -> OWNAVCommand:
        message = cls("*7*9**##")
        message._human_readable_log = "Closing video stream."
        return message



class OWNSoundCommand(OWNCommand):
    """WHO 16 commands for sound sources and amplifier zones."""

    @classmethod
    def status(cls, where: str | int) -> OWNSoundCommand:
        # WHO 16 status is dimension 5: gateways NACK the bare `*#16*WHERE##`.
        target = _require_non_empty_where(where)
        message = cls(f"*#16*{target}*5##")
        message._human_readable_log = f"Requesting sound system status of {target}."
        return message

    @classmethod
    def turn_on(cls, where: str | int) -> OWNSoundCommand:
        target = _require_non_empty_where(where)
        message = cls(f"*16*3*{target}##")
        message._human_readable_log = f"Turning on audio zone {target}."
        return message

    @classmethod
    def turn_off(cls, where: str | int) -> OWNSoundCommand:
        target = _require_non_empty_where(where)
        message = cls(f"*16*13*{target}##")
        message._human_readable_log = f"Turning off audio zone {target}."
        return message

    @classmethod
    def select_source(
        cls, where: str | int, source_id: int | str
    ) -> list[OWNSoundCommand]:
        """Build the frames routing an amplifier zone to a source.

        `where` is the two-digit amplifier address `EA`, where `E` (1–9) is
        the environment and `A` (0–9) the amplifier within it: the published
        amplifier range is `01..99` (who-16-sound-system#where,
        #amplifier-address-structure) and routing uses the environment digit
        only (#matrix-source-routing). Single-digit, environment 0 and
        non-numeric addresses cannot be routed to a matrix source and raise
        ValueError: environment 0 would spell `10S`, the source address itself.
        `*16*3*20##` is accepted by the six WHO 16-forwarding emulated
        gateways (ORACLE_CONFIRM S2), so amplifier `20` routes like `21..29`.

        Two frames are returned:

        * `*16*3*10S##` activates source `S` on the bus;
        * `*16*3*1ES##` routes environment `E` of the matrix to source `S`.

        For example, amplifier `23` (environment 2) on source 2 yields
        `*16*3*102##` followed by `*16*3*122##`.
        """
        source = int(source_id)
        if not 1 <= source <= 9:
            raise ValueError("source_id must be between 1 and 9")
        zone = str(where).strip()
        if not zone:
            raise ValueError("where must identify an audio zone")
        if not re.fullmatch(r"[1-9][0-9]", zone, re.ASCII):
            raise ValueError(
                f"where must be a two-digit amplifier address with environment 1-9 and amplifier 0-9, got '{where}'"
            )

        source_address = 100 + source
        activate = cls(f"*16*3*{source_address}##")
        activate._human_readable_log = f"Activating audio source {source}."

        route_address = f"1{zone[0]}{source}"
        route = cls(f"*16*3*{route_address}##")
        route._human_readable_log = (
            f"Routing audio zone {where} to source {source}."
        )
        return [activate, route]

    @classmethod
    def source_cycle(cls) -> OWNSoundCommand:
        message = cls("*16*23*100##")
        message._human_readable_log = "Cycling to the next audio source."
        return message

    @classmethod
    def volume_up(cls, where: str | int) -> OWNSoundCommand:
        target = _require_non_empty_where(where)
        message = cls(f"*16*1001*{target}##")
        message._human_readable_log = f"Increasing audio zone {target} volume."
        return message

    @classmethod
    def volume_down(cls, where: str | int) -> OWNSoundCommand:
        # 1101 = volume down by one step (1101..1115); 1000 is not a WHO 16 WHAT.
        target = _require_non_empty_where(where)
        message = cls(f"*16*1101*{target}##")
        message._human_readable_log = f"Decreasing audio zone {target} volume."
        return message

    @classmethod
    def set_volume(cls, where: str | int, volume: int | str) -> OWNSoundCommand:
        """Write the amplifier volume: ``*#16*WHERE*#1*VOLUME##``, VOLUME 0..31.

        Dimension 1 is ``0..31`` (who-16-sound-system#dimension-values,
        #volume). The firmware oracle refuses ``*#16*21*#1*50##`` on 12/12
        emulated gateways and forwards ``*#16*21*#1*31##`` on the six WHO 16
        gateways (ORACLE_CONFIRM S1); BtExperience writes ``P * 31 / 100``
        (ENCY_CONFIRM SD-S1).
        """
        target = _require_non_empty_where(where)
        level = int(volume)
        if not 0 <= level <= 31:
            raise ValueError("volume must be between 0 and 31")
        message = cls(f"*#16*{target}*#1*{level}##")
        message._human_readable_log = (
            f"Setting audio zone {target} volume to {level}."
        )
        return message

    @classmethod
    def next_track(cls, where: str | int, step: int = 1) -> OWNSoundCommand:
        """Advance track or station forward (1..15 steps)."""
        target = _require_non_empty_where(where)
        s = int(step)
        if not 1 <= s <= 15:
            raise ValueError(f"step must be between 1 and 15, got {step}")
        what = 6000 + s
        message = cls(f"*16*{what}*{target}##")
        message._human_readable_log = (
            f"Advancing track/station on {target} by {s} step(s)."
        )
        return message

    @classmethod
    def previous_track(cls, where: str | int, step: int = 1) -> OWNSoundCommand:
        """Return track or station backward (1..15 steps)."""
        target = _require_non_empty_where(where)
        s = int(step)
        if not 1 <= s <= 15:
            raise ValueError(f"step must be between 1 and 15, got {step}")
        what = 6100 + s
        message = cls(f"*16*{what}*{target}##")
        message._human_readable_log = (
            f"Returning track/station on {target} by {s} step(s)."
        )
        return message

    @classmethod
    def seek_up(cls, where: str | int) -> OWNSoundCommand:
        """Seek forward to next receivable FM station."""
        target = _require_non_empty_where(where)
        message = cls(f"*16*5000*{target}##")
        message._human_readable_log = f"Seeking forward on {target}."
        return message

    @classmethod
    def seek_down(cls, where: str | int) -> OWNSoundCommand:
        """Seek backward to previous receivable FM station."""
        target = _require_non_empty_where(where)
        message = cls(f"*16*5100*{target}##")
        message._human_readable_log = f"Seeking backward on {target}."
        return message

    @classmethod
    def step_frequency_up(cls, where: str | int, step: int = 1) -> OWNSoundCommand:
        """Increase the tuner frequency by 1..15 steps: ``*16*5001..5015*WHERE##``.

        Encyclopedia Machine KB ``ownkb:chunk:r000371`` (``ownkb:claim:c002096``,
        ``c002098``): WHAT ``5001..5015`` is the manual frequency step up,
        ``5101..5115`` the step down; ``5000`` / ``5100`` are the automatic
        seeks of ``seek_up`` / ``seek_down``. ``*16*5001*101##`` is
        ACKed and put on the bus (``$0494018FA1``) by F453, F453AV, F454,
        H4684, MH200 and MH200N in the firmware oracle
        (``sound-who16-source``); F450, F459, F460, F461, MH202 and
        MyHomeServer1 NACK it.
        """
        target = _require_non_empty_where(where)
        s = _validate_frequency_step(step)
        message = cls(f"*16*{5000 + s}*{target}##")
        message._human_readable_log = f"Increasing frequency on {target} by {s} step(s)."
        return message

    @classmethod
    def step_frequency_down(cls, where: str | int, step: int = 1) -> OWNSoundCommand:
        """Decrease the tuner frequency by 1..15 steps: ``*16*5101..5115*WHERE##`` (oracle bus ``$0494018FB1``, as ``step_frequency_up``)."""
        target = _require_non_empty_where(where)
        s = _validate_frequency_step(step)
        message = cls(f"*16*{5100 + s}*{target}##")
        message._human_readable_log = f"Decreasing frequency on {target} by {s} step(s)."
        return message

    @classmethod
    def store_station(cls, where: str | int, station: int) -> OWNSoundCommand:
        """Store the tuned frequency into station 1..5: ``*#16*WHERE*#10*STATION##``.

        DIMENSION 10 is the write-only memorised-station store (Encyclopedia
        Machine KB ``ownkb:chunk:r000376``, ``ownkb:claim:c002128``: station
        1 through 5; ``bt_difson`` NACKs 6 and above, and never emits a
        DIMENSION 10 report, ``ownkb:claim:c002135``). Stations ``6..15`` of
        an F500N are stored through WHO 22
        :meth:`OWNSoundDiffusionCommand.store_preset` (``*22*33#P*2#S##``).
        The firmware oracle ACKs ``*#16*101*#10*5##`` on F453, F453AV, F454,
        H4684, MH200 and MH200N (``sound-who16-source``, bus
        ``$0493018FD4``); F450, F459, F460, F461, MH202 and MyHomeServer1
        NACK it.
        """
        target = _require_non_empty_where(where)
        if isinstance(station, bool) or not isinstance(station, (int, str)):
            raise ValueError(f"station must be between 1 and 5, got {station!r}")
        st = int(station)
        if not 1 <= st <= 5:
            raise ValueError(f"station must be between 1 and 5, got {station}")
        message = cls(f"*#16*{target}*#10*{st}##")
        message._human_readable_log = f"Storing current frequency into station {st} on {target}."
        return message

    @classmethod
    def select_track(cls, where: str | int, track: int) -> OWNSoundCommand:
        """Select stored station or CD/track number.

        Note:
            For tuner sources (radio), the stored station preset range is 1–5
            per the OpenWebNet specification (or up to 15 on extended tuners such
            as F500N). For CD or external media sources, track numbers can be
            greater (>= 1).
        """
        target = _require_non_empty_where(where)
        t = int(track)
        if t < 1:
            raise ValueError(f"track must be greater than or equal to 1, got {track}")
        message = cls(f"*#16*{target}*#7*{t}##")
        message._human_readable_log = (
            f"Selecting station/track {t} on {target}."
        )
        return message

    @classmethod
    def request_track(cls, where: str | int) -> OWNSoundCommand:
        """Request currently playing station or track number."""
        target = _require_non_empty_where(where)
        message = cls(f"*#16*{target}*7##")
        message._human_readable_log = f"Requesting station/track of {target}."
        return message

    @classmethod
    def set_frequency(
        cls, where: str | int, kilohertz: int | float
    ) -> OWNSoundCommand:
        """Tune tuner source to frequency in kHz (leading 0 parameter).

        The value is sent without zero padding: an F500N on an MH200N
        accepted `*#16*101*#6*0*96200##` (MyHOME#427).

        Examples:
            `107000` tunes to 107.00 MHz FM, `96200` to 96.20 MHz.
        """
        target = _require_non_empty_where(where)
        val = float(kilohertz)
        if not math.isfinite(val):
            raise ValueError(f"frequency in kHz must be finite, got {kilohertz}")
        khz = int(round(val))
        if khz <= 0:
            raise ValueError(f"frequency in kHz must be positive, got {kilohertz}")
        message = cls(f"*#16*{target}*#6*0*{khz}##")
        message._human_readable_log = (
            f"Tuning {target} to {khz} kHz."
        )
        return message

    @classmethod
    def request_frequency(cls, where: str | int) -> OWNSoundCommand:
        """Request tuned frequency."""
        target = _require_non_empty_where(where)
        message = cls(f"*#16*{target}*6##")
        message._human_readable_log = f"Requesting frequency of {target}."
        return message

    @classmethod
    def start_rds(cls, where: str | int) -> OWNSoundCommand:
        """Start autonomous RDS station name reporting."""
        target = _require_non_empty_where(where)
        message = cls(f"*16*101*{target}##")
        message._human_readable_log = f"Starting RDS reporting on {target}."
        return message

    @classmethod
    def stop_rds(cls, where: str | int) -> OWNSoundCommand:
        """Stop autonomous RDS station name reporting."""
        target = _require_non_empty_where(where)
        message = cls(f"*16*102*{target}##")
        message._human_readable_log = f"Stopping RDS reporting on {target}."
        return message

    @classmethod
    def request_rds(cls, where: str | int) -> OWNSoundCommand:
        """Request RDS station text."""
        target = _require_non_empty_where(where)
        message = cls(f"*#16*{target}*8##")
        message._human_readable_log = f"Requesting RDS text of {target}."
        return message


register_event_parser(16, OWNSoundEvent)
register_command_parser(16, OWNSoundCommand)


class OWNSoundDiffusionEvent(OWNEvent):
    """Event reported by a WHO 22 advanced sound diffusion system."""

    def __init__(self, data: str) -> None:
        super().__init__(data)

        self._target_type: str = "unknown"
        self._area: int | None = None
        self._point: int | None = None
        self._source_id: int | None = None
        self._volume: int | None = None
        self._volume_step: int | None = None
        self._device_state: int | None = None
        self._multimedia_type: int | None = None
        self._frequency_khz: int | None = None
        self._frequency_mhz: float | None = None
        self._frequency_band: int | None = None
        self._station: int | None = None
        self._is_station_cleared: bool = False
        self._preset: int | None = None
        self._frequency_step: int | None = None
        self._rds_text: str | None = None
        self._is_rds_blank: bool = False
        self._source_request: int | None = None
        self._matrix_area: int | None = None
        self._what_area: int | None = None
        self._high_tones: int | None = None
        self._medium_tones: int | None = None
        self._low_tones: int | None = None
        self._play_status: int | None = None
        self._balance: str | None = None
        self._sound_3d: int | None = None
        self._loudness: bool | None = None
        self._equalizer_group: int | None = None
        self._equalizer_values: list[int] | None = None
        self._tone_band: str | None = None
        self._tone_step: int | None = None
        self._balance_step: int | None = None

        target = (
            f"{self._where}#{'#'.join(self._where_param)}"
            if self._where and self._where_param
            else (self._where or "")
        )
        self._target_address: str = target

        # Decode structured target class from target address. The frame
        # grammar admits only `#DIGITS` WHERE parameters, so every part after
        # the tag converts.
        if target:
            parts = target.split("#")
            kind = parts[0]
            if kind == "3" and len(parts) >= 3:
                self._target_type = "speaker"
                self._area = int(parts[1])
                self._point = int(parts[2])
            elif kind == "4" and len(parts) >= 2:
                self._target_type = "area"
                self._area = int(parts[1])
            elif kind == "2" and len(parts) >= 2:
                self._target_type = "source"
                self._source_id = int(parts[1])
            elif kind == "5" and len(parts) >= 3 and parts[1] == "2":
                self._target_type = "source"
                self._source_id = int(parts[2])
            elif kind == "5" and len(parts) >= 4 and parts[1] == "3":
                # 5#3#AREA#POINT: zone control of a wall unit; 5#3#0#0 is every zone.
                self._target_type = "zone_control"
                self._area = int(parts[2])
                self._point = int(parts[3])
            elif kind == "6":
                self._target_type = "all_sources"

        # Relative volume step in WHAT
        if self._what in (3, 4):
            if self._what_param and self._what_param[0].isdigit():
                self._volume_step = int(self._what_param[0])
            else:
                self._volume_step = 1

        # Power and activity carry ``WHAT#MULTIMEDIA_TYPE#AREA`` (Encyclopedia
        # who-22-sound-diffusion#what "source power uses
        # WHAT#MULTIMEDIA_TYPE#AREA", #historical-touchscreen-syntax-and-extensions
        # `*22*0#4#AREA*3#AREA#POINT##` / `*22*34#4#AREA*3#AREA#POINT##`,
        # #source-activity-and-rds `WHAT 2#4#AREA`): the second parameter is
        # the AREA, never a source. Plant captures `*22*2#4#1*5#2#1##` (area 1,
        # source 1 in WHERE) and `*22*2#4#2*5#2#1##` (area 2) confirm it
        # (ENCY_CONFIRM SD-D1). The source is only in WHERE (`2#S`, `5#2#S`)
        # or in the matrix route `35#TYPE#AREA#SOURCE`.
        # The frame grammar admits only `#DIGITS` WHAT parameters, so each
        # present parameter converts.
        if self._what in (0, 1, 2, 34) and len(self._what_param) >= 2:
            self._multimedia_type = int(self._what_param[0])
            self._what_area = int(self._what_param[1])
        elif self._what == 35 and len(self._what_param) >= 3:
            self._multimedia_type = int(self._what_param[0])
            self._matrix_area = int(self._what_param[1])
            self._what_area = self._matrix_area
            self._source_request = int(self._what_param[2])
        elif self._what == 33 and self._what_param:
            # WHAT 33 stores the tuned frequency as a STATION (#what,
            # `*22*33#STATION*2#SOURCE_ID##`), not an equalizer preset.
            self._station = int(self._what_param[0])
        elif self._what in (36, 37, 38, 39, 40, 41):
            # Tone steps (#what 36..41): `36#1` increments the low tones by one.
            self._tone_band = {36: "low", 37: "low", 38: "mid", 39: "mid", 40: "high", 41: "high"}[self._what]
            tone_step = int(self._what_param[0]) if self._what_param else 1
            self._tone_step = tone_step if self._what % 2 == 0 else -tone_step
        elif self._what in (42, 43):
            # Balance steps: the published labels say 42 right / 43 left; the
            # page records the direction as unresolved between sources
            # (#tone-balance-and-presets), so the sign follows the labels.
            balance_step = int(self._what_param[0]) if self._what_param else 1
            self._balance_step = balance_step if self._what == 42 else -balance_step
        # A WHERE without an area (`2#S`, `5#2#S`, `6`) takes the area the
        # WHAT carries; a speaker / area WHERE keeps its own.
        if self._area is None and self._what_area is not None:
            self._area = self._what_area

        # Manual tuner steps: ``*22*5#STEP*2#S##`` up, ``*22*6#STEP*2#S##`` down,
        # STEP 1..15 (Encyclopedia ownkb:chunk:r000478-r000480,
        # ownkb:claim:c002729). A bare WHAT 5 / 6 is the automatic seek; a step
        # outside 1..15 (``5#0`` aliases the seek on bt_multi, 16 and above
        # overflow its one-nibble step) fails closed with ``frequency_step`` None.
        if self._what in (5, 6) and len(self._what_param) == 1:
            if _WHO22_FREQUENCY_STEP_REGEX.fullmatch(self._what_param[0]):
                self._frequency_step = int(self._what_param[0])

        # Dimensions
        if self._dimension == 1 and self._dimension_value:
            if self._dimension_value[0].isdigit() and 0 <= int(self._dimension_value[0]) <= 31:
                self._volume = int(self._dimension_value[0])
        elif self._dimension == 12 and self._dimension_value:
            if self._dimension_value[0].isdigit():
                self._device_state = int(self._dimension_value[0])
            if len(self._dimension_value) > 1 and self._dimension_value[1].isdigit():
                self._multimedia_type = int(self._dimension_value[1])
        elif self._dimension in (5, 11) and self._dimension_value:
            # Dimension 5 is `MODULATION*FREQUENCY`, dimension 11
            # `MODULATION*FREQUENCY*STATION_OR_TRACK` (Encyclopedia
            # who-22-sound-diffusion#payloads-and-concrete-operations);
            # modulation 1 FM, 2 AM-LW, 3 AM-MW, 4 AM-SW (#core-parameters).
            # A trailing empty field is preserved by the frame (#published-
            # inconsistencies) and ignored here. The FM unit is 10 kHz on an
            # MH200N / F454 and 100 kHz on a MyHomeServer1; the FM ranges
            # (8750..10800, 875..1080) do not overlap, so the value picks the
            # unit. The AM value is taken as kHz (inference: the page gives no
            # AM unit, D3 of the 2026-10-28 audit).
            expected = 2 if self._dimension == 5 else 3
            values = list(self._dimension_value)
            if len(values) == expected + 1 and values[-1] == "":
                values.pop()
            if len(values) == expected and values[1].isdigit():
                if values[0].isdigit():
                    self._frequency_band = int(values[0])
                khz = _who22_frequency_khz(self._frequency_band, int(values[1]))
                if khz:
                    self._frequency_khz = khz
                    self._frequency_mhz = round(khz / 1000.0, 2)
                    if self._dimension == 11 and values[2].isdigit():
                        if int(values[2]) > 0:
                            self._station = int(values[2])
                        else:
                            # An explicit station 0: the tuner is tuned off every
                            # stored station. ``station`` stays None as for a frame
                            # without a station field (dimension 5).
                            self._is_station_cleared = True
        elif self._dimension == 6 and len(self._dimension_value) == 1:
            # Dimension 6 is the stored station / track (#dimension), 1..5 on
            # an F500, 1..15 on an F500N, 1..999 for a track (#core-parameters).
            if self._dimension_value[0].isdigit() and int(self._dimension_value[0]) >= 1:
                self._station = int(self._dimension_value[0])
        elif self._dimension in (2, 3, 4) and len(self._dimension_value) == 1:
            # `TONE_VALUE` 1..63 (#core-parameters), kept raw: the touchscreen
            # shows `raw / 3 - 10` (#tone-balance-and-presets).
            if self._dimension_value[0].isdigit() and 1 <= int(self._dimension_value[0]) <= 63:
                tone = int(self._dimension_value[0])
                if self._dimension == 2:
                    self._high_tones = tone
                elif self._dimension == 3:
                    self._medium_tones = tone
                else:
                    self._low_tones = tone
        elif self._dimension == 7 and len(self._dimension_value) == 1:
            # Play status: the page defines the dimension, not its domain; kept raw.
            if self._dimension_value[0].isdigit():
                self._play_status = int(self._dimension_value[0])
        elif self._dimension == 17 and len(self._dimension_value) == 1:
            # Balance is textual: `030` is left 10, `115` right 5; the leading
            # zero is significant (#tone-balance-and-presets).
            if self._dimension_value[0].isdigit():
                self._balance = self._dimension_value[0]
        elif self._dimension == 18 and len(self._dimension_value) == 1:
            if self._dimension_value[0].isdigit() and 0 <= int(self._dimension_value[0]) <= 10:
                self._sound_3d = int(self._dimension_value[0])
        elif self._dimension == 19 and len(self._dimension_value) == 1:
            # Preset 2..11 built-in, 16..25 user defined (#core-parameters);
            # the gaps 12..15 are ignored by the tested decoder.
            if self._dimension_value[0].isdigit() and _is_who22_preset(int(self._dimension_value[0])):
                self._preset = int(self._dimension_value[0])
        elif self._dimension == 20 and len(self._dimension_value) == 1:
            if self._dimension_value[0] in ("0", "1"):
                self._loudness = self._dimension_value[0] == "1"
        elif self._dimension == 21 and len(self._dimension_param) == 1 and self._dimension_value:
            # Equalizer reports `21#1`, `21#2`, `21#3` carry bands 1..3, 4..6
            # and 7..8 (#payloads-and-concrete-operations); the band-value
            # domain is not published, so the values are kept raw.
            if self._dimension_param[0] in ("1", "2", "3") and all(v.isdigit() for v in self._dimension_value):
                self._equalizer_group = int(self._dimension_param[0])
                self._equalizer_values = [int(v) for v in self._dimension_value]
        elif self._dimension == 10 and 0 < len(self._dimension_value) <= 8:
            # RDS programme service: 1 to 8 decimal ASCII codes (F500 tuner continuous flux sends
            # 8 codes via 1+4+3 telegrams). Lengths outside 1..8 are bus glitches and are ignored.
            chars = [
                chr(int(code))
                for code in self._dimension_value
                if code.isdigit() and 32 <= int(code) <= 126
            ]
            text = "".join(chars).strip()
            self._rds_text = text or None
            self._is_rds_blank = text == ""

        # Human-readable log
        subject = (
            f"Speaker {target} (Zone {self.equivalent_who16_where})"
            if self._target_type == "speaker" and self.equivalent_who16_where
            else (
                f"Audio Source {self._source_id}"
                if self._target_type == "source" and self._source_id is not None
                else (f"Sound diffusion device {target}" if target else "Sound diffusion system")
            )
        )
        if self._dimension == 1 and self._volume is not None:
            self._human_readable_log = f"{subject} volume is set to {self._volume}."
        elif self._dimension == 12 and self._device_state is not None:
            if self._device_state == 1 and self.audio_channel is not None:
                self._human_readable_log = f"{subject} is ON, audio channel {self.audio_channel}."
            elif self.is_standby:
                self._human_readable_log = f"{subject} is in standby (OFF or muted by a priority call)."
            else:
                state_str = "ON" if self._device_state == 1 else "OFF"
                self._human_readable_log = f"{subject} device state is {state_str}."
        elif self._dimension in (5, 11) and self._frequency_khz is not None:
            station = (
                f" (station {self._station})"
                if self._station
                else (" (no stored station)" if self._is_station_cleared else "")
            )
            if self._frequency_band == 1:
                tuned = f"{self._frequency_khz / 1000:.2f} MHz"
            else:
                tuned = f"{self._frequency_khz} kHz {self.frequency_band_name}"
            self._human_readable_log = f"{subject} is tuned to {tuned}{station}."
        elif self._dimension == 6 and self._station is not None:
            self._human_readable_log = f"{subject} station is {self._station}."
        elif self._dimension == 10 and (self._rds_text is not None or self._is_rds_blank):
            self._human_readable_log = f"{subject} RDS text: '{self._rds_text or ''}'."
        elif self._dimension == 2 and self._high_tones is not None:
            self._human_readable_log = f"{subject} high tones are {self._high_tones}."
        elif self._dimension == 3 and self._medium_tones is not None:
            self._human_readable_log = f"{subject} medium tones are {self._medium_tones}."
        elif self._dimension == 4 and self._low_tones is not None:
            self._human_readable_log = f"{subject} low tones are {self._low_tones}."
        elif self._dimension == 7 and self._play_status is not None:
            self._human_readable_log = f"{subject} play status is {self._play_status}."
        elif self._dimension == 17 and self._balance is not None:
            self._human_readable_log = f"{subject} balance is {self._balance} ({self.balance_side} {self.balance_level})."
        elif self._dimension == 18 and self._sound_3d is not None:
            self._human_readable_log = f"{subject} 3D level is {self._sound_3d}."
        elif self._dimension == 19 and self._preset is not None:
            self._human_readable_log = f"{subject} equalizer preset is {self._preset}."
        elif self._dimension == 20 and self._loudness is not None:
            self._human_readable_log = f"{subject} loudness is {'ON' if self._loudness else 'OFF'}."
        elif self._dimension == 21 and self._equalizer_values is not None:
            bands = ", ".join(str(v) for v in self._equalizer_values)
            self._human_readable_log = f"{subject} equalizer group {self._equalizer_group} is {bands}."
        elif self._dimension is not None:
            self._human_readable_log = f"{subject} reported dimension {self._dimension}."
        elif self._what == 1 and self._what_area is not None:
            self._human_readable_log = f"{subject} is switched ON (area {self._what_area})."
        elif self._what == 2 and self._what_area is not None:
            self._human_readable_log = f"{subject} is active in area {self._what_area}."
        elif self._what in (1, 2):
            self._human_readable_log = f"{subject} is switched ON."
        elif self.is_atomic_off:
            self._human_readable_log = f"{subject} is switched OFF (atomic)."
        elif self._what == 0:
            self._human_readable_log = f"{subject} is switched OFF."
        elif self._what == 35 and self._source_request is not None:
            area_str = f" on matrix area {self._matrix_area}" if self._matrix_area is not None else ""
            self._human_readable_log = f"{subject} is routed to source {self._source_request}{area_str}."
        elif self._what == 31:
            self._human_readable_log = f"{subject} started RDS reporting."
        elif self._what == 32:
            self._human_readable_log = f"{subject} stopped RDS reporting."
        elif self._what == 33 and self._station is not None:
            self._human_readable_log = f"{subject} stored frequency to station {self._station}."
        elif self._what == 34:
            self._human_readable_log = f"{subject} follow-me."
        elif self._what == 22:
            self._human_readable_log = f"{subject} sliding request."
        elif self._tone_step is not None:
            verb = "increased" if self._tone_step > 0 else "decreased"
            self._human_readable_log = f"{subject} {self._tone_band} tones {verb} by {abs(self._tone_step)}."
        elif self._balance_step is not None:
            side = "right" if self._balance_step > 0 else "left"
            self._human_readable_log = f"{subject} balance moved {side} by {abs(self._balance_step)}."
        elif self._what == 55:
            self._human_readable_log = f"{subject} next preset."
        elif self._what == 56:
            self._human_readable_log = f"{subject} previous preset."
        elif self._what == 19:
            self._human_readable_log = f"{subject} opens paging channel {self.paging_channel}."
        elif self._what == 20:
            self._human_readable_log = f"{subject} starts paging voice on channel {self.paging_channel}."
        elif self.is_keypress:
            self._human_readable_log = f"{subject} keypad pressed."
        elif self._what == 3:
            step = f" by {self._volume_step}" if self._volume_step and self._volume_step > 1 else ""
            self._human_readable_log = f"{subject} volume increased{step}."
        elif self._what == 4:
            step = f" by {self._volume_step}" if self._volume_step and self._volume_step > 1 else ""
            self._human_readable_log = f"{subject} volume decreased{step}."
        elif self.is_step_frequency_up:
            self._human_readable_log = f"{subject} steps the frequency up by {self._frequency_step} step(s)."
        elif self.is_step_frequency_down:
            self._human_readable_log = f"{subject} steps the frequency down by {self._frequency_step} step(s)."
        elif self.is_seek_up:
            self._human_readable_log = f"{subject} seeks the next station up."
        elif self.is_seek_down:
            self._human_readable_log = f"{subject} seeks the next station down."
        elif self._what == 9:
            self._human_readable_log = f"{subject} next station."
        elif self._what == 10:
            self._human_readable_log = f"{subject} previous station."
        elif self._what == 11:
            self._human_readable_log = f"{subject} next track."
        elif self._what == 12:
            self._human_readable_log = f"{subject} previous track."
        elif self._what is not None:
            self._human_readable_log = f"{subject} received command: {self._what}."

    @property
    def target_type(self) -> str:
        """Target category: 'speaker' (3#A#P), 'area' (4#A), 'source' (2#S or 5#2#S), 'zone_control' (5#3#A#P, 5#3#0#0 is every zone), 'all_sources' (6), or 'unknown'."""
        return self._target_type

    @property
    def area(self) -> int | None:
        """Area/environment number (1..9; 0 in 5#3#0#0, every zone)."""
        return self._area

    @property
    def point(self) -> int | None:
        """Amplifier / speaker point number (1..9; 0 in 5#3#0#0, every zone)."""
        return self._point

    @property
    def source_id(self) -> int | None:
        """Audio source ID."""
        return self._source_id

    @property
    def volume(self) -> int | None:
        """Absolute volume level (0..31)."""
        return self._volume

    @property
    def volume_step(self) -> int | None:
        """Volume adjustment step for WHAT 3 / 4."""
        return self._volume_step

    @property
    def device_state(self) -> int | None:
        """Device power state reported under dimension 12: 0=OFF, 1=ON."""
        return self._device_state

    @property
    def multimedia_type(self) -> int | None:
        """Second value of dimension 12, whatever the state.

        Traces: with state 1 it is the audio channel (see ``audio_channel``), with state 0 it is 10
        (see ``is_standby``).
        """
        return self._multimedia_type

    @property
    def frequency_khz(self) -> int | None:
        """Tuned frequency in kHz from dimension 5 or 11.

        FM (``frequency_band`` 1) is reported in 10 kHz units on an MH200N
        and 100 kHz units on a MyHomeServer1 and must fall in 87.5..108 MHz;
        AM-LW / AM-MW / AM-SW (2 / 3 / 4) are taken as kHz (inference, see
        ``_who22_frequency_khz``); any other modulation gives ``None``.
        """
        return self._frequency_khz

    @property
    def station(self) -> int | None:
        """Stored station / track: dimension 6, dimension 11 (``0`` means 'not stored') or WHAT ``33#STATION``.

        Encyclopedia who-22-sound-diffusion#dimension (``6`` Track/station,
        ``11`` Frequency and station) and #what (``33`` store tuned frequency
        as a station); 1..5 on an F500, 1..15 on an F500N, 1..999 for a track.
        """
        return self._station

    @property
    def preset(self) -> int | None:
        """Equalizer preset of a dimension 19 report: 2..11 built in, 16..25 user defined.

        Encyclopedia who-22-sound-diffusion#dimension (``19`` Preset),
        #core-parameters (``2`` normal .. ``11`` full treble, ``16..25`` user
        defined); the gaps ``12..15`` give ``None``.

        Deprecated alias: for a dimension 6 / 11 or WHAT 33 frame this still
        returns the stored station, as it did before 2.0.0b13 when OWNd called
        the station "preset". Read ``station`` for those frames; this fallback
        will be removed.
        """
        if self._dimension == 19:
            return self._preset
        return self._station

    @property
    def equalizer_preset(self) -> int | None:
        """Equalizer preset of a dimension 19 report only (2..11, 16..25), else ``None``."""
        return self._preset

    @property
    def rds_text(self) -> str | None:
        """RDS programme service text from dimension 10; ``None`` when blank or malformed."""
        return self._rds_text

    @property
    def is_station_cleared(self) -> bool:
        """True for a dimension 11 report with an explicit station ``0``: tuned off every stored station.

        Defensive parsing of the spec-shaped ``*#22*WHERE*11*BAND*FREQ*0##``
        frame, against ``*#22*5#2#1*11*1*10530*5##`` once station 5 is
        selected at the same frequency. ``station`` is ``None`` in both the
        cleared case and a frame without a station field (dimension 5); this
        flag tells them apart.
        """
        return self._is_station_cleared

    @property
    def is_preset_cleared(self) -> bool:
        """Deprecated alias of ``is_station_cleared`` (the dimension 11 field is the station, not the preset)."""
        return self._is_station_cleared

    @property
    def what_area(self) -> int | None:
        """Area carried by the WHAT of a power / activity / Follow Me / route frame.

        ``WHAT#MULTIMEDIA_TYPE#AREA`` for WHAT 0 / 1 / 2 / 34 and
        ``35#TYPE#AREA#SOURCE`` for WHAT 35 (Encyclopedia
        who-22-sound-diffusion#what, #historical-touchscreen-syntax-and-extensions,
        #source-activity-and-rds; plant captures ``*22*2#4#1*5#2#1##`` = area 1 /
        source 1, ENCY_CONFIRM SD-D1). ``area`` reads the WHERE area first and
        falls back to this one for a source / all-sources WHERE.
        """
        return self._what_area

    @property
    def frequency_band_name(self) -> str | None:
        """``FM``, ``AM-LW``, ``AM-MW`` or ``AM-SW`` for modulation 1..4, else ``None``."""
        return _WHO22_BAND_NAMES.get(self._frequency_band) if self._frequency_band is not None else None

    @property
    def high_tones(self) -> int | None:
        """Dimension 2 ``TONE_VALUE`` (1..63, raw; the touchscreen shows ``raw / 3 - 10``)."""
        return self._high_tones

    @property
    def medium_tones(self) -> int | None:
        """Dimension 3 ``TONE_VALUE`` (1..63, raw)."""
        return self._medium_tones

    @property
    def low_tones(self) -> int | None:
        """Dimension 4 ``TONE_VALUE`` (1..63, raw)."""
        return self._low_tones

    @property
    def play_status(self) -> int | None:
        """Dimension 7 play status, raw (the page defines the dimension, not its values)."""
        return self._play_status

    @property
    def balance(self) -> str | None:
        """Dimension 17 balance as sent, leading zero kept: ``030`` is left 10, ``115`` right 5 (touchscreen reading)."""
        return self._balance

    @property
    def balance_side(self) -> str | None:
        """``left`` when the dimension 17 balance starts with ``0``, else ``right``; ``None`` without a balance."""
        if self._balance is None:
            return None
        return "left" if self._balance.startswith("0") else "right"

    @property
    def balance_level(self) -> int | None:
        """Magnitude digits of the dimension 17 balance after the side digit (``030`` -> 30, ``115`` -> 15), raw."""
        if self._balance is None:
            return None
        return int(self._balance[1:] or "0")

    @property
    def sound_3d(self) -> int | None:
        """Dimension 18 3D level (0..10)."""
        return self._sound_3d

    @property
    def loudness(self) -> bool | None:
        """Dimension 20 loudness: ``True`` for ``1``, ``False`` for ``0``."""
        return self._loudness

    @property
    def equalizer_group(self) -> int | None:
        """Equalizer selector of a ``21#1`` / ``21#2`` / ``21#3`` report (bands 1..3, 4..6, 7..8)."""
        return self._equalizer_group

    @property
    def equalizer_values(self) -> list[int] | None:
        """Band values of a ``21#G`` report, raw (the band-value domain is not published)."""
        return list(self._equalizer_values) if self._equalizer_values is not None else None

    @property
    def tone_band(self) -> str | None:
        """``low`` for WHAT 36 / 37, ``mid`` for 38 / 39, ``high`` for 40 / 41."""
        return self._tone_band

    @property
    def tone_step(self) -> int | None:
        """Signed tone step of WHAT 36..41 (``36#1`` -> +1, ``37#1`` -> -1; a bare WHAT counts as 1)."""
        return self._tone_step

    @property
    def balance_step(self) -> int | None:
        """Signed balance step of WHAT 42 (right, +) / 43 (left, -) by the published labels; the direction is unresolved on the page."""
        return self._balance_step

    @property
    def is_sliding_request(self) -> bool:
        """True for WHAT 22, the sliding request (the touchscreen treats ``22#4#AREA`` as a one-second temporary off)."""
        return self._what == 22

    @property
    def is_next_preset(self) -> bool:
        """True for WHAT 55, next equalizer preset."""
        return self._what == 55

    @property
    def is_previous_preset(self) -> bool:
        """True for WHAT 56, previous equalizer preset."""
        return self._what == 56

    @property
    def is_source_active(self) -> bool:
        """True for WHAT 2, a source-turned-on / activity notification (``2#4#AREA`` names the active area)."""
        return self._what == 2

    @property
    def is_rds_blank(self) -> bool:
        """True for a well-formed RDS frame with no visible text (the tuner is retuning)."""
        return self._is_rds_blank

    @property
    def audio_channel(self) -> int | None:
        """Audio channel / source the zone plays, from ``12*1*N`` (N = 1 or 2 on a F441 plant)."""
        if self._dimension == 12 and self._device_state == 1:
            return self._multimedia_type
        return None

    @property
    def is_standby(self) -> bool:
        """True for ``12*0*10``: standby, which is also how a priority call (paging) mutes a zone."""
        return self._dimension == 12 and self._device_state == 0 and self._multimedia_type == 10

    @property
    def matrix_area(self) -> int | None:
        """Area of a WHAT 35 route (``35#TYPE#AREA#SOURCE``): the area being routed, the same as the WHERE area (``what_area`` for WHAT 35)."""
        return self._matrix_area

    @property
    def frequency_mhz(self) -> float | None:
        """Tuned frequency in MHz."""
        return self._frequency_mhz

    @property
    def frequency_band(self) -> int | None:
        """Frequency band: 1 = FM, 2 = AM-LW, 3 = AM-MW, 4 = AM-SW."""
        return self._frequency_band

    @property
    def is_rds_start(self) -> bool:
        """True for WHAT 31 (Start RDS Open)."""
        return self._what == 31

    @property
    def is_rds_stop(self) -> bool:
        """True for WHAT 32 (Stop RDS Open)."""
        return self._what == 32

    @property
    def is_follow_me(self) -> bool:
        """True for WHAT 34 (ON_FOLLOW_ME)."""
        return self._what == 34

    @property
    def requested_source(self) -> int | None:
        """Source of a WHAT 35 route (``35#TYPE#AREA#SOURCE``), else ``None``.

        Until 2.0.0b13 a ``1#TYPE#X`` power-on also filled this with ``X``;
        that field is the AREA (``what_area``), so WHAT 1 now gives ``None``.
        """
        return self._source_request

    @property
    def is_route_source(self) -> bool:
        """True for WHAT 35, which routes the target zone to a source on the matrix."""
        return self._what == 35

    @property
    def is_atomic_off(self) -> bool:
        """True for ``0#TYPE#AREA`` (``*22*0#4#AREA*3#AREA#POINT##``), the single-frame power off; a plain WHAT 0 carries no parameters."""
        return self._what == 0 and len(self._what_param) >= 1

    @property
    def paging_channel(self) -> int | None:
        """Channel of a paging frame (``19#C`` open, ``20#C`` voice)."""
        if self._what in (19, 20) and self._what_param and self._what_param[0].isdigit():
            return int(self._what_param[0])
        return None

    @property
    def is_paging_open(self) -> bool:
        """True for WHAT 19, the paging channel opening (whole house on ``5#3#0#0``)."""
        return self._what == 19

    @property
    def is_paging_voice(self) -> bool:
        """True for WHAT 20, the paging voice transmission starting."""
        return self._what == 20

    @property
    def is_all_zones(self) -> bool:
        """True when the target is ``5#3#0#0``, every zone."""
        return self._target_type == "zone_control" and self._area == 0 and self._point == 0

    @property
    def is_keypress(self) -> bool:
        """True for WHAT 9 aimed at a zone control (``9`` on ``5#3#A#P``): a wall unit button press."""
        return self._what == 9 and self._target_type == "zone_control"

    @property
    def equivalent_who16_where(self) -> str | None:
        """Mathematical equivalent WHO 16 zone address: EA = Area * 10 + Point."""
        if self._target_type == "speaker" and self._area is not None and self._point is not None:
            return f"{self._area}{self._point}"
        return None

    @property
    def is_on(self) -> bool:
        """True if the device received a power-on state (WHAT=1 or 2, or dimension 12 state 1)."""
        if self._what in (1, 2):
            return True
        if self._dimension == 12 and self._device_state == 1:
            return True
        return False

    @property
    def is_off(self) -> bool:
        """True if the device received a power-off state (WHAT=0, or dimension 12 state 0)."""
        if self._what == 0:
            return True
        if self._dimension == 12 and self._device_state == 0:
            return True
        return False

    @property
    def is_volume_up(self) -> bool:
        """True if WHAT represents volume increase (WHAT=3)."""
        return self._what == 3

    @property
    def is_volume_down(self) -> bool:
        """True if WHAT represents volume decrease (WHAT=4)."""
        return self._what == 4

    @property
    def is_next_track(self) -> bool:
        """True if WHAT represents next track (WHAT=11)."""
        return self._what == 11

    @property
    def is_previous_track(self) -> bool:
        """True if WHAT represents previous track (WHAT=12)."""
        return self._what == 12

    @property
    def is_seek_up(self) -> bool:
        """True for a bare WHAT 5, automatic tuning up (``*22*5*2#S##``).

        The manual form ``*22*5#STEP*2#S##`` carries a step parameter and is
        ``is_step_frequency_up`` instead.
        """
        return self._what == 5 and not self._what_param

    @property
    def is_seek_down(self) -> bool:
        """True for a bare WHAT 6, automatic tuning down (``*22*6*2#S##``)."""
        return self._what == 6 and not self._what_param

    @property
    def frequency_step(self) -> int | None:
        """Manual tuner step 1..15 of ``*22*5#STEP*2#S##`` / ``*22*6#STEP*2#S##``, else ``None``.

        Encyclopedia ``ownkb:chunk:r000478``-``r000480``, ``ownkb:claim:c002729``.
        A step outside 1..15 fails closed (``None``).
        """
        return self._frequency_step

    @property
    def is_step_frequency_up(self) -> bool:
        """True for WHAT ``5#STEP`` with a step 1..15, one manual frequency step up."""
        return self._what == 5 and self._frequency_step is not None

    @property
    def is_step_frequency_down(self) -> bool:
        """True for WHAT ``6#STEP`` with a step 1..15, one manual frequency step down."""
        return self._what == 6 and self._frequency_step is not None

    @property
    def is_next_station(self) -> bool:
        """True if WHAT represents next radio station (WHAT=9, unless it is a keypress)."""
        return self._what == 9 and not self.is_keypress

    @property
    def is_previous_station(self) -> bool:
        """True if WHAT represents previous radio station (WHAT=10)."""
        return self._what == 10

    @property
    def target_address(self) -> str:
        """Structured target address including point/source parameters (e.g. 3#4#1, 2#3)."""
        return self._target_address


class OWNSoundDiffusionCommand(OWNCommand):
    """Commands for WHO 22 advanced sound diffusion system."""

    @property
    def target_address(self) -> str:
        """Structured target address including point/source parameters (e.g. 3#4#1, 2#3)."""
        if self._where and self._where_param:
            return f"{self._where}#{'#'.join(self._where_param)}"
        return self._where or ""

    @classmethod
    def status(cls, where: str | int) -> OWNSoundDiffusionCommand:
        target = _require_non_empty_where(where)
        message = cls(f"*#22*{target}##")
        message._human_readable_log = f"Requesting status of sound diffusion device {target}."
        return message

    @classmethod
    def turn_on(cls, where: str | int) -> OWNSoundDiffusionCommand:
        target = _require_non_empty_where(where)
        message = cls(f"*22*1*{target}##")
        message._human_readable_log = f"Turning ON sound diffusion device {target}."
        return message

    @classmethod
    def turn_off(cls, where: str | int) -> OWNSoundDiffusionCommand:
        target = _require_non_empty_where(where)
        message = cls(f"*22*0*{target}##")
        message._human_readable_log = f"Turning OFF sound diffusion device {target}."
        return message

    @classmethod
    def turn_on_atomic(
        cls,
        where: str | int,
        area: int | str | None = None,
        multimedia_type: int | str = 4,
    ) -> OWNSoundDiffusionCommand:
        """Power a speaker on in one frame: ``*22*1#TYPE#AREA*WHERE##``.

        The second WHAT parameter is the AREA of the target (Encyclopedia
        who-22-sound-diffusion#what "source power uses
        ``WHAT#MULTIMEDIA_TYPE#AREA``", the tested Speaker OFF / Follow Me
        forms of #historical-touchscreen-syntax-and-extensions, plant
        captures ``*22*2#4#1*5#2#1##`` = area 1 / source 1, ENCY_CONFIRM
        SD-D1). It is derived from ``3#AREA#POINT``, ``4#AREA`` or
        ``5#3#AREA#POINT``; a source or ``6`` target needs ``area=``. The
        emulated gateways copy the parameter verbatim onto the bus
        (``*22*1#4#2*3#2#1##`` -> ``$0490018223``, ORACLE_CONFIRM D1), so a
        wrong value reaches the plant. TYPE 4 (stereo) on the traced plant.
        """
        target = _require_non_empty_where(where)
        a = _validate_area(area, str(where), target)
        mm_type = int(multimedia_type)
        if mm_type < 0:
            raise ValueError("multimedia_type must be non-negative")
        message = cls(f"*22*1#{mm_type}#{a}*{target}##")
        message._human_readable_log = f"Turning ON sound diffusion device {target} (area {a})."
        return message

    @classmethod
    def turn_on_with_source(
        cls,
        where: str | int,
        source_id: int | str,
        multimedia_type: int | str = 4,
        area: int | str | None = None,
    ) -> OWNSoundDiffusionCommand:
        """Deprecated: ``turn_on_atomic`` under its pre-2.0.0b13 name; the source is not on the wire.

        Until 2.0.0b13 this built ``*22*1#TYPE#SOURCE*WHERE##``, reading the
        AREA slot as a source (audit 2026-10-28 D1). WHAT 1 carries no source
        (Encyclopedia who-22-sound-diffusion#what); selecting a source is
        WHAT 35, ``route_source``. ``source_id`` is validated (1..) for
        compatibility and otherwise ignored; the frame is
        ``*22*1#TYPE#AREA*WHERE##`` with the target's area (or ``area=``).
        """
        source = int(source_id)
        if source < 1:
            raise ValueError("source must be positive")
        return cls.turn_on_atomic(where, area, multimedia_type)

    @classmethod
    def turn_off_atomic(
        cls,
        where: str | int,
        multimedia_type: int | str = 4,
        area: int | str | None = None,
    ) -> OWNSoundDiffusionCommand:
        """Power a speaker off in one frame: ``*22*0#TYPE#AREA*WHERE##``.

        Tested touchscreen emission ``*22*0#4#AREA*3#AREA#POINT##``
        (Encyclopedia who-22-sound-diffusion#historical-touchscreen-syntax-and-extensions);
        the area is derived from the target as in ``turn_on_atomic``. Until
        2.0.0b13 the area slot was a constant ``0`` (audit 2026-10-28 D1);
        ``*22*0#4#0*3#2#1##`` and ``*22*0#4#2*3#2#1##`` both reach the bus
        with the parameter copied verbatim (``$0491018203`` / ``$0491018223``,
        ORACLE_CONFIRM D1). ``*22*0#4#0*3#0#6##`` and ``*22*0#4#0*5#3#0#0##``
        (area 0 targets) are in the firmware oracle (``sound-who22``).
        """
        target = _require_non_empty_where(where)
        a = _validate_area(area, str(where), target)
        mm_type = int(multimedia_type)
        if mm_type < 0:
            raise ValueError("multimedia_type must be non-negative")
        message = cls(f"*22*0#{mm_type}#{a}*{target}##")
        message._human_readable_log = f"Turning OFF sound diffusion device {target} (atomic)."
        return message

    @classmethod
    def route_source(
        cls,
        where: str | int,
        source_id: int | str,
        matrix_area: int | str | None = None,
        multimedia_type: int | str = 4,
        area: int | str | None = None,
    ) -> OWNSoundDiffusionCommand:
        """Turn a speaker on with a source: ``*22*35#TYPE#AREA#SOURCE*WHERE##``.

        The third WHAT parameter is the AREA being routed, the same area as
        in WHERE (Encyclopedia who-22-sound-diffusion#payloads-and-concrete-operations
        ``*22*35#4#AREA#SOURCE_ID*3#AREA#POINT##``,
        #historical-touchscreen-syntax-and-extensions "sends eight commands,
        one for each area 1..8"; ENCY_CONFIRM SD-D2). The emulated gateways
        address the bus from that parameter, not from WHERE:
        ``*22*35#4#1#7*3#2#1##`` goes to area 1 and ``*22*35#4#2#7*3#2#1##``
        to area 2 (ORACLE_CONFIRM D2), so until 2.0.0b13 the ``matrix_area=1``
        default routed area 1 for every target (audit 2026-10-28 D2). The
        area is now derived from ``3#AREA#POINT``, ``4#AREA`` or
        ``5#3#AREA#POINT``; ``area=`` (or the older ``matrix_area=``) sets
        it explicitly, and a source or ``6`` target requires it.

        The page's source ID domain is ``1..4`` (#core-parameters); ``7``
        is the FM tuner of the traced MH200N / F441 plant and is forwarded
        by nine emulated gateways (``*22*35#4#2#7*3#2#0##``, firmware oracle
        ``sound-who22``), so 1..9 (the single-digit ``2#S`` WHERE) is
        accepted.

        Parameters:
            where: Target address (``3#1#1``, ``4#2``, ``5#3#0#0``).
            source_id: Source 1..9.
            matrix_area: Older spelling of ``area``.
            multimedia_type: Audio routing mode (default 4 = stereo).
            area: Area 0..9 to route; defaults to the target's area.
        """
        target = _require_non_empty_where(where)
        source = int(source_id)
        if not 1 <= source <= 9:
            raise ValueError("source must be between 1 and 9")
        if area is None:
            area = matrix_area
        a = _validate_area(area, str(where), target)
        mm_type = int(multimedia_type)
        if mm_type < 0:
            raise ValueError("multimedia_type must be non-negative")
        message = cls(f"*22*35#{mm_type}#{a}#{source}*{target}##")
        message._human_readable_log = f"Routing sound diffusion device {target} to source {source} on matrix area {a}."
        return message

    @classmethod
    def set_frequency(
        cls,
        where: str | int,
        frequency_khz: int | float,
        band: int = 1,
    ) -> OWNSoundDiffusionCommand:
        """Tune tuner source to frequency: ``*#22*WHERE*#5*BAND*FREQ_10KHZ##``.

        Frequency is transmitted in 10 kHz units per gateway firmware specification
        (e.g., 101.50 MHz = 101500 kHz -> 10150).
        """
        target = _require_non_empty_where(where)
        val = float(frequency_khz)
        if not math.isfinite(val):
            raise ValueError("frequency must be finite")
        khz = int(round(val))
        if khz <= 0:
            raise ValueError("frequency must be positive")
        freq_10k = khz // 10
        if freq_10k < 1:
            raise ValueError("frequency must be at least 10 kHz")
        b = int(band)
        if not 1 <= b <= 4:
            raise ValueError("band must be between 1 and 4")
        message = cls(f"*#22*{target}*#5*{b}*{freq_10k}##")
        message._human_readable_log = f"Tuning sound diffusion device {target} to {khz} kHz ({khz/1000.0:.2f} MHz)."
        return message

    @classmethod
    def request_frequency(cls, where: str | int) -> OWNSoundDiffusionCommand:
        """Request tuned frequency: ``*#22*WHERE*5##``."""
        target = _require_non_empty_where(where)
        message = cls(f"*#22*{target}*5##")
        message._human_readable_log = f"Requesting frequency for sound diffusion device {target}."
        return message

    @classmethod
    def select_station(cls, where: str | int, station: int | str) -> OWNSoundDiffusionCommand:
        """Select a stored station: ``*#22*WHERE*#6*STATION##``.

        Tested touchscreen emission ``*#22*2#SOURCE*#6*STATION##``
        (Encyclopedia who-22-sound-diffusion#historical-touchscreen-syntax-and-extensions);
        dimension 6 is the track / station (#dimension), 1..5 on an F500,
        1..15 on an F500N, 1..999 for a track (#core-parameters).
        ``*#22*2#1*#6*7##`` is in the firmware oracle (``sound-who22``).
        """
        target = _require_non_empty_where(where)
        st = int(station)
        if not 1 <= st <= 999:
            raise ValueError("station must be between 1 and 999")
        message = cls(f"*#22*{target}*#6*{st}##")
        message._human_readable_log = f"Selecting station {st} on sound diffusion device {target}."
        return message

    @classmethod
    def request_station(cls, where: str | int) -> OWNSoundDiffusionCommand:
        """Request the stored station / track: ``*#22*WHERE*6##`` (``*#22*2#1*6##`` is in the firmware oracle)."""
        target = _require_non_empty_where(where)
        message = cls(f"*#22*{target}*6##")
        message._human_readable_log = f"Requesting station for sound diffusion device {target}."
        return message

    @classmethod
    def set_preset(
        cls,
        where: str | int,
        preset: int | str,
        frequency_khz: int | float | None = None,
        band: int = 1,
    ) -> OWNSoundDiffusionCommand:
        """Deprecated: ``select_station`` under its pre-2.0.0b13 name (dimension 6 is the station, not the preset).

        Without ``frequency_khz`` this is ``select_station``:
        ``*#22*WHERE*#6*STATION##``. With ``frequency_khz`` it writes
        ``*#22*WHERE*#11*BAND*FREQ*STATION##``, not in the published grammar:
        dimension 11 is a report payload (Encyclopedia
        who-22-sound-diffusion#payloads-and-concrete-operations) and no
        client write of it is documented (ENCY_CONFIRM SD-D7). The emulated
        gateways forward ``*#22*2#1*#11*1*10150*3##`` (``$06D101F83202031FB8``,
        ORACLE_CONFIRM D7) without any evidence of what a tuner does with it.
        The equalizer preset of dimension 19 is ``set_equalizer_preset``.
        """
        target = _require_non_empty_where(where)
        p = int(preset)
        if p < 1:
            raise ValueError("preset must be positive")
        if frequency_khz is not None:
            val = float(frequency_khz)
            if not math.isfinite(val):
                raise ValueError("frequency must be finite")
            khz = int(round(val))
            if khz <= 0:
                raise ValueError("frequency must be positive")
            freq_10k = khz // 10
            if freq_10k < 1:
                raise ValueError("frequency must be at least 10 kHz")
            b = int(band)
            if not 1 <= b <= 4:
                raise ValueError("band must be between 1 and 4")
            message = cls(f"*#22*{target}*#11*{b}*{freq_10k}*{p}##")
            message._human_readable_log = f"Programming preset {p} on {target} to {khz} kHz."
        else:
            message = cls(f"*#22*{target}*#6*{p}##")
            message._human_readable_log = f"Selecting preset {p} on sound diffusion device {target}."
        return message

    @classmethod
    def request_preset(cls, where: str | int) -> OWNSoundDiffusionCommand:
        """Deprecated: ``request_station`` under its pre-2.0.0b13 name (``*#22*WHERE*6##`` reads the station; the preset is dimension 19, ``request_equalizer_preset``)."""
        return cls.request_station(where)

    @classmethod
    def set_equalizer_preset(cls, where: str | int, preset: int | str) -> OWNSoundDiffusionCommand:
        """Select an equalizer preset: ``*#22*WHERE*#19*PRESET##``.

        Encyclopedia who-22-sound-diffusion#payloads-and-concrete-operations
        ("Set speaker preset ``*#22*3#AREA#POINT*#19*PRESET##``");
        preset ``2`` normal, ``3`` dance, ``4`` pop, ``5`` rock, ``6`` classic,
        ``7`` techno, ``8`` party, ``9`` soft, ``10`` full bass, ``11`` full
        treble, ``16..25`` user defined (#core-parameters; ENCY_CONFIRM
        SD-D4). Not in the firmware oracle.
        """
        target = _require_non_empty_where(where)
        p = int(preset)
        if not _is_who22_preset(p):
            raise ValueError(f"preset must be 2..11 or 16..25, got {preset}")
        message = cls(f"*#22*{target}*#19*{p}##")
        message._human_readable_log = f"Selecting equalizer preset {p} on sound diffusion device {target}."
        return message

    @classmethod
    def request_equalizer_preset(cls, where: str | int) -> OWNSoundDiffusionCommand:
        """Request the equalizer preset: ``*#22*WHERE*19##`` (the touchscreen reads ``19`` at initialisation, #tone-balance-and-presets)."""
        target = _require_non_empty_where(where)
        message = cls(f"*#22*{target}*19##")
        message._human_readable_log = f"Requesting equalizer preset for sound diffusion device {target}."
        return message

    @classmethod
    def next_preset(cls, where: str | int) -> OWNSoundDiffusionCommand:
        """Next equalizer preset: ``*22*55*WHERE##`` (tested touchscreen emission ``*22*55*3#AREA#POINT##``)."""
        target = _require_non_empty_where(where)
        message = cls(f"*22*55*{target}##")
        message._human_readable_log = f"Next equalizer preset on sound diffusion device {target}."
        return message

    @classmethod
    def previous_preset(cls, where: str | int) -> OWNSoundDiffusionCommand:
        """Previous equalizer preset: ``*22*56*WHERE##`` (tested touchscreen emission ``*22*56*3#AREA#POINT##``)."""
        target = _require_non_empty_where(where)
        message = cls(f"*22*56*{target}##")
        message._human_readable_log = f"Previous equalizer preset on sound diffusion device {target}."
        return message

    @classmethod
    def start_rds(cls, where: str | int) -> OWNSoundDiffusionCommand:
        """Start RDS reporting: ``*22*31*WHERE##``."""
        target = _require_non_empty_where(where)
        message = cls(f"*22*31*{target}##")
        message._human_readable_log = f"Starting RDS reporting on sound diffusion device {target}."
        return message

    @classmethod
    def stop_rds(cls, where: str | int) -> OWNSoundDiffusionCommand:
        """Stop RDS reporting: ``*22*32*WHERE##``."""
        target = _require_non_empty_where(where)
        message = cls(f"*22*32*{target}##")
        message._human_readable_log = f"Stopping RDS reporting on sound diffusion device {target}."
        return message

    @classmethod
    def store_station(cls, where: str | int, station: int | str) -> OWNSoundDiffusionCommand:
        """Store the tuned frequency as a station: ``*22*33#STATION*WHERE##``.

        Encyclopedia who-22-sound-diffusion#what (``33`` store tuned frequency
        as a station), #payloads-and-concrete-operations
        (``*22*33#STATION*2#SOURCE_ID##``); stored station 1..5 on an F500,
        1..15 on an F500N (#core-parameters). ``*22*33#3*2#1##`` is in the
        firmware oracle (``sound-who22``).
        """
        target = _require_non_empty_where(where)
        st = int(station)
        if st < 1:
            raise ValueError("station must be positive")
        message = cls(f"*22*33#{st}*{target}##")
        message._human_readable_log = f"Storing current frequency into station {st} on {target}."
        return message

    @classmethod
    def store_preset(cls, where: str | int, preset: int | str) -> OWNSoundDiffusionCommand:
        """Deprecated: ``store_station`` under its pre-2.0.0b13 name (WHAT 33 stores a station, not an equalizer preset)."""
        return cls.store_station(where, preset)

    @classmethod
    def send_rds_text(cls, where: str | int, text: str) -> OWNSoundDiffusionCommand:
        """Format an 8-character RDS Program Service frame: ``*#22*WHERE*#10*c0*...*c7##``.

        Not in the published grammar: dimension 10 is a report payload carrying
        the tuner's RDS text (Encyclopedia who-22-sound-diffusion#payloads-and-concrete-operations,
        #source-activity-and-rds), RDS is controlled by WHAT 31 / 32 and no
        client write of dimension 10 is documented (ENCY_CONFIRM SD-D7). In
        the ``bt_multi`` gateway firmwares (F453AV, F454, F459, F460, F461,
        MH200N, MH202, MyHomeServer1) a client ``*#22*WHERE*#10*...##`` is
        NACKed with no SCS bus output. Use ``start_rds``, ``stop_rds`` and
        ``request_rds``; kept for callers that already build it.
        """
        target = _require_non_empty_where(where)
        formatted = text[:8].ljust(8)
        codes = [str(ord(c)) for c in formatted]
        message = cls(f"*#22*{target}*#10*{'*'.join(codes)}##")
        message._human_readable_log = f"Broadcasting RDS text '{formatted.strip()}' to sound diffusion device {target}."
        return message

    @classmethod
    def request_rds(cls, where: str | int) -> OWNSoundDiffusionCommand:
        """Request RDS station text: ``*#22*WHERE*10##``."""
        target = _require_non_empty_where(where)
        message = cls(f"*#22*{target}*10##")
        message._human_readable_log = f"Requesting RDS text for sound diffusion device {target}."
        return message

    @classmethod
    def open_paging(cls, where: str | int = "5#3#0#0", channel: int | str = 1) -> OWNSoundDiffusionCommand:
        """Open a paging channel: ``*22*19#CHANNEL*WHERE##`` (``5#3#0#0`` is the whole house).

        Not in the published grammar: the WHO 22 WHAT table has no ``19`` or
        ``20`` (Encyclopedia who-22-sound-diffusion#what; ENCY_CONFIRM SD-D7).
        Trace-derived from a plant with a paging unit; nine emulated gateways
        forward ``*22*19#1*5#3#0#0##`` (``$04B7008010``, ORACLE_CONFIRM D7)
        without a documented counterpart.
        """
        target = _require_non_empty_where(where)
        ch = int(channel)
        if ch < 1:
            raise ValueError("channel must be positive")
        message = cls(f"*22*19#{ch}*{target}##")
        message._human_readable_log = f"Opening paging channel {ch} on {target}."
        return message

    @classmethod
    def start_paging_voice(cls, where: str | int = "5#3#0#0", channel: int | str = 1) -> OWNSoundDiffusionCommand:
        """Start the paging voice transmission: ``*22*20#CHANNEL*WHERE##`` (not in the published grammar, as ``open_paging``)."""
        target = _require_non_empty_where(where)
        ch = int(channel)
        if ch < 1:
            raise ValueError("channel must be positive")
        message = cls(f"*22*20#{ch}*{target}##")
        message._human_readable_log = f"Starting paging voice on channel {ch} on {target}."
        return message

    @classmethod
    def volume_up(cls, where: str | int, step: int = 1) -> OWNSoundDiffusionCommand:
        """Increase the volume by ``step`` (1..31): ``*22*3*WHERE##`` / ``*22*3#STEP*WHERE##``.

        A step of 1 is sent as the bare ``*22*3*WHERE##`` and a larger step as
        ``*22*3#STEP*WHERE##``: both forms are preserved on purpose (#127,
        maintainer decision D19; #128 bounds ``step`` to ``1..31``). The page
        defines only ``*22*3#VOLUME_STEP*3#AREA#POINT##`` (Encyclopedia
        who-22-sound-diffusion#payloads-and-concrete-operations,
        #core-parameters step ``1..31``). Oracle note (ORACLE_CONFIRM D5,
        audit 2026-10-28): F454, F459 and MyHomeServer1 put the bare form on
        the bus with step ``00`` (``$0494018100``) where ``3#1`` gives ``01``;
        F453, F453AV, F460, F461, MH200N and MH202 send the same bytes for
        both. ``*22*3#1*3#1#1##`` is in the firmware oracle (``sound-who22``);
        the bare form is not. Changing the step-1 form needs a #127 reopen.
        """
        s = int(step)
        if not 1 <= s <= 31:
            raise ValueError("step must be positive and between 1 and 31")
        target = _require_non_empty_where(where)
        what = f"3#{s}" if s > 1 else "3"
        message = cls(f"*22*{what}*{target}##")
        message._human_readable_log = f"Increasing sound diffusion device {target} volume."
        return message

    @classmethod
    def volume_down(cls, where: str | int, step: int = 1) -> OWNSoundDiffusionCommand:
        """Decrease the volume by ``step`` (1..31): bare ``*22*4*WHERE##`` for step 1, ``*22*4#STEP*WHERE##`` above (both kept on purpose, #127 / D19; see ``volume_up`` for the oracle note)."""
        s = int(step)
        if not 1 <= s <= 31:
            raise ValueError("step must be positive and between 1 and 31")
        target = _require_non_empty_where(where)
        what = f"4#{s}" if s > 1 else "4"
        message = cls(f"*22*{what}*{target}##")
        message._human_readable_log = f"Decreasing sound diffusion device {target} volume."
        return message

    @classmethod
    def set_volume(cls, where: str | int, volume: int | str) -> OWNSoundDiffusionCommand:
        target = _require_non_empty_where(where)
        level = int(volume)
        if not 0 <= level <= 31:
            raise ValueError("volume must be between 0 and 31 per WHO 22 specification")
        message = cls(f"*#22*{target}*#1*{level}##")
        message._human_readable_log = f"Setting sound diffusion device {target} volume to {level}."
        return message

    @classmethod
    def request_volume(cls, where: str | int) -> OWNSoundDiffusionCommand:
        target = _require_non_empty_where(where)
        message = cls(f"*#22*{target}*1##")
        message._human_readable_log = f"Requesting volume status for sound diffusion device {target}."
        return message

    @classmethod
    def request_device_state(cls, where: str | int) -> OWNSoundDiffusionCommand:
        target = _require_non_empty_where(where)
        message = cls(f"*#22*{target}*12##")
        message._human_readable_log = f"Requesting device state for sound diffusion device {target}."
        return message

    @classmethod
    def next_track(cls, where: str | int = "6") -> OWNSoundDiffusionCommand:
        target = _require_non_empty_where(where)
        message = cls(f"*22*11*{target}##")
        message._human_readable_log = f"Next track on sound diffusion device {target}."
        return message

    @classmethod
    def previous_track(cls, where: str | int = "6") -> OWNSoundDiffusionCommand:
        target = _require_non_empty_where(where)
        message = cls(f"*22*12*{target}##")
        message._human_readable_log = f"Previous track on sound diffusion device {target}."
        return message

    @classmethod
    def next_station(cls, where: str | int = "6") -> OWNSoundDiffusionCommand:
        target = _require_non_empty_where(where)
        message = cls(f"*22*9*{target}##")
        message._human_readable_log = f"Next station on sound diffusion device {target}."
        return message

    @classmethod
    def previous_station(cls, where: str | int = "6") -> OWNSoundDiffusionCommand:
        target = _require_non_empty_where(where)
        message = cls(f"*22*10*{target}##")
        message._human_readable_log = f"Previous station on sound diffusion device {target}."
        return message

    @classmethod
    def seek_up(cls, where: str | int = "6") -> OWNSoundDiffusionCommand:
        """Automatic tuning up: ``*22*5*WHERE##``.

        ``*22*5*2#1##`` is ACKed and put on the bus (``$0494018FA0``) by
        F453, F453AV, F454, F459, F460, F461, MH200N and MyHomeServer1 in
        the firmware oracle (``sound-who22``); F450, H4684 and MH200 NACK it.
        """
        target = _require_non_empty_where(where)
        message = cls(f"*22*5*{target}##")
        message._human_readable_log = f"Seeking the next station up on sound diffusion device {target}."
        return message

    @classmethod
    def seek_down(cls, where: str | int = "6") -> OWNSoundDiffusionCommand:
        """Automatic tuning down: ``*22*6*WHERE##`` (oracle bus ``$0494018FB0``, as ``seek_up``)."""
        target = _require_non_empty_where(where)
        message = cls(f"*22*6*{target}##")
        message._human_readable_log = f"Seeking the next station down on sound diffusion device {target}."
        return message

    @classmethod
    def step_frequency_up(cls, where: str | int = "6", step: int = 1) -> OWNSoundDiffusionCommand:
        """Manual frequency step up by 1..15: ``*22*5#STEP*WHERE##``.

        Encyclopedia Machine KB ``ownkb:chunk:r000478``-``r000480``,
        ``ownkb:claim:c002729``. ``*22*5#1*2#1##`` is ACKed and put on the
        bus (``$0494018FA1``) by F453, F453AV, F454, F459, F460, F461,
        MH200N and MyHomeServer1 in the firmware oracle (``sound-who22``);
        F450, H4684 and MH200 NACK it. ``5#0`` would alias the automatic
        seek and 16 and above overflow the one-nibble step of bt_multi, so
        both are refused.
        """
        target = _require_non_empty_where(where)
        s = _validate_frequency_step(step)
        message = cls(f"*22*5#{s}*{target}##")
        message._human_readable_log = f"Stepping the frequency up by {s} step(s) on sound diffusion device {target}."
        return message

    @classmethod
    def step_frequency_down(cls, where: str | int = "6", step: int = 1) -> OWNSoundDiffusionCommand:
        """Manual frequency step down by 1..15: ``*22*6#STEP*WHERE##`` (oracle bus ``$0494018FB1``, as ``step_frequency_up``)."""
        target = _require_non_empty_where(where)
        s = _validate_frequency_step(step)
        message = cls(f"*22*6#{s}*{target}##")
        message._human_readable_log = f"Stepping the frequency down by {s} step(s) on sound diffusion device {target}."
        return message

    @classmethod
    def speaker_address(cls, area: int | str, point: int | str) -> str:
        """Format structured speaker point target: 3#AREA#POINT (area 1..9, point 1..9)."""
        a, p = int(area), int(point)
        if not (1 <= a <= 9 and 1 <= p <= 9):
            raise ValueError(f"Area ({a}) and point ({p}) must both be between 1 and 9 per WHO 22 specification")
        return f"3#{a}#{p}"

    @classmethod
    def area_address(cls, area: int | str) -> str:
        """Format structured area target: 4#AREA (area 1..9)."""
        a = int(area)
        if not (1 <= a <= 9):
            raise ValueError(f"Area ({a}) must be between 1 and 9 per WHO 22 specification")
        return f"4#{a}"

    @classmethod
    def source_address(cls, source_id: int | str) -> str:
        """Format structured source target: ``2#SOURCE_ID``, source 1..4 (Encyclopedia who-22-sound-diffusion#core-parameters).

        Until 2.0.0b13 any positive value was accepted (``2#9``, audit
        2026-10-28 D7). The published Source ID domain is ``1..4``; the
        historical touchscreen matrix model admits sources 1..4 as well.
        A plant-specific source outside it (the traced ``7``) can be spelled
        directly as ``2#7``.
        """
        s = int(source_id)
        if not 1 <= s <= 4:
            raise ValueError(f"Source ID ({s}) must be between 1 and 4 per WHO 22 specification")
        return f"2#{s}"

    @classmethod
    def zone_control_address(cls, area: int | str, point: int | str) -> str:
        """Format a zone control target: 5#3#AREA#POINT (0..9; 5#3#0#0 is every zone)."""
        a, p = int(area), int(point)
        if not (0 <= a <= 9 and 0 <= p <= 9):
            raise ValueError(f"Area ({a}) and point ({p}) must both be between 0 and 9 per WHO 22 traces")
        return f"5#3#{a}#{p}"

    @classmethod
    def all_sources_address(cls) -> str:
        """Target address for all sources: '6'."""
        return "6"


register_event_parser(22, OWNSoundDiffusionEvent)
register_command_parser(22, OWNSoundDiffusionCommand)
