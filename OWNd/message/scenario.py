"""WHO 0, 9, 17: Scenario, Auxiliary, and MH200/MH202 Scene events and commands."""

from __future__ import annotations

from .base import (
    OWNCommand,
    OWNEvent,
    register_command_parser,
    register_event_parser,
)


class OWNScenarioEvent(OWNEvent):
    def __init__(self, data: str) -> None:
        super().__init__(data)

        self._scenario = self._what
        self._control_panel = self._where
        self._programming_scenario: int | None = None
        self._event: str | None = None
        # WHAT 40-46 are scenario-module programming states, not scenarios
        # (libqtdevices scenario_device.cpp:27-35, 93-156; mhs1 bt_luci
        # accepts *0*40#N*W##, 41#N, 42, 42#N, 43, 44 and emits 40#N..46#N).
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
        return self._scenario

    @property
    def control_panel(self) -> str | None:
        return self._control_panel

    @property
    def event(self) -> str | None:
        """'launched' for WHAT 1-31, the programming/lock state for WHAT 40-46, None for a status request."""
        return self._event

    @property
    def programming_scenario(self) -> int | None:
        """Scenario named by a WHAT 40/41/42 parameter, None when it targets all."""
        return self._programming_scenario



#: WHAT names the Encyclopedia establishes for WHO 9 (``who-9-auxiliaries/README.md#corpus-status``):
#: ``*9*1*WHERE##`` ON and ``*9*0*WHERE##`` OFF only.
AUX_WHAT_NAMES: dict[int, str] = {0: "OFF", 1: "ON"}

#: Names for WHAT 2..10 as used by openwebnet4j and by the log lines below.
#: They are NOT established by the Encyclopedia ("Unknown values remain
#: unspecified rather than inferred"; the TS10 decoder "rejects other WHAT
#: cases") and no committed plant trace carries them: provenance caveat only,
#: the log strings are unchanged.
AUX_WHAT_NAMES_UNVERIFIED: dict[int, str] = {
    2: "TOGGLE",
    3: "STOP",
    4: "UP",
    5: "DOWN",
    6: "ENABLED",
    7: "DISABLED",
    8: "RESET_GEN",
    9: "RESET_BI",
    10: "RESET_TRI",
}


class OWNAuxEvent(OWNEvent):
    """WHO 9 auxiliary channel indication, ``*9*WHAT*WHERE##``.

    Encyclopedia ``who-9-auxiliaries/README.md#corpus-status`` establishes only
    ``*#9*WHERE##`` (status request), ``*9*1*WHERE##`` (ON) and ``*9*0*WHERE##``
    (OFF), and "does not establish an auxiliary-address range": ``channel`` is
    the WHERE as sent, not a 1..9 number. The WHAT 2..10 names in the log
    lines come from openwebnet4j and are unverified
    (``AUX_WHAT_NAMES_UNVERIFIED``); they are kept as they were.
    """

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
        """The WHERE as sent; the Encyclopedia establishes no auxiliary-address range."""
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


class OWNSceneCommand(OWNCommand):
    """WHO 17: MH200/MH200N/MH202 Scene Management commands.

    Published functional model:
    *17*1*WHERE## - Start scene
    *17*2*WHERE## - Stop scene
    *17*3*WHERE## - Enable scene
    *17*4*WHERE## - Disable scene
    *#17*WHERE##  - Query scene status
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
        """Start/execute scene."""
        return cls(f"*17*1*{where}##")

    @classmethod
    def stop(cls, where: str | int) -> OWNSceneCommand:
        """Stop/abort running scene."""
        return cls(f"*17*2*{where}##")

    @classmethod
    def enable(cls, where: str | int) -> OWNSceneCommand:
        """Enable scene for execution."""
        return cls(f"*17*3*{where}##")

    @classmethod
    def disable(cls, where: str | int) -> OWNSceneCommand:
        """Disable scene execution."""
        return cls(f"*17*4*{where}##")

    @classmethod
    def status(cls, where: str | int | None = "0") -> OWNSceneCommand:
        """Query scene status (default '0' for general status)."""
        if where is not None and str(where) != "":
            return cls(f"*#17*{where}##")
        return cls("*#17##")


register_event_parser(0, OWNScenarioEvent)
register_event_parser(9, OWNAuxEvent)
register_event_parser(17, OWNSceneEvent)
register_command_parser(17, OWNSceneCommand)
