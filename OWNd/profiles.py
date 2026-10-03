"""Gateway capabilities and conservative transport defaults."""

from __future__ import annotations

from dataclasses import dataclass

WHO_LIGHTING = 1
WHO_AUTOMATION = 2
WHO_LOAD_CONTROL = 3
WHO_HEATING = 4
WHO_ALARM = 5
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
    supports_native_transitions: bool = False
    supports_extended_frames: bool = False
    supported_who: tuple[int, ...] = DEFAULT_SUPPORTED_WHO
    extra_features: tuple[str, ...] = ()

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
            features.append("Sound system (WHO 16)")
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


class F454Profile(GatewayProfile):
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
    def __init__(self) -> None:
        super().__init__(
            model_name="F461",
            max_command_sessions=4,
            command_queue_delay=0.05,
            max_queue_size=250,
            event_keepalive_interval=90,
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
    measured on an MH200. As documented in the BTicino TiMH200N release
    notes, support for CEN+ (WHO 25) and virtual objects was newly introduced
    specifically for the MH200N; the legacy MH200 firmware predates and
    does not support CEN+, supporting only classic CEN (WHO 15).
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
    heating, CEN or scenarios, so absence in a trace is not inferred. Sessions,
    pacing and authentication are the class defaults, not measurements. WHO 5
    here means reading the alarm: the plant owner reports the central unit
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
            supports_hmac=True,
            supports_native_transitions=True,
            supports_extended_frames=True,
        )


class GenericGatewayProfile(GatewayProfile):
    def __init__(self, model_name: str = "Generic") -> None:
        super().__init__(model_name=model_name)


_GENERIC = GenericGatewayProfile()

_PROFILES = {
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
}


def get_gateway_profile(model_name: str | None) -> GatewayProfile:
    """Resolve a model name to a profile, falling back conservatively."""
    if not model_name:
        return _GENERIC

    normalized = "".join(
        character for character in model_name.lower() if character.isalnum()
    )
    normalized = _ALIASES.get(normalized, normalized)
    profile = _PROFILES.get(normalized)
    if profile is not None:
        return profile
    return GenericGatewayProfile(model_name=model_name)
