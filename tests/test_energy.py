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
