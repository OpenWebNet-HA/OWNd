"""WHO 4 WHAT 22/23/24/30/31 are central-unit status reports (Legrand WHO 4
v2.0.0 p. 5, p. 24, p. 64; libqtdevices TS10_1_0_23 thermal_device.cpp:47-48
MALFUNCTIONING_FOUND = 30, BATTERY_KO = 31)."""

import pytest

from OWNd.message import OWNEvent, OWNHeatingEvent


@pytest.mark.parametrize(
    ("what", "text"),
    [
        (22, "at least one probe is OFF"),
        (23, "at least one probe is in antifreeze"),
        (24, "at least one probe is in manual mode"),
        (30, "a failure was discovered"),
        (31, "the central unit battery is KO"),
    ],
)
def test_central_unit_status_whats_are_named(what: int, text: str):
    msg = OWNEvent.parse(f"*4*{what}*#0##")
    assert isinstance(msg, OWNHeatingEvent)
    assert msg.mode is None
    assert msg.message_type != "hvac_mode"
    assert text in msg.human_readable_log
    assert "unknown" not in msg.human_readable_log


def test_other_unknown_whats_still_log_unknown():
    msg = OWNEvent.parse("*4*999*1##")
    assert msg.mode is None
    assert "unknown" in msg.human_readable_log
