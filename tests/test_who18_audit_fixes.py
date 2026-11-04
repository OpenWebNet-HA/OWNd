"""WHO 18 audit (report 21): documentation and fixture relabelling kept after review.

Only the rows that change no runtime behaviour are pinned here: the existing
``52#YY#M`` builder output (E1), the Wh wording (E8), the DIMENSION 1200
docstrings (E9) and the ``conflict`` golden relabelling (E12). The behaviour
changes of the audit were held back pending committed plant traces.
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
# E1: the existing report_current_month_energy builder output is pinned as is:
# the documented 52#YY#M form with a two-digit year when year and month are
# given, the parameter-less form when both are omitted. The four-digit-year
# form crashes F460 / F461 (findings/audit-crash-frames.md) and is never built;
# the send layer refuses it (tests/test_who18_dimension52_guard.py).
# ---------------------------------------------------------------------------


def test_e1_report_current_month_energy_emits_two_digit_year() -> None:
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


def test_e1_report_current_month_energy_validation_unchanged() -> None:
    with pytest.raises(ValueError, match="both be provided or both omitted"):
        OWNEnergyCommand.report_current_month_energy("51", 100, year=2026)
    with pytest.raises(ValueError, match="year and month must be integers"):
        OWNEnergyCommand.report_current_month_energy("51", 100, 2026.5, 10)
    with pytest.raises(ValueError, match="year must be between 2000 and 2099"):
        OWNEnergyCommand.report_current_month_energy("51", 100, 1999, 10)
    with pytest.raises(ValueError, match="month must be between 1 and 12"):
        OWNEnergyCommand.report_current_month_energy("51", 100, 2026, 13)


# ---------------------------------------------------------------------------
# E8: Wh, not kWh (dimensions.md "DIMENSION 72 - totalizer state";
# README.md "Measurement model").
# ---------------------------------------------------------------------------


def test_e8_documentation_says_wh() -> None:
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
# E9: DIMENSION 1200 Time is the report-on-change parameter (dimensions.md
# "DIMENSION 1200 - automatic active-power updates").
# ---------------------------------------------------------------------------


def test_e9_dimension_1200_docstrings_describe_report_on_change() -> None:
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
# E12: the `*#18*1*1##` / `*#18*1*11*...##` fixtures are grammar-only
# (dimensions.md "Identifier table": no DIMENSION 1, active power is 113;
# zigbee-variant.md "Dimension table": 11 is Voltage; no kWh on the wire).
# ---------------------------------------------------------------------------


def test_e12_golden_fixtures_are_not_labelled_as_spec() -> None:
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
