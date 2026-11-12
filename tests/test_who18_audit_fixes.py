"""WHO 18 (Encyclopedia audit of OWNd master): documentation and fixture relabelling.

Only what changes no runtime behaviour is pinned here: the existing ``52#YY#M``
builder output, the Wh wording, the DIMENSION 1200 docstrings and the
``conflict`` golden relabelling. The behaviour changes of the audit were held
back pending committed plant traces; the DIMENSION 52 send guard has its own
module, tests/test_who18_dimension52_guard.py.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from OWNd.message import (
    MESSAGE_TYPE_ACTIVE_POWER,
    OWNEnergyCommand,
    OWNEnergyEvent,
    OWNMessage,
)

_ORACLE = Path(__file__).parent / "golden" / "firmware_oracle.json"


def _oracle_out(frame: str) -> set[str]:
    verdicts = json.loads(_ORACLE.read_text(encoding="utf-8"))["verdicts"]
    return {row["product"] for row in verdicts[frame] if row["verdict"] == "out"}


# ---------------------------------------------------------------------------
# The existing report_current_month_energy builder output is pinned as is:
# the documented 52#YY#M form with a two-digit year when year and month are
# given, the parameter-less form when both are omitted. The four-digit-year
# form crashes the F460, F461 and 3488 (own-firmware-oracle ownd-audit-frames)
# and is never built; the send layer refuses it (test_who18_dimension52_guard.py).
# ---------------------------------------------------------------------------


def test_report_current_month_energy_emits_two_digit_year() -> None:
    assert (
        str(OWNEnergyCommand.report_current_month_energy("51", 100, 2026, 9))
        == "*#18*51*52#26#9*100##"
    )
    # Parameter-less form, unchanged (MyHOME `expose.py` relies on it;
    # `tests/test_expose.py` pins `*#18*51*52*120500##`).
    default = OWNEnergyCommand.report_current_month_energy("51", 100)
    assert str(default) == "*#18*51*52*100##"
    assert default.human_readable_log == "Reporting monthly energy consumption of 100 Wh for sensor 51."
    assert "#2026#" not in str(
        OWNEnergyCommand.report_current_month_energy("51", 100, 2026, 10)
    )
    assert _oracle_out("*#18*51*52#26#9##") >= {"F460", "F461", "MyHomeServer1"}


def test_report_current_month_energy_validation_unchanged() -> None:
    with pytest.raises(ValueError, match="both be provided or both omitted"):
        OWNEnergyCommand.report_current_month_energy("51", 100, year=2026)
    with pytest.raises(ValueError, match="year and month must be integers"):
        OWNEnergyCommand.report_current_month_energy("51", 100, 2026.5, 10)
    with pytest.raises(ValueError, match="year must be between 2000 and 2099"):
        OWNEnergyCommand.report_current_month_energy("51", 100, 1999, 10)
    with pytest.raises(ValueError, match="month must be between 1 and 12"):
        OWNEnergyCommand.report_current_month_energy("51", 100, 2026, 13)


# ---------------------------------------------------------------------------
# Wh, not kWh (dimensions.md "DIMENSION 72 - totalizer state";
# README.md "Measurement model").
# ---------------------------------------------------------------------------


def test_documentation_says_wh() -> None:
    root = Path(__file__).resolve().parent.parent
    readme_row = next(
        line for line in (root / "README.md").read_text(encoding="utf-8").splitlines()
        if line.startswith("| **18** |")
    )
    matrix_row = next(
        line
        for line in (root / "docs" / "protocol_conformance_matrix.md").read_text(encoding="utf-8").splitlines()
        if line.startswith("| **18** |")
    )
    for row in (readme_row, matrix_row):
        assert "kWh" not in row
        assert "(Wh)" in row


# ---------------------------------------------------------------------------
# DIMENSION 1200 Time is the report-on-change parameter (dimensions.md
# "DIMENSION 1200 - automatic active-power updates").
# ---------------------------------------------------------------------------


def test_dimension_1200_docstrings_describe_report_on_change() -> None:
    for doc in (
        OWNEnergyEvent.update_interval.__doc__,
        OWNEnergyCommand.start_sending_instant_power.__doc__,
        OWNEnergyCommand.stream_duration.__doc__,
    ):
        assert doc is not None
        assert "report-on-change" in doc
        assert "stream duration" not in doc
    assert "report-on-change" in (OWNEnergyEvent.stream_duration.__doc__ or "")
    event = OWNMessage.parse("*#18*56*1200#1*2##")
    assert event.update_interval == 2
    assert event.stream_duration == 2
    assert event.is_streaming_active is True


# ---------------------------------------------------------------------------
# The `*#18*1*1##` / `*#18*1*11*...##` fixtures are grammar-only
# (dimensions.md "Identifier table": no DIMENSION 1, active power is 113;
# zigbee-variant.md "DIMENSION table": 11 is Voltage; no kWh on the wire).
# ---------------------------------------------------------------------------


def test_golden_fixtures_are_not_labelled_as_spec() -> None:
    corpus = json.loads((Path(__file__).parent / "golden" / "corpus.json").read_text(encoding="utf-8"))
    records = {r["id"]: r for r in corpus}
    for fixture_id in (
        "energy.req.active_power.meter1",
        "energy.resp.active_power.meter1.1450",
        "energy.req.lifetime.meter1",
        "energy.resp.lifetime.meter1.45230",
    ):
        record = records[fixture_id]
        assert record["source"] == "conflict", fixture_id
        assert "kWh" not in record["mcp_notes"]
        assert "message_type None" in record["mcp_notes"]
        parsed = OWNMessage.parse(record["frame"])
        assert getattr(parsed, "message_type", None) is None
    assert records["energy.resp.active_power.meter51.572"]["source"] == "community-plant-capture"
    assert OWNMessage.parse("*#18*51*113*572##").message_type == MESSAGE_TYPE_ACTIVE_POWER
