"""Gateway capabilities and conservative transport defaults."""

from __future__ import annotations

from dataclasses import dataclass

WHO_LIGHTING = 1
WHO_AUTOMATION = 2
WHO_LOAD_CONTROL = 3
WHO_HEATING = 4
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
    supports_native_transitions: bool = False
    supports_extended_frames: bool = False
    supported_who: tuple[int, ...] = DEFAULT_SUPPORTED_WHO

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
    def __init__(self) -> None:
        super().__init__(
            model_name="F455",
            max_command_sessions=4,
            max_queue_size=250,
            supports_hmac=True,
            supports_native_transitions=True,
            supports_extended_frames=True,
        )


class MH200NProfile(GatewayProfile):
    def __init__(self) -> None:
        super().__init__(
            model_name="MH200N",
            command_queue_delay=0.15,
            max_queue_size=100,
            event_keepalive_interval=90,
            supports_energy_instant_power=False,
            supports_audio=False,
            supported_who=(
                WHO_LIGHTING,
                WHO_AUTOMATION,
                WHO_HEATING,
                WHO_CEN,
                WHO_SCENARIO,
                WHO_CEN_PLUS,
            ),
        )


class MH201Profile(GatewayProfile):
    def __init__(self) -> None:
        super().__init__(
            model_name="MH201",
            command_queue_delay=0.10,
            max_queue_size=100,
            supports_extended_frames=True,
        )


class MH202Profile(GatewayProfile):
    def __init__(self) -> None:
        super().__init__(
            model_name="MH202",
            max_command_sessions=2,
            command_queue_delay=0.10,
            supports_hmac=True,
            supports_extended_frames=True,
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
    "mh200n": MH200NProfile(),
    "mh201": MH201Profile(),
    "mh202": MH202Profile(),
    "myhomeserver1": MyHomeServer1Profile(),
}

_ALIASES = {
    "mh200": "mh200n",
    "mhs1": "myhomeserver1",
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
