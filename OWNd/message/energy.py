"""WHO 18: Energy management events, commands, and consumption types."""

from __future__ import annotations

import datetime
import re
from typing import Any

from dateutil.relativedelta import relativedelta

from .base import OWNCommand, OWNEvent, register_command_parser, register_event_parser

MESSAGE_TYPE_ACTIVE_POWER = "active_power"
MESSAGE_TYPE_ENERGY_TOTALIZER = "energy_totalizer"
MESSAGE_TYPE_HOURLY_CONSUMPTION = "hourly_consumption"
MESSAGE_TYPE_DAILY_CONSUMPTION = "daily_consumption"
MESSAGE_TYPE_MONTHLY_CONSUMPTION = "monthly_consumption"
MESSAGE_TYPE_CURRENT_DAY_CONSUMPTION = "current_day_partial_consumption"
MESSAGE_TYPE_CURRENT_MONTH_CONSUMPTION = "current_month_partial_consumption"
MESSAGE_TYPE_AUTO_UPDATE_INTERVAL = "auto_update_interval"


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
                self._update_interval = _integer_value(self._dimension_value, 0)
                self._energy_type = _integer_value(self._dimension_param, 0, 0) if self._dimension_param else None
                self._human_readable_log = f"Sensor {self._sensor} automatic updates every {self._update_interval} s (0 = stopped)."  # pylint: disable=line-too-long
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
        """Seconds between automatic power updates from a 1200 reply, 0 when stopped."""
        return self._update_interval

    @property
    def energy_type(self) -> int | None:
        """Energy type of a 1200 reply (1 electricity, 2 gas, 3 heat, 4 water)."""
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
    def human_readable_log(self) -> str:
        return self._human_readable_log



class OWNEnergyCommand(OWNCommand):
    @classmethod
    def start_sending_instant_power(
        cls, where: str | int, duration: int = 65
    ) -> OWNEnergyCommand:
        where = f"{where}#0" if str(where).startswith("7") else str(where)
        duration = 255 if duration > 255 else duration
        message = cls(f"*#18*{where}*#1200#1*{duration}##")
        message._human_readable_log = f"Requesting instant power draw update from sensor {where} for {duration} minutes."  # pylint: disable=line-too-long
        return message

    @classmethod
    def get_hourly_consumption(
        cls, where: str | int, date: datetime.date
    ) -> OWNEnergyCommand | None:
        where = f"{where}#0" if str(where).startswith("7") else str(where)
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
        where = f"{where}#0" if str(where).startswith("7") else str(where)
        message = cls(f"*#18*{where}*54##")
        message._human_readable_log = (
            f"Requesting today's partial power consumption from sensor {where}."
        )
        return message

    @classmethod
    def get_daily_consumption(
        cls, where: str | int, year: int, month: int
    ) -> OWNEnergyCommand | None:
        where = f"{where}#0" if str(where).startswith("7") else str(where)
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
        where = f"{where}#0" if str(where).startswith("7") else str(where)
        message = cls(f"*#18*{where}*53##")
        message._human_readable_log = (
            f"Requesting this month's partial power consumption from sensor {where}."
        )
        return message

    @classmethod
    def get_monthly_consumption(
        cls, where: str | int, year: int, month: int
    ) -> OWNEnergyCommand:
        where = f"{where}#0" if str(where).startswith("7") else str(where)
        message = cls(f"*#18*{where}*52#{str(year)[2:]}#{month}##")
        message._human_readable_log = f"Requesting monthly power consumption for {year}-{month} from sensor {where}."  # pylint: disable=line-too-long
        return message

    @classmethod
    def get_total_consumption(cls, where: str | int) -> OWNEnergyCommand:
        where = f"{where}#0" if str(where).startswith("7") else str(where)
        message = cls(f"*#18*{where}*51##")
        message._human_readable_log = (
            f"Requesting total power consumption from sensor {where}."
        )
        return message


register_event_parser(18, OWNEnergyEvent)
register_command_parser(18, OWNEnergyCommand)
