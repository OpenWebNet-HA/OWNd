"""Regression tests for energy edge cases."""

import datetime
from unittest.mock import patch

from OWNd.message import OWNEnergyCommand, OWNEnergyEvent


class FixedLeapDay(datetime.date):
    @classmethod
    def today(cls) -> "FixedLeapDay":
        return cls(2024, 2, 29)


def test_unsupported_energy_address_is_fully_initialized() -> None:
    event = OWNEnergyEvent("*#18*923*113*50##")

    assert event.message_type is None
    assert event.active_power == 0
    assert event.total_consumption == 0
    assert event.hourly_consumption == {}
    assert event.daily_consumption == {}
    assert event.monthly_consumption == {}


def test_hourly_consumption_window_handles_leap_day() -> None:
    with patch("OWNd.message.datetime.date", FixedLeapDay):
        command = OWNEnergyCommand.get_hourly_consumption(
            "51", datetime.date(2023, 2, 28)
        )
        too_old = OWNEnergyCommand.get_hourly_consumption(
            "51", datetime.date(2023, 2, 27)
        )

    assert str(command) == "*#18*51*511#2#28##"
    assert too_old is None


def test_energy_command_infeasible_inputs() -> None:
    import pytest

    for bad_where in ("", "   ", "51*1"):
        with pytest.raises(ValueError, match="where must be a non-empty address without '\\*'"):
            OWNEnergyCommand.request_active_power(bad_where)

    for bad_type in (0, 5, -1):
        with pytest.raises(ValueError, match="energy_type must be between 1 and 4"):
            OWNEnergyCommand.start_sending_instant_power("51", energy_type=bad_type)
        with pytest.raises(ValueError, match="energy_type must be between 1 and 4"):
            OWNEnergyCommand.stop_sending_instant_power("51", energy_type=bad_type)

    for bad_year in (1999, 2100, 99):
        with pytest.raises(ValueError, match="year must be between 2000 and 2099"):
            OWNEnergyCommand.get_monthly_consumption("51", bad_year, 1)

    for bad_month in (0, 13, -1):
        with pytest.raises(ValueError, match="month must be between 1 and 12"):
            OWNEnergyCommand.get_monthly_consumption("51", 2026, bad_month)


def test_energy_event_out_of_calendar_day_is_dropped_with_a_reason() -> None:
    """WHO 18 PDF 5.1.5 / 5.1.6: the 513 / 514 series carries tags 1..31 whatever the month.

    A live F461 2.0.11 answers ``*#18*51*513#11##`` with a day 31 for November
    (plant run 2026-11-11). The sample is not a date: it stays untyped, and the
    log says why instead of echoing the raw frame.
    """
    from OWNd.message import OWNEnergyEvent

    day_31 = OWNEnergyEvent.parse("*#18*51*513#11*31*0##")
    assert day_31 is not None
    assert day_31.message_type is None
    assert day_31.human_readable_log == (
        "Sensor 1 is reporting dimension 513 for day 31 of month 11, "
        "which is not a calendar date; sample ignored."
    )

    day_32_last_year = OWNEnergyEvent.parse("*#18*51*514#4*32*0##")
    assert day_32_last_year is not None
    assert day_32_last_year.message_type is None
    assert "dimension 514 for day 32 of month 4" in day_32_last_year.human_readable_log

    hourly_feb_30 = OWNEnergyEvent.parse("*#18*51*511#2#30*1*0##")
    assert hourly_feb_30 is not None
    assert hourly_feb_30.message_type is None
    assert hourly_feb_30.human_readable_log == (
        "Sensor 1 is reporting dimension 511 for month/day 2/30, "
        "which is not a calendar date; sample ignored."
    )

    # A real day of the series decodes as before.
    day_11 = OWNEnergyEvent.parse("*#18*51*513#11*11*20##")
    assert day_11 is not None
    assert day_11.message_type == "daily_consumption"
    assert day_11.daily_consumption["value"] == 20
