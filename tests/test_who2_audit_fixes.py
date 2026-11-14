"""WHO 2 follow-ups that change no decoded behaviour.

Kept from the Encyclopedia audit: fail-early WHERE validation on every
``OWNAutomationCommand`` builder (``require_address_where``, the helper the
WHO 1 builders use; ``OWNCommand.parse`` stays permissive) and the
documentation / golden corpus clean-up (no "slat tilt" wording; the DIMENSION
10 write fixture is a ``conflict`` record). The decoding of advanced WHATs,
DIMENSION 10 fields and DIMENSION 11 frames is unchanged: the committed
captures (MyHOME fixtures ``issue_445``, ``issue_466``, ``f461_live_2026-11-04``)
carry the gateway's own commands and echoes, and MyHOME reads positions from
DIMENSION 10 only (see the module docstring of ``OWNd/message/automation.py``).
"""

from __future__ import annotations

import json
import re
from pathlib import Path

import pytest

from OWNd.message import OWNAutomationCommand, OWNAutomationEvent, OWNCommand

REPO_ROOT = Path(__file__).resolve().parent.parent

BUILDERS = [
    pytest.param(OWNAutomationCommand.status, id="status"),
    pytest.param(OWNAutomationCommand.get_shutter_status, id="get_shutter_status"),
    pytest.param(OWNAutomationCommand.raise_shutter, id="raise_shutter"),
    pytest.param(OWNAutomationCommand.lower_shutter, id="lower_shutter"),
    pytest.param(OWNAutomationCommand.stop_shutter, id="stop_shutter"),
    pytest.param(lambda where: OWNAutomationCommand.set_shutter_level(where, 50), id="set_shutter_level"),
    pytest.param(lambda where: OWNAutomationCommand.report_shutter_level(where, 50), id="report_shutter_level"),
]


def test_base_whats_and_ordinary_states_are_unchanged() -> None:
    assert OWNAutomationEvent("*2*0*31##").state == 0
    assert OWNAutomationEvent("*2*1*31##").state == 1
    assert OWNAutomationEvent("*2*2*31##").state == 2
    closing = OWNAutomationEvent("*2*2*31##")
    assert closing.is_closing is True and closing.is_opening is False
    # Advanced and DIMENSION 10 forms decode exactly as before.
    advanced = OWNAutomationEvent("*2*11#100#001#1*0##")
    assert advanced.state == 11 and advanced.what_param == ["100", "001", "1"]
    status = OWNAutomationEvent("*#2*21*10*12*40*001*14##")
    assert (status.state, status.current_position, status.is_closing) == (12, 40, True)


def test_committed_plant_frames_decode_as_on_master() -> None:
    """The committed MyHOME captures the module docstring cites, decoded as before."""
    # MyHomeServer1 + LN4660M2 centralised commands (MyHOME fixture issue_445).
    for frame, state in (("*2*11#100#001#1*0##", 11), ("*2*12#100#001#1*0##", 12), ("*2*10#001#1*0##", 10)):
        event = OWNAutomationEvent(frame)
        assert (event.state, event.where) == (state, "0"), frame
    # F454 relative steps and their 1000# echoes (MyHOME fixture issue_466).
    assert OWNAutomationEvent("*2*11#10#001*31##").is_opening is True
    assert OWNAutomationEvent("*2*12#2#001*31##").is_closing is True
    echo = OWNAutomationEvent("*2*1000#12#10#001#1*31##")
    assert echo.state is None and echo.what == 1000
    # F461 2.0.11 translations of WHAT 13 / 14 (MyHOME fixture f461_live_2026-11-04).
    assert OWNAutomationEvent("*2*13*05##").is_opening is True
    assert OWNAutomationEvent("*2*14*05##").is_closing is True
    assert OWNAutomationEvent("*2*1000#13#001#1*05##").state is None


def test_golden_corpus_dimension_10_write_is_conflict_and_no_tilt() -> None:
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
    assert echo["direction"] == "dimension_write"  # the F461 echo stays a command
    for path in ("README.md", "docs/protocol_conformance_matrix.md", "tests/golden/README.md"):
        text = (REPO_ROOT / path).read_text(encoding="utf-8").lower()
        assert "tilt" not in text, path
    # The golden README advertises the fixture count; keep it equal to the corpus.
    golden_readme = (REPO_ROOT / "tests" / "golden" / "README.md").read_text(encoding="utf-8")
    match = re.search(r"## Supported Subsystems Catalog \((\d+) Fixtures\)", golden_readme)
    assert match is not None
    assert int(match.group(1)) == len(frames) == 175


@pytest.mark.parametrize("builder", BUILDERS)
@pytest.mark.parametrize("where", ["", "*", "  ", "31*1", "31*10"])
def test_builders_reject_empty_or_star_where(builder, where: str) -> None:
    """addressing.md#where-forms: WHERE is 0, A, APL, #GR or APL#4#INTERFACE.

    ``raise_shutter("")`` built ``*2*1*##`` (``is_valid`` False), ``raise_shutter("*")``
    the valid-looking ``*2*1**##`` and ``get_shutter_status("")`` the valid-looking
    ``*#2**10##``; ``status("31*10")`` built the DIMENSION 10 read ``*#2*31*10##``.
    All raise now."""
    with pytest.raises(ValueError, match="where must be a non-empty address without"):
        builder(where)


@pytest.mark.parametrize("builder", BUILDERS)
@pytest.mark.parametrize("where", [True, False, None, 12.5, b"31", ["31"], "31##", "31 1", "31\t1", "31\n1"])
def test_builders_reject_bool_none_and_malformed_where(builder, where: object) -> None:
    """``issubclass(bool, int)`` lets ``raise_shutter(True)`` through a ``str | int``
    check and ``str(None)`` is a string: ``require_non_empty_where`` built
    ``*2*1*True##`` and ``*#2*None##`` (``is_valid`` False, logged as "shutter None"),
    ``"31##"`` built ``*2*1*31####`` and ``"31 1"`` built ``*2*1*31 1##``. All raise now."""
    with pytest.raises(ValueError, match="where must be a non-empty address without"):
        builder(where)


def test_builders_accept_every_documented_where_form() -> None:
    assert str(OWNAutomationCommand.status(" 0 ")) == "*#2*0##"
    assert str(OWNAutomationCommand.status("31\n")) == "*#2*31##"  # stripped, as require_address_where does for WHO 1
    assert str(OWNAutomationCommand.get_shutter_status("#3")) == "*#2*#3*10##"
    assert str(OWNAutomationCommand.raise_shutter(31)) == "*2*1*31##"
    assert str(OWNAutomationCommand.lower_shutter("21#4#01")) == "*2*2*21#4#01##"
    assert str(OWNAutomationCommand.stop_shutter("100")) == "*2*0*100##"
    assert str(OWNAutomationCommand.set_shutter_level("05", 50)) == "*#2*05*#11#001*50##"
    assert str(OWNAutomationCommand.report_shutter_level(31, 40, 10, "001", 0)) == "*#2*31*10*10*40*001*0##"
    for frame in ("*#2*0##", "*#2*#3*10##", "*2*1*31##", "*2*2*21#4#01##", "*2*0*100##", "*#2*05*#11#001*50##"):
        assert OWNAutomationCommand(frame).is_valid is True
    assert OWNAutomationCommand.lower_shutter("21#4#01").human_readable_log == "Lowering shutter 21 on interface 01."


def test_report_shutter_level_priority_string_must_be_ascii_digits() -> None:
    """``"００１".isdigit()`` is True and ``int("００１")`` is 1, so the fullwidth
    string reached the wire verbatim as ``*#2*31*10*10*40*００１*0##``; it is now
    encoded through ``int`` like any other non-ASCII or non-digit string."""
    frame = str(OWNAutomationCommand.report_shutter_level("31", 40, 10, "００１", 0))
    assert frame == "*#2*31*10*10*40*1*0##"
    assert frame.isascii()
    assert str(OWNAutomationCommand.report_shutter_level("31", 40, 10, "001", 0)) == "*#2*31*10*10*40*001*0##"
    assert str(OWNAutomationCommand.report_shutter_level("31", 40, 10, 1, 0)) == "*#2*31*10*10*40*1*0##"


def test_parser_still_accepts_an_empty_where_frame() -> None:
    # Only the builders are guarded; OWNCommand.parse does not raise on the
    # frame and classifies it exactly as before (an invalid WHO 2 command).
    parsed = OWNCommand.parse("*2*1*##")
    assert isinstance(parsed, OWNAutomationCommand)
    assert parsed.is_valid is False
    assert OWNCommand.parse("*#2*##") is None
    star = OWNCommand.parse("*#2**10##")
    assert isinstance(star, OWNAutomationCommand) and star.is_valid is True
