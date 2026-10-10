"""Unit tests for the documentation anti-drift sentinel and synchronizer."""
from __future__ import annotations

from pathlib import Path
import re

import pytest

from OWNd.profiles import canonical_profiles
from scripts.sync_documentation import (
    COVERAGE_END_MARKER,
    COVERAGE_START_MARKER,
    GATEWAY_END_MARKER,
    GATEWAY_START_MARKER,
    WHO_DEFINITIONS,
    WHO_END_MARKER,
    WHO_START_MARKER,
    WhoCatalogDefinition,
    _replace_marker_block,
    _resolve_subsystem_classes,
    build_coverage_table,
    build_gateway_profiles_table,
    build_who_catalog_table,
    generate_coverage_svg,
    main,
    normalize_coverage_filename,
    sync_documentation,
    verify_who_catalog_coverage,
)


def test_build_gateway_profiles_table() -> None:
    """Verify generated gateway profiles table contains all canonical profiles."""
    table = build_gateway_profiles_table()
    assert "| Gateway Model | Concurrency | Queue Delay | Event keepalive | Features |" in table
    assert "|:---|:---:|:---:|:---:|:---|" in table

    profiles = canonical_profiles()
    for profile in profiles:
        model_name = (
            "Generic Gateway"
            if profile.model_name in ("Generic", "Generic Gateway")
            else profile.model_name
        )
        assert f"**{model_name}**" in table
        assert profile.concurrency_summary in table
        assert profile.queue_delay_summary in table


def test_build_who_catalog_table() -> None:
    """Verify generated WHO catalog table contains all defined subsystems and classes."""
    table = build_who_catalog_table()
    assert "| WHO | Subsystem | Description & Capabilities | Event / Command Classes |" in table
    assert "|:---:|:---|:---|:---|" in table

    # Verify key subsystem names and WHO identifiers
    for defn in WHO_DEFINITIONS:
        assert f"| {defn.who} | {defn.name} |" in table

    # Verify WHO 17 includes both OWNSceneCommand and OWNSceneEvent
    assert "`OWNSceneCommand`, `OWNSceneEvent`" in table

    # Verify WHO 1 includes OWNLightingCommand and OWNLightingEvent
    assert "`OWNLightingCommand`, `OWNLightingEvent`" in table

    # Verify WHO 4 includes OWNHeatingCommand and OWNHeatingEvent
    assert "`OWNHeatingCommand`, `OWNHeatingEvent`" in table

    # Verify WHO 0 includes OWNScenarioEvent
    assert "| **0** | Scenarios |" in table
    assert "`OWNScenarioEvent`" in table

    # Verify WHO 9 includes OWNAuxEvent
    assert "| **9** | Auxiliary |" in table
    assert "`OWNAuxEvent`" in table

    # Verify WHO 15 includes CEN classes without OWNScenarioEvent
    assert "| **15** | CEN Scenarios |" in table
    assert "`OWNCenCommand`, `OWNCENEvent`" in table

    # Verify WHO 25 includes CEN+ and DryContact classes
    assert "`OWNCenPlusCommand`, `OWNCENPlusEvent`, `OWNDryContactCommand`, `OWNDryContactEvent`" in table


def test_resolve_subsystem_classes_validation() -> None:
    """Verify _resolve_subsystem_classes validates class existence in OWNd.message."""
    # Invalid class name that does not exist in OWNd.message
    invalid_def = WhoCatalogDefinition(
        who="**99**",
        name="Invalid Subsystem",
        description="Fake",
        dispatch_who_keys=(),
        explicit_classes=("NonExistentCommandClass",),
    )
    with pytest.raises(AttributeError, match="not found in OWNd.message"):
        _resolve_subsystem_classes(invalid_def)

    # Object that exists in OWNd.message module but is not in __all__
    invalid_all_def = WhoCatalogDefinition(
        who="**99**",
        name="Private Class",
        description="Fake",
        dispatch_who_keys=(),
        explicit_classes=("re",),
    )
    with pytest.raises(ValueError, match="not exported in OWNd.message.__all__"):
        _resolve_subsystem_classes(invalid_all_def)


def test_normalize_coverage_filename(tmp_path: Path) -> None:
    """Verify filename normalization from coverage.xml paths."""
    assert normalize_coverage_filename("OWNd/message/lighting.py", tmp_path) == "OWNd/message/lighting.py"
    assert normalize_coverage_filename("message/lighting.py", tmp_path) == "OWNd/message/lighting.py"

    abs_path = str(tmp_path / "OWNd" / "profiles.py")
    assert normalize_coverage_filename(abs_path, tmp_path) == "OWNd/profiles.py"

    # Edge cases: non-module files, external paths, empty strings
    assert normalize_coverage_filename("") is None
    assert normalize_coverage_filename("   ") is None
    assert normalize_coverage_filename("tests/test_sync_documentation.py") is None
    assert normalize_coverage_filename("scripts/sync_documentation.py") is None
    assert normalize_coverage_filename("setup.py") is None
    assert normalize_coverage_filename("OWNd/py.typed") is None


def test_coverage_table_and_svg(tmp_path: Path) -> None:
    """Verify coverage XML parsing and SVG badge generation."""
    sample_xml = """<?xml version="1.0" ?>
<coverage version="7.0" line-rate="0.954">
    <packages>
        <package name="OWNd">
            <classes>
                <class name="profiles.py" filename="OWNd/profiles.py" line-rate="1.0" />
                <class name="discovery.py" filename="OWNd/discovery.py" line-rate="0.95" />
                <class name="__main__.py" filename="OWNd/__main__.py" line-rate="0.5" />
                <class name="empty.py" filename="" line-rate="0.0" />
                <class name="test_dummy.py" filename="tests/test_dummy.py" line-rate="1.0" />
                <class name="bad_rate.py" filename="OWNd/energy.py" line-rate="invalid" />
            </classes>
        </package>
    </packages>
</coverage>
"""
    xml_file = tmp_path / "coverage.xml"
    xml_file.write_text(sample_xml, encoding="utf-8")

    table, rate, color = build_coverage_table(xml_file, repo_root=tmp_path)
    assert rate == 95
    assert color == "#4c1"
    assert "| Component / Module | Coverage | Notes |" in table
    assert "| [`OWNd/profiles.py`](OWNd/profiles.py) | **100%** |" in table
    assert "| [`OWNd/discovery.py`](OWNd/discovery.py) | **95%** |" in table
    assert "| [`OWNd/energy.py`](OWNd/energy.py) | 0% |" in table
    # __main__.py and tests are ignored
    assert "__main__.py" not in table
    assert "tests/" not in table

    # SVG badge tests across rate thresholds
    svg_green = generate_coverage_svg(95)
    assert 'fill="#4c1"' in svg_green
    assert ">95%<" in svg_green

    svg_yellow = generate_coverage_svg(75)
    assert 'fill="#dfb317"' in svg_yellow
    assert ">75%<" in svg_yellow

    svg_red = generate_coverage_svg(50)
    assert 'fill="#e05d44"' in svg_red
    assert ">50%<" in svg_red

    # Non-existent coverage XML raises FileNotFoundError
    with pytest.raises(FileNotFoundError):
        build_coverage_table(tmp_path / "nonexistent.xml")

    # Malformed XML raises ValueError
    malformed_xml = tmp_path / "malformed.xml"
    malformed_xml.write_text("<coverage><unclosed>", encoding="utf-8")
    with pytest.raises(ValueError, match="Failed to parse coverage XML"):
        build_coverage_table(malformed_xml)


def test_replace_marker_block_edge_cases() -> None:
    """Test marker replacement error handling."""
    content = "Header\n<!-- START -->Old<!-- END -->\nFooter"

    # Missing markers
    with pytest.raises(ValueError, match="Marker pair"):
        _replace_marker_block(content, "<!-- MISSING_START -->", "<!-- END -->", "New")

    # Clean replacement
    updated, changed = _replace_marker_block(content, "<!-- START -->", "<!-- END -->", "New")
    assert changed is True
    assert updated == "Header\n<!-- START -->\nNew\n<!-- END -->\nFooter"

    # No change if content matches
    _, changed_again = _replace_marker_block(updated, "<!-- START -->", "<!-- END -->", "New")
    assert changed_again is False


def test_sync_documentation_live_readme() -> None:
    """Verify that the repository's live README.md is in sync."""
    repo_root = Path(__file__).resolve().parent.parent
    readme_path = repo_root / "README.md"
    coverage_xml = repo_root / "coverage.xml"

    is_in_sync, diff, messages = sync_documentation(
        readme_path=readme_path,
        coverage_xml_path=coverage_xml if coverage_xml.is_file() else None,
        check_only=True,
    )

    assert is_in_sync is True, f"Live README.md has drifted:\n{diff}"
    assert diff == ""


def test_sync_documentation_drift_detection_and_inplace_update(tmp_path: Path) -> None:
    """Verify drift detection, unified diff generation, and in-place updating."""
    # Build a simulated README with outdated WHO catalog and Gateway profiles
    readme_content = f"""# Test Readme

{WHO_START_MARKER}
| WHO | Subsystem | Description & Capabilities | Event / Command Classes |
|:---:|:---|:---|:---|
| **17** | Scenario Programmer | Old description | `OWNSceneEvent` |
{WHO_END_MARKER}

{GATEWAY_START_MARKER}
| Gateway Model | Concurrency | Queue Delay | Event keepalive | Features |
|:---|:---:|:---:|:---:|:---|
| **OldGateway** | 1 session | 100 ms | OS TCP only | Old |
{GATEWAY_END_MARKER}

{COVERAGE_START_MARKER}
| Component / Module | Coverage | Notes |
|---|:---:|---|
| [`OWNd/profiles.py`](OWNd/profiles.py) | **90%** | Old note |
{COVERAGE_END_MARKER}
"""
    readme_file = tmp_path / "README.md"
    readme_file.write_text(readme_content, encoding="utf-8")

    sample_xml = """<?xml version="1.0" ?>
<coverage line-rate="1.0">
    <packages>
        <package name="OWNd">
            <classes>
                <class name="profiles.py" filename="OWNd/profiles.py" line-rate="1.0" />
            </classes>
        </package>
    </packages>
</coverage>
"""
    xml_file = tmp_path / "coverage.xml"
    xml_file.write_text(sample_xml, encoding="utf-8")
    svg_file = tmp_path / "coverage.svg"

    # 1. Run in check_only mode -> should report drift
    in_sync, diff, messages = sync_documentation(
        readme_path=readme_file,
        coverage_xml_path=xml_file,
        coverage_svg_path=svg_file,
        check_only=True,
    )
    assert in_sync is False
    assert "-| **OldGateway**" in diff
    assert "+| **MyHomeServer1**" in diff
    assert "+| **17** | Scenario Programmer" in diff
    assert "`OWNSceneCommand`, `OWNSceneEvent`" in diff

    # 2. Run in update mode -> should update in-place
    in_sync_update, _, update_msgs = sync_documentation(
        readme_path=readme_file,
        coverage_xml_path=xml_file,
        coverage_svg_path=svg_file,
        check_only=False,
    )
    assert in_sync_update is False  # Was modified during update
    assert svg_file.is_file()

    # 3. Re-run in check_only mode -> now in sync
    in_sync_after, diff_after, _ = sync_documentation(
        readme_path=readme_file,
        coverage_xml_path=xml_file,
        coverage_svg_path=svg_file,
        check_only=True,
    )
    assert in_sync_after is True
    assert diff_after == ""


def test_coverage_svg_drift_detection_in_check_mode(tmp_path: Path) -> None:
    """Verify that drifted coverage.svg is detected in check_only mode."""
    gw_table = build_gateway_profiles_table()
    who_table = build_who_catalog_table()

    sample_xml = """<?xml version="1.0" ?>
<coverage line-rate="1.0">
    <packages>
        <package name="OWNd">
            <classes>
                <class name="profiles.py" filename="OWNd/profiles.py" line-rate="1.0" />
            </classes>
        </package>
    </packages>
</coverage>
"""
    xml_file = tmp_path / "coverage.xml"
    xml_file.write_text(sample_xml, encoding="utf-8")

    cov_table, _, _ = build_coverage_table(xml_file, repo_root=tmp_path)
    readme_content = f"""# Test Readme
{WHO_START_MARKER}
{who_table}
{WHO_END_MARKER}
{GATEWAY_START_MARKER}
{gw_table}
{GATEWAY_END_MARKER}
{COVERAGE_START_MARKER}
{cov_table}
{COVERAGE_END_MARKER}
"""
    readme_file = tmp_path / "README.md"
    readme_file.write_text(readme_content, encoding="utf-8")

    # SVG badge exists on disk but has outdated 75% rate
    svg_file = tmp_path / "coverage.svg"
    svg_file.write_text(generate_coverage_svg(75), encoding="utf-8")

    # In check_only mode, drift must be caught
    in_sync, _, msgs = sync_documentation(
        readme_path=readme_file,
        coverage_xml_path=xml_file,
        coverage_svg_path=svg_file,
        check_only=True,
    )
    assert in_sync is False
    assert any("coverage.svg drifted" in m for m in msgs)

    # 2. In update mode, SVG is corrected
    in_sync_update, _, _ = sync_documentation(
        readme_path=readme_file,
        coverage_xml_path=xml_file,
        coverage_svg_path=svg_file,
        check_only=False,
    )
    assert in_sync_update is False
    assert ">100%<" in svg_file.read_text(encoding="utf-8")

    # 3. Check mode now passes cleanly
    in_sync_after, _, _ = sync_documentation(
        readme_path=readme_file,
        coverage_xml_path=xml_file,
        coverage_svg_path=svg_file,
        check_only=True,
    )
    assert in_sync_after is True


def test_sync_documentation_crlf_detection(tmp_path: Path) -> None:
    """Verify CRLF line ending drift detection and LF normalization."""
    gw_table = build_gateway_profiles_table()
    who_table = build_who_catalog_table()

    # Create README with Windows CRLF line endings
    readme_content = (
        f"# Test Readme\r\n\r\n"
        f"{WHO_START_MARKER}\r\n{who_table}\r\n{WHO_END_MARKER}\r\n\r\n"
        f"{GATEWAY_START_MARKER}\r\n{gw_table}\r\n{GATEWAY_END_MARKER}\r\n\r\n"
        f"{COVERAGE_START_MARKER}\r\n| Component / Module | Coverage | Notes |\r\n|---|:---:|---|\r\n| [`OWNd/profiles.py`](OWNd/profiles.py) | **100%** | notes |\r\n{COVERAGE_END_MARKER}\r\n"
    )
    readme_file = tmp_path / "README.md"
    readme_file.write_bytes(readme_content.encode("utf-8"))

    # 1. Check mode flags CRLF drift
    in_sync, _, msgs = sync_documentation(
        readme_path=readme_file,
        coverage_xml_path=None,
        check_only=True,
    )
    assert in_sync is False
    assert any("contains CRLF line endings" in m for m in msgs)

    # 2. Update mode normalizes to LF only
    in_sync_up, _, _ = sync_documentation(
        readme_path=readme_file,
        coverage_xml_path=None,
        check_only=False,
    )
    assert in_sync_up is False
    assert b"\r" not in readme_file.read_bytes()

    # 3. Check mode now passes cleanly
    in_sync_after, _, _ = sync_documentation(
        readme_path=readme_file,
        coverage_xml_path=None,
        check_only=True,
    )
    assert in_sync_after is True


def test_who_catalog_dispatch_coverage() -> None:
    """Verify all registered WHO command and event parsers are covered in WHO_DEFINITIONS."""
    violations = verify_who_catalog_coverage()
    assert not violations, f"WHO catalog definition gaps found: {violations}"


def test_who_catalog_dispatch_coverage_detects_unmapped_registries(monkeypatch: pytest.MonkeyPatch) -> None:
    """Verify verify_who_catalog_coverage catches missing WHOs in commands, events, or both."""
    import OWNd.message.base as base_mod

    # Clean initial state
    clean_cmds = dict(base_mod._COMMAND_DISPATCH)
    clean_evts = dict(base_mod._EVENT_DISPATCH)
    assert verify_who_catalog_coverage() == []

    # 1. Isolated command-only registration
    cmd_only = dict(clean_cmds)
    cmd_only[998] = lambda frame: base_mod.OWNCommand(frame)
    monkeypatch.setattr(base_mod, "_COMMAND_DISPATCH", cmd_only)
    monkeypatch.setattr(base_mod, "_EVENT_DISPATCH", dict(clean_evts))
    assert verify_who_catalog_coverage() == [
        "WHO 998 registered in _COMMAND_DISPATCH but not mapped in WHO_DEFINITIONS."
    ]

    # 2. Isolated event-only registration
    evt_only = dict(clean_evts)
    evt_only[999] = lambda frame: base_mod.OWNEvent(frame)
    monkeypatch.setattr(base_mod, "_COMMAND_DISPATCH", dict(clean_cmds))
    monkeypatch.setattr(base_mod, "_EVENT_DISPATCH", evt_only)
    assert verify_who_catalog_coverage() == [
        "WHO 999 registered in _EVENT_DISPATCH but not mapped in WHO_DEFINITIONS."
    ]

    # 3. Isolated dual registration (both command and event dispatch)
    both_cmd = dict(clean_cmds)
    both_cmd[997] = lambda frame: base_mod.OWNCommand(frame)
    both_evt = dict(clean_evts)
    both_evt[997] = lambda frame: base_mod.OWNEvent(frame)
    monkeypatch.setattr(base_mod, "_COMMAND_DISPATCH", both_cmd)
    monkeypatch.setattr(base_mod, "_EVENT_DISPATCH", both_evt)
    assert verify_who_catalog_coverage() == [
        "WHO 997 registered in _COMMAND_DISPATCH and _EVENT_DISPATCH but not mapped in WHO_DEFINITIONS."
    ]


def test_sync_documentation_fails_on_catalog_gap_and_refuses_write(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Verify sync_documentation and CLI refuse writing and exit 1 on catalog gaps."""
    import OWNd.message.base as base_mod

    repo_root = Path(__file__).resolve().parent.parent
    readme_path = repo_root / "README.md"

    # Register an unmapped event-only WHO (e.g. 999)
    fake_evt_dispatch = dict(base_mod._EVENT_DISPATCH)
    fake_evt_dispatch[999] = lambda frame: base_mod.OWNEvent(frame)
    monkeypatch.setattr(base_mod, "_EVENT_DISPATCH", fake_evt_dispatch)

    # 1. sync_documentation in check mode must return in_sync=False
    in_sync, diff, messages = sync_documentation(
        readme_path=readme_path,
        coverage_xml_path=None,
        check_only=True,
    )
    assert in_sync is False
    assert any("WHO catalog gap:" in m for m in messages)
    assert any("WHO 999 registered in _EVENT_DISPATCH" in m for m in messages)

    # 2. sync_documentation in update mode must refuse writing when catalog gaps exist
    drifted_content = readme_path.read_text(encoding="utf-8").replace(
        WHO_END_MARKER, f"| **999** | Fake | Description | `FakeEvent` |\n{WHO_END_MARKER}"
    )
    temp_readme = tmp_path / "README_drift.md"
    temp_readme.write_text(drifted_content, encoding="utf-8")

    in_sync_update, _, update_msgs = sync_documentation(
        readme_path=temp_readme,
        coverage_xml_path=None,
        check_only=False,
    )
    assert in_sync_update is False
    assert any("Refused to update" in m for m in update_msgs)
    # File content must NOT have been modified
    assert temp_readme.read_text(encoding="utf-8") == drifted_content

    # 3. CLI --check must exit 1
    assert main(["--check"]) == 1

    # 4. CLI update mode must also exit 1 on catalog gaps
    assert main(["--readme", str(temp_readme)]) == 1


def test_sync_documentation_missing_coverage_graceful(tmp_path: Path) -> None:
    """Verify that absent coverage.xml does not break check mode if markers are present."""
    gw_table = build_gateway_profiles_table()
    who_table = build_who_catalog_table()

    readme_content = f"""# Test Readme

{WHO_START_MARKER}
{who_table}
{WHO_END_MARKER}

{GATEWAY_START_MARKER}
{gw_table}
{GATEWAY_END_MARKER}

{COVERAGE_START_MARKER}
| Component / Module | Coverage | Notes |
|---|:---:|---|
| Existing table | 100% | Note |
{COVERAGE_END_MARKER}
"""
    readme_file = tmp_path / "README.md"
    readme_file.write_text(readme_content, encoding="utf-8")

    in_sync, diff, msgs = sync_documentation(
        readme_path=readme_file,
        coverage_xml_path=None,
        check_only=True,
    )
    assert in_sync is True
    assert diff == ""
    assert any("Coverage table check skipped" in m for m in msgs)


def test_main_cli_modes(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """Test CLI main() function across check, update, and error modes."""
    # 1. Main check on live repository exits 0
    assert main(["--check"]) == 0

    # 2. Main update flag on live repository exits 0
    assert main(["--update"]) == 0

    # 3. Main default (no flags) on live repository exits 0
    assert main([]) == 0

    # 4. Main check on drifted file exits 1
    drifted_readme = tmp_path / "README.md"
    drifted_readme.write_text("Missing all markers", encoding="utf-8")
    assert main(["--readme", str(drifted_readme), "--check"]) == 1

    # 5. Main on invalid file exits 1
    assert main(["--readme", str(tmp_path / "does_not_exist.md")]) == 1

    # 6. Explicit non-existent coverage XML exits 1
    assert main(["--coverage-xml", str(tmp_path / "nonexistent.xml")]) == 1
