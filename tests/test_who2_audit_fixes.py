"""WHO 2 audit follow-ups that change no decoded behaviour (review-session rows A4, A5, A9).

Kept from the audit: the non-empty-WHERE guards on the ``OWNAutomationCommand``
builders (``*2*1*##`` and ``*#2**10##`` are NACKed 12/12 in the firmware
oracle; ``OWNCommand.parse`` stays permissive) and the documentation / golden
corpus clean-up (no "slat tilt" wording; the DIMENSION 10 write fixture is a
``conflict`` record). The decoding of advanced WHATs, DIMENSION 10 fields and
DIMENSION 11 frames is unchanged: no committed on-wire plant trace exercises
those forms (Encyclopedia ``who-2-automation/what.md``, ``dimensions.md`` and
``addressing.md`` are documentation context only).
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from OWNd.message import OWNAutomationCommand, OWNAutomationEvent, OWNCommand

REPO_ROOT = Path(__file__).resolve().parent.parent


def test_base_whats_and_ordinary_states_are_unchanged() -> None:
    assert OWNAutomationEvent("*2*0*31##").state == 0
    assert OWNAutomationEvent("*2*1*31##").state == 1
    assert OWNAutomationEvent("*2*2*31##").state == 2
    closing = OWNAutomationEvent("*2*2*31##")
    assert closing.is_closing is True and closing.is_opening is False
    # Advanced and DIMENSION 10 forms decode exactly as before this audit.
    advanced = OWNAutomationEvent("*2*11#100#001#1*0##")
    assert advanced.state == 11 and advanced.what_param == ["100", "001", "1"]
    status = OWNAutomationEvent("*#2*21*10*12*40*001*14##")
    assert (status.state, status.current_position, status.is_closing) == (12, 40, True)


# ── A4 / A5: the DIMENSION 10 write is a conflict record; no slat tilt wording ─


def test_a4_a5_golden_corpus_dimension_10_write_is_conflict_and_no_tilt() -> None:
    corpus = json.loads((REPO_ROOT / "tests" / "golden" / "corpus.json").read_text(encoding="utf-8"))
    frames = corpus["frames"] if isinstance(corpus, dict) else corpus
    records = [f for f in frames if f.get("who") == 2]
    assert records
    pos_write = next(f for f in records if f["id"] == "cover.dim.write.pos.75")
    assert pos_write["frame"] == "*#2*93*#10*75##"
    assert pos_write["source"] == "conflict"
    assert "DIMENSION 11" in pos_write["mcp_notes"]
    assert not any("tilt" in (f.get("mcp_notes") or "").lower() for f in records)
    assert not any("tilt" in f["id"] for f in records)
    echo = next(f for f in records if f["id"] == "cover.evt.level.50.virtual.25.f461")
    assert echo["direction"] == "dimension_write"  # stays a command (gate, D56)
    for path in ("README.md", "docs/protocol_conformance_matrix.md", "tests/golden/README.md"):
        text = (REPO_ROOT / path).read_text(encoding="utf-8").lower()
        assert "tilt" not in text, path


# ── A9: WHO 2 builders validate WHERE; the parser stays permissive ──────────


@pytest.mark.parametrize(
    "builder",
    [
        OWNAutomationCommand.status,
        OWNAutomationCommand.get_shutter_status,
        OWNAutomationCommand.raise_shutter,
        OWNAutomationCommand.lower_shutter,
        OWNAutomationCommand.stop_shutter,
        lambda where: OWNAutomationCommand.set_shutter_level(where, 50),
        lambda where: OWNAutomationCommand.report_shutter_level(where, 50),
    ],
)
@pytest.mark.parametrize("where", ["", "*", "  ", "31*1"])
def test_a9_builders_reject_empty_or_star_where(builder, where: str) -> None:
    # addressing.md#where-forms: 0, A, APL, #GR or APL#4#INTERFACE only;
    # *2*1*## and *#2**10## are NACKed 12/12 in the firmware oracle.
    with pytest.raises(ValueError, match="where must be a non-empty address without '\\*'"):
        builder(where)


def test_a9_builders_accept_every_documented_where_form() -> None:
    assert str(OWNAutomationCommand.status(" 0 ")) == "*#2*0##"
    assert str(OWNAutomationCommand.get_shutter_status("#3")) == "*#2*#3*10##"
    assert str(OWNAutomationCommand.raise_shutter(31)) == "*2*1*31##"
    assert str(OWNAutomationCommand.lower_shutter("21#4#01")) == "*2*2*21#4#01##"
    assert str(OWNAutomationCommand.stop_shutter("100")) == "*2*0*100##"
    for frame in ("*#2*0##", "*#2*#3*10##", "*2*1*31##", "*2*2*21#4#01##", "*2*0*100##"):
        assert OWNAutomationCommand(frame).is_valid is True
    assert OWNAutomationCommand.lower_shutter("21#4#01").human_readable_log == "Lowering shutter 21 on interface 01."


def test_a9_parser_still_accepts_an_empty_where_frame() -> None:
    # Only the builders are guarded; OWNCommand.parse does not raise on the
    # frame and classifies it exactly as before (an invalid WHO 2 command).
    parsed = OWNCommand.parse("*2*1*##")
    assert isinstance(parsed, OWNAutomationCommand)
    assert parsed.is_valid is False
