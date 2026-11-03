"""WHO 0, 9, 17: Scenario, Auxiliary, and MH200/MH202 Scene events and commands."""

from __future__ import annotations

from .base import (
    OWNCommand,
    OWNEvent,
    register_command_parser,
    register_event_parser,
    require_non_empty_where,
)


# WHO 0 WHAT ranges (Encyclopedia who-0-scenarios/README.md "WHAT reference"):
# 1..16 activate a stored scenario on an F420 or a 3456 IR interface, 17..20
# only on a 3456; 40..46 are F420 programming / central-unit states. WHAT 0
# and anything above 20 are not defined; the scenario library's 1..31 API
# assertions "do not extend the published F420 or 3456 capacities"
# ("Historical touchscreen behavior"; ENCY_CONFIRM LS-S1).
SCENARIO_MAX_F420 = 16
SCENARIO_MAX_3456 = 20

SCENARIO_AVAILABILITY_F420_AND_3456 = "F420 and 3456"
SCENARIO_AVAILABILITY_3456 = "3456"


class OWNScenarioEvent(OWNEvent):
    """WHO 0 scenario activation and F420 programming / central-unit events.

    ``*0*N*WHERE##`` with ``N`` 1..16 (F420 and 3456) or 17..20 (3456 only) is
    a scenario activation; WHAT 40..46 are the F420 programming vocabulary and
    central-unit states (who-0-scenarios/README.md "WHAT reference", "Event
    model"). Any other WHAT (``0``, ``21``..) is reported as unknown, not as a
    launch.
    """

    def __init__(self, data: str) -> None:
        super().__init__(data)

        self._scenario: int | None = None
        self._unknown_what: int | None = None
        self._availability: str | None = None
        self._control_panel = self._where
        self._programming_scenario: int | None = None
        self._event: str | None = None
        # WHAT 40-46 are scenario-module programming states, not scenarios
        # (who-0-scenarios/README.md "Start recording - WHAT 40#X" ..
        # "Lock and unlock - WHAT 43 / 44"; libqtdevices scenario_device.cpp:27-35,
        # 93-156; mhs1 bt_luci accepts *0*40#N*W##, 41#N, 42, 42#N, 43, 44 and
        # emits 40#N..46#N). The ``event`` values are kept stable; the log uses
        # the page's wording.
        _programming = {
            40: "programming started",
            41: "programming stopped",
            42: "deleted",
            43: "locked",
            44: "unlocked",
            45: "unavailable",
            46: "memory full",
        }
        module = f"Scenario module {self._control_panel}"
        unit = f"Scenario central unit {self._control_panel}"
        if self._what is None:
            # Status request (*#0*W##, *#0##): no scenario and no event, as
            # OWNAuxEvent does for a bare *#9##.
            pass
        elif self._what in _programming:
            self._event = _programming[self._what]
            # The grammar only admits digits in a WHAT parameter, so int()
            # cannot fail here.
            self._programming_scenario = (
                int(self._what_param[0]) if self._what_param else None
            )
            target = self._programming_scenario
            if self._what == 40:
                self._human_readable_log = (
                    f"{module}: recording of scenario {target} started."
                    if target is not None
                    else f"{module}: recording started (no scenario selected)."
                )
            elif self._what == 41:
                self._human_readable_log = (
                    f"{module}: recording of scenario {target} ended."
                    if target is not None
                    else f"{module}: recording ended (no scenario selected)."
                )
            elif self._what == 42:
                self._human_readable_log = (
                    f"{module}: scenario {target} erased."
                    if target is not None
                    else f"{module}: all scenarios erased."
                )
            else:
                # 43..46 describe the central unit, not a stored scenario
                # ("Lock and unlock - WHAT 43 / 44"): "locked", "unlocked",
                # "unavailable", "memory full".
                suffix = f" (scenario {target})" if target is not None else ""
                state = (
                    "memory is full" if self._what == 46 else f"is {self._event}"
                )
                self._human_readable_log = f"{unit} {state}{suffix}."
        elif 1 <= self._what <= SCENARIO_MAX_3456:
            self._scenario = self._what
            self._event = "launched"
            self._availability = (
                SCENARIO_AVAILABILITY_F420_AND_3456
                if self._what <= SCENARIO_MAX_F420
                else SCENARIO_AVAILABILITY_3456
            )
            note = (
                ""
                if self._what <= SCENARIO_MAX_F420
                else " (3456 IR interface only)"
            )
            self._human_readable_log = f"Scenario {self._scenario} from control panel {self._control_panel} has been launched{note}."  # pylint: disable=line-too-long
        else:
            self._unknown_what = self._what
            self._human_readable_log = f"Scenario module {self._control_panel} reports unknown WHAT {self._unknown_what}."  # pylint: disable=line-too-long

    @property
    def scenario(self) -> int | None:
        """Activated scenario number (WHAT 1..20), None for every other frame."""
        return self._scenario

    @property
    def scenario_availability(self) -> str | None:
        """``"F420 and 3456"`` for WHAT 1..16, ``"3456"`` for WHAT 17..20, else None
        (who-0-scenarios/README.md "WHAT reference")."""
        return self._availability

    @property
    def unknown_what(self) -> int | None:
        """The raw WHAT when it is neither an activation (1..20) nor a
        programming / central-unit state (40..46), else None."""
        return self._unknown_what

    @property
    def control_panel(self) -> str | None:
        return self._control_panel

    @property
    def event(self) -> str | None:
        """'launched' for WHAT 1-20 (1..16 F420 and 3456, 17..20 3456 only), the
        programming / central-unit state for WHAT 40-46, None for a status
        request or an unknown WHAT (see unknown_what)."""
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


def _scene_where(where: str | int | None) -> str:
    """WHO 17 scene WHERE: non-empty, no ``*`` (``None`` is not an address)."""
    if where is None:
        raise ValueError("where must be a non-empty address without '*'")
    return require_non_empty_where(where)


class OWNSceneCommand(OWNCommand):
    """WHO 17: MH200/MH200N/MH202 Scene Management commands.

    Published functional model (who-17-scenario-management/README.md):
    *17*1*WHERE## - Start scene
    *17*2*WHERE## - Stop scene
    *17*3*WHERE## - Enable scene
    *17*4*WHERE## - Disable scene
    *#17*WHERE##  - Query scene status (WHERE 0 = general)

    There is no bare ``*#17##`` form on the page, and the firmware oracle has
    it NACKed on all 12 emulated gateways (ORACLE_CONFIRM.md row M2); the
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
        elif self._message_type == "STATUS_REQUEST":
            # *#17*WHERE## ("Status request"); the bare *#17## is undocumented.
            self._human_readable_log = (
                f"Requesting status of scene {self._scene}."
                if self._where
                else "Requesting global scene status (undocumented *#17## form)."
            )
        elif self._dimension is not None:
            # DIMENSION 40 / 41 are MyHOME_Suite implementation-only operations
            # ("MyHOME_Suite extended scenario-programmer operations"): a write
            # or a read of them is not the published status request.
            if self.is_dimension_writing:
                self._human_readable_log = (
                    f"Writing scene {self._scene} dimension {self._dimension}."
                )
            elif self.is_dimension_request:
                self._human_readable_log = (
                    f"Requesting scene {self._scene} dimension {self._dimension}."
                )
            else:
                self._human_readable_log = (
                    f"Scene {self._scene} dimension {self._dimension} report."
                )

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
    def status(cls, where: str | int | None = "0") -> OWNSceneCommand:
        """Query scene status: ``*#17*WHERE##`` (default ``0`` = general).

        ``None`` or an empty WHERE raises ``ValueError``: the page defines no
        bare ``*#17##`` and the firmware oracle has it NACKed on all 12
        emulated gateways (``scenario-who17``; ORACLE_CONFIRM.md row M2).
        """
        return cls(f"*#17*{_scene_where(where)}##")


register_event_parser(0, OWNScenarioEvent)
register_event_parser(9, OWNAuxEvent)
register_event_parser(17, OWNSceneEvent)
register_command_parser(17, OWNSceneCommand)
