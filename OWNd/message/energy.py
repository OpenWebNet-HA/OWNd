"""WHO 18: Energy management events, commands, and consumption types."""

from __future__ import annotations

import datetime
import re
from typing import Any

from dateutil.relativedelta import relativedelta

from .base import (
    OWNCommand,
    OWNEvent,
    register_command_parser,
    register_event_parser,
    require_non_empty_where,
)

MESSAGE_TYPE_ACTIVE_POWER = "active_power"
MESSAGE_TYPE_ENERGY_TOTALIZER = "energy_totalizer"
MESSAGE_TYPE_HOURLY_CONSUMPTION = "hourly_consumption"
MESSAGE_TYPE_DAILY_CONSUMPTION = "daily_consumption"
MESSAGE_TYPE_MONTHLY_CONSUMPTION = "monthly_consumption"
MESSAGE_TYPE_CURRENT_DAY_CONSUMPTION = "current_day_partial_consumption"
MESSAGE_TYPE_CURRENT_MONTH_CONSUMPTION = "current_month_partial_consumption"
MESSAGE_TYPE_AUTO_UPDATE_INTERVAL = "auto_update_interval"
MESSAGE_TYPE_STOP_AND_GO = "stop_and_go"

# Stop&Go (F16EB) automatic reset breaker constants (findings/MyHomeServer1/energy-ts10.md)
STOP_AND_GO_OPEN = 21
STOP_AND_GO_CLOSE = 22
STOP_AND_GO_TEST_POSITIVE = 23
STOP_AND_GO_TEST_NEGATIVE = 24
STOP_AND_GO_AUTORESET_ENABLE = 26
STOP_AND_GO_AUTORESET_DISABLE = 27
STOP_AND_GO_TRACKING_ENABLE = 28
STOP_AND_GO_TRACKING_DISABLE = 29

STOP_AND_GO_DIM_TEST_FREQUENCY = 212
STOP_AND_GO_DIM_STATUS_MASK = 250
STOP_AND_GO_DIM_OPEN = 251
STOP_AND_GO_DIM_FAILURE = 252
STOP_AND_GO_DIM_BLOCKED = 253
STOP_AND_GO_DIM_NEUTRAL_SHORT_CIRCUIT = 254
STOP_AND_GO_DIM_GROUND_FAULT = 255
STOP_AND_GO_DIM_MAX_VOLTAGE = 256
STOP_AND_GO_DIM_SELF_TEST_DISABLED = 257
STOP_AND_GO_DIM_AUTORESET_OFF = 258
STOP_AND_GO_DIM_CHECK_OFF = 259
STOP_AND_GO_DIM_WAITING_CLOSING = 260
STOP_AND_GO_DIM_FIRST_24H_OPENING = 261
STOP_AND_GO_DIM_DOWNSTREAM_POWER_FAILURE = 262
STOP_AND_GO_DIM_UPSTREAM_POWER_FAILURE = 263

STOP_AND_GO_FLAG_DIMENSIONS = frozenset(
    range(STOP_AND_GO_DIM_OPEN, STOP_AND_GO_DIM_UPSTREAM_POWER_FAILURE + 1)
)

STOP_AND_GO_WHATS = {
    STOP_AND_GO_OPEN,
    STOP_AND_GO_CLOSE,
    STOP_AND_GO_TEST_POSITIVE,
    STOP_AND_GO_TEST_NEGATIVE,
    STOP_AND_GO_AUTORESET_ENABLE,
    STOP_AND_GO_AUTORESET_DISABLE,
    STOP_AND_GO_TRACKING_ENABLE,
    STOP_AND_GO_TRACKING_DISABLE,
}
STOP_AND_GO_DIMENSIONS = {
    STOP_AND_GO_DIM_TEST_FREQUENCY,
    STOP_AND_GO_DIM_STATUS_MASK,
    *STOP_AND_GO_FLAG_DIMENSIONS,
}


def _integer_value(
    values: list[str], index: int, default: int = 0
) -> int:
    """Read an integer field without letting an empty telemetry value crash."""
    try:
        return int(values[index])
    except (IndexError, TypeError, ValueError):
        return default



class OWNEnergyEvent(OWNEvent):
    def __init__(self, data: str) -> None:
        super().__init__(data)

        self._type: str | None = None
        where = self._where or ""
        self._sensor = where[1:] if len(where) > 1 else where
        self._active_power = 0
        self._total_consumption = 0
        # Values are heterogeneous: dates, hours (int) and Wh readings (int).
        self._hourly_consumption: dict[str, Any] = {}
        self._daily_consumption: dict[str, Any] = {}
        self._current_day_partial_consumption = 0
        self._monthly_consumption: dict[str, Any] = {}
        self._current_month_partial_consumption = 0
        self._update_interval: int | None = None
        self._energy_type: int | None = None

        if not where.startswith(("1", "5", "7")):
            return

        if self._dimension is not None:
            if self._dimension == 113:
                self._type = MESSAGE_TYPE_ACTIVE_POWER
                self._active_power = _integer_value(self._dimension_value, 0)
                self._human_readable_log = f"Sensor {self._sensor} is reporting an active power draw of {self._active_power} W."  # pylint: disable=line-too-long
            elif self._dimension == 511:
                _now = datetime.date.today()
                try:
                    _raw_message_date = datetime.date(
                        _now.year,
                        int(self._dimension_param[0]),
                        int(self._dimension_param[1]),
                    )
                    if _raw_message_date > _now:
                        _message_date = datetime.date(
                            _now.year - 1,
                            int(self._dimension_param[0]),
                            int(self._dimension_param[1]),
                        )
                    else:
                        _message_date = _raw_message_date
                except (ValueError, IndexError):
                    # Invalid date for the current year (e.g. Feb 29) or
                    # missing parameters: drop the sample, keep the session.
                    return

                if len(self._dimension_value) < 2 or not all(
                    self._dimension_value[:2]
                ):
                    return
                if int(self._dimension_value[0]) != 25:
                    self._type = MESSAGE_TYPE_HOURLY_CONSUMPTION
                    self._hourly_consumption["date"] = _message_date
                    self._hourly_consumption["hour"] = int(self._dimension_value[0]) - 1
                    self._hourly_consumption["value"] = int(self._dimension_value[1])
                    self._human_readable_log = f"Sensor {self._sensor} is reporting a power consumption of {self._hourly_consumption['value']} Wh for {self._hourly_consumption['date']} at {self._hourly_consumption['hour']}."  # pylint: disable=line-too-long
                else:
                    self._type = MESSAGE_TYPE_DAILY_CONSUMPTION
                    self._daily_consumption["date"] = _message_date
                    self._daily_consumption["value"] = int(self._dimension_value[1])
                    self._human_readable_log = f"Sensor {self._sensor} is reporting a power consumption of {self._daily_consumption['value']} Wh for {self._daily_consumption['date']}."  # pylint: disable=line-too-long
            elif self._dimension == 513 or self._dimension == 514:
                if len(self._dimension_value) < 2 or not all(
                    self._dimension_value[:2]
                ):
                    return
                _now = datetime.date.today()
                try:
                    _raw_message_date = datetime.date(
                        _now.year, int(self._dimension_param[0]), 1
                    )
                    if self._dimension == 513 and _raw_message_date > _now:
                        _message_date = datetime.date(
                            _now.year - 1,
                            int(self._dimension_param[0]),
                            int(self._dimension_value[0]),
                        )
                    elif self._dimension == 514:
                        if _raw_message_date > _now:
                            _message_date = datetime.date(
                                _now.year - 2,
                                int(self._dimension_param[0]),
                                int(self._dimension_value[0]),
                            )
                        else:
                            _message_date = datetime.date(
                                _now.year - 1,
                                int(self._dimension_param[0]),
                                int(self._dimension_value[0]),
                            )
                    else:
                        _message_date = datetime.date(
                            _now.year,
                            int(self._dimension_param[0]),
                            int(self._dimension_value[0]),
                        )
                except (ValueError, IndexError):
                    return
                self._type = MESSAGE_TYPE_DAILY_CONSUMPTION
                self._daily_consumption["date"] = _message_date
                self._daily_consumption["value"] = int(self._dimension_value[1])
                self._human_readable_log = f"Sensor {self._sensor} is reporting a power consumption of {self._daily_consumption['value']} Wh for {self._daily_consumption['date']}."  # pylint: disable=line-too-long
            elif self._dimension == 51:
                self._type = MESSAGE_TYPE_ENERGY_TOTALIZER
                self._total_consumption = _integer_value(self._dimension_value, 0)
                self._human_readable_log = f"Sensor {self._sensor} is reporting a total power consumption of {self._total_consumption} Wh."  # pylint: disable=line-too-long
            elif self._dimension == 54:
                self._type = MESSAGE_TYPE_CURRENT_DAY_CONSUMPTION
                self._current_day_partial_consumption = _integer_value(
                    self._dimension_value, 0
                )
                self._human_readable_log = f"Sensor {self._sensor} is reporting a power consumption of {self._current_day_partial_consumption} Wh up to now today."  # pylint: disable=line-too-long
            elif self._dimension == 52:
                self._type = MESSAGE_TYPE_MONTHLY_CONSUMPTION
                try:
                    # The month must be converted to int: passing the raw
                    # string to datetime.date raises TypeError.
                    _message_date = datetime.date(
                        int(f"20{self._dimension_param[0]}"),
                        int(self._dimension_param[1]),
                        1,
                    )
                except (ValueError, IndexError):
                    return
                self._monthly_consumption["date"] = _message_date
                self._monthly_consumption["value"] = _integer_value(
                    self._dimension_value, 0
                )
                self._human_readable_log = f"Sensor {self._sensor} is reporting a power consumption of {self._monthly_consumption['value']} Wh for {self._monthly_consumption['date'].strftime('%B %Y')}."  # pylint: disable=line-too-long
            elif self._dimension == 1200 and self._dimension_value:
                # *#18*W*1200#type*time##: the meter confirms (time > 0) or
                # ends (time = 0) the automatic power updates; libqtdevices
                # re-arms the stream on time = 0 (energy_device.cpp:289-322,
                # 719-726). type: 1 electricity, 2 gas, 3 heat, 4 water
                # (energy_device.cpp:50-56).
                self._type = MESSAGE_TYPE_AUTO_UPDATE_INTERVAL
                parsed_interval = _integer_value(self._dimension_value, 0)
                self._update_interval = max(0, parsed_interval)
                self._energy_type = (
                    max(0, _integer_value(self._dimension_param, 0, 0))
                    if self._dimension_param
                    else None
                )
                if self._update_interval == 0:
                    self._human_readable_log = f"Sensor {self._sensor} automatic updates stopped."
                else:
                    self._human_readable_log = f"Sensor {self._sensor} automatic updates for {self._update_interval} minutes."
            elif self._dimension == 53:
                self._type = MESSAGE_TYPE_CURRENT_MONTH_CONSUMPTION
                self._current_month_partial_consumption = _integer_value(
                    self._dimension_value, 0
                )
                self._human_readable_log = f"Sensor {self._sensor} is reporting a power consumption of {self._current_month_partial_consumption} Wh up to now this month."  # pylint: disable=line-too-long

    @property
    def message_type(self) -> str | None:
        return self._type

    @property
    def sensor(self) -> str:
        return self._sensor

    @property
    def update_interval(self) -> int | None:
        """Time field of a 1200 reply (stream duration in minutes per Legrand WHO 18), 0 when stopped.

        Retained for backward compatibility; prefer :attr:`stream_duration`.
        """
        return self._update_interval

    @property
    def stream_duration(self) -> int | None:
        """Time field of a 1200 reply (stream duration in minutes, 0..255 per Legrand WHO 18), 0 when stopped."""
        return self._update_interval

    @property
    def is_streaming_active(self) -> bool | None:
        """True if automatic updates are streaming (> 0 minutes), False if stopped (0 minutes), None if not a 1200 event."""
        if self._update_interval is None:
            return None
        return self._update_interval > 0

    @property
    def energy_type(self) -> int | None:
        """Energy type of a 1200 reply (1 electricity per Legrand WHO 18; 2 gas, 3 heat, 4 water per libqtdevices)."""
        return self._energy_type

    @property
    def active_power(self) -> int:
        return self._active_power

    @property
    def total_consumption(self) -> int:
        return self._total_consumption

    @property
    def hourly_consumption(self) -> dict[str, Any]:
        return self._hourly_consumption

    @property
    def daily_consumption(self) -> dict[str, Any]:
        return self._daily_consumption

    @property
    def current_day_partial_consumption(self) -> int:
        return self._current_day_partial_consumption

    @property
    def monthly_consumption(self) -> dict[str, Any]:
        return self._monthly_consumption

    @property
    def current_month_partial_consumption(self) -> int:
        return self._current_month_partial_consumption

    @property
    def target_address(self) -> str:
        """The full target address including any actuator channel suffix (#0)."""
        if self._where and self._where_param:
            return f"{self._where}#{'#'.join(self._where_param)}"
        return self._where or ""

    @property
    def is_actuator(self) -> bool:
        """True if the event originates from an energy management actuator (7N#0)."""
        return bool(
            self._where
            and (
                self._where.startswith("7")
                or (self._where_param and self._where_param == ["0"])
            )
        )

    @property
    def human_readable_log(self) -> str:
        return self._human_readable_log


def _normalize_actuator_where(where: str | int) -> str:
    """Normalize actuator address by ensuring #0 suffix per WHO 18 specification."""
    target = require_non_empty_where(where)
    if target.startswith("7") and not target.endswith("#0"):
        return f"{target}#0"
    return target


class OWNEnergyCommand(OWNCommand):
    @classmethod
    def start_sending_instant_power(
        cls, where: str | int, duration: int = 65, energy_type: int = 1
    ) -> OWNEnergyCommand:
        """Start automatic updates: *#18*W*#1200#type*time##.

        ``duration`` is the Time field (1..255, minutes per Legrand WHO 18;
        the meter answers *#18*W*1200#type*time##). ``energy_type`` 1 is
        electricity, 2 gas, 3 heat, 4 water (libqtdevices energy_device.cpp:50-56).
        """
        where = _normalize_actuator_where(where)
        etype = int(energy_type)
        if not 1 <= etype <= 4:
            raise ValueError("energy_type must be between 1 and 4")
        duration = 255 if duration > 255 else max(0, int(duration))
        message = cls(f"*#18*{where}*#1200#{etype}*{duration}##")
        if duration == 0:
            message._human_readable_log = f"Stopping instant power draw updates from sensor {where}."  # pylint: disable=line-too-long
        else:
            message._human_readable_log = f"Requesting instant power draw update from sensor {where} for {duration} minutes."  # pylint: disable=line-too-long
        return message

    @classmethod
    def stop_sending_instant_power(
        cls, where: str | int, energy_type: int = 1
    ) -> OWNEnergyCommand:
        """Stop automatic updates: *#18*W*#1200#type*0## (Time = 0).

        Firmware replay on bt_supervisione: *#18*51*#1200#1*0## ACK, bus
        D1 A1 02 32 00 02 1D 00; the meter then reports *#18*W*1200#type*0##.
        """
        where = _normalize_actuator_where(where)
        etype = int(energy_type)
        if not 1 <= etype <= 4:
            raise ValueError("energy_type must be between 1 and 4")
        message = cls(f"*#18*{where}*#1200#{etype}*0##")
        message._human_readable_log = f"Stopping instant power draw updates from sensor {where}."  # pylint: disable=line-too-long
        return message

    @classmethod
    def request_active_power(cls, where: str | int) -> OWNEnergyCommand:
        """Request instantaneous active power: *#18*W*113##.

        Legrand WHO 18 section 5.2.18 Dimension 113.
        """
        where = _normalize_actuator_where(where)
        message = cls(f"*#18*{where}*113##")
        message._human_readable_log = (
            f"Requesting active power from sensor {where}."
        )
        return message

    # Alias for API symmetry with get_total_consumption / downstream integrations
    get_instant_power = request_active_power

    @classmethod
    def get_hourly_consumption(
        cls, where: str | int, date: datetime.date
    ) -> OWNEnergyCommand | None:
        where = _normalize_actuator_where(where)
        today = datetime.date.today()
        one_year_ago = today - relativedelta(years=1)
        if date < one_year_ago:
            return None
        message = cls(f"*#18*{where}*511#{date.month}#{date.day}##")
        message._human_readable_log = (
            f"Requesting hourly power consumption from sensor {where} for {date}."
        )
        return message

    @classmethod
    def get_partial_daily_consumption(cls, where: str | int) -> OWNEnergyCommand:
        where = _normalize_actuator_where(where)
        message = cls(f"*#18*{where}*54##")
        message._human_readable_log = (
            f"Requesting today's partial power consumption from sensor {where}."
        )
        return message

    @classmethod
    def get_daily_consumption(
        cls, where: str | int, year: int, month: int
    ) -> OWNEnergyCommand | None:
        where = _normalize_actuator_where(where)
        today = datetime.date.today()
        one_year_ago = today - relativedelta(years=1)
        two_year_ago = today - relativedelta(years=2)
        target = datetime.date(year=year, month=month, day=1)
        if target > today:
            return None
        if target > one_year_ago:
            message = cls(f"*18*59#{month}*{where}##")
        elif target > two_year_ago:
            message = cls(f"*18*510#{month}*{where}##")
        else:
            return None
        message._human_readable_log = f"Requesting daily power consumption for {year}-{month} from sensor {where}."  # pylint: disable=line-too-long
        return message

    @classmethod
    def get_partial_monthly_consumption(cls, where: str | int) -> OWNEnergyCommand:
        where = _normalize_actuator_where(where)
        message = cls(f"*#18*{where}*53##")
        message._human_readable_log = (
            f"Requesting this month's partial power consumption from sensor {where}."
        )
        return message

    @classmethod
    def get_monthly_consumption(
        cls, where: str | int, year: int, month: int
    ) -> OWNEnergyCommand:
        where = _normalize_actuator_where(where)
        y = int(year)
        m = int(month)
        if not (2000 <= y <= 2099):
            raise ValueError("year must be between 2000 and 2099")
        if not (1 <= m <= 12):
            raise ValueError("month must be between 1 and 12")
        message = cls(f"*#18*{where}*52#{y % 100:02d}#{m}##")
        message._human_readable_log = f"Requesting monthly power consumption for {y}-{m} from sensor {where}."  # pylint: disable=line-too-long
        return message

    @classmethod
    def get_total_consumption(cls, where: str | int) -> OWNEnergyCommand:
        where = _normalize_actuator_where(where)
        message = cls(f"*#18*{where}*51##")
        message._human_readable_log = (
            f"Requesting total power consumption from sensor {where}."
        )
        return message


def _normalize_stop_and_go_where(where: str | int) -> str:
    """Normalize Stop&Go line address to 1N format (11..19)."""
    target = str(where).strip()
    if target.isdigit():
        val = int(target)
        if 1 <= val <= 9:
            return f"1{val}"
        if 11 <= val <= 19:
            return str(val)
    raise ValueError(
        f"Invalid Stop&Go line address '{where}': line must be 1..9 or address 11..19"
    )


class OWNStopAndGoEvent(OWNEvent):
    """WHO 18: Stop&Go automatic reset breaker (F16EB) events and telemetry.

    Derived from firmware evidence (energy-ts10 suite on MyHomeServer1, MH202, F454):
    - Breaker open/close: *18*21*1N## / *18*22*1N##
    - Differential self-test: *18*23*1N## (positive) / *18*24*1N## (negative)
    - Auto-reset activation/deactivation: *18*26*1N## / *18*27*1N##
    - Earth leakage tracking: *18*28*1N## / *18*29*1N##
        - Self-test frequency: *#18*1N*212*DAYS## (read response)
        - Status mask: *#18*1N*250*MASK##
        - Individual status flags: *#18*1N*251..263*BIT##
    Addresses are formatted as 1N (11..19, where line is 1..9).
    """

    def __init__(self, data: str) -> None:
        super().__init__(data)

        self._type = MESSAGE_TYPE_STOP_AND_GO
        self._state: int | None = None
        self._is_open: bool | None = None
        self._is_closed: bool | None = None
        self._is_auto_reset_active: bool | None = None
        self._is_tracking_active: bool | None = None
        self._differential_test_passed: bool | None = None
        self._differential_test_result: str | None = None
        self._test_frequency_days: int | None = None
        self._status_mask: str | None = None
        self._flag_dimension: int | None = None
        self._flag_active: bool | None = None

        line_num: int | None = None
        if (
            self._where
            and len(self._where) == 2
            and self._where.startswith("1")
            and self._where[1].isdigit()
        ):
            line_num = int(self._where[1])

        self._line = line_num

        if self._what is not None:
            self._state = self._what
            if self._what == STOP_AND_GO_OPEN:
                self._is_open = True
                self._is_closed = False
                self._human_readable_log = f"Stop&Go breaker {self._where} is open."
            elif self._what == STOP_AND_GO_CLOSE:
                self._is_open = False
                self._is_closed = True
                self._human_readable_log = f"Stop&Go breaker {self._where} is closed."
            elif self._what == STOP_AND_GO_TEST_POSITIVE:
                self._differential_test_passed = True
                self._differential_test_result = "positive"
                self._human_readable_log = (
                    f"Stop&Go breaker {self._where} differential test passed (positive)."
                )
            elif self._what == STOP_AND_GO_TEST_NEGATIVE:
                self._differential_test_passed = False
                self._differential_test_result = "negative"
                self._human_readable_log = (
                    f"Stop&Go breaker {self._where} differential test failed (negative)."
                )
            elif self._what == STOP_AND_GO_AUTORESET_ENABLE:
                self._is_auto_reset_active = True
                self._human_readable_log = (
                    f"Stop&Go breaker {self._where} auto-reset enabled."
                )
            elif self._what == STOP_AND_GO_AUTORESET_DISABLE:
                self._is_auto_reset_active = False
                self._human_readable_log = (
                    f"Stop&Go breaker {self._where} auto-reset disabled."
                )
            elif self._what == STOP_AND_GO_TRACKING_ENABLE:
                self._is_tracking_active = True
                self._human_readable_log = (
                    f"Stop&Go breaker {self._where} earth leakage tracking enabled."
                )
            elif self._what == STOP_AND_GO_TRACKING_DISABLE:
                self._is_tracking_active = False
                self._human_readable_log = (
                    f"Stop&Go breaker {self._where} earth leakage tracking disabled."
                )

        if self._dimension is not None:
            if (
                self._dimension == STOP_AND_GO_DIM_TEST_FREQUENCY
                and self._dimension_value
            ):
                self._test_frequency_days = _integer_value(self._dimension_value, 0)
                self._human_readable_log = (
                    f"Stop&Go breaker {self._where} test frequency is {self._test_frequency_days} days."
                )
            elif (
                self._dimension == STOP_AND_GO_DIM_STATUS_MASK
                and self._dimension_value
            ):
                self._status_mask = self._dimension_value[0]
                self._human_readable_log = (
                    f"Stop&Go breaker {self._where} status mask is {self._status_mask}."
                )
            elif (
                self._dimension in STOP_AND_GO_FLAG_DIMENSIONS
                and self._dimension_value
            ):
                bit = _integer_value(self._dimension_value, 0)
                active = bit == 1
                self._flag_dimension = self._dimension
                self._flag_active = active
                if self._dimension == STOP_AND_GO_DIM_OPEN:
                    self._is_open = active
                    self._is_closed = not active
                elif self._dimension == STOP_AND_GO_DIM_AUTORESET_OFF:
                    self._is_auto_reset_active = not active
                elif self._dimension == STOP_AND_GO_DIM_CHECK_OFF:
                    self._is_tracking_active = not active
                self._human_readable_log = (
                    f"Stop&Go breaker {self._where} status flag {self._dimension} is {bit}."
                )

    @property
    def message_type(self) -> str | None:
        return self._type

    @property
    def line(self) -> int | None:
        """Line number (1..9) corresponding to address 1N, or None if non-standard."""
        return self._line

    @property
    def state(self) -> int | None:
        return self._state

    @property
    def is_open(self) -> bool | None:
        return self._is_open

    @property
    def is_closed(self) -> bool | None:
        return self._is_closed

    @property
    def is_auto_reset_active(self) -> bool | None:
        return self._is_auto_reset_active

    @property
    def is_tracking_active(self) -> bool | None:
        return self._is_tracking_active

    @property
    def differential_test_passed(self) -> bool | None:
        return self._differential_test_passed

    @property
    def differential_test_result(self) -> str | None:
        return self._differential_test_result

    @property
    def test_frequency_days(self) -> int | None:
        return self._test_frequency_days

    @property
    def status_mask(self) -> str | None:
        return self._status_mask

    @property
    def flag_dimension(self) -> int | None:
        """Individual Stop&Go status flag dimension (251..263), if applicable."""
        return self._flag_dimension

    @property
    def flag_active(self) -> bool | None:
        """Whether the reported single-bit Stop&Go status flag (251..263) is set (`1`)."""
        return self._flag_active


class OWNStopAndGoCommand(OWNCommand):
    """WHO 18: Stop&Go automatic reset breaker commands and requests."""

    def __init__(self, data: str) -> None:
        super().__init__(data)
        if self._what is not None:
            if self._what == STOP_AND_GO_OPEN:
                self._human_readable_log = f"Opening Stop&Go breaker {self._where}."
            elif self._what == STOP_AND_GO_CLOSE:
                self._human_readable_log = f"Closing Stop&Go breaker {self._where}."
            elif self._what == STOP_AND_GO_TEST_POSITIVE:
                self._human_readable_log = (
                    f"Triggering positive differential test on Stop&Go breaker {self._where}."
                )
            elif self._what == STOP_AND_GO_TEST_NEGATIVE:
                self._human_readable_log = (
                    f"Triggering negative differential test on Stop&Go breaker {self._where}."
                )
            elif self._what == STOP_AND_GO_AUTORESET_ENABLE:
                self._human_readable_log = (
                    f"Enabling auto-reset on Stop&Go breaker {self._where}."
                )
            elif self._what == STOP_AND_GO_AUTORESET_DISABLE:
                self._human_readable_log = (
                    f"Disabling auto-reset on Stop&Go breaker {self._where}."
                )
            elif self._what == STOP_AND_GO_TRACKING_ENABLE:
                self._human_readable_log = (
                    f"Enabling earth leakage tracking on Stop&Go breaker {self._where}."
                )
            elif self._what == STOP_AND_GO_TRACKING_DISABLE:
                self._human_readable_log = (
                    f"Disabling earth leakage tracking on Stop&Go breaker {self._where}."
                )
        elif self._dimension is not None:
            if self._dimension == STOP_AND_GO_DIM_TEST_FREQUENCY:
                if self._dimension_value:
                    self._human_readable_log = (
                        f"Setting Stop&Go breaker {self._where} test frequency to {self._dimension_value[0]} days."
                    )
                else:
                    self._human_readable_log = (
                        f"Requesting Stop&Go breaker {self._where} test frequency."
                    )
            elif self._dimension == STOP_AND_GO_DIM_STATUS_MASK:
                self._human_readable_log = (
                    f"Requesting Stop&Go breaker {self._where} status mask."
                )
            elif self._dimension in STOP_AND_GO_FLAG_DIMENSIONS:
                self._human_readable_log = (
                    f"Requesting Stop&Go breaker {self._where} status flag {self._dimension}."
                )

    @classmethod
    def open_breaker(cls, where: str | int) -> OWNStopAndGoCommand:
        target = _normalize_stop_and_go_where(where)
        return cls(f"*18*{STOP_AND_GO_OPEN}*{target}##")

    @classmethod
    def close_breaker(cls, where: str | int) -> OWNStopAndGoCommand:
        target = _normalize_stop_and_go_where(where)
        return cls(f"*18*{STOP_AND_GO_CLOSE}*{target}##")

    @classmethod
    def test_differential_positive(cls, where: str | int) -> OWNStopAndGoCommand:
        target = _normalize_stop_and_go_where(where)
        return cls(f"*18*{STOP_AND_GO_TEST_POSITIVE}*{target}##")

    @classmethod
    def test_differential_negative(cls, where: str | int) -> OWNStopAndGoCommand:
        target = _normalize_stop_and_go_where(where)
        return cls(f"*18*{STOP_AND_GO_TEST_NEGATIVE}*{target}##")

    @classmethod
    def set_auto_reset(cls, where: str | int, enabled: bool) -> OWNStopAndGoCommand:
        target = _normalize_stop_and_go_where(where)
        what = (
            STOP_AND_GO_AUTORESET_ENABLE if enabled else STOP_AND_GO_AUTORESET_DISABLE
        )
        return cls(f"*18*{what}*{target}##")

    @classmethod
    def enable_auto_reset(cls, where: str | int) -> OWNStopAndGoCommand:
        return cls.set_auto_reset(where, True)

    @classmethod
    def disable_auto_reset(cls, where: str | int) -> OWNStopAndGoCommand:
        return cls.set_auto_reset(where, False)

    @classmethod
    def set_tracking(cls, where: str | int, enabled: bool) -> OWNStopAndGoCommand:
        target = _normalize_stop_and_go_where(where)
        what = STOP_AND_GO_TRACKING_ENABLE if enabled else STOP_AND_GO_TRACKING_DISABLE
        return cls(f"*18*{what}*{target}##")

    @classmethod
    def enable_tracking(cls, where: str | int) -> OWNStopAndGoCommand:
        return cls.set_tracking(where, True)

    @classmethod
    def disable_tracking(cls, where: str | int) -> OWNStopAndGoCommand:
        return cls.set_tracking(where, False)

    @classmethod
    def set_test_frequency(cls, where: str | int, days: int) -> OWNStopAndGoCommand:
        target = _normalize_stop_and_go_where(where)
        if days < 1 or days > 255:
            raise ValueError(
                f"Self-test frequency days must be between 1 and 255, got {days}"
            )
        return cls(f"*#18*{target}*#{STOP_AND_GO_DIM_TEST_FREQUENCY}*{days}##")

    @classmethod
    def request_test_frequency(cls, where: str | int) -> OWNStopAndGoCommand:
        target = _normalize_stop_and_go_where(where)
        return cls(f"*#18*{target}*{STOP_AND_GO_DIM_TEST_FREQUENCY}##")

    @classmethod
    def request_status_mask(cls, where: str | int) -> OWNStopAndGoCommand:
        target = _normalize_stop_and_go_where(where)
        return cls(f"*#18*{target}*{STOP_AND_GO_DIM_STATUS_MASK}##")

    @classmethod
    def request_status_flag(
        cls, where: str | int, dimension: int
    ) -> OWNStopAndGoCommand:
        target = _normalize_stop_and_go_where(where)
        if dimension not in STOP_AND_GO_FLAG_DIMENSIONS:
            raise ValueError(
                f"Stop&Go status flag dimension must be between {STOP_AND_GO_DIM_OPEN} and {STOP_AND_GO_DIM_UPSTREAM_POWER_FAILURE}, got {dimension}"
            )
        return cls(f"*#18*{target}*{dimension}##")


def _parse_who18_event(data: str) -> OWNEvent:
    event = OWNEvent(data)
    if event._what in STOP_AND_GO_WHATS or event._dimension in STOP_AND_GO_DIMENSIONS:
        return OWNStopAndGoEvent(data)
    return OWNEnergyEvent(data)


def _parse_who18_command(data: str) -> OWNCommand:
    cmd = OWNCommand(data)
    if cmd._what in STOP_AND_GO_WHATS or cmd._dimension in STOP_AND_GO_DIMENSIONS:
        return OWNStopAndGoCommand(data)
    return OWNEnergyCommand(data)


register_event_parser(18, _parse_who18_event)
register_command_parser(18, _parse_who18_command)

