"""``set_central_mode`` only on a central-unit ``#`` address.

Central-unit WHATs address the central unit by API contract (OWNd#77 fix 3).
The plain zone form ``*4*311*Z##`` is ``nack``/``silent`` on all 12 emulated
gateways (firmware oracle ``thermo-zone-mode`` and ``ownd-pr82-heating``), and
a live F461 2.0.11 NACKs ``*4*311*2##`` while it ACKs ``*4*311*#2##``.
"""

from __future__ import annotations

import pytest

from OWNd.message import CLIMATE_MODE_AUTO, CLIMATE_MODE_HEAT, CLIMATE_MODE_OFF, OWNHeatingCommand


@pytest.mark.parametrize(
    "where",
    ["1", "2", "0", "23#1", "", "#", "##0", "#0*22", "#a", "#0\n", "#\u0661", "#1#2", "#00#1", "#0#"],
)
def test_set_central_mode_requires_a_central_address(where: str) -> None:
    with pytest.raises(ValueError, match="central unit"):
        OWNHeatingCommand.set_central_mode(where, CLIMATE_MODE_AUTO)


@pytest.mark.parametrize(
    "mode", [CLIMATE_MODE_AUTO, CLIMATE_MODE_HEAT, CLIMATE_MODE_OFF]
)
def test_set_central_mode_refuses_a_plain_zone_for_every_mode(mode: str) -> None:
    """The guard is per address, not per WHAT: 311, 1 and 303 alike."""
    with pytest.raises(ValueError, match="central unit"):
        OWNHeatingCommand.set_central_mode("1", mode)


@pytest.mark.parametrize(
    ("where", "frame"),
    [("#0", "*4*311*#0##"), ("#0#1", "*4*311*#0#1##"), ("#23", "*4*311*#23##")],
)
def test_set_central_mode_keeps_central_addresses(where: str, frame: str) -> None:
    assert str(OWNHeatingCommand.set_central_mode(where, CLIMATE_MODE_AUTO)) == frame


def test_set_central_mode_default_is_the_central_unit() -> None:
    assert str(OWNHeatingCommand.set_central_mode(mode=CLIMATE_MODE_HEAT)) == "*4*1*#0##"
