"""WHO 16: Sound diffusion and audio/video door entry events and commands."""

from __future__ import annotations

import re

from .base import OWNCommand, OWNEvent, register_command_parser, register_event_parser


class OWNSoundEvent(OWNEvent):
    """State reported by a WHO 16 sound source or amplifier zone."""

    def __init__(self, data: str) -> None:
        super().__init__(data)

        self._state = self._what
        self._zone = self._where or ""
        self._is_source_event = bool(re.fullmatch(r"10[1-9]", self._zone))
        self._source_id = (
            str(int(self._zone) - 100) if self._is_source_event else None
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
        self._is_seek_up: bool = False
        self._is_seek_down: bool = False

        if self._is_source_event:
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
        elif self._state is not None:
            self._human_readable_log = f"{subject} received command: {self._state}."
        elif self._dimension == 1 and self._dimension_value:
            try:
                self._volume = int(self._dimension_value[0])
            except ValueError:
                return
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
        return self._is_source_event

    @property
    def source_id(self) -> str | None:
        return self._source_id

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
        if int(where) < 100:
            where_str = f"40{camera_id}"
        elif int(where) >= 4000 and int(where) < 5000:
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
        message = cls(f"*#16*{where}*5##")
        message._human_readable_log = f"Requesting sound system status of {where}."
        return message

    @classmethod
    def turn_on(cls, where: str | int) -> OWNSoundCommand:
        message = cls(f"*16*3*{where}##")
        message._human_readable_log = f"Turning on audio zone {where}."
        return message

    @classmethod
    def turn_off(cls, where: str | int) -> OWNSoundCommand:
        message = cls(f"*16*13*{where}##")
        message._human_readable_log = f"Turning off audio zone {where}."
        return message

    @classmethod
    def select_source(
        cls, where: str | int, source_id: int | str
    ) -> list[OWNSoundCommand]:
        """Build the frames routing an amplifier zone to a source.

        `where` is the two-digit amplifier address `EA`, where `E` (1–9) is
        the environment and `A` (1–9) the amplifier within it. Single-digit,
        environment 0, amplifier 0, and non-numeric addresses cannot be routed
        to a matrix source and raise ValueError. Only routing rejects
        amplifier 0: the other builders pass any `WHERE` from the published
        `01`-`99` range through.

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
        if not re.fullmatch(r"[1-9]{2}", zone):
            raise ValueError(
                f"where must be a two-digit amplifier address with environment and amplifier 1-9, got '{where}'"
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
        message = cls(f"*16*1001*{where}##")
        message._human_readable_log = f"Increasing audio zone {where} volume."
        return message

    @classmethod
    def volume_down(cls, where: str | int) -> OWNSoundCommand:
        # 1101 = volume down by one step (1101..1115); 1000 is not a WHO 16 WHAT.
        message = cls(f"*16*1101*{where}##")
        message._human_readable_log = f"Decreasing audio zone {where} volume."
        return message

    @classmethod
    def set_volume(cls, where: str | int, volume: int | str) -> OWNSoundCommand:
        level = int(volume)
        if not 0 <= level <= 100:
            raise ValueError("volume must be between 0 and 100")
        message = cls(f"*#16*{where}*#1*{level}##")
        message._human_readable_log = (
            f"Setting audio zone {where} volume to {level}."
        )
        return message

    @classmethod
    def next_track(cls, where: str | int, step: int = 1) -> OWNSoundCommand:
        """Advance track or station forward (1..15 steps)."""
        s = int(step)
        if not 1 <= s <= 15:
            raise ValueError(f"step must be between 1 and 15, got {step}")
        what = 6000 + s
        message = cls(f"*16*{what}*{where}##")
        message._human_readable_log = (
            f"Advancing track/station on {where} by {s} step(s)."
        )
        return message

    @classmethod
    def previous_track(cls, where: str | int, step: int = 1) -> OWNSoundCommand:
        """Return track or station backward (1..15 steps)."""
        s = int(step)
        if not 1 <= s <= 15:
            raise ValueError(f"step must be between 1 and 15, got {step}")
        what = 6100 + s
        message = cls(f"*16*{what}*{where}##")
        message._human_readable_log = (
            f"Returning track/station on {where} by {s} step(s)."
        )
        return message

    @classmethod
    def seek_up(cls, where: str | int) -> OWNSoundCommand:
        """Seek forward to next receivable FM station."""
        message = cls(f"*16*5000*{where}##")
        message._human_readable_log = f"Seeking forward on {where}."
        return message

    @classmethod
    def seek_down(cls, where: str | int) -> OWNSoundCommand:
        """Seek backward to previous receivable FM station."""
        message = cls(f"*16*5100*{where}##")
        message._human_readable_log = f"Seeking backward on {where}."
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
        t = int(track)
        if t < 1:
            raise ValueError(f"track must be greater than or equal to 1, got {track}")
        message = cls(f"*#16*{where}*#7*{t}##")
        message._human_readable_log = (
            f"Selecting station/track {t} on {where}."
        )
        return message

    @classmethod
    def request_track(cls, where: str | int) -> OWNSoundCommand:
        """Request currently playing station or track number."""
        message = cls(f"*#16*{where}*7##")
        message._human_readable_log = f"Requesting station/track of {where}."
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
        khz = int(round(float(kilohertz)))
        if khz <= 0:
            raise ValueError(f"frequency in kHz must be positive, got {kilohertz}")
        message = cls(f"*#16*{where}*#6*0*{khz}##")
        message._human_readable_log = (
            f"Tuning {where} to {khz} kHz."
        )
        return message

    @classmethod
    def request_frequency(cls, where: str | int) -> OWNSoundCommand:
        """Request tuned frequency."""
        message = cls(f"*#16*{where}*6##")
        message._human_readable_log = f"Requesting frequency of {where}."
        return message

    @classmethod
    def start_rds(cls, where: str | int) -> OWNSoundCommand:
        """Start autonomous RDS station name reporting."""
        message = cls(f"*16*101*{where}##")
        message._human_readable_log = f"Starting RDS reporting on {where}."
        return message

    @classmethod
    def stop_rds(cls, where: str | int) -> OWNSoundCommand:
        """Stop autonomous RDS station name reporting."""
        message = cls(f"*16*102*{where}##")
        message._human_readable_log = f"Stopping RDS reporting on {where}."
        return message

    @classmethod
    def request_rds(cls, where: str | int) -> OWNSoundCommand:
        """Request RDS station text."""
        message = cls(f"*#16*{where}*8##")
        message._human_readable_log = f"Requesting RDS text of {where}."
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
        self._preset: int | None = None
        self._rds_text: str | None = None
        self._is_rds_blank: bool = False
        self._source_request: int | None = None
        self._matrix_area: int | None = None

        target = (
            f"{self._where}#{'#'.join(self._where_param)}"
            if self._where and self._where_param
            else (self._where or "")
        )
        self._target_address: str = target

        # Decode structured target class from target address
        if target:
            parts = target.split("#")
            kind = parts[0]
            if kind == "3" and len(parts) >= 3:
                self._target_type = "speaker"
                if parts[1].isdigit():
                    self._area = int(parts[1])
                if parts[2].isdigit():
                    self._point = int(parts[2])
            elif kind == "4" and len(parts) >= 2:
                self._target_type = "area"
                if parts[1].isdigit():
                    self._area = int(parts[1])
            elif kind == "2" and len(parts) >= 2:
                self._target_type = "source"
                if parts[1].isdigit():
                    self._source_id = int(parts[1])
            elif kind == "5" and len(parts) >= 3 and parts[1] == "2":
                self._target_type = "source"
                if parts[2].isdigit():
                    self._source_id = int(parts[2])
            elif kind == "5" and len(parts) >= 4 and parts[1] == "3":
                # 5#3#AREA#POINT: zone control of a wall unit; 5#3#0#0 is every zone.
                self._target_type = "zone_control"
                if parts[2].isdigit():
                    self._area = int(parts[2])
                if parts[3].isdigit():
                    self._point = int(parts[3])
            elif kind == "6":
                self._target_type = "all_sources"

        # Relative volume step in WHAT
        if self._what in (3, 4):
            if self._what_param and self._what_param[0].isdigit():
                self._volume_step = int(self._what_param[0])
            else:
                self._volume_step = 1

        # Source named by a power-on (1#TYPE#SOURCE) or a matrix route (35#TYPE#AREA#SOURCE)
        if self._what == 1 and len(self._what_param) >= 2 and self._what_param[1].isdigit():
            self._source_request = int(self._what_param[1])
        elif self._what == 35 and len(self._what_param) >= 3:
            if self._what_param[0].isdigit():
                self._multimedia_type = int(self._what_param[0])
            if self._what_param[1].isdigit():
                self._matrix_area = int(self._what_param[1])
            if self._what_param[2].isdigit():
                self._source_request = int(self._what_param[2])
        elif self._what == 33 and self._what_param and self._what_param[0].isdigit():
            self._preset = int(self._what_param[0])

        # Dimensions
        if self._dimension == 1 and self._dimension_value:
            if self._dimension_value[0].isdigit():
                self._volume = int(self._dimension_value[0])
        elif self._dimension == 12 and self._dimension_value:
            if self._dimension_value[0].isdigit():
                self._device_state = int(self._dimension_value[0])
            if len(self._dimension_value) > 1 and self._dimension_value[1].isdigit():
                self._multimedia_type = int(self._dimension_value[1])
        elif self._dimension in (5, 11) and self._dimension_value:
            # Tuner frequency after one leading value (band ID: 1 = FM, 2 = AM-LW, 3 = AM-MW, 4 = AM-SW);
            # dimension 11 adds the station preset.
            # The unit is 10 kHz on an MH200N / F454 and 100 kHz on MyHomeServer1;
            # the FM ranges (8750..10800, 875..1080) do not overlap.
            expected = 2 if self._dimension == 5 else 3
            values = self._dimension_value
            if len(values) == expected and values[1].isdigit():
                if values[0].isdigit():
                    self._frequency_band = int(values[0])
                khz = next((v for v in (int(values[1]) * 10, int(values[1]) * 100) if 87500 <= v <= 108000), 0)
                if khz:
                    self._frequency_khz = khz
                    self._frequency_mhz = round(khz / 1000.0, 2)
                    if self._dimension == 11 and values[2].isdigit() and int(values[2]) > 0:
                        self._preset = int(values[2])
        elif self._dimension == 6 and len(self._dimension_value) == 1:
            if self._dimension_value[0].isdigit() and int(self._dimension_value[0]) >= 1:
                self._preset = int(self._dimension_value[0])
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
            preset = f" (station {self._preset})" if self._preset else ""
            self._human_readable_log = (
                f"{subject} is tuned to {self._frequency_khz / 1000:.2f} MHz{preset}."
            )
        elif self._dimension == 6 and self._preset is not None:
            self._human_readable_log = f"{subject} station is {self._preset}."
        elif self._dimension == 10 and (self._rds_text is not None or self._is_rds_blank):
            self._human_readable_log = f"{subject} RDS text: '{self._rds_text or ''}'."
        elif self._dimension is not None:
            self._human_readable_log = f"{subject} reported dimension {self._dimension}."
        elif self._what == 1 and self._source_request is not None:
            self._human_readable_log = f"{subject} is switched ON with source {self._source_request}."
        elif self._what in (1, 2):
            self._human_readable_log = f"{subject} is switched ON."
        elif self.is_atomic_off:
            self._human_readable_log = f"{subject} is switched OFF (atomic)."
        elif self._what == 0:
            self._human_readable_log = f"{subject} is switched OFF."
        elif self._what == 35 and self._source_request is not None:
            area_str = f" on matrix area {self._matrix_area}" if self._matrix_area is not None and self._matrix_area != 1 else ""
            self._human_readable_log = f"{subject} is routed to source {self._source_request}{area_str}."
        elif self._what == 31:
            self._human_readable_log = f"{subject} started RDS reporting."
        elif self._what == 32:
            self._human_readable_log = f"{subject} stopped RDS reporting."
        elif self._what == 33 and self._preset is not None:
            self._human_readable_log = f"{subject} stored frequency to preset {self._preset}."
        elif self._what == 34:
            self._human_readable_log = f"{subject} follow-me."
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
        """FM frequency in kHz from dimension 5 or 11 (reported in 10 kHz units on an MH200N, 100 kHz on a MyHomeServer1), if in the FM band."""
        return self._frequency_khz

    @property
    def preset(self) -> int | None:
        """Stored tuner station (1..): dimension 6, or dimension 11 where 0 means 'not stored'."""
        return self._preset

    @property
    def rds_text(self) -> str | None:
        """RDS programme service text from dimension 10; ``None`` when blank or malformed."""
        return self._rds_text

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
        """Matrix audio distribution channel / area (e.g. 1 in 35#4#1#2)."""
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
        """Source named by a command: ``1#TYPE#S`` (power on with source) or ``35#TYPE#AREA#S`` (route)."""
        return self._source_request

    @property
    def is_route_source(self) -> bool:
        """True for WHAT 35, which routes the target zone to a source on the matrix."""
        return self._what == 35

    @property
    def is_atomic_off(self) -> bool:
        """True for ``0#4#0``, the single-frame power off (a plain WHAT 0 carries no parameters)."""
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
        target = str(where).strip()
        message = cls(f"*#22*{target}##")
        message._human_readable_log = f"Requesting status of sound diffusion device {target}."
        return message

    @classmethod
    def turn_on(cls, where: str | int) -> OWNSoundDiffusionCommand:
        target = str(where).strip()
        message = cls(f"*22*1*{target}##")
        message._human_readable_log = f"Turning ON sound diffusion device {target}."
        return message

    @classmethod
    def turn_off(cls, where: str | int) -> OWNSoundDiffusionCommand:
        target = str(where).strip()
        message = cls(f"*22*0*{target}##")
        message._human_readable_log = f"Turning OFF sound diffusion device {target}."
        return message

    @classmethod
    def turn_on_with_source(
        cls, where: str | int, source_id: int | str, multimedia_type: int | str = 4
    ) -> OWNSoundDiffusionCommand:
        """Power a zone on and play a source: ``*22*1#TYPE#SOURCE*WHERE##`` (TYPE 4 on the traced plant)."""
        target = str(where).strip()
        source = int(source_id)
        if source < 1:
            raise ValueError("source must be positive")
        message = cls(f"*22*1#{int(multimedia_type)}#{source}*{target}##")
        message._human_readable_log = f"Turning ON sound diffusion device {target} with source {source}."
        return message

    @classmethod
    def turn_off_atomic(cls, where: str | int, multimedia_type: int | str = 4) -> OWNSoundDiffusionCommand:
        """Power a zone off in one frame: ``*22*0#TYPE#0*WHERE##``."""
        target = str(where).strip()
        message = cls(f"*22*0#{int(multimedia_type)}#0*{target}##")
        message._human_readable_log = f"Turning OFF sound diffusion device {target} (atomic)."
        return message

    @classmethod
    def route_source(
        cls,
        where: str | int,
        source_id: int | str,
        matrix_area: int | str = 1,
        multimedia_type: int | str = 4,
    ) -> OWNSoundDiffusionCommand:
        """Route a zone to a source on the matrix: ``*22*35#TYPE#AREA#SOURCE*WHERE##``.

        Parameters:
            where: Target zone address (e.g. 3#1#1).
            source_id: Source ID (e.g. 1, 2, 7 for FM Tuner).
            matrix_area: Matrix distribution channel/area (default 1; area 0 on plant broadcast).
            multimedia_type: Audio routing mode (default 4 = Stereo).
        """
        target = str(where).strip()
        source = int(source_id)
        if source < 1:
            raise ValueError("source must be positive")
        area = int(matrix_area)
        mm_type = int(multimedia_type)
        message = cls(f"*22*35#{mm_type}#{area}#{source}*{target}##")
        area_str = f" on matrix area {area}" if area != 1 else ""
        message._human_readable_log = f"Routing sound diffusion device {target} to source {source}{area_str}."
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
        target = str(where).strip()
        khz = int(round(float(frequency_khz)))
        if khz <= 0:
            raise ValueError("frequency must be positive")
        freq_10k = khz // 10
        message = cls(f"*#22*{target}*#5*{int(band)}*{freq_10k}##")
        message._human_readable_log = f"Tuning sound diffusion device {target} to {khz} kHz ({khz/1000.0:.2f} MHz)."
        return message

    @classmethod
    def request_frequency(cls, where: str | int) -> OWNSoundDiffusionCommand:
        """Request tuned frequency: ``*#22*WHERE*5##``."""
        target = str(where).strip()
        message = cls(f"*#22*{target}*5##")
        message._human_readable_log = f"Requesting frequency for sound diffusion device {target}."
        return message

    @classmethod
    def set_preset(
        cls,
        where: str | int,
        preset: int | str,
        frequency_khz: int | float | None = None,
        band: int = 1,
    ) -> OWNSoundDiffusionCommand:
        """Select or store a preset station: ``*#22*WHERE*#6*PRESET##`` or ``*#22*WHERE*#11*BAND*FREQ*PRESET##``."""
        target = str(where).strip()
        p = int(preset)
        if p < 1:
            raise ValueError("preset must be positive")
        if frequency_khz is not None:
            khz = int(round(float(frequency_khz)))
            freq_10k = khz // 10
            message = cls(f"*#22*{target}*#11*{int(band)}*{freq_10k}*{p}##")
            message._human_readable_log = f"Programming preset {p} on {target} to {khz} kHz."
        else:
            message = cls(f"*#22*{target}*#6*{p}##")
            message._human_readable_log = f"Selecting preset {p} on sound diffusion device {target}."
        return message

    @classmethod
    def request_preset(cls, where: str | int) -> OWNSoundDiffusionCommand:
        """Request active preset: ``*#22*WHERE*6##``."""
        target = str(where).strip()
        message = cls(f"*#22*{target}*6##")
        message._human_readable_log = f"Requesting preset for sound diffusion device {target}."
        return message

    @classmethod
    def start_rds(cls, where: str | int) -> OWNSoundDiffusionCommand:
        """Start RDS reporting: ``*22*31*WHERE##``."""
        target = str(where).strip()
        message = cls(f"*22*31*{target}##")
        message._human_readable_log = f"Starting RDS reporting on sound diffusion device {target}."
        return message

    @classmethod
    def stop_rds(cls, where: str | int) -> OWNSoundDiffusionCommand:
        """Stop RDS reporting: ``*22*32*WHERE##``."""
        target = str(where).strip()
        message = cls(f"*22*32*{target}##")
        message._human_readable_log = f"Stopping RDS reporting on sound diffusion device {target}."
        return message

    @classmethod
    def store_preset(cls, where: str | int, preset: int | str) -> OWNSoundDiffusionCommand:
        """Store current tuned frequency into preset: ``*22*33#PRESET*WHERE##``."""
        target = str(where).strip()
        p = int(preset)
        message = cls(f"*22*33#{p}*{target}##")
        message._human_readable_log = f"Storing current frequency into preset {p} on {target}."
        return message

    @classmethod
    def send_rds_text(cls, where: str | int, text: str) -> OWNSoundDiffusionCommand:
        """Format an 8-character RDS Program Service frame: ``*#22*WHERE*#10*c0*...*c7##``.

        Note: In ``bt_multi`` gateway firmwares (F453AV, F454, F459, F460, F461,
        MH200N, MH202, MyHomeServer1), ``DIMENSION 10`` is an upward tuner-to-gateway
        report and client-originated ``*#22*WHERE*#10*...##`` writes are NACKed with
        no SCS bus output. Use ``start_rds``, ``stop_rds``, and ``request_rds`` for
        client-to-gateway RDS control.
        """
        target = str(where).strip()
        formatted = text[:8].ljust(8)
        codes = [str(ord(c)) for c in formatted]
        message = cls(f"*#22*{target}*#10*{'*'.join(codes)}##")
        message._human_readable_log = f"Broadcasting RDS text '{formatted.strip()}' to sound diffusion device {target}."
        return message

    @classmethod
    def request_rds(cls, where: str | int) -> OWNSoundDiffusionCommand:
        """Request RDS station text: ``*#22*WHERE*10##``."""
        target = str(where).strip()
        message = cls(f"*#22*{target}*10##")
        message._human_readable_log = f"Requesting RDS text for sound diffusion device {target}."
        return message

    @classmethod
    def open_paging(cls, where: str | int = "5#3#0#0", channel: int | str = 1) -> OWNSoundDiffusionCommand:
        """Open a paging channel: ``*22*19#CHANNEL*WHERE##`` (``5#3#0#0`` is the whole house)."""
        target = str(where).strip()
        message = cls(f"*22*19#{int(channel)}*{target}##")
        message._human_readable_log = f"Opening paging channel {int(channel)} on {target}."
        return message

    @classmethod
    def start_paging_voice(cls, where: str | int = "5#3#0#0", channel: int | str = 1) -> OWNSoundDiffusionCommand:
        """Start the paging voice transmission: ``*22*20#CHANNEL*WHERE##``."""
        target = str(where).strip()
        message = cls(f"*22*20#{int(channel)}*{target}##")
        message._human_readable_log = f"Starting paging voice on channel {int(channel)} on {target}."
        return message

    @classmethod
    def volume_up(cls, where: str | int, step: int = 1) -> OWNSoundDiffusionCommand:
        s = int(step)
        if s < 1:
            raise ValueError("step must be positive")
        target = str(where).strip()
        what = f"3#{s}" if s > 1 else "3"
        message = cls(f"*22*{what}*{target}##")
        message._human_readable_log = f"Increasing sound diffusion device {target} volume."
        return message

    @classmethod
    def volume_down(cls, where: str | int, step: int = 1) -> OWNSoundDiffusionCommand:
        s = int(step)
        if s < 1:
            raise ValueError("step must be positive")
        target = str(where).strip()
        what = f"4#{s}" if s > 1 else "4"
        message = cls(f"*22*{what}*{target}##")
        message._human_readable_log = f"Decreasing sound diffusion device {target} volume."
        return message

    @classmethod
    def set_volume(cls, where: str | int, volume: int | str) -> OWNSoundDiffusionCommand:
        target = str(where).strip()
        level = int(volume)
        if not 0 <= level <= 31:
            raise ValueError("volume must be between 0 and 31 per WHO 22 specification")
        message = cls(f"*#22*{target}*#1*{level}##")
        message._human_readable_log = f"Setting sound diffusion device {target} volume to {level}."
        return message

    @classmethod
    def request_volume(cls, where: str | int) -> OWNSoundDiffusionCommand:
        target = str(where).strip()
        message = cls(f"*#22*{target}*1##")
        message._human_readable_log = f"Requesting volume status for sound diffusion device {target}."
        return message

    @classmethod
    def request_device_state(cls, where: str | int) -> OWNSoundDiffusionCommand:
        target = str(where).strip()
        message = cls(f"*#22*{target}*12##")
        message._human_readable_log = f"Requesting device state for sound diffusion device {target}."
        return message

    @classmethod
    def next_track(cls, where: str | int = "6") -> OWNSoundDiffusionCommand:
        target = str(where).strip()
        message = cls(f"*22*11*{target}##")
        message._human_readable_log = f"Next track on sound diffusion device {target}."
        return message

    @classmethod
    def previous_track(cls, where: str | int = "6") -> OWNSoundDiffusionCommand:
        target = str(where).strip()
        message = cls(f"*22*12*{target}##")
        message._human_readable_log = f"Previous track on sound diffusion device {target}."
        return message

    @classmethod
    def next_station(cls, where: str | int = "6") -> OWNSoundDiffusionCommand:
        target = str(where).strip()
        message = cls(f"*22*9*{target}##")
        message._human_readable_log = f"Next station on sound diffusion device {target}."
        return message

    @classmethod
    def previous_station(cls, where: str | int = "6") -> OWNSoundDiffusionCommand:
        target = str(where).strip()
        message = cls(f"*22*10*{target}##")
        message._human_readable_log = f"Previous station on sound diffusion device {target}."
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
        """Format structured source target: 2#SOURCE_ID (source_id >= 1)."""
        s = int(source_id)
        if s < 1:
            raise ValueError(f"Source ID ({s}) must be positive per WHO 22 specification")
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
