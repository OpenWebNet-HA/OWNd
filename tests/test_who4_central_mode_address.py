"""``set_central_mode`` only on the central unit's own address.

Central-unit WHATs address the central unit by API contract (OWNd#77 fix 3):
``#0`` (3550, 99 zones) or ``#0#C`` (4695, ``C`` 1..99 / ``01``..``99``), the
forms MyHOME and the golden corpus use. The plain zone form ``*4*311*Z##`` is
``nack``/``silent`` on all 12 emulated gateways (firmware oracle
``thermo-zone-mode`` and ``ownd-pr82-heating``), and a live F461 2.0.11 NACKs
``*4*311*2##`` while it ACKs ``*4*311*#2##``. ``#Z`` and ``#Z#C`` are zone /
probe addresses (libqtdevices ``ControlledProbeDevice``, bus command byte
``C2``) that ``set_mode`` builds; ``set_central_mode`` refuses them.
"""

from __future__ import annotations

import pytest

from OWNd.message import CLIMATE_MODE_AUTO, CLIMATE_MODE_HEAT, CLIMATE_MODE_OFF, OWNHeatingCommand


@pytest.mark.parametrize(
    "where",
    [
        "1",
        "2",
        "0",
        "23#1",
        "",
        " ",
        "#",
        "##0",
        "#0*22",
        "#a",
        "#0\n1",
        "#\u0661",
        "#00#1",
        "#0#",
        # Zones through the central unit, ``#Z`` and ``#Z#C`` (zone Z under
        # 4-zone central unit C): ``set_mode`` builds them, see below.
        "#1",
        "#01",
        "#2",
        "#23",
        "#99",
        "#23#1",
        "#1#2",
        "#23#12",
        # Central selectors are 1..99 (or 01..99); ``#00``, ``#0#0`` and
        # ``#0#00`` name nothing, three digits are out of range.
        "#00",
        "#100",
        "#999",
        "#0#0",
        "#0#00",
        "#0#100",
        "#0#999",
        "#1#0",
        "#1#00",
        "#1#100",
        "#1#2#3",
        "#0#1#2",
        None,
        True,
        -1,
    ],
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
    [
        # ``#0``: the 3550 99-zone central unit (golden corpus
        # ``thermo.cmd.central.mode.*.cu99``).
        ("#0", "*4*311*#0##"),
        # ``#0#C``: the 4695 4-zone central unit ``C``, 1..99 or 01..99
        # (MyHOME_Suite ``#0#[ZA][ZB]``, MHCatalogue 4695 ``ZAZB_CENTRAL``,
        # golden corpus ``#0#1``).
        ("#0#1", "*4*311*#0#1##"),
        ("#0#4", "*4*311*#0#4##"),
        ("#0#5", "*4*311*#0#5##"),
        ("#0#05", "*4*311*#0#05##"),
        ("#0#12", "*4*311*#0#12##"),
        ("#0#99", "*4*311*#0#99##"),
        # Surrounding whitespace is stripped, as ``actuators_status`` does.
        (" #0 ", "*4*311*#0##"),
        ("#0\n", "*4*311*#0##"),
        (" #0#1\t", "*4*311*#0#1##"),
    ],
)
def test_set_central_mode_keeps_central_addresses(where: str, frame: str) -> None:
    command = OWNHeatingCommand.set_central_mode(where, CLIMATE_MODE_AUTO)

    assert str(command) == frame
    assert command.human_readable_log == (
        f"Setting Central Unit {where.strip()} mode to 'auto' (code 311)."
    )


@pytest.mark.parametrize(
    ("zone", "frame"),
    [
        # ``#Z#C``: zone 23 under 4-zone central unit 1, the probe address
        # libqtdevices ``ControlledProbeDevice`` sends with bus command byte
        # ``C2`` (``D1 01 03 02 C2 17 00 00``, zone ``0x17`` = 23).
        ("23#1", "*4*311*#23#1##"),
        ("23", "*4*311*#23##"),
        (1, "*4*311*#1##"),
    ],
)
def test_set_central_mode_refuses_what_set_mode_builds(zone: str | int, frame: str) -> None:
    """A zone through the central unit is ``set_mode``'s address, not this one's."""
    zone_command = OWNHeatingCommand.set_mode(zone, CLIMATE_MODE_AUTO)
    assert zone_command is not None
    assert str(zone_command) == frame
    zone_where = frame.split("*")[3]
    assert zone_where.startswith("#")

    with pytest.raises(ValueError, match="set_mode") as excinfo:
        OWNHeatingCommand.set_central_mode(zone_where, CLIMATE_MODE_AUTO)
    assert repr(zone_where) in str(excinfo.value)
    assert "Central unit mode needs a central unit address" in str(excinfo.value)


def test_set_central_mode_error_quotes_the_stripped_address() -> None:
    with pytest.raises(ValueError, match="central unit") as excinfo:
        OWNHeatingCommand.set_central_mode(" 1 ", CLIMATE_MODE_AUTO)
    assert str(excinfo.value).endswith(": '1'")


def test_set_central_mode_default_is_the_central_unit() -> None:
    assert str(OWNHeatingCommand.set_central_mode(mode=CLIMATE_MODE_HEAT)) == "*4*1*#0##"
