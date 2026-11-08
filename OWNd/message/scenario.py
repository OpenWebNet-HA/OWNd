"""WHO 0, 9, 17: Scenario, Auxiliary, and MH200/MH202 Scene events and commands."""

from __future__ import annotations

from .base import (
    OWNCommand,
    OWNEvent,
    register_command_parser,
    register_event_parser,
    require_address_where,
)



class OWNScenarioEvent(OWNEvent):
    """WHO 0 scenario activation and F420 programming / central-unit events.

    The published table (who-0-scenarios/README.md "WHAT reference") lists
    ``*0*N*WHERE##`` with ``N`` 1..16 (F420 and 3456) and 17..20 (3456 only),
    and WHAT 40..46 as the F420 programming vocabulary and central-unit states.
    Decoding is unchanged: any WHAT outside 40..46 is reported as a launch of
    that number, pending committed plant traces.
    """

    def __init__(self, data: str) -> None:
        super().__init__(data)

        self._scenario = self._what
        self._control_panel = self._where
        self._programming_scenario: int | None = None
        self._event: str | None = None
        # WHAT 40-46 are scenario-module programming states, not scenarios
        # (who-0-scenarios/README.md "Start recording - WHAT 40#X" ..
        # "Lock and unlock - WHAT 43 / 44"; libqtdevices scenario_device.cpp:27-35,
        # 93-156; mhs1 bt_luci accepts *0*40#N*W##, 41#N, 42, 42#N, 43, 44 and
        # emits 40#N..46#N).
        _programming = {
            40: "programming started",
            41: "programming stopped",
            42: "deleted",
            43: "locked",
            44: "unlocked",
            45: "unavailable",
            46: "memory full",
        }
        if self._what is None:
            # Status request (*#0*W##, *#0##): no scenario and no event, as
            # OWNAuxEvent does for a bare *#9##.
            self._scenario = None
        elif self._what in _programming:
            self._event = _programming[self._what]
            self._scenario = None
            # The grammar only admits digits in a WHAT parameter, so int()
            # cannot fail here.
            self._programming_scenario = (
                int(self._what_param[0]) if self._what_param else None
            )
            _target = (
                f"scenario {self._programming_scenario}"
                if self._programming_scenario is not None
                else "all scenarios"
            )
            self._human_readable_log = f"Scenario module {self._control_panel}: {_target} {self._event}."  # pylint: disable=line-too-long
        else:
            self._event = "launched"
            self._human_readable_log = f"Scenario {self._scenario} from control panel {self._control_panel} has been launched."  # pylint: disable=line-too-long

    @property
    def scenario(self) -> int | None:
        """Activated scenario number (any WHAT outside 40..46), None for a programming / status frame."""
        return self._scenario

    @property
    def control_panel(self) -> str | None:
        return self._control_panel

    @property
    def event(self) -> str | None:
        """'launched' for any WHAT outside 40..46, the programming/lock state for WHAT 40..46, None for a status request."""
        return self._event

    @property
    def programming_scenario(self) -> int | None:
        """Scenario named by a WHAT 40/41/42 parameter, None when it targets all."""
        return self._programming_scenario



class OWNAuxEvent(OWNEvent):
    def __init__(self, data: str) -> None:
        super().__init__(data)

        self._channel = self._where

        self._state = self._what
        if self._state is None:
            # Bare status request (e.g. *#9##): keep the raw frame as the log.
            pass
        elif self._state == 0:
            self._human_readable_log = (
                f"Auxiliary channel {self._channel} is set to 'OFF'."
            )
        elif self._state == 1:
            self._human_readable_log = (
                f"Auxiliary channel {self._channel} is set to 'ON'."
            )
        elif self._state == 2:
            self._human_readable_log = (
                f"Auxiliary channel {self._channel} is set to 'TOGGLE'."
            )
        elif self._state == 3:
            self._human_readable_log = (
                f"Auxiliary channel {self._channel} is set to 'STOP'."
            )
        elif self._state == 4:
            self._human_readable_log = (
                f"Auxiliary channel {self._channel} is set to 'UP'."
            )
        elif self._state == 5:
            self._human_readable_log = (
                f"Auxiliary channel {self._channel} is set to 'DOWN'."
            )
        elif self._state == 6:
            self._human_readable_log = (
                f"Auxiliary channel {self._channel} is set to 'ENABLED'."
            )
        elif self._state == 7:
            self._human_readable_log = (
                f"Auxiliary channel {self._channel} is set to 'DISABLED'."
            )
        elif self._state == 8:
            self._human_readable_log = (
                f"Auxiliary channel {self._channel} is set to 'RESET_GEN'."
            )
        elif self._state == 9:
            self._human_readable_log = (
                f"Auxiliary channel {self._channel} is set to 'RESET_BI'."
            )
        elif self._state == 10:
            self._human_readable_log = (
                f"Auxiliary channel {self._channel} is set to 'RESET_TRI'."
            )
        else:
            self._human_readable_log = (
                f"Auxiliary channel {self._channel} state is {self._state}."
            )

    @property
    def channel(self) -> str | None:
        return self._channel

    @property
    def state_code(self) -> int | None:
        return self._state

    @property
    def is_on(self) -> bool:
        return self._state == 1



class OWNSceneEvent(OWNEvent):
    def __init__(self, data: str) -> None:
        super().__init__(data)

        self._scene = self._where
        self._state = self._what

        if self._dimension == 40:
            self._human_readable_log = (
                f"Scene {self._scene} state report (dimension 40)."
            )
        elif self._dimension == 41:
            self._human_readable_log = (
                f"Scene {self._scene} error report (dimension 41)."
            )
        elif self._dimension is not None:
            self._human_readable_log = (
                f"Scene {self._scene} dimension {self._dimension} report."
            )
        elif self._state == 1:
            self._human_readable_log = f"Scene {self._scene} is started."
        elif self._state == 2:
            self._human_readable_log = f"Scene {self._scene} is stopped."
        elif self._state == 3:
            self._human_readable_log = f"Scene {self._scene} is enabled."
        elif self._state == 4:
            self._human_readable_log = f"Scene {self._scene} is disabled."
        elif self._state is not None:
            self._human_readable_log = f"Scene {self._scene} is unknown ({self._state})."

    @property
    def scenario(self) -> str | None:
        return self._scene

    @property
    def scene(self) -> str | None:
        return self._scene

    @property
    def state(self) -> int | None:
        return self._state

    @property
    def is_on(self) -> bool | None:
        if self._state == 1:
            return True
        if self._state == 2:
            return False
        return None

    @property
    def is_enabled(self) -> bool | None:
        if self._state == 3:
            return True
        if self._state == 4:
            return False
        return None


def _scene_where(where: object) -> str:
    """WHO 17 scene WHERE: a ``str`` or ``int`` (not ``bool`` or ``None``), non-empty,
    without ``*``, ``##`` or whitespace. ``start(True)`` would otherwise build
    ``*17*1*True##`` and fall back to the "Requesting global scene status" log;
    untyped callers still get ``ValueError`` for ``None``."""
    return require_address_where(where)


class OWNSceneCommand(OWNCommand):
    """WHO 17: MH200/MH200N/MH202 Scene Management commands.

    Published functional model (who-17-scenario-management/README.md):
    *17*1*WHERE## - Start scene
    *17*2*WHERE## - Stop scene
    *17*3*WHERE## - Enable scene
    *17*4*WHERE## - Disable scene
    *#17*WHERE##  - Query scene status (WHERE 0 = general)

    There is no bare ``*#17##`` form on the page, and the firmware oracle has
    it NACKed on all 12 emulated gateways (``scenario-who17``); the
    parser still reads it, the builder no longer emits it.
    """

    def __init__(self, data: str) -> None:
        super().__init__(data)

        self._scene = self._where
        self._action = self._what

        if self._action == 1:
            self._human_readable_log = f"Starting scene {self._scene}."
        elif self._action == 2:
            self._human_readable_log = f"Stopping scene {self._scene}."
        elif self._action == 3:
            self._human_readable_log = f"Enabling scene {self._scene}."
        elif self._action == 4:
            self._human_readable_log = f"Disabling scene {self._scene}."
        elif self._action is None and self._where:
            self._human_readable_log = f"Requesting status of scene {self._scene}."
        elif self._action is None and not self._where:
            self._human_readable_log = "Requesting global scene status."

    @property
    def scenario(self) -> str | None:
        """Scene identifier (WHERE)."""
        return self._scene

    @property
    def scene(self) -> str | None:
        """Scene identifier (alias for scenario)."""
        return self._scene

    @property
    def action(self) -> int | None:
        """Command action code (WHAT: 1=start, 2=stop, 3=enable, 4=disable)."""
        return self._action

    @classmethod
    def start(cls, where: str | int) -> OWNSceneCommand:
        """Start/execute scene (``*17*1*WHERE##``); WHERE must be non-empty."""
        return cls(f"*17*1*{_scene_where(where)}##")

    @classmethod
    def stop(cls, where: str | int) -> OWNSceneCommand:
        """Stop/abort running scene (``*17*2*WHERE##``); WHERE must be non-empty."""
        return cls(f"*17*2*{_scene_where(where)}##")

    @classmethod
    def enable(cls, where: str | int) -> OWNSceneCommand:
        """Enable scene for execution (``*17*3*WHERE##``); WHERE must be non-empty."""
        return cls(f"*17*3*{_scene_where(where)}##")

    @classmethod
    def disable(cls, where: str | int) -> OWNSceneCommand:
        """Disable scene execution (``*17*4*WHERE##``); WHERE must be non-empty."""
        return cls(f"*17*4*{_scene_where(where)}##")

    @classmethod
    def status(cls, where: str | int = "0") -> OWNSceneCommand:
        """Query scene status: ``*#17*WHERE##`` (default ``0`` = general).

        ``None`` or an empty WHERE raises ``ValueError``: the page defines no
        bare ``*#17##`` and the firmware oracle has it NACKed on all 12
        emulated gateways (own-firmware-oracle ``scenario-who17``).
        """
        return cls(f"*#17*{_scene_where(where)}##")


register_event_parser(0, OWNScenarioEvent)
register_event_parser(9, OWNAuxEvent)
register_event_parser(17, OWNSceneEvent)
register_command_parser(17, OWNSceneCommand)
