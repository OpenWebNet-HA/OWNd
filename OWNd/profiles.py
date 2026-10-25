"""Gateway capabilities and conservative transport defaults."""

from __future__ import annotations

from dataclasses import dataclass, field
import re

WHO_LIGHTING = 1
WHO_AUTOMATION = 2
WHO_LOAD_CONTROL = 3
WHO_HEATING = 4
WHO_ALARM = 5
WHO_DOOR_ENTRY = 6
WHO_LOCK = 8
WHO_INTERCOM = 8
WHO_CEN = 15
WHO_SOUND = 16
WHO_SCENARIO = 17
WHO_ENERGY = 18
WHO_SOUND_DIFFUSION = 22
WHO_CEN_PLUS = 25

DEFAULT_SUPPORTED_WHO = (
    WHO_LIGHTING,
    WHO_AUTOMATION,
    WHO_LOAD_CONTROL,
    WHO_HEATING,
    WHO_CEN,
    WHO_SOUND,
    WHO_SCENARIO,
    WHO_ENERGY,
    WHO_SOUND_DIFFUSION,
    WHO_CEN_PLUS,
)


def parse_firmware_version(
    version: str | tuple[int, ...] | list[int] | None,
) -> tuple[int, ...]:
    """Parse and normalize firmware version into a comparable integer tuple.

    Zero-pads to at least 3 parts (V, R, B) to guarantee semantic comparison
    without tuple-length comparison flaws (e.g. (2, 1) < (2, 1, 7)).
    """
    if version is None:
        return (0, 0, 0)
    if isinstance(version, (list, tuple)):
        parts: list[int] = []
        for item in version:
            if isinstance(item, int):
                parts.append(item)
            elif isinstance(item, str):
                parts.extend(int(m) for m in re.findall(r"\d+", item))
            else:
                pass
    elif isinstance(version, str):
        parts = [int(m) for m in re.findall(r"\d+", version)]
    elif isinstance(version, int):
        parts = [version]
    else:
        parts = []
    while len(parts) < 3:
        parts.append(0)
    return tuple(parts)


@dataclass(frozen=True, slots=True)
class GatewayProfile:
    """Capabilities and safe defaults for an OpenWebNet gateway family."""

    model_name: str
    max_command_sessions: int = 1
    default_command_sessions: int = 1
    default_port: int = 20000
    command_queue_delay: float = 0.05
    max_queue_size: int = 200
    event_keepalive_interval: float | None = None
    requires_password: bool = True
    recommended_transition_mode: str = "software_stepped"
    supports_energy_instant_power: bool = True
    supports_audio: bool = True
    supports_hmac: bool = False
    auth_measured: bool = True
    # False when no WHO 16/22 reply from this gateway is captured; sound support
    # is then the class default and is labelled "Sound unmeasured".
    audio_measured: bool = True
    supports_native_transitions: bool = False
    supports_extended_frames: bool = False
    # How the command session treats frames that inject state for a virtual
    # device. None means unverified: no capture or published oracle verdict
    # exists for this family. Only F461Profile sets them, from live captures.
    # Reply-form frames *#1*W*1*..##, *#2*W*10*..##, *#4*W*0*T##, *#13**D*..##.
    supports_dimension_response_injection: bool | None = None
    # WHO 4 Dimension #0 temperature writes (*#4*W*#0*TTTT##).
    supports_who4_command_injection: bool | None = None
    # WHO 18 reply-form frames (*#18*W*DIM*VAL##). True means acknowledged on
    # the command session, not that the value is shown to reach the bus.
    supports_who18_response_injection: bool | None = None
    supported_who: tuple[int, ...] = DEFAULT_SUPPORTED_WHO
    extra_features: tuple[str, ...] = ()
    firmware_version: str | None = field(default=None, kw_only=True)

    @property
    def max_workers(self) -> int:
        return self.max_command_sessions

    @property
    def default_workers(self) -> int:
        return self.default_command_sessions

    @property
    def max_command_workers(self) -> int:
        return self.max_command_sessions

    @property
    def command_delay(self) -> float:
        return self.command_queue_delay

    @property
    def display_name(self) -> str:
        return f"{self.model_name} Gateway"

    @property
    def concurrency_summary(self) -> str:
        """Formatted concurrency string for documentation and diagnostics."""
        suffix = "session" if self.max_command_sessions == 1 else "sessions"
        if self.default_command_sessions > 1:
            return f"{self.max_command_sessions} {suffix} ({self.default_command_sessions} default)"
        return f"{self.max_command_sessions} {suffix}"

    @property
    def queue_delay_summary(self) -> str:
        """Formatted queue pacing delay string."""
        return f"{int(self.command_queue_delay * 1000)} ms"

    @property
    def keepalive_summary(self) -> str:
        """Formatted keepalive interval string."""
        if self.event_keepalive_interval is not None:
            return f"{int(self.event_keepalive_interval)} s"
        return "OS TCP only"

    @property
    def features_summary(self) -> str:
        """Formatted capabilities and features string."""
        if isinstance(self, GenericGatewayProfile):
            return "Conservative fallback"
        features: list[str] = []
        if self.command_queue_delay >= 0.15:
            features.append("Safe pacing")
        if not self.auth_measured:
            features.append("Auth unmeasured")
        elif self.supports_hmac:
            features.append("HMAC-SHA2")
        elif self.requires_password:
            features.append("Legacy password auth")
        if self.supports_native_transitions:
            features.append("Native transitions")
        if self.supports_extended_frames:
            features.append("Extended frames")
        if self.supports_who(WHO_SOUND) or self.supports_audio:
            if self.audio_measured:
                features.append("Sound system (WHO 16)")
            else:
                features.append("Sound unmeasured")
        if self.supports_who(WHO_ALARM):
            features.append("Burglar alarm (WHO 5)")
        features.extend(self.extra_features)
        return ", ".join(features) or "Conservative fallback"

    def supports_who(self, who: int) -> bool:
        """Return whether the profile advertises a WHO subsystem."""
        return who in self.supported_who

    def supports_session_count(self, count: int) -> bool:
        """Return whether a command-session count is safe for this gateway."""
        return 1 <= count <= self.max_command_sessions

    def can_support_workers(self, count: int) -> bool:
        return self.supports_session_count(count)


# Class default minus CEN+ (WHO 25), for gateways the Legrand tables list as NO.
_DEFAULT_WITHOUT_CEN_PLUS = tuple(
    who for who in DEFAULT_SUPPORTED_WHO if who != WHO_CEN_PLUS
)

# Firmware at which Legrand documents CEN+ on the F453AV (WHO 25 p. 13).
_F453AV_CEN_PLUS_FIRMWARE = (2, 1, 7)

# Firmware generation at which physical H/L4684 captures show WHO 22 (bt_multi)
# alongside WHO 16 (MyHOME#466 comment 6398442412: FW 6.0.11, distro 6.0.0).
_H4684_WHO22_FIRMWARE = (6, 0, 0)


class F452Profile(GatewayProfile):
    """The F452 Web Server.

    Only WHO 25 is documented: Legrand's WHO 25 specification (p. 13,
    https://developer.legrand.com/uploads/2019/12/WHO_25.pdf) and WHO 15-25
    specification (p. 24, https://developer.legrand.com/uploads/2019/12/WHO_15-25.pdf)
    list the F452 as NO for CEN+ and dry contact / IR state, so WHO 25 is
    dropped. Every other subsystem is the class default and unverified.
    Sessions and authentication are the class defaults, not measurements;
    pacing is copied from the MH200 because nothing is measured.
    """

    def __init__(self) -> None:
        super().__init__(
            model_name="F452",
            command_queue_delay=0.15,
            auth_measured=False,
            audio_measured=False,
            supported_who=_DEFAULT_WITHOUT_CEN_PLUS,
        )


class F452VProfile(GatewayProfile):
    """The F452V Web Server.

    Only WHO 25 is documented: Legrand's WHO 25 specification (p. 13,
    https://developer.legrand.com/uploads/2019/12/WHO_25.pdf) and WHO 15-25
    specification (p. 24, https://developer.legrand.com/uploads/2019/12/WHO_15-25.pdf)
    list the F452V as NO for CEN+ and dry contact / IR state, so WHO 25 is
    dropped. Every other subsystem is the class default and unverified.
    Sessions and authentication are the class defaults, not measurements;
    pacing is copied from the MH200 because nothing is measured.
    """

    def __init__(self) -> None:
        super().__init__(
            model_name="F452V",
            command_queue_delay=0.15,
            auth_measured=False,
            audio_measured=False,
            supported_who=_DEFAULT_WITHOUT_CEN_PLUS,
        )


class F453Profile(GatewayProfile):
    """The F453 Web Server.

    Verified by the firmware oracle (``F453 010100``, ``results/F453/010100/oracle/full/``)
    and Legrand specifications:
    - WHO 1 & 2 (Lighting & Automation): ``bt_fls`` translates all lighting and
      automation requests onto the SCS bus.
    - WHO 3 (Load Control): ``bt_energia`` translates all 9 WHO 3 force and
      measurement requests onto the SCS bus (``energy-ts10.tsv``).
    - WHO 4 (Thermoregulation): ``bt_H4690`` translates zone and central-unit
      queries and commands.
    - WHO 15 & 25 (CEN & CEN+): ``bt_cen`` translates both classic CEN and
      CEN+ / dry-contact frames; also listed as YES in Legrand's WHO 25
      specification (p. 13, https://developer.legrand.com/uploads/2019/12/WHO_25.pdf)
      and WHO 15-25 specification (p. 24,
      https://developer.legrand.com/uploads/2019/12/WHO_15-25.pdf).
    - WHO 16 & 22 (Sound System): packages both ``bt_difson`` (answering
      ``*#16*0*5##`` and 69 other WHO 16 requests with ``ack``/``out``) and
      ``bt_multi`` (answering 60 WHO 22 requests with ``out``) in ``sound-ts08.tsv``
      and ``sound-who22.tsv``.
    - WHO 18 (Energy Management): packages ``bt_energy`` (answering ``*#18*51*51##``
      with ``ack``/``out``) alongside the TiF453 Energy Management chapter (pp. 39-40,
      https://www.bticino.be/sites/default/files/Service-en-support/software-en-schemas2/My%20Home/Tif453/TiF453%20Version2_0_07/Software_Manual_F453_EN.pdf).
    - Authentication: ``openserver`` uses legacy OPEN password authentication
      (no HMAC), matching the TiF453 user guide (p. 17, default 12345).
    """

    def __init__(self) -> None:
        super().__init__(
            model_name="F453",
            command_queue_delay=0.15,
        )


class F453AVProfile(GatewayProfile):
    """The F453AV Web Server (Legrand Arteor 573992).

    Verified by the firmware oracle (``F453AV 030014``, ``results/F453AV/030014/oracle/full/``)
    and Legrand specifications:
    - WHO 25: Legrand's WHO 25 specification (p. 13,
      https://developer.legrand.com/uploads/2019/12/WHO_25.pdf) and WHO 15-25
      specification (p. 24, https://developer.legrand.com/uploads/2019/12/WHO_15-25.pdf)
      list F453AV v1.0.19 as NO and F453AV / 573992 v2.1.7 as YES (verified on
      ``030014`` via ``bt_cen``). Behaviour between those two versions is not
      documented. Firmware below 2.1.7, or unknown firmware, is treated as
      without CEN+; that is a conservative choice, not a documented threshold.
    - WHO 3 & 18: ``bt_energia`` (WHO 3) and ``bt_energy`` (WHO 18) are both
      packaged and verified in ``energy-ts10.tsv`` alongside the TiF453AV user
      guide (pp. 39-40,
      https://www.bticino.be/sites/default/files/Service-en-support/software-en-schemas2/My%20Home/TiF453AV/Version%203_0_64/Software_Manual_F453AV_EN.pdf).
    - WHO 16 & 22: packages both ``bt_difson`` (answering ``*#16*0*5##`` and 69
      other WHO 16 requests with ``ack``/``out``) and ``bt_multi`` (answering 58
      WHO 22 requests with ``out``) in ``sound-ts08.tsv`` and ``sound-who22.tsv``.
    - Authentication: ``openserver`` uses legacy OPEN password authentication
      (no HMAC), matching the TiF453AV user guide (p. 18, default 12345).
    - WHO 7: Legrand's WHO 7 specification names the F453AV as its device
      (p. 1, https://developer.legrand.com/uploads/2019/12/WHO_7.pdf). OWNd does
      not model WHO 7, so it is not listed in ``supported_who``.
    """

    def __init__(
        self,
        firmware_version: str | tuple[int, ...] | list[int] | None = None,
    ) -> None:
        if not firmware_version:
            fw_str = None
        elif isinstance(firmware_version, (list, tuple)):
            fw_str = ".".join(str(p) for p in firmware_version)
        else:
            fw_str = str(firmware_version)
        has_cen_plus = (
            parse_firmware_version(firmware_version) >= _F453AV_CEN_PLUS_FIRMWARE
        )
        super().__init__(
            model_name="F453AV",
            firmware_version=fw_str,
            command_queue_delay=0.15,
            supported_who=(
                DEFAULT_SUPPORTED_WHO if has_cen_plus else _DEFAULT_WITHOUT_CEN_PLUS
            ),
            extra_features=() if has_cen_plus else ("CEN+ documented from FW 2.1.7",),
        )


class F454Profile(GatewayProfile):
    """The F454 Web Server (Legrand 003598).

    Verified by the firmware oracle (``F454 020051``, ``results/F454/020051/oracle/full/``):
    packages ``openserver`` (HMAC-SHA2), ``bt_fls`` (WHO 1/2), ``bt_energia`` (WHO 3),
    ``bt_H4690`` (WHO 4), ``bt_cen`` (WHO 15/25), ``bt_difson`` (WHO 16, answering
    ``*#16*0*5##`` and 69 other WHO 16 requests with ``ack``/``out``), ``bt_multi``
    (WHO 22), and ``bt_energy`` (WHO 18).
    """

    def __init__(self) -> None:
        super().__init__(
            model_name="F454",
            max_command_sessions=4,
            max_queue_size=250,
            event_keepalive_interval=90,
            supports_hmac=True,
            supports_native_transitions=True,
            supports_extended_frames=True,
        )


class F455Profile(GatewayProfile):
    """The F455 Basic Gateway (0 035 94).

    Entry-level IP gateway connecting an Ethernet LAN to a single SCS
    automation/lighting bus (WHO 1, 2, 4, 18). Per official installer manual
    RA00125AB ("Funzioni principali"):
    - Funzioni gestite: Luci, Automazione, Termoregolazione, Gestione energia.
    - Funzioni non gestite: Videocitofonia, Diffusione sonora (WHO 16/22),
      Antintrusione (WHO 5), Gestione avanzata tapparelle (positioned covers),
      Lighting, scenari avanzati.
    - Hardware socket budget: max 5 simultaneous sockets. Defaults to 2 command
      sessions (leaving headroom for the event session, reconnection overlap,
      and the mobile app) with a ceiling of 4.
    - Keepalive: no reconnect loop observed on firmware 1.0.86 with OS TCP
      keepalive only (MyHOME#466).
    """

    def __init__(self) -> None:
        super().__init__(
            model_name="F455",
            max_command_sessions=4,
            default_command_sessions=2,
            max_queue_size=250,
            supports_audio=False,
            supports_hmac=True,
            supports_native_transitions=True,
            supports_extended_frames=True,
            supported_who=(
                WHO_LIGHTING,
                WHO_AUTOMATION,
                WHO_LOAD_CONTROL,
                WHO_HEATING,
                WHO_CEN,
                WHO_SCENARIO,
                WHO_ENERGY,
                WHO_CEN_PLUS,
            ),
        )


class F461Profile(GatewayProfile):
    """The F461 server gateway stack (AArch64 / ARM64).

    Subsystems:
    - WHO 3 (Load Control): Like MyHomeServer1 and F460, F461 firmware
      (`020011`) does not package the ``bt_energia`` translator and strictly
      NACKs all WHO 3 requests without bus activity (`results/F461/020011/oracle/full/energy-ts10.tsv`).
      WHO 3 is therefore excluded from ``supported_who``.

    Injection flags, from the live F461 2.0.11 capture of 2026-10-18
    (MyHOME ``tests/fixtures/traces/f461_live_2026-10-18``) and the plant
    check in MyHOME#750 (comment 6277050571):
    - Reply-form frames are not injected. ``*#1*08*1*150*0##`` and
      ``*#2*25*10*10*50*0*0##`` are NACKed; ``*#4*2*0*0999##`` and
      ``*#13**0*22*51*00*999##`` are answered as reads with the real zone 2
      temperature and the gateway's own time.
    - ``*#4*50*#0*0215##`` is ACKed (0.155 s).
    - ``*#18*51*113*450##``, ``*#18*51*51*12345##`` and ``*#18*51*54*320##``
      are ACKed (1.27-1.40 s) with no event after the ACK.
    """

    def __init__(self) -> None:
        super().__init__(
            model_name="F461",
            max_command_sessions=4,
            command_queue_delay=0.05,
            max_queue_size=250,
            event_keepalive_interval=90,
            audio_measured=False,
            supports_hmac=True,
            supports_native_transitions=True,
            supports_extended_frames=True,
            supports_dimension_response_injection=False,
            supports_who4_command_injection=True,
            supports_who18_response_injection=True,
            supported_who=tuple(
                w for w in DEFAULT_SUPPORTED_WHO if w != WHO_LOAD_CONTROL
            ),
        )


class MH200Profile(GatewayProfile):
    """The original MH200 (WHO=13 device type 4).

    WHO 16 is verified: on a live MH200 (``*#13**15*4##``, firmware
    ``*#13**16*2*1*0##`` = 2.1.0, 2026-09-23) ``*#16*0*5##`` returned a
    state frame for every amplifier and source within 0.6 s, and the bare
    ``*#16*0##`` returned none (#53). Pacing, queue size, keepalive and the other
    subsystems are copied from the MH200N profile and have not been
    measured on an MH200.

    WHO 3 (Load Control) is verified by the firmware oracle: MH200 firmware
    2.1.2 (``020102``) ships ``bt_energia`` and translates all 9 WHO 3 force
    and measurement requests onto the SCS bus (``results/MH200/020102/oracle/full/energy-ts10.tsv``).

    WHO 25 covers both CEN+ and dry contact / IR state functions (WHAT 31/32).
    As documented in Legrand's WHO 25 specification ("Dry contact and IR state
    functions", v1.0.0, 2010, https://developer.legrand.com/uploads/2019/12/WHO_25.pdf,
    page 13 "Gateways that allow the function": MH200 NO, MH200N 03565 YES),
    the legacy MH200 firmware supports neither, supporting only classic
    CEN (WHO 15).

    WHO 6 and 8 (video door entry) are listed because a live MH200 (firmware
    2.1.0, MyHOME#667) relayed ``*8*1#1#4*74##``, ``*8*9#1#4*73##`` and
    ``*6*9##`` from a 2-wire entrance panel. They are bus-level subsystems: a
    plant without a door entry system never emits them. No other gateway
    model has a capture either way, so they are not in ``DEFAULT_SUPPORTED_WHO``.
    """

    def __init__(self) -> None:
        super().__init__(
            model_name="MH200",
            command_queue_delay=0.15,
            max_queue_size=100,
            event_keepalive_interval=90,
            supports_energy_instant_power=False,
            supported_who=(
                WHO_LIGHTING,
                WHO_AUTOMATION,
                WHO_LOAD_CONTROL,
                WHO_HEATING,
                WHO_DOOR_ENTRY,
                WHO_LOCK,
                WHO_CEN,
                WHO_SOUND,
                WHO_SCENARIO,
            ),
        )


class MH200NProfile(GatewayProfile):
    """The MH200N.

    Supports sound system discovery (WHO 16) and WHO 22 sound diffusion
    (``bt_multi`` translator verified in firmware 1.1.8 and live F500 tuner
    traces). Hardware verified answering ``*#16*0*5##`` without NACK and
    returning full source and amplifier inventory (MyHOME#427 / comment
    5848181845).

    WHO 3 (Load Control) is verified by the firmware oracle: MH200N firmware
    1.1.8 (``010108``) ships ``bt_energia`` and translates all 9 WHO 3 force
    and measurement requests onto the SCS bus (``results/MH200N/010108/oracle/full/energy-ts10.tsv``).

    WHO 6 and 8 are listed by family with the MH200, whose capture proves the
    relay (see ``MH200Profile``). Nothing has been captured on an MH200N itself;
    its 1.1.8 image ships a ``bt_vct`` translator, which the firmware oracle
    target does not run, so the oracle's WHO 8 NACKs for it are not evidence.
    """

    def __init__(self) -> None:
        super().__init__(
            model_name="MH200N",
            command_queue_delay=0.15,
            max_queue_size=100,
            event_keepalive_interval=90,
            supports_energy_instant_power=False,
            supports_audio=True,
            supported_who=(
                WHO_LIGHTING,
                WHO_AUTOMATION,
                WHO_LOAD_CONTROL,
                WHO_HEATING,
                WHO_DOOR_ENTRY,
                WHO_LOCK,
                WHO_CEN,
                WHO_SCENARIO,
                WHO_CEN_PLUS,
                WHO_SOUND,
                WHO_SOUND_DIFFUSION,
            ),
        )


class MH201Profile(GatewayProfile):
    def __init__(self) -> None:
        super().__init__(
            model_name="MH201",
            command_queue_delay=0.10,
            max_queue_size=100,
            audio_measured=False,
            supports_extended_frames=True,
            extra_features=("Clock diagnostics",),
        )


class MH202Profile(GatewayProfile):
    """The MH202 scenario programmer and gateway.

    Hardware verified relaying the alarm bus (WHO 5) in MyHOME#564 (comment
    5917195080): the capture is a status dump of a disarmed panel (*5*1*0##,
    *5*9*0##) and its zone states (WHAT 11/18). WHO 5 here means reading the
    alarm: the plant owner reports the central unit rejects SCS arm/disarm from
    any gateway and arms through WHO 9 AUX frames instead (see OWNAlarmCommand).
    """

    def __init__(self) -> None:
        super().__init__(
            model_name="MH202",
            max_command_sessions=2,
            command_queue_delay=0.10,
            audio_measured=False,
            supports_hmac=True,
            supports_extended_frames=True,
            supported_who=(*DEFAULT_SUPPORTED_WHO, WHO_ALARM),
        )


class H4890Profile(GatewayProfile):
    """The 4890 3.5" touch screen family (AM4890, H4890, LN4890, LN4890A).

    The screen sits on the SCS bus next to the burglar alarm central unit and
    relays the alarm bus: the H4890 capture in MyHOME#466 / PR #484 carries a
    disarmed panel's status dump (*5*1*0##, *5*9*0##) and zone states (WHAT
    11/18); no arm transition or alarm event is captured. ``supported_who`` is
    the class default plus WHO 5: the captures do not show the screen dropping
    heating, CEN or scenarios, so absence in a trace is not inferred. Sound is
    captured: the MyHOME#466 H4890 sweep and trace (firmware 4.0.15) carry
    received WHO 16 and WHO 22 state frames (``*16*3*Z##``, ``*16*13*Z##``,
    ``*22*...##``, ``*#22*...*12*...##``). Sessions, pacing and authentication
    are the class defaults, not measurements. WHO 5 here means reading the alarm: the plant owner reports the central unit
    rejects SCS arm/disarm from any gateway and arms through WHO 9 AUX frames
    instead (see OWNAlarmCommand).
    """

    def __init__(self) -> None:
        super().__init__(
            model_name="H4890",
            auth_measured=False,
            supported_who=(*DEFAULT_SUPPORTED_WHO, WHO_ALARM),
        )


class H4684Profile(GatewayProfile):
    """The H4684 colour touch screen family (H4684, H/L4684, L4684, N4684, NT4684, LGRH4684).

    Two firmware generations are evidenced:
    1. Emulated H4684 firmware 2.0.54 in the 22-suite firmware oracle
       (``*#13**15*13##``, ``*#13**16*2*0*54##``, ``*#13**23*2*0*5##``,
       ``*#13**24*3*0*0##``, ``*#1013**1*19##``):
       - Ships ``bt_autom``, ``bt_termoreg``, ``bt_energia`` and ``bt_difson``
         (WHO 1, 2, 3, 4, 15, 16, 18; ``*#16*0*5##`` answers ``ack``/``out`` in
         ``sound-who16-source.tsv``), with legacy OPEN password authentication
         in ``openserver``.
       - Does not ship ``bt_multi`` or ``bt_supervisione``, and NACKs all WHO 17
         (``scenario-who17``), WHO 22 (``sound-who22``), and WHO 25
         (``who25-messages``) frames.
    2. Physical H/L4684 firmware 6.0.11 (MyHOME#466 comment 6398442412: UPnP
       ``modelName`` ``H/L4684``, ``*#13**15*23##``, ``*#13**16*6*0*11##``,
       ``*#13**23*2*6*2##``, ``*#13**24*6*0*0##``):
       - Ships ``bt_multi`` alongside ``bt_difson``, translating ``*#16*0*5##``
         into dual-dialect WHO 16 and WHO 22 event-session inventory
         (``*#22*3#2#1*0*...##``, ``*#22*1#1#1*3*...##``).
       - Behaviour between 2.0.54 and 6.0.0 is uncaptured, so firmware below
         6.0.0 or unknown firmware conservatively omits WHO 22.
    """

    def __init__(
        self,
        firmware_version: str | tuple[int, ...] | list[int] | None = None,
    ) -> None:
        if not firmware_version:
            fw_str = None
        elif isinstance(firmware_version, (list, tuple)):
            fw_str = ".".join(str(p) for p in firmware_version)
        else:
            fw_str = str(firmware_version)
        base_who = (
            WHO_LIGHTING,
            WHO_AUTOMATION,
            WHO_LOAD_CONTROL,
            WHO_HEATING,
            WHO_CEN,
            WHO_SOUND,
            WHO_ENERGY,
        )
        has_who22 = (
            parse_firmware_version(firmware_version) >= _H4684_WHO22_FIRMWARE
        )
        super().__init__(
            model_name="H4684",
            firmware_version=fw_str,
            supported_who=(
                (*base_who, WHO_SOUND_DIFFUSION) if has_who22 else base_who
            ),
        )


class MyHomeServer1Profile(GatewayProfile):
    """The MyHomeServer1 (Eliot / Legrand Living Now gateway).

    Subsystems:
    - WHO 3 (Load Control): MyHomeServer1 firmware does not package the
      ``bt_energia`` translator (unlike MH202, F454, and F459), so it strictly
      NACKs all WHO 3 requests without bus activity (see own-firmware-oracle
      findings/MyHomeServer1/energy-ts10.md). WHO 3 is therefore excluded from
      ``supported_who``.
    """

    def __init__(self) -> None:
        super().__init__(
            model_name="MyHomeServer1",
            max_command_sessions=4,
            default_command_sessions=2,
            command_queue_delay=0.02,
            max_queue_size=300,
            audio_measured=False,
            supports_hmac=True,
            supports_native_transitions=True,
            supports_extended_frames=True,
            supported_who=tuple(
                w for w in DEFAULT_SUPPORTED_WHO if w != WHO_LOAD_CONTROL
            ),
        )


class GenericGatewayProfile(GatewayProfile):
    def __init__(self, model_name: str = "Generic") -> None:
        super().__init__(model_name=model_name)


_GENERIC = GenericGatewayProfile()

_PROFILES = {
    "f452": F452Profile(),
    "f452v": F452VProfile(),
    "f453": F453Profile(),
    "f453av": F453AVProfile(),
    "f454": F454Profile(),
    "f455": F455Profile(),
    "f461": F461Profile(),
    "h4684": H4684Profile(),
    "h4890": H4890Profile(),
    "mh200": MH200Profile(),
    "mh200n": MH200NProfile(),
    "mh201": MH201Profile(),
    "mh202": MH202Profile(),
    "myhomeserver1": MyHomeServer1Profile(),
}

CANONICAL_PROFILE_ORDER = (
    "myhomeserver1",
    "f452",
    "f452v",
    "f453",
    "f453av",
    "f454",
    "f455",
    "f461",
    "h4684",
    "h4890",
    "mh202",
    "mh201",
    "mh200",
    "mh200n",
)


def canonical_profiles() -> tuple[GatewayProfile, ...]:
    return tuple(_PROFILES[key] for key in CANONICAL_PROFILE_ORDER) + (_GENERIC,)


CANONICAL_PROFILES: tuple[GatewayProfile, ...] = canonical_profiles()

_ALIASES = {
    "mhs1": "myhomeserver1",
    "am4890": "h4890",
    "ln4890": "h4890",
    "ln4890a": "h4890",
    "4890": "h4890",
    "l4684": "h4684",
    "hl4684": "h4684",
    "hc4684": "h4684",
    "n4684": "h4684",
    "nt4684": "h4684",
    "lgrh4684": "h4684",
    "lgr4684": "h4684",
    # Item numbers. MHCatalogue.db (MyHOME_Suite 3.5.38, fingerprinted in
    # OpenWebNet-Encyclopedia sources/manifest.yaml) gives each gateway a name
    # row and a number row sharing one EN_DEVICE.id_item: MH202/003535 (1902),
    # F454/003598 (1455), F455/003594 (2064), MH200N/003565 (1331).
    # 573992 is its own Legrand Arteor item; WHO_25.pdf p. 13 lists it with the
    # F453AV. Public pages: WHO_25.pdf p. 13 (03565, 573992) and the MyHOME_Suite
    # Version History (003598, 003594, 003565, 573992); none shows 003535.
    "573992": "f453av",
    "arteor573992": "f453av",
    "arteorf453av": "f453av",
    "003598": "f454",
    "03598": "f454",
    "003594": "f455",
    "03594": "f455",
    "03565": "mh200n",
    "003565": "mh200n",
    "003535": "mh202",
    "03535": "mh202",
}


def get_gateway_profile(
    model_name: str | None,
    firmware_version: str | tuple[int, ...] | list[int] | None = None,
) -> GatewayProfile:
    """Resolve a model name and optional firmware version to a profile, falling back conservatively."""
    if not model_name:
        return _GENERIC

    normalized = "".join(
        character for character in model_name.lower() if character.isalnum()
    )
    normalized = _ALIASES.get(normalized, normalized)
    if normalized == "f453av":
        return F453AVProfile(firmware_version=firmware_version)
    if normalized == "h4684":
        return H4684Profile(firmware_version=firmware_version)
    profile = _PROFILES.get(normalized)
    if profile is not None:
        return profile
    return GenericGatewayProfile(model_name=model_name)
