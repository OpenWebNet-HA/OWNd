"""OpenWebNet message framing, parsing, and WHO subsystem modules."""

from __future__ import annotations

import colorsys
import datetime
import re
from typing import Any
from zoneinfo import ZoneInfo

from dateutil.relativedelta import relativedelta

from .alarm import (
    OWNAlarmCommand,
    OWNAlarmEvent,
)
from .automation import (
    OWNAutomationCommand,
    OWNAutomationEvent,
)
from .base import (
    OWNCommand,
    OWNEvent,
    OWNMessage,
    OWNSignaling,
    OWNStatusRequest,
    _ensure_all_subsystems_registered,
    register_command_parser,
    register_event_parser,
)
from .cen import (
    OWNCENEvent,
    OWNCENPlusEvent,
    OWNCenCommand,
    OWNCenPlusCommand,
    OWNScenarioPlusCommand,
    OWNScenarioPlusEvent,
    OWNDryContactCommand,
    OWNDryContactEvent,
)
from .energy import (
    MESSAGE_TYPE_ACTIVE_POWER,
    MESSAGE_TYPE_CURRENT_DAY_CONSUMPTION,
    MESSAGE_TYPE_CURRENT_MONTH_CONSUMPTION,
    MESSAGE_TYPE_DAILY_CONSUMPTION,
    MESSAGE_TYPE_ENERGY_TOTALIZER,
    MESSAGE_TYPE_HOURLY_CONSUMPTION,
    MESSAGE_TYPE_MONTHLY_CONSUMPTION,
    _integer_value,
    OWNEnergyCommand,
    OWNEnergyEvent,
)
from .gateway import (
    _gateway_timezone,
    _validate_gateway_clock_values,
    OWNGatewayCommand,
    OWNGatewayEvent,
)
from .heating import (
    CLIMATE_MODE_AUTO,
    CLIMATE_MODE_COOL,
    CLIMATE_MODE_HEAT,
    CLIMATE_MODE_OFF,
    LOCAL_CONTROL_NORMAL,
    LOCAL_CONTROL_OFF,
    LOCAL_CONTROL_OFFSET,
    LOCAL_CONTROL_OVERRIDE,
    LOCAL_CONTROL_PROTECTION,
    LOCAL_CONTROL_UNKNOWN,
    MESSAGE_TYPE_FAN_SPEED,
    MESSAGE_TYPE_LOCAL_OFFSET,
    MESSAGE_TYPE_LOCAL_TARGET_TEMPERATURE,
    MESSAGE_TYPE_MAIN_HUMIDITY,
    MESSAGE_TYPE_MAIN_TEMPERATURE,
    MESSAGE_TYPE_MODE,
    MESSAGE_TYPE_MODE_TARGET,
    MESSAGE_TYPE_SECONDARY_TEMPERATURE,
    MESSAGE_TYPE_TARGET_TEMPERATURE,
    MESSAGE_TYPE_ZONE_STATE,
    ZONE_CONTEXT_AUTOMATIC,
    ZONE_CONTEXT_COOLING,
    ZONE_CONTEXT_GENERIC,
    ZONE_CONTEXT_HEATING,
    ZONE_STATE_COMFORT,
    ZONE_STATE_ECO,
    ZONE_STATE_OFF,
    ZONE_STATE_PROTECTION,
    ZONE_STATE_SETPOINT,
    _WHO4_TEMP_REGEX,
    _ZONE_CONTEXTS,
    _ZONE_STATES,
    _zone_state,
    _zone_state_text,
    who4_temperature,
    OWNHeatingCommand,
    OWNHeatingEvent,
)
from .lighting import (
    MESSAGE_TYPE_ACTION,
    MESSAGE_TYPE_ILLUMINANCE,
    MESSAGE_TYPE_MOTION,
    MESSAGE_TYPE_MOTION_TIMEOUT,
    MESSAGE_TYPE_PIR_SENSITIVITY,
    PIR_SENSITIVITY_MAPPING,
    OWNLightingCommand,
    OWNLightingEvent,
)
from .scenario import (
    OWNAuxEvent,
    OWNScenarioEvent,
    OWNSceneEvent,
)
from .sound import (
    OWNAVCommand,
    OWNSoundCommand,
    OWNSoundEvent,
)

__all__ = [
    # Base framing
    "OWNMessage",
    "OWNSignaling",
    "OWNEvent",
    "OWNCommand",
    "OWNStatusRequest",
    "register_event_parser",
    "register_command_parser",
    "_ensure_all_subsystems_registered",
    # Lighting (WHO 1)
    "MESSAGE_TYPE_ACTION",
    "MESSAGE_TYPE_MOTION",
    "MESSAGE_TYPE_PIR_SENSITIVITY",
    "MESSAGE_TYPE_ILLUMINANCE",
    "MESSAGE_TYPE_MOTION_TIMEOUT",
    "PIR_SENSITIVITY_MAPPING",
    "OWNLightingEvent",
    "OWNLightingCommand",
    # Automation (WHO 2)
    "OWNAutomationEvent",
    "OWNAutomationCommand",
    # Heating (WHO 4)
    "MESSAGE_TYPE_MAIN_TEMPERATURE",
    "MESSAGE_TYPE_MAIN_HUMIDITY",
    "MESSAGE_TYPE_SECONDARY_TEMPERATURE",
    "MESSAGE_TYPE_TARGET_TEMPERATURE",
    "MESSAGE_TYPE_LOCAL_OFFSET",
    "MESSAGE_TYPE_LOCAL_TARGET_TEMPERATURE",
    "MESSAGE_TYPE_MODE",
    "MESSAGE_TYPE_MODE_TARGET",
    "MESSAGE_TYPE_FAN_SPEED",
    "MESSAGE_TYPE_ZONE_STATE",
    "CLIMATE_MODE_OFF",
    "CLIMATE_MODE_HEAT",
    "CLIMATE_MODE_COOL",
    "CLIMATE_MODE_AUTO",
    "LOCAL_CONTROL_NORMAL",
    "LOCAL_CONTROL_OFFSET",
    "LOCAL_CONTROL_OFF",
    "LOCAL_CONTROL_PROTECTION",
    "LOCAL_CONTROL_OVERRIDE",
    "LOCAL_CONTROL_UNKNOWN",
    "ZONE_CONTEXT_GENERIC",
    "ZONE_CONTEXT_HEATING",
    "ZONE_CONTEXT_COOLING",
    "ZONE_CONTEXT_AUTOMATIC",
    "ZONE_STATE_SETPOINT",
    "ZONE_STATE_PROTECTION",
    "ZONE_STATE_COMFORT",
    "ZONE_STATE_ECO",
    "ZONE_STATE_OFF",
    "_ZONE_CONTEXTS",
    "_ZONE_STATES",
    "_WHO4_TEMP_REGEX",
    "who4_temperature",
    "_zone_state",
    "_zone_state_text",
    "OWNHeatingEvent",
    "OWNHeatingCommand",
    # Burglar Alarm (WHO 5)
    "OWNAlarmEvent",
    "OWNAlarmCommand",
    # Gateway (WHO 13)
    "_validate_gateway_clock_values",
    "_gateway_timezone",
    "OWNGatewayEvent",
    "OWNGatewayCommand",
    # CEN & Dry Contact (WHO 15 & 25)
    "OWNCENEvent",
    "OWNDryContactEvent",
    "OWNCENPlusEvent",
    "OWNCenCommand",
    "OWNDryContactCommand",
    "OWNCenPlusCommand",
    "OWNScenarioPlusEvent",
    "OWNScenarioPlusCommand",
    # Sound & AV (WHO 16 & 22 & 7)
    "OWNSoundEvent",
    "OWNAVCommand",
    "OWNSoundCommand",
    # Energy (WHO 18)
    "MESSAGE_TYPE_ACTIVE_POWER",
    "MESSAGE_TYPE_ENERGY_TOTALIZER",
    "MESSAGE_TYPE_HOURLY_CONSUMPTION",
    "MESSAGE_TYPE_DAILY_CONSUMPTION",
    "MESSAGE_TYPE_MONTHLY_CONSUMPTION",
    "MESSAGE_TYPE_CURRENT_DAY_CONSUMPTION",
    "MESSAGE_TYPE_CURRENT_MONTH_CONSUMPTION",
    "_integer_value",
    "OWNEnergyEvent",
    "OWNEnergyCommand",
    # Scenario (WHO 0, 9, 17)
    "OWNScenarioEvent",
    "OWNAuxEvent",
    "OWNSceneEvent",
]

_ensure_all_subsystems_registered()
