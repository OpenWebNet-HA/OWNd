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
