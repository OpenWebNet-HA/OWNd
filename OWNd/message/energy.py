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
                    # missing parameters: drop the sample, keep the session,
                    # and say so instead of echoing the raw frame.
                    self._human_readable_log = f"Sensor {self._sensor} is reporting dimension 511 for month/day {'/'.join(self._dimension_param)}, which is not a calendar date; sample ignored."  # pylint: disable=line-too-long
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
                    # The series always carries tags 1..31 (WHO 18 PDF 5.1.5
                    # and 5.1.6, "<Tag> the day from: 1 to 31"): a live F461
                    # 2.0.11 answers *#18*51*513#11## with a day 31 for
                    # November. Not a calendar date: drop the sample, keep the
                    # session, and say so instead of echoing the raw frame.
                    self._human_readable_log = f"Sensor {self._sensor} is reporting dimension {self._dimension} for day {self._dimension_value[0]} of month {'/'.join(self._dimension_param)}, which is not a calendar date; sample ignored."  # pylint: disable=line-too-long
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


# WHO 18 DIMENSION 52 (monthly energy): ``*#18*51*52#2026#10##`` and the
# value-field form ``*#18*51*52#2026#10*100##`` crash the F460 020012, the F461
# 020011 and the 3488 030205 (HOMETOUCH) after the telegram went out, while
# the documented two-digit form ``*#18*51*52#26#9##`` went out without a crash
# (OpenWebNet-HA/own-firmware-oracle, suite ``ownd-audit-frames``, index
# SHA-256 db03cc878d84d514b9e324c2d01d050264f2e4ccd0c1aad33937683c30e472ca,
# ``findings/audit-crash-frames.md`` and ``tools/expected_divergences.yaml``
# ``crash_frames``; emulated firmware, ``harness=full``, not yet replayed on
# physical hardware). The firmware reads the year of ``52#Y#M`` with atoi()
# into a one-byte slot (``26`` -> ``1A`` in ``$06D1A1023350161A09``), and
# ``2026`` (0x7EA) overflows that formatter (``$006D1A1023350167EA0``), so every
# spelling atoi() reads as a wide year does the same (``02026``, ``256``);
# leading zeros on WHO or DIMENSION (``*#018*``, ``*052``), a ``#52`` write, an
# extra ``#`` parameter, an empty WHERE, a non-ASCII digit or more than one
# value field were not replayed. As for WHO 4 dimension 22
# (``is_who4_dimension_22_crash_form``), the allowance is the tested forms,
# not the complement of the crash set. No builder emits a refused form; the
# send paths refuse one handed in as a raw frame.
#
# ``_WHO18_DIMENSION_52_REGEX`` recognises every DIMENSION 52 spelling, anchored
# to the first ``*`` of each ``##``-delimited chunk (mid-frame ``*#18*`` is a
# WHERE or DIMENSION ``#18``); WHO and DIMENSION accept what the gateway's
# atoi() reads as 18 / 52 (leading zeros, whitespace, a ``+`` sign).
_WHO18_DIMENSION_52_REGEX = re.compile(
    r"^[^*]*\*#\s*\+?0*18\s*\*[^*]*\*\s*#?\s*\+?0*52(?:\s*\Z|[#*\s])"
)
# The forms that go out, spelled canonically: WHO ``18``, a non-empty ASCII
# WHERE of the published families (digits, ``#0`` suffix for an actuator),
# DIMENSION ``52`` as a request or report (``*52``, ``*52*Wh``) or with the
# documented year and month (``52#YY#M``, ``YY`` 0..99 as one or two digits,
# ``M`` 1..12, optionally ``*Wh``). ``\Z`` on the end (``$`` also matches
# before a trailing newline); ASCII only.
_WHO18_DIMENSION_52_SENDABLE_REGEX = re.compile(
    r"^\*#18\*[0-9]+(?:#0)?\*52(?:#[0-9]{1,2}#(?:0?[1-9]|1[0-2]))?(?:\*[0-9]+)?\Z",
    re.ASCII,
)


def _decode_frame(frame: object) -> str:
    return (
        bytes(frame).decode("latin-1")
        if isinstance(frame, (bytes, bytearray, memoryview))
        else str(frame)
    )


def is_who18_dimension_52(frame: object) -> bool:
    """True if ``frame`` (or any ``##``-delimited frame in it) is WHO 18 DIMENSION 52.

    Every spelling, the safe forms included. The send paths refuse the narrower
    :func:`is_who18_dimension_52_crash_form`. ``bytes``, ``bytearray`` and
    ``memoryview`` are decoded as latin-1 (the wire encoding); anything else is
    checked through ``str()``.
    """
    raw = _decode_frame(frame)
    return any(_WHO18_DIMENSION_52_REGEX.search(chunk) for chunk in raw.split("##"))


def is_who18_dimension_52_crash_form(frame: object) -> bool:
    """True if ``frame`` holds a WHO 18 DIMENSION 52 frame that every send path refuses.

    That is every DIMENSION 52 spelling except the canonical forms the firmware
    oracle replayed without a crash or that the builders emit: ``*#18*WHERE*52##``,
    ``*#18*WHERE*52*Wh##``, ``*#18*WHERE*52#YY#M##`` and ``*#18*WHERE*52#YY#M*Wh##``
    with a one- or two-digit year and a month 1..12. Refused: a four-digit or
    wider year (``52#2026#10`` crashes the F460, F461 and 3488; ``02026`` and
    ``256`` reach the same one-byte formatter), a month outside 1..12 or with
    three digits, leading zeros, whitespace or ``+`` on WHO or DIMENSION, a
    ``#52`` write, an extra ``#`` parameter, an empty or non-digit WHERE, a
    non-ASCII digit and more than one value field. Buffers are decoded like
    :func:`is_who18_dimension_52`.
    """
    raw = _decode_frame(frame)
    return any(
        _WHO18_DIMENSION_52_REGEX.search(chunk)
        and not _WHO18_DIMENSION_52_SENDABLE_REGEX.match(chunk)
        for chunk in raw.split("##")
    )


# The name of the first release of the guard, kept for its callers.
is_who18_dimension_52_four_digit_year = is_who18_dimension_52_crash_form


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
        """Build a WHO 18 Dimension 52 monthly energy report (*#18*WHERE*52[#YY#M]*Wh##).

        With ``year`` and ``month`` the documented ``52#YY#M`` form is built
        with a two-digit year (``*#18*51*52#26#9*100##``); WHO_18.pdf defines
        DIMENSION 52 only with the year and month parameters. A four-digit
        year is never emitted: ``52#2026#10`` crashed the F460, F461 and 3488
        in the firmware oracle (``ownd-audit-frames``), and the send layer
        refuses every untested spelling
        (:func:`is_who18_dimension_52_crash_form`). With both omitted
        the parameter-less ``*#18*WHERE*52*Wh##`` is built as before, for the
        existing callers (MyHOME ``expose.py``).
        """
        target = _normalize_actuator_where(where)
        val = _validate_non_negative_energy(wh, "wh")
        if (year is None) != (month is None):
            raise ValueError("year and month must both be provided or both omitted")
        if year is not None and month is not None:
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
        else:
            message = cls(f"*#18*{target}*52*{val}##")
        message._human_readable_log = (
            f"Reporting monthly energy consumption of {val} Wh for sensor {target}."
        )
        return message

    @classmethod
    def report_partial_month_energy(
        cls, where: str | int, wh: int | float, month: int | None = None
    ) -> OWNEnergyCommand:
        """Build a WHO 18 Dimension 53 current-month partial energy report (*#18*WHERE*53[#M]*Wh##).

        WHO_18.pdf lists DIMENSION 53 as a parameter-less scalar (capture:
        ``*#18*52*53*1##``, F454 2.0.51, MyHOME#466); the ``53#M`` form built
        when ``month`` is given is the TS10 touchscreen's parameterised
        variant, not a form of the PDF. Both forms are kept on the wire as
        before, pending a committed plant trace of the parameterised reply.
        """
        target = _normalize_actuator_where(where)
        val = _validate_non_negative_energy(wh, "wh")
        if month is not None:
            if (
                isinstance(month, bool)
                or (isinstance(month, float) and month % 1 != 0)
                or not 1 <= int(month) <= 12
            ):
                raise ValueError("month must be between 1 and 12")
            message = cls(f"*#18*{target}*53#{int(month)}*{val}##")
        else:
            message = cls(f"*#18*{target}*53*{val}##")
        message._human_readable_log = (
            f"Reporting partial monthly energy consumption of {val} Wh for sensor {target}."
        )
        return message

    @classmethod
    def report_partial_day_energy(
        cls, where: str | int, wh: int | float, day: int | None = None
    ) -> OWNEnergyCommand:
        """Build a WHO 18 Dimension 54 current-day partial energy report (*#18*WHERE*54[#D]*Wh##).

        WHO_18.pdf lists DIMENSION 54 as a parameter-less scalar (capture:
        ``*#18*51*54*13165##``, F454 2.0, MyHOME#661); the ``54#D`` form built
        when ``day`` is given is the TS10 touchscreen's parameterised variant,
        not a form of the PDF. Both forms are kept on the wire as before,
        pending a committed plant trace of the parameterised reply.
        """
        target = _normalize_actuator_where(where)
        val = _validate_non_negative_energy(wh, "wh")
        if day is not None:
            if (
                isinstance(day, bool)
                or (isinstance(day, float) and day % 1 != 0)
                or not 1 <= int(day) <= 31
            ):
                raise ValueError("day must be between 1 and 31")
            message = cls(f"*#18*{target}*54#{int(day)}*{val}##")
        else:
            message = cls(f"*#18*{target}*54*{val}##")
        message._human_readable_log = (
            f"Reporting partial daily energy consumption of {val} Wh for sensor {target}."
        )
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


def _normalize_stop_and_go_where(where: str | int) -> str:
    """Normalize Stop&Go line address to 1N format (11..19).

    WHO_18.pdf's WHERE table publishes the Stop&Go family as ``1N`` with
    N = 1..127; the builders accept lines 1..9 / addresses 11..19 only,
    master's range (derived from the firmware oracle ``energy-ts10`` suite; no
    physical Stop&Go trace is committed), kept until a plant trace of a wider
    address is committed.
    """
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
    Addresses are formatted as 1N (11..19, where line is 1..9). WHO_18.pdf
    publishes the family as 1N with N = 1..127; ``line`` is decoded for the
    single-digit addresses only, master's range from the firmware oracle
    ``energy-ts10`` suite, kept until a physical Stop&Go trace is committed.
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
        """Line number (1..9) corresponding to address 1N, or None if non-standard (WHO_18.pdf publishes N = 1..127; wider addresses are not decoded until a physical Stop&Go trace is committed)."""
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
        """Set the self-test interval: *#18*1N*#212*DAYS## (1..255).

        DIMENSION 212 is not in WHO_18.pdf; the TS10 touchscreen client
        (``TS10_1_0_23``) that defines it uses DAYS = 1..180. The accepted
        range stays 1..255 as before, pending a committed plant trace.
        """
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

