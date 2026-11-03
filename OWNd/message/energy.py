"""WHO 18: Energy management events, commands, and consumption types."""

from __future__ import annotations

import datetime
import math
import re
from typing import Any

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
# DIMENSION 512#M*Tag*Val (Encyclopedia who-18 dimensions.md
# "DIMENSION 512 - monthly-average hourly series").
MESSAGE_TYPE_MONTHLY_AVERAGE_CONSUMPTION = "monthly_average_consumption"
# DIMENSION 71 / 72#Tot_N / 73 (dimensions.md "Energy Management actuator
# information").
MESSAGE_TYPE_ACTUATOR_STATUS = "actuator_status"
MESSAGE_TYPE_TOTALIZER_STATE = "totalizer_state"
MESSAGE_TYPE_DIFFERENTIAL_CURRENT_LEVEL = "differential_current_level"
# WHAT 57#M#D / 58#M / 59#M / 510#M (what.md "Historical-series commands").
MESSAGE_TYPE_HISTORICAL_SERIES_START = "historical_series_start"
# WHAT 71 / 73[#Time] / 74 / 75#Tot_N (what.md "Actuator commands",
# "Reset totalizer").
MESSAGE_TYPE_ACTUATOR_ENABLED = "actuator_enabled"
MESSAGE_TYPE_ACTUATOR_FORCED = "actuator_forced"
MESSAGE_TYPE_ACTUATOR_FORCING_ENDED = "actuator_forcing_ended"
MESSAGE_TYPE_TOTALIZER_RESET = "totalizer_reset"

# Energy Management actuator WHATs (Encyclopedia who-18 what.md "Commands").
ENERGY_ACTUATOR_ENABLE = 71
ENERGY_ACTUATOR_FORCE = 73
ENERGY_ACTUATOR_END_FORCING = 74
ENERGY_TOTALIZER_RESET = 75
# Historical-series start WHATs: an enumerated set, not the interval 57..510
# (what.md "Historical-series commands").
ENERGY_SERIES_DAILY = 57
ENERGY_SERIES_MONTHLY_AVERAGE = 58
ENERGY_SERIES_CURRENT_YEAR = 59
ENERGY_SERIES_PREVIOUS_YEAR = 510
HISTORICAL_SERIES_DIMENSIONS = {
    ENERGY_SERIES_DAILY: 511,
    ENERGY_SERIES_MONTHLY_AVERAGE: 512,
    ENERGY_SERIES_CURRENT_YEAR: 513,
    ENERGY_SERIES_PREVIOUS_YEAR: 514,
}

# Stop&Go family WHERE is 1N with N = 1..127 (Encyclopedia who-18
# addressing.md "Published WHERE forms"; README.md "Device families").
STOP_AND_GO_LINE_MAX = 127
_STOP_AND_GO_WHERE = re.compile(r"^1(?P<line>[1-9]\d{0,2})$", re.ASCII)

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
        # ``sensor`` strips the family prefix (meter ``51`` -> ``1``); kept
        # for compatibility. Logs and ``address`` keep the complete WHERE
        # (Encyclopedia who-18 addressing.md: "preserve the complete
        # syntactic form").
        self._sensor = where[1:] if len(where) > 1 else where
        self._address = (
            f"{where}#{'#'.join(self._where_param)}" if where and self._where_param else where
        )
        self._active_power = 0
        self._total_consumption = 0
        # Values are heterogeneous: dates, hours (int) and Wh readings (int).
        self._hourly_consumption: dict[str, Any] = {}
        self._daily_consumption: dict[str, Any] = {}
        self._current_day_partial_consumption = 0
        self._monthly_consumption: dict[str, Any] = {}
        self._current_month_partial_consumption = 0
        self._monthly_average_consumption: dict[str, Any] = {}
        self._actuator_status: dict[str, bool | None] = {}
        self._totalizer: dict[str, Any] = {}
        self._differential_current_level: int | None = None
        self._series_dimension: int | None = None
        self._series_month: int | None = None
        self._series_day: int | None = None
        self._forcing_time: int | None = None
        self._totalizer_number: int | None = None
        self._update_interval: int | None = None
        self._energy_type: int | None = None

        if not where.startswith(("1", "5", "7")):
            return

        if self._what is not None:
            self._decode_what()
        elif self._dimension is not None:
            self._decode_dimension()

    def _decode_what(self) -> None:
        """Decode the WHO 18 WHATs an event session echoes.

        WHAT 57#M#D / 58#M / 59#M / 510#M start a historical series (Encyclopedia
        who-18 what.md "Historical-series commands"); WHAT 71, 73[#Time], 74 and
        75#Tot_N are the Energy Management actuator commands (what.md "Actuator
        commands", "Reset totalizer"). Other WHATs stay ``message_type`` None.
        """
        params = self._what_param
        if self._what in HISTORICAL_SERIES_DIMENSIONS:
            expected = 2 if self._what == ENERGY_SERIES_DAILY else 1
            # Guarded: a non-digit or empty parameter keeps the typed fields None.
            if len(params) != expected or not all(p.isdigit() for p in params):
                return
            month = int(params[0])
            day = int(params[1]) if expected == 2 else None
            if not 1 <= month <= 12 or (day is not None and not 1 <= day <= 31):
                return
            self._type = MESSAGE_TYPE_HISTORICAL_SERIES_START
            self._series_dimension = HISTORICAL_SERIES_DIMENSIONS[self._what]
            self._series_month = month
            self._series_day = day
            period = f"month {month}" if day is None else f"{month}/{day}"
            self._human_readable_log = f"Sensor {self._address} starts the DIMENSION {self._series_dimension} series for {period}."  # pylint: disable=line-too-long
        elif self._what == ENERGY_ACTUATOR_ENABLE and not params:
            self._type = MESSAGE_TYPE_ACTUATOR_ENABLED
            self._human_readable_log = f"Actuator {self._address} is enabled."
        elif self._what == ENERGY_ACTUATOR_FORCE:
            if params:
                # Time in tens of minutes, 1..254 (what.md "Force for a
                # specified time").
                if len(params) != 1 or not params[0].isdigit() or not 1 <= int(params[0]) <= 254:
                    return
                self._forcing_time = int(params[0])
                self._human_readable_log = f"Actuator {self._address} is forced for {self._forcing_time * 10} minutes."  # pylint: disable=line-too-long
            else:
                self._human_readable_log = f"Actuator {self._address} is forced for the default time."  # pylint: disable=line-too-long
            self._type = MESSAGE_TYPE_ACTUATOR_FORCED
        elif self._what == ENERGY_ACTUATOR_END_FORCING and not params:
            self._type = MESSAGE_TYPE_ACTUATOR_FORCING_ENDED
            self._human_readable_log = f"Actuator {self._address} forcing ended."
        elif self._what == ENERGY_TOTALIZER_RESET:
            if len(params) != 1 or params[0] not in ("1", "2"):
                return
            self._type = MESSAGE_TYPE_TOTALIZER_RESET
            self._totalizer_number = int(params[0])
            self._human_readable_log = f"Actuator {self._address} totalizer {self._totalizer_number} reset."  # pylint: disable=line-too-long

    def _decode_dimension(self) -> None:
        """Decode the WHO 18 DIMENSION replies and events."""
        if self._dimension == 113:
            self._type = MESSAGE_TYPE_ACTIVE_POWER
            self._active_power = _integer_value(self._dimension_value, 0)
            self._human_readable_log = f"Sensor {self._address} is reporting an active power draw of {self._active_power} W."  # pylint: disable=line-too-long
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
                v.isdigit() for v in self._dimension_value[:2]
            ):
                return
            # Tag 1..24 is an hourly measure, 25 the daily total; nothing
            # else is defined (Encyclopedia who-18 dimensions.md
            # "DIMENSION 511 - daily hourly series").
            tag = int(self._dimension_value[0])
            if 1 <= tag <= 24:
                self._type = MESSAGE_TYPE_HOURLY_CONSUMPTION
                self._hourly_consumption["date"] = _message_date
                self._hourly_consumption["hour"] = tag - 1
                self._hourly_consumption["value"] = int(self._dimension_value[1])
                self._human_readable_log = f"Sensor {self._address} is reporting a power consumption of {self._hourly_consumption['value']} Wh for {self._hourly_consumption['date']} at {self._hourly_consumption['hour']}."  # pylint: disable=line-too-long
            elif tag == 25:
                self._type = MESSAGE_TYPE_DAILY_CONSUMPTION
                self._daily_consumption["date"] = _message_date
                self._daily_consumption["value"] = int(self._dimension_value[1])
                self._human_readable_log = f"Sensor {self._address} is reporting a power consumption of {self._daily_consumption['value']} Wh for {self._daily_consumption['date']}."  # pylint: disable=line-too-long
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
            self._human_readable_log = f"Sensor {self._address} is reporting a power consumption of {self._daily_consumption['value']} Wh for {self._daily_consumption['date']}."  # pylint: disable=line-too-long
        elif self._dimension == 51:
            self._type = MESSAGE_TYPE_ENERGY_TOTALIZER
            self._total_consumption = _integer_value(self._dimension_value, 0)
            self._human_readable_log = f"Sensor {self._address} is reporting a total power consumption of {self._total_consumption} Wh."  # pylint: disable=line-too-long
        elif self._dimension == 54:
            self._type = MESSAGE_TYPE_CURRENT_DAY_CONSUMPTION
            self._current_day_partial_consumption = _integer_value(
                self._dimension_value, 0
            )
            self._human_readable_log = f"Sensor {self._address} is reporting a power consumption of {self._current_day_partial_consumption} Wh up to now today."  # pylint: disable=line-too-long
        elif self._dimension == 52:
            # *#18*WHERE*52#Y#M*Val##, Y two-digit (Encyclopedia who-18
            # dimensions.md "DIMENSION 52 - monthly energy/unit totalizer";
            # "Explicit 52#Y#M replies use 2000 + Y"). A reply without
            # #Y#M or with an invalid month keeps the value and reports
            # None for year, month and date (audit E1).
            self._type = MESSAGE_TYPE_MONTHLY_CONSUMPTION
            _month_date: datetime.date | None = None
            try:
                # The month must be converted to int: passing the raw
                # string to datetime.date raises TypeError.
                _month_date = datetime.date(
                    int(f"20{self._dimension_param[0]}"),
                    int(self._dimension_param[1]),
                    1,
                )
            except (ValueError, IndexError):
                _month_date = None
            self._monthly_consumption["date"] = _month_date
            self._monthly_consumption["year"] = (
                _month_date.year if _month_date else None
            )
            self._monthly_consumption["month"] = (
                _month_date.month if _month_date else None
            )
            self._monthly_consumption["value"] = _integer_value(
                self._dimension_value, 0
            )
            period = (
                _month_date.strftime("%B %Y")
                if _month_date
                else "an unspecified month"
            )
            self._human_readable_log = f"Sensor {self._address} is reporting a power consumption of {self._monthly_consumption['value']} Wh for {period}."  # pylint: disable=line-too-long
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
                self._human_readable_log = f"Sensor {self._address} automatic updates stopped."
            else:
                self._human_readable_log = f"Sensor {self._address} automatic updates for {self._update_interval} minutes."
        elif self._dimension == 53:
            self._type = MESSAGE_TYPE_CURRENT_MONTH_CONSUMPTION
            self._current_month_partial_consumption = _integer_value(
                self._dimension_value, 0
            )
            self._human_readable_log = f"Sensor {self._address} is reporting a power consumption of {self._current_month_partial_consumption} Wh up to now this month."  # pylint: disable=line-too-long
        elif self._dimension == 512:
            self._decode_monthly_average()
        elif self._dimension == 71:
            self._decode_actuator_status()
        elif self._dimension == 72:
            self._decode_totalizer()
        elif self._dimension == 73:
            # *#18*WHERE*73*level##, level 1..3 (Encyclopedia who-18
            # dimensions.md "DIMENSION 73 - differential-current level";
            # libqtdevices labels 1 OK, 2 warning, 3 critical, a client
            # classification, not a published one).
            if len(self._dimension_value) != 1 or self._dimension_value[0] not in ("1", "2", "3"):
                return
            self._type = MESSAGE_TYPE_DIFFERENTIAL_CURRENT_LEVEL
            self._differential_current_level = int(self._dimension_value[0])
            self._human_readable_log = f"Actuator {self._address} differential-current level is {self._differential_current_level}."  # pylint: disable=line-too-long

    def _decode_monthly_average(self) -> None:
        """*#18*WHERE*512#M*Tag*Val##: monthly-average hourly series.

        Tags 1..24 are hourly averages over month M, tag 25 the monthly-average
        total (Encyclopedia who-18 dimensions.md "DIMENSION 512 -
        monthly-average hourly series"); started by WHAT 58#M. The frame carries
        no year, and none is inferred.
        """
        if (
            len(self._dimension_param) != 1
            or not self._dimension_param[0].isdigit()
            or len(self._dimension_value) != 2
            or not all(v.isdigit() for v in self._dimension_value)
        ):
            return
        month = int(self._dimension_param[0])
        tag = int(self._dimension_value[0])
        if not 1 <= month <= 12 or not 1 <= tag <= 25:
            return
        self._type = MESSAGE_TYPE_MONTHLY_AVERAGE_CONSUMPTION
        self._monthly_average_consumption = {
            "month": month,
            "tag": tag,
            "hour": tag - 1 if tag <= 24 else None,
            "value": int(self._dimension_value[1]),
        }
        if tag <= 24:
            self._human_readable_log = f"Sensor {self._address} is reporting an average power consumption of {self._monthly_average_consumption['value']} Wh at hour {tag - 1} of month {month}."  # pylint: disable=line-too-long
        else:
            self._human_readable_log = f"Sensor {self._address} is reporting a monthly-average power consumption of {self._monthly_average_consumption['value']} Wh for month {month}."  # pylint: disable=line-too-long

    def _decode_actuator_status(self) -> None:
        """*#18*WHERE*71*disabled*forcing*threshold*protection*phase*advanced##.

        Six positional fields (Encyclopedia who-18 dimensions.md "DIMENSION 71 -
        actuator status"): disabled 0/1, forcing 0 not forced / 1 forced,
        threshold 0 above / 1 below, protection 0/1, phase 0 disable of other
        phase / 1 disable of local phase, advanced 1 advanced / 2 basic. Any
        other shape stays ``message_type`` None.
        """
        values = self._dimension_value
        if len(values) != 6 or not all(v in ("0", "1") for v in values[:5]) or values[5] not in ("1", "2"):
            return
        self._type = MESSAGE_TYPE_ACTUATOR_STATUS
        self._actuator_status = {
            "disabled": values[0] == "1",
            "forced": values[1] == "1",
            "below_threshold": values[2] == "1",
            "protection": values[3] == "1",
            "local_phase_disabled": values[4] == "1",
            "advanced": values[5] == "1",
        }
        state = "disabled" if self._actuator_status["disabled"] else "enabled"
        forced = ", forced" if self._actuator_status["forced"] else ""
        self._human_readable_log = f"Actuator {self._address} is {state}{forced}."

    def _decode_totalizer(self) -> None:
        """*#18*WHERE*72#Tot_N*Energy*D*M*Y*H*m##: totalizer state.

        Tot_N 1..2, Energy in Wh since the reset, then the day, month, year, hour
        and minute of the last reset (Encyclopedia who-18 dimensions.md
        "DIMENSION 72 - totalizer state"). ``reset`` is a ``datetime`` when the
        five fields form a valid timestamp; a two-digit year is read as
        ``2000 + Y`` by analogy with DIMENSION 52 (an inference: the page does
        not state the width of ``Y``).
        """
        if (
            len(self._dimension_param) != 1
            or self._dimension_param[0] not in ("1", "2")
            or len(self._dimension_value) != 6
            or not all(v.isdigit() for v in self._dimension_value)
        ):
            return
        energy, day, month, year, hour, minute = (int(v) for v in self._dimension_value)
        if year < 100:
            year += 2000
        try:
            reset: datetime.datetime | None = datetime.datetime(year, month, day, hour, minute)
        except ValueError:
            reset = None
        self._type = MESSAGE_TYPE_TOTALIZER_STATE
        self._totalizer_number = int(self._dimension_param[0])
        self._totalizer = {
            "number": self._totalizer_number,
            "value": energy,
            "reset": reset,
            "day": day,
            "month": month,
            "year": year,
            "hour": hour,
            "minute": minute,
        }
        since = f" since {reset:%Y-%m-%d %H:%M}" if reset else ""
        self._human_readable_log = f"Actuator {self._address} totalizer {self._totalizer_number} is {energy} Wh{since}."  # pylint: disable=line-too-long

    @property
    def message_type(self) -> str | None:
        return self._type

    @property
    def sensor(self) -> str:
        """WHERE without its family prefix (meter ``51`` -> ``1``, actuator ``71#0`` -> ``1``).

        Kept for compatibility; the prefix is part of the address (Encyclopedia
        who-18 addressing.md), so prefer :attr:`address`.
        """
        return self._sensor

    @property
    def address(self) -> str:
        """The complete WHERE as received, family prefix and suffix included (``51``, ``71#0``, ``11``)."""
        return self._address

    @property
    def update_interval(self) -> int | None:
        """Time field of a 1200 reply, 0 when the automatic updates are stopped.

        The published WHO 18 text defines ``Time`` (1..255 minutes) as "after
        how many minutes consumption/status is sent when it changes", a
        report-on-change parameter rather than an unconditional sampling
        interval (Encyclopedia who-18 dimensions.md "DIMENSION 1200 -
        automatic active-power updates"). On an F520 behind an F454 2.0 the
        updates stop ``Time`` minutes after the start (``*#18*56*1200#1*0##``
        about 126 s after ``*#18*56*#1200#1*2##``, MyHOME#661), so the field
        also bounds the stream. Retained for backward compatibility; prefer
        :attr:`stream_duration`.
        """
        return self._update_interval

    @property
    def stream_duration(self) -> int | None:
        """Time field of a 1200 reply (0..255 minutes), 0 when stopped.

        See :attr:`update_interval` for the published report-on-change meaning
        of ``Time`` and the capture showing it bounds the stream.
        """
        return self._update_interval

    @property
    def is_streaming_active(self) -> bool | None:
        """True if automatic updates are active (Time > 0), False if stopped (Time = 0), None if not a 1200 event."""
        if self._update_interval is None:
            return None
        return self._update_interval > 0

    @property
    def monthly_average_consumption(self) -> dict[str, Any]:
        """DIMENSION 512#M*Tag*Val: ``month``, ``tag`` (1..25), ``hour`` (0..23, None for the tag-25 total), ``value`` (Wh)."""
        return self._monthly_average_consumption

    @property
    def actuator_status(self) -> dict[str, bool | None]:
        """DIMENSION 71 fields: ``disabled``, ``forced``, ``below_threshold``, ``protection``, ``local_phase_disabled``, ``advanced``."""
        return self._actuator_status

    @property
    def totalizer(self) -> dict[str, Any]:
        """DIMENSION 72#Tot_N: ``number``, ``value`` (Wh since reset), ``reset`` (datetime or None), ``day``, ``month``, ``year``, ``hour``, ``minute``."""
        return self._totalizer

    @property
    def totalizer_number(self) -> int | None:
        """Tot_N (1..2) of a DIMENSION 72 state or a WHAT 75#Tot_N reset, else None."""
        return self._totalizer_number

    @property
    def differential_current_level(self) -> int | None:
        """DIMENSION 73 level 1..3, else None."""
        return self._differential_current_level

    @property
    def series_dimension(self) -> int | None:
        """DIMENSION (511..514) that a WHAT 57 / 58 / 59 / 510 series start announces, else None."""
        return self._series_dimension

    @property
    def series_month(self) -> int | None:
        """Month parameter of a WHAT 57 / 58 / 59 / 510 series start, else None."""
        return self._series_month

    @property
    def series_day(self) -> int | None:
        """Day parameter of a WHAT 57#M#D series start, else None."""
        return self._series_day

    @property
    def forcing_time(self) -> int | None:
        """Time parameter of WHAT 73#Time in tens of minutes (1..254); None for WHAT 73 (default time) and other events."""
        return self._forcing_time

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
        """The full target address including any actuator channel suffix (#0); same as :attr:`address`."""
        return self._address

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


# Energy Management actuator address ``7N#0``, N = 1..255, no leading zero
# (Encyclopedia who-18 addressing.md "Published WHERE forms").
_ACTUATOR_WHERE = re.compile(r"^7(?P<number>[1-9]\d{0,2})#0$")


def _normalize_actuator_where(where: str | int) -> str:
    """Normalize actuator address by ensuring #0 suffix per WHO 18 specification."""
    target = require_non_empty_where(where)
    if target.startswith("7") and not target.endswith("#0"):
        return f"{target}#0"
    return target


def _require_actuator_where(where: str | int) -> str:
    """Normalize and require an Energy Management actuator address ``7N#0``.

    Actuator commands and DIMENSION 71..73 apply to the ``7N#0`` family only
    (Encyclopedia who-18 addressing.md "Family-specific operations").
    """
    target = _normalize_actuator_where(where)
    match = _ACTUATOR_WHERE.match(target)
    if match is None or not 1 <= int(match.group("number")) <= 255:
        raise ValueError(
            f"Invalid Energy Management actuator address '{where}': expected 7N#0 (N = 1..255)"
        )
    return target


class OWNEnergyCommand(OWNCommand):
    @classmethod
    def start_sending_instant_power(
        cls, where: str | int, duration: int = 65, energy_type: int = 1
    ) -> OWNEnergyCommand:
        """Start automatic updates: *#18*W*#1200#type*time##.

        ``duration`` is the Time field (1..255 minutes): the published text
        says "after how many minutes consumption/status is sent when it
        changes", a report-on-change parameter and not an unconditional
        sampling interval (Encyclopedia who-18 dimensions.md "DIMENSION 1200 -
        automatic active-power updates"); the meter answers
        *#18*W*1200#type*time## and, on the F520 capture of MyHOME#661,
        reports ``*#18*W*1200#type*0##`` once Time minutes have elapsed.
        ``energy_type`` 1 is the published active power; 2 gas, 3 heat, 4 water
        are libqtdevices extensions (dimensions.md "Measurement families and
        automatic updates").
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
        one_year_ago = today.replace(
            year=today.year - 1,
            day=28 if (today.month, today.day) == (2, 29) else today.day,
        )
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
        one_year_ago = today.replace(
            year=today.year - 1,
            day=28 if (today.month, today.day) == (2, 29) else today.day,
        )
        two_year_ago = today.replace(
            year=today.year - 2,
            day=28 if (today.month, today.day) == (2, 29) else today.day,
        )
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

    @property
    def is_dimension_query(self) -> bool:
        """True if this message is a WHO 18 dimension request (*#18*WHERE*DIM##)."""
        return self.is_dimension_request and bool(self._where)

    @property
    def is_auto_update_command(self) -> bool:
        """True if this message is a WHO 18 Dimension 1200 streaming write (*#18*WHERE*#1200#TYPE*TIME##)."""
        return (
            self.is_dimension_writing
            and self._dimension == 1200
            and bool(self._where)
        )

    @property
    def stream_duration(self) -> int | None:
        """Time field (0..255 minutes, the report-on-change parameter of DIMENSION 1200) of a 1200 write, or None."""
        if self._dimension == 1200 and self._dimension_value:
            return max(0, min(255, _integer_value(self._dimension_value, 0)))
        return None

    @classmethod
    def report_active_power(
        cls, where: str | int, watts: int | float
    ) -> OWNEnergyCommand:
        """Build a WHO 18 Dimension 113 active power report (*#18*WHERE*113*W##)."""
        target = _normalize_actuator_where(where)
        w = _validate_non_negative_energy(watts, "watts")
        message = cls(f"*#18*{target}*113*{w}##")
        message._human_readable_log = (
            f"Reporting active power of {w} W for sensor {target}."
        )
        return message

    @classmethod
    def report_total_energy(
        cls, where: str | int, wh: int | float
    ) -> OWNEnergyCommand:
        """Build a WHO 18 Dimension 51 total energy report (*#18*WHERE*51*Wh##)."""
        target = _normalize_actuator_where(where)
        val = _validate_non_negative_energy(wh, "wh")
        message = cls(f"*#18*{target}*51*{val}##")
        message._human_readable_log = (
            f"Reporting total energy consumption of {val} Wh for sensor {target}."
        )
        return message

    @classmethod
    def report_current_month_energy(
        cls,
        where: str | int,
        wh: int | float,
        year: int | None = None,
        month: int | None = None,
    ) -> OWNEnergyCommand:
        """Build a WHO 18 Dimension 52 monthly energy report (*#18*WHERE*52#YY#M*Wh##).

        DIMENSION 52 exists only with the two-digit year and the month
        (Encyclopedia who-18 dimensions.md "DIMENSION 52 - monthly energy/unit
        totalizer"): pass ``year`` and ``month`` to build that form. The
        parameter-less ``*#18*51*52*100##`` is refused by 11 of the 12
        emulated gateways, and a four-digit year (``52#2026#10``) crashes the
        emulated F460 020012 and F461 020011 (ORACLE_CONFIRM E1);
        ``*#18*51*52#26#9##`` goes out on nine (firmware oracle
        ``energy-params`` / ``energy-ts10``).

        Deprecated: with ``year`` and ``month`` both omitted the legacy
        parameter-less ``*#18*WHERE*52*Wh##`` is still built, because MyHOME
        ``expose.py`` relies on it (``tests/test_expose.py`` pins
        ``*#18*51*52*120500##``); callers should pass the year and month.
        """
        target = _normalize_actuator_where(where)
        val = _validate_non_negative_energy(wh, "wh")
        if (year is None) != (month is None):
            raise ValueError("year and month must both be provided or both omitted")
        if year is None or month is None:
            message = cls(f"*#18*{target}*52*{val}##")
            message._human_readable_log = (
                f"Reporting monthly energy consumption of {val} Wh for sensor {target}."
            )
            return message
        if any(
            isinstance(x, bool) or (isinstance(x, float) and x % 1 != 0)
            for x in (year, month)
        ):
            raise ValueError("year and month must be integers")
        y = int(year)
        m = int(month)
        if not 2000 <= y <= 2099:
            raise ValueError("year must be between 2000 and 2099")
        if not 1 <= m <= 12:
            raise ValueError("month must be between 1 and 12")
        message = cls(f"*#18*{target}*52#{y % 100:02d}#{m}*{val}##")
        message._human_readable_log = (
            f"Reporting monthly energy consumption of {val} Wh for sensor {target}."
        )
        return message

    @classmethod
    def report_partial_month_energy(
        cls, where: str | int, wh: int | float, month: int | None = None
    ) -> OWNEnergyCommand:
        """Build a WHO 18 Dimension 53 current-month partial energy report (*#18*WHERE*53*Wh##).

        DIMENSION 53 is a parameter-less scalar (Encyclopedia who-18
        dimensions.md "DIMENSION 53 - current-month partial totalizer"); the
        ``53#M`` form is not defined there, and mcp#24 classifies the WHO 18
        forms beyond the published table as ``TS10_1_0_23`` touchscreen
        extensions rather than ``WHO_18.pdf`` forms, so no ``#M`` parameter is
        emitted. Capture: ``*#18*52*53*1##`` (F454 2.0.5, MyHOME#466).

        ``month`` is deprecated and ignored on the wire: it is still accepted
        (and validated as an integer 1..12, ``ValueError`` otherwise) so that
        existing callers such as MyHOME ``expose.py`` keep working.
        """
        target = _normalize_actuator_where(where)
        val = _validate_non_negative_energy(wh, "wh")
        if month is not None:
            _validate_int_range(month, "month", 1, 12)
        message = cls(f"*#18*{target}*53*{val}##")
        message._human_readable_log = (
            f"Reporting partial monthly energy consumption of {val} Wh for sensor {target}."
        )
        return message

    @classmethod
    def report_partial_day_energy(
        cls, where: str | int, wh: int | float, day: int | None = None
    ) -> OWNEnergyCommand:
        """Build a WHO 18 Dimension 54 current-day partial energy report (*#18*WHERE*54*Wh##).

        DIMENSION 54 is a parameter-less scalar (Encyclopedia who-18
        dimensions.md "DIMENSION 54 - current-day partial totalizer"); the
        ``54#D`` form is not defined there (see ``report_partial_month_energy``
        for the mcp#24 touchscreen-extension framing), so no ``#D`` parameter
        is emitted. Capture: ``*#18*51*54*13165##`` (F454 2.0, MyHOME#661).

        ``day`` is deprecated and ignored on the wire: it is still accepted
        (and validated as an integer 1..31, ``ValueError`` otherwise) so that
        existing callers such as MyHOME ``expose.py`` keep working.
        """
        target = _normalize_actuator_where(where)
        val = _validate_non_negative_energy(wh, "wh")
        if day is not None:
            _validate_int_range(day, "day", 1, 31)
        message = cls(f"*#18*{target}*54*{val}##")
        message._human_readable_log = (
            f"Reporting partial daily energy consumption of {val} Wh for sensor {target}."
        )
        return message

    @classmethod
    def start_daily_series(
        cls, where: str | int, month: int, day: int
    ) -> OWNEnergyCommand:
        """Start the daily hourly series: *18*57#M#D*WHERE## (DIMENSION 511 replies).

        Encyclopedia who-18 what.md "Daily hourly series"; the read form
        ``*#18*WHERE*511#M#D##`` of :meth:`get_hourly_consumption` is the
        old-PIC variant of the same request. ``*18*57#10#1*51##`` goes out on
        eight emulated gateways (firmware oracle ``energy-ts10``).
        """
        target = _normalize_actuator_where(where)
        m = _validate_int_range(month, "month", 1, 12)
        d = _validate_int_range(day, "day", 1, 31)
        message = cls(f"*18*{ENERGY_SERIES_DAILY}#{m}#{d}*{target}##")
        message._human_readable_log = f"Requesting the daily hourly series for {m}/{d} from sensor {target}."  # pylint: disable=line-too-long
        return message

    @classmethod
    def start_monthly_average_series(
        cls, where: str | int, month: int
    ) -> OWNEnergyCommand:
        """Start the monthly-average hourly series: *18*58#M*WHERE## (DIMENSION 512 replies).

        Encyclopedia who-18 what.md "Monthly-average hourly series".
        ``*18*58#10*51##`` goes out on eight emulated gateways (firmware oracle
        ``energy-ts10``).
        """
        target = _normalize_actuator_where(where)
        m = _validate_int_range(month, "month", 1, 12)
        message = cls(f"*18*{ENERGY_SERIES_MONTHLY_AVERAGE}#{m}*{target}##")
        message._human_readable_log = f"Requesting the monthly-average hourly series for month {m} from sensor {target}."  # pylint: disable=line-too-long
        return message

    @classmethod
    def get_monthly_average_consumption(
        cls, where: str | int, month: int
    ) -> OWNEnergyCommand:
        """Read form of the monthly-average series: *#18*WHERE*512#M##.

        The old-PIC request variant of WHAT 58#M (Encyclopedia who-18 what.md
        "Historical graph request variants"); ``*#18*51*512#10##`` goes out on
        eight emulated gateways (firmware oracle ``energy-ts10``).
        """
        target = _normalize_actuator_where(where)
        m = _validate_int_range(month, "month", 1, 12)
        message = cls(f"*#18*{target}*512#{m}##")
        message._human_readable_log = f"Requesting the monthly-average hourly series for month {m} from sensor {target}."  # pylint: disable=line-too-long
        return message

    @classmethod
    def enable_actuator(cls, where: str | int) -> OWNEnergyCommand:
        """Enable an Energy Management actuator: *18*71*7N#0##.

        Encyclopedia who-18 what.md "Actuator commands" / "Enable";
        ``*18*71*71#0##`` goes out on nine emulated gateways (firmware oracle
        ``energy-ts10``).
        """
        target = _require_actuator_where(where)
        message = cls(f"*18*{ENERGY_ACTUATOR_ENABLE}*{target}##")
        message._human_readable_log = f"Enabling actuator {target}."
        return message

    @classmethod
    def force_actuator(
        cls, where: str | int, time: int | None = None
    ) -> OWNEnergyCommand:
        """Force an actuator: *18*73#Time*7N#0## (Time in tens of minutes, 1..254) or *18*73*7N#0## for the default time.

        Encyclopedia who-18 what.md "Force for a specified time" / "Force for
        default time"; the encoded range is preserved as published.
        ``*18*73#15*71#0##`` and ``*18*73*71#0##`` go out on nine emulated
        gateways (firmware oracle ``energy-ts10``).
        """
        target = _require_actuator_where(where)
        if time is None:
            message = cls(f"*18*{ENERGY_ACTUATOR_FORCE}*{target}##")
            message._human_readable_log = f"Forcing actuator {target} for the default time."
            return message
        t = _validate_int_range(time, "time", 1, 254)
        message = cls(f"*18*{ENERGY_ACTUATOR_FORCE}#{t}*{target}##")
        message._human_readable_log = f"Forcing actuator {target} for {t * 10} minutes."
        return message

    @classmethod
    def end_actuator_forcing(cls, where: str | int) -> OWNEnergyCommand:
        """End the forced state of an actuator: *18*74*7N#0##.

        Encyclopedia who-18 what.md "End forcing"; ``*18*74*71#0##`` goes out
        on nine emulated gateways (firmware oracle ``energy-ts10``).
        """
        target = _require_actuator_where(where)
        message = cls(f"*18*{ENERGY_ACTUATOR_END_FORCING}*{target}##")
        message._human_readable_log = f"Ending the forcing of actuator {target}."
        return message

    @classmethod
    def reset_totalizer(cls, where: str | int, number: int) -> OWNEnergyCommand:
        """Reset totalizer Tot_N (1..2): *18*75#Tot_N*7N#0##.

        Encyclopedia who-18 what.md "Reset totalizer"; ``*18*75#1*71#0##``
        and ``*18*75#2*71#0##`` go out on eight emulated gateways (firmware
        oracle ``energy-ts10``).
        """
        target = _require_actuator_where(where)
        n = _validate_int_range(number, "number", 1, 2)
        message = cls(f"*18*{ENERGY_TOTALIZER_RESET}#{n}*{target}##")
        message._human_readable_log = f"Resetting totalizer {n} of actuator {target}."
        return message

    @classmethod
    def request_actuator_status(cls, where: str | int) -> OWNEnergyCommand:
        """Request the actuator status: *#18*7N#0*71## (Encyclopedia who-18 dimensions.md "DIMENSION 71 - actuator status").

        ``*#18*71#0*71##`` goes out on eight emulated gateways (firmware oracle
        ``energy-ts10``).
        """
        target = _require_actuator_where(where)
        message = cls(f"*#18*{target}*71##")
        message._human_readable_log = f"Requesting the status of actuator {target}."
        return message

    @classmethod
    def request_totalizer(cls, where: str | int, number: int) -> OWNEnergyCommand:
        """Request totalizer Tot_N (1..2): *#18*7N#0*72#Tot_N## (Encyclopedia who-18 dimensions.md "DIMENSION 72 - totalizer state").

        ``*#18*71#0*72#1##`` and ``*#18*71#0*72#2##`` go out on eight emulated
        gateways (firmware oracle ``energy-ts10``).
        """
        target = _require_actuator_where(where)
        n = _validate_int_range(number, "number", 1, 2)
        message = cls(f"*#18*{target}*72#{n}##")
        message._human_readable_log = f"Requesting totalizer {n} of actuator {target}."
        return message

    @classmethod
    def request_differential_current_level(cls, where: str | int) -> OWNEnergyCommand:
        """Request the differential-current level: *#18*7N#0*73## (Encyclopedia who-18 dimensions.md "DIMENSION 73 - differential-current level").

        ``*#18*71#0*73##`` goes out on eight emulated gateways (firmware oracle
        ``energy-ts10``).
        """
        target = _require_actuator_where(where)
        message = cls(f"*#18*{target}*73##")
        message._human_readable_log = f"Requesting the differential-current level of actuator {target}."  # pylint: disable=line-too-long
        return message

    @classmethod
    def report_streaming_state(
        cls, where: str | int, duration: int, energy_type: int = 1
    ) -> OWNEnergyCommand:
        """Build a WHO 18 Dimension 1200 streaming confirmation/expiry reply (*#18*WHERE*1200#TYPE*TIME##)."""
        target = _normalize_actuator_where(where)
        if any(
            isinstance(x, bool) or (isinstance(x, float) and x % 1 != 0)
            for x in (duration, energy_type)
        ):
            raise ValueError("duration and energy_type must be integers")
        et = int(energy_type)
        if not 1 <= et <= 4:
            raise ValueError("energy_type must be between 1 and 4")
        dur = int(duration)
        if not 0 <= dur <= 255:
            raise ValueError("duration must be between 0 and 255")
        message = cls(f"*#18*{target}*1200#{et}*{dur}##")
        message._human_readable_log = (
            f"Reporting instant power stream state ({dur} min) for sensor {target}."
        )
        return message


def _validate_non_negative_energy(value: int | float, name: str) -> int:
    """Validate that an energy or power value is a finite non-negative number."""
    if isinstance(value, bool):
        raise ValueError(f"{name} must be a finite non-negative number")
    fval = float(value)
    if not math.isfinite(fval) or fval < 0:
        raise ValueError(f"{name} must be a finite non-negative number")
    return int(round(fval))


def _validate_int_range(value: int, name: str, low: int, high: int) -> int:
    """Validate an integral parameter within ``low..high`` and return it as ``int``."""
    if isinstance(value, bool) or (isinstance(value, float) and value % 1 != 0):
        raise ValueError(f"{name} must be between {low} and {high}")
    try:
        ivalue = int(value)
    except (TypeError, ValueError) as exc:
        raise ValueError(f"{name} must be between {low} and {high}") from exc
    if not low <= ivalue <= high:
        raise ValueError(f"{name} must be between {low} and {high}")
    return ivalue


def stop_and_go_line(where: str | None) -> int | None:
    """Line N of a Stop&Go WHERE ``1N`` (N = 1..127, no leading zero), else None.

    Encyclopedia who-18 addressing.md "Published WHERE forms".
    """
    match = _STOP_AND_GO_WHERE.match(where or "")
    if match is None:
        return None
    line = int(match.group("line"))
    return line if line <= STOP_AND_GO_LINE_MAX else None


def _normalize_stop_and_go_where(where: str | int) -> str:
    """Normalize a Stop&Go target to the published ``1N`` address, N = 1..127.

    A value that already is a ``1N`` address (``11``..``19``, ``110``..``1127``)
    is kept; otherwise a bare line number 1..127 is prefixed with ``1``. The
    address reading wins where the two overlap (``11`` is the address of line
    1, not line 11; ``110``..``127`` are the addresses of lines 10..27), so
    lines 11..27 and 110..127 are reached through their ``1N`` address.
    Encyclopedia who-18 addressing.md "Published WHERE forms"; the firmware
    forwards ``*18*21*110##``, ``*18*21*120##`` and ``*18*21*1127##`` on the
    same nine emulated gateways as ``*18*21*11##`` (ORACLE_CONFIRM E2).
    """
    target = str(where).strip()
    if stop_and_go_line(target) is not None:
        return target
    if target.isdigit() and 1 <= int(target) <= STOP_AND_GO_LINE_MAX:
        return f"1{int(target)}"
    raise ValueError(
        f"Invalid Stop&Go line address '{where}': line must be 1..{STOP_AND_GO_LINE_MAX} or address 11..1{STOP_AND_GO_LINE_MAX}"
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
    Addresses are formatted as 1N, N = 1..127 (Encyclopedia who-18
    addressing.md "Published WHERE forms").
    """

    def __init__(self, data: str) -> None:
        super().__init__(data)

        self._type = MESSAGE_TYPE_STOP_AND_GO
        self._state: int | None = None
        self._is_open: bool | None = None
        self._is_closed: bool | None = None
        self._is_auto_reset_active: bool | None = None
        self._is_tracking_active: bool | None = None
        self._is_check_active: bool | None = None
        self._differential_test_passed: bool | None = None
        self._differential_test_result: str | None = None
        self._test_frequency_days: int | None = None
        self._status_mask: str | None = None
        self._flag_dimension: int | None = None
        self._flag_active: bool | None = None

        self._line = stop_and_go_line(self._where)

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
                    # DIMENSION 259 is "Check off/on" (Encyclopedia who-18
                    # dimensions.md "Individual Stop&Go flags"): is_check_active
                    # carries it. is_tracking_active is kept as before for
                    # existing consumers (the pre-2.0.0b13 reading of 259 as
                    # the WHAT 28/29 tracking state; the docs do not equate
                    # the two, so is_check_active is the documented field).
                    self._is_check_active = not active
                    self._is_tracking_active = not active
                self._human_readable_log = (
                    f"Stop&Go breaker {self._where} status flag {self._dimension} is {bit}."
                )

    @property
    def message_type(self) -> str | None:
        return self._type

    @property
    def line(self) -> int | None:
        """Line number N (1..127) of the Stop&Go address 1N, or None if non-standard."""
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
        """Earth leakage tracking state from WHAT 28 / 29 (libqtdevices TS10_1_0_23 Stop&Go controls) and, for compatibility, from DIMENSION 259 (see ``is_check_active``), else None."""
        return self._is_tracking_active

    @property
    def is_check_active(self) -> bool | None:
        """Check state from DIMENSION 259 (1 = check off, 0 = check on; Encyclopedia who-18 dimensions.md "Individual Stop&Go flags"), else None."""
        return self._is_check_active

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
        # DIMENSION 212 is a TS10_1_0_23 touchscreen extension, not a
        # WHO_18.pdf form (Encyclopedia who-18 dimensions.md "Historical
        # touchscreen extensions" > "Stop&Go self-test interval": the library
        # defines DAYS = 1..180; mcp#24); *#18*11*#212*200## is nack/silent on
        # all 12 emulated gateways while *#18*11*#212*180## goes out on nine
        # (ORACLE_CONFIRM E3).
        if isinstance(days, bool) or (isinstance(days, float) and days % 1 != 0):
            raise ValueError(
                f"Self-test frequency days must be an integer between 1 and 180, got {days!r}"
            )
        if days < 1 or days > 180:
            raise ValueError(
                f"Self-test frequency days must be between 1 and 180, got {days}"
            )
        return cls(f"*#18*{target}*#{STOP_AND_GO_DIM_TEST_FREQUENCY}*{int(days)}##")

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

