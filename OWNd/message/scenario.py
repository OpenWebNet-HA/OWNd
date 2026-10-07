"""WHO 0, 9, 17: Scenario, Auxiliary, and MH200/MH202 Scene events."""

from __future__ import annotations

import re

from .base import OWNEvent, register_event_parser


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
            45: "status 45",
            46: "status 46",
        }
        if self._what in _programming:
            self._event = _programming[self._what]
            self._scenario = None
            try:
                self._programming_scenario = (
                    int(self._what_param[0]) if self._what_param else None
                )
            except (TypeError, ValueError):
                self._programming_scenario = None
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
        """'launched' for WHAT 1-31, else the programming/lock state (WHAT 40-46)."""
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

        if self._state == 1:
            _status = "started"
        elif self._state == 2:
            _status = "stopped"
        elif self._state == 3:
            _status = "enabled"
        elif self._state == 4:
            _status = "disabled"
        else:
            _status = f"unknown ({self._state})"

        self._human_readable_log = f"Scene {self._scene} is {_status}."

    @property
    def scenario(self) -> str | None:
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


register_event_parser(0, OWNScenarioEvent)
register_event_parser(9, OWNAuxEvent)
register_event_parser(17, OWNSceneEvent)
