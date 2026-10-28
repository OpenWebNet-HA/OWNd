"""Every central-unit builder shares one ``where`` contract.

``set_central_mode``, ``set_central_temperature``, ``set_central_program``,
``set_central_scenario``, ``set_central_weekend``, ``set_central_holiday``,
``set_holiday_end_date``, ``set_holiday_end_time`` and
``set_timed_manual_end_time`` default to ``where="#0"`` and log "Setting
Central Unit ...": they accept the central unit itself, ``#0`` (3550) or
``#0#C`` (4695, ``C`` 1..99 / ``01``..``99``), and refuse a bare zone
(``*4*3101*1##`` used to be built), a zone through the central unit (``#Z``,
``#Z#C``: ``set_mode``'s addresses, bus command byte ``C2``), ``#00``,
``#0#0``, three digits and non-strings through ``_validate_central_where``.
"""

from __future__ import annotations

from collections.abc import Callable

import pytest

from OWNd.message import CLIMATE_MODE_HEAT, OWNHeatingCommand
from OWNd.message.heating import _validate_central_where

# (builder name, builder taking only ``where``, frame with ``{where}``, purpose)
CENTRAL_UNIT_BUILDERS: tuple[tuple[str, Callable[[str], OWNHeatingCommand], str, str], ...] = (
    (
        "set_central_mode",
        lambda where: OWNHeatingCommand.set_central_mode(where, CLIMATE_MODE_HEAT),
        "*4*1*{where}##",
        "Central unit mode",
    ),
    (
        "set_central_temperature",
        lambda where: OWNHeatingCommand.set_central_temperature(where, 21.0, CLIMATE_MODE_HEAT),
        "*#4*{where}*#14*0210*1##",
        "Central unit setpoint",
    ),
    (
        "set_central_program",
        lambda where: OWNHeatingCommand.set_central_program(where, 1),
        "*4*3101*{where}##",
        "Central unit weekly program",
    ),
    (
        "set_central_scenario",
        lambda where: OWNHeatingCommand.set_central_scenario(where, 1),
        "*4*3201*{where}##",
        "Central unit scenario",
    ),
    (
        "set_central_weekend",
        lambda where: OWNHeatingCommand.set_central_weekend(where, 2),
        "*4*315#3102*{where}##",
        "Central unit weekend mode",
    ),
    (
        "set_central_holiday",
        lambda where: OWNHeatingCommand.set_central_holiday(where, days=3, program=2),
        "*4*33003#3102*{where}##",
        "Central unit holiday mode",
    ),
    (
        "set_holiday_end_date",
        lambda where: OWNHeatingCommand.set_holiday_end_date(where, 29, 8, 2026),
        "*#4*{where}*#30*29*08*2026##",
        "Central unit holiday end date",
    ),
    (
        "set_holiday_end_time",
        lambda where: OWNHeatingCommand.set_holiday_end_time(where, 23, 8),
        "*#4*{where}*#31*23*08##",
        "Central unit holiday end time",
    ),
    (
        "set_timed_manual_end_time",
        lambda where: OWNHeatingCommand.set_timed_manual_end_time(where, 13, 5),
        "*#4*{where}*#32*13*05##",
        "Central unit timed manual end time",
    ),
)
BUILDER_IDS = [name for name, _, _, _ in CENTRAL_UNIT_BUILDERS]

ACCEPTED_WHERES = ["#0", "#0#1", "#0#12", "#0#05"]
REFUSED_WHERES = ["1", "#1", "#23#1", "#00", "#0#0", "#0#100", None, True]


@pytest.mark.parametrize("where", ACCEPTED_WHERES)
@pytest.mark.parametrize(("name", "build", "template", "purpose"), CENTRAL_UNIT_BUILDERS, ids=BUILDER_IDS)
def test_central_unit_builders_accept_the_central_unit(
    name: str,
    build: Callable[[str], OWNHeatingCommand],
    template: str,
    purpose: str,
    where: str,
) -> None:
    command = build(where)

    assert str(command) == template.format(where=where)
    assert command.is_valid
    assert command.human_readable_log.startswith(f"Setting Central Unit {where} ")


@pytest.mark.parametrize("where", REFUSED_WHERES, ids=repr)
@pytest.mark.parametrize(("name", "build", "template", "purpose"), CENTRAL_UNIT_BUILDERS, ids=BUILDER_IDS)
def test_central_unit_builders_refuse_zones_and_junk(
    name: str,
    build: Callable[[str], OWNHeatingCommand],
    template: str,
    purpose: str,
    where: str,
) -> None:
    with pytest.raises(ValueError, match="central unit") as excinfo:
        build(where)

    message = str(excinfo.value)
    assert message.startswith(f"{purpose} needs a central unit address such as '#0' or '#0#1'")
    assert "set_mode" in message
    shown = "" if where is None else str(where)
    assert message.endswith(f": {shown!r}")


@pytest.mark.parametrize(("name", "build", "template", "purpose"), CENTRAL_UNIT_BUILDERS, ids=BUILDER_IDS)
def test_central_unit_builders_strip_whitespace(
    name: str,
    build: Callable[[str], OWNHeatingCommand],
    template: str,
    purpose: str,
) -> None:
    command = build(" #0#1\n")

    assert str(command) == template.format(where="#0#1")
    assert "Setting Central Unit #0#1 " in command.human_readable_log


@pytest.mark.parametrize(("name", "build", "template", "purpose"), CENTRAL_UNIT_BUILDERS, ids=BUILDER_IDS)
def test_central_unit_builders_default_to_hash_zero(
    name: str,
    build: Callable[[str], OWNHeatingCommand],
    template: str,
    purpose: str,
) -> None:
    builder = getattr(OWNHeatingCommand, name)
    default_frame = str(builder()) if name != "set_central_mode" else str(builder(mode=CLIMATE_MODE_HEAT))
    assert "*#0" in default_frame


@pytest.mark.parametrize(
    ("where", "expected"),
    [("#0", "#0"), ("#0#1", "#0#1"), ("#0#99", "#0#99"), ("#0#01", "#0#01"), (" #0 ", "#0")],
)
def test_validate_central_where_returns_the_stripped_address(where: str, expected: str) -> None:
    assert _validate_central_where(where) == expected


@pytest.mark.parametrize("where", ["1", "#1", "#23#1", "#00", "#0#0", "#0#100", "#0#1#2", b"#0", None, True, 0])
def test_validate_central_where_default_purpose(where: object) -> None:
    with pytest.raises(ValueError, match="^Central unit command needs a central unit address"):
        _validate_central_where(where)
