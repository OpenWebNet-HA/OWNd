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

    Documented:
    - WHO 25: YES in Legrand's WHO 25 specification (p. 13,
      https://developer.legrand.com/uploads/2019/12/WHO_25.pdf) and WHO 15-25
      specification (p. 24, https://developer.legrand.com/uploads/2019/12/WHO_15-25.pdf).
    - WHO 18: the TiF453 user guide has an Energy Management chapter (load
      control and energy data pages, pp. 39-40,
      https://www.bticino.be/sites/default/files/Service-en-support/software-en-schemas2/My%20Home/Tif453/TiF453%20Version2_0_07/Software_Manual_F453_EN.pdf).
      That shows the gateway handles energy on its own web pages, not that
      it relays WHO 18 to OpenWebNet clients.
    - Authentication: the same guide (p. 17) configures only an OPEN
      password (default 12345). The F454 user manual (p. 69,
      https://dar.bticino.com/asset/Documents/O1755J_U_EN.pdf) offers OPEN or
      HMAC; the F453 guide has no HMAC option, so ``supports_hmac`` stays
      False. No handshake is captured, so ``auth_measured`` is False.

    Every other subsystem, including sound (WHO 16/22), is the class default
    and unverified. Sessions are the class default; pacing is copied from the
    MH200 because nothing is measured.
    """

    def __init__(self) -> None:
        super().__init__(
            model_name="F453",
            command_queue_delay=0.15,
            auth_measured=False,
            audio_measured=False,
        )


class F453AVProfile(GatewayProfile):
    """The F453AV Web Server (Legrand Arteor 573992).

    Documented:
    - WHO 25: Legrand's WHO 25 specification (p. 13,
      https://developer.legrand.com/uploads/2019/12/WHO_25.pdf) and WHO 15-25
      specification (p. 24, https://developer.legrand.com/uploads/2019/12/WHO_15-25.pdf)
      list F453AV v1.0.19 as NO and F453AV / 573992 v2.1.7 as YES. Behaviour
      between those two versions is not documented. Firmware below 2.1.7, or
      unknown firmware, is treated as without CEN+; that is a conservative
      choice, not a documented threshold.
    - WHO 18: the TiF453AV user guide has an Energy Management chapter (pp.
      39-40,
      https://www.bticino.be/sites/default/files/Service-en-support/software-en-schemas2/My%20Home/TiF453AV/Version%203_0_64/Software_Manual_F453AV_EN.pdf).
      That shows the gateway handles energy on its own web pages, not that
      it relays WHO 18 to OpenWebNet clients.
    - Authentication: the same guide (p. 18) configures only an OPEN
      password (default 12345) and, unlike the F454 user manual (p. 69,
      https://dar.bticino.com/asset/Documents/O1755J_U_EN.pdf), offers no HMAC
      option, so ``supports_hmac`` stays False. No handshake is captured, so
      ``auth_measured`` is False.
    - WHO 7: Legrand's WHO 7 specification names the F453AV as its device
      (p. 1, https://developer.legrand.com/uploads/2019/12/WHO_7.pdf). OWNd does
      not model WHO 7, so it is not listed in ``supported_who``.

    Every other subsystem, including sound (WHO 16/22), is the class default
    and unverified. Sessions are the class default; pacing is copied from the
    MH200 because nothing is measured.
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
            auth_measured=False,
            audio_measured=False,
            supported_who=(
                DEFAULT_SUPPORTED_WHO if has_cen_plus else _DEFAULT_WITHOUT_CEN_PLUS
            ),
            extra_features=() if has_cen_plus else ("CEN+ documented from FW 2.1.7",),
        )


class F454Profile(GatewayProfile):
    def __init__(self) -> None:
        super().__init__(
            model_name="F454",
            max_command_sessions=4,
            max_queue_size=250,
            event_keepalive_interval=90,
            audio_measured=False,
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
        )


class MH200Profile(GatewayProfile):
    """The original MH200 (WHO=13 device type 4).

    WHO 16 is verified: on a live MH200 (``*#13**15*4##``, firmware
    ``*#13**16*2*1*0##`` = 2.1.0, 2026-09-23) ``*#16*0*5##`` returned a
    state frame for every amplifier and source within 0.6 s, and the bare
    ``*#16*0##`` returned none (#53). Pacing, queue size, keepalive and the other
    subsystems are copied from the MH200N profile and have not been
    measured on an MH200.

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

    Supports sound system discovery (WHO 16). Hardware verified answering
    ``*#16*0*5##`` without NACK and returning full source and amplifier inventory
    (MyHOME#427 / comment 5848181845).

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
                WHO_HEATING,
                WHO_DOOR_ENTRY,
                WHO_LOCK,
                WHO_CEN,
                WHO_SCENARIO,
                WHO_CEN_PLUS,
                WHO_SOUND,
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


class MyHomeServer1Profile(GatewayProfile):
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
    profile = _PROFILES.get(normalized)
    if profile is not None:
        return profile
    return GenericGatewayProfile(model_name=model_name)
