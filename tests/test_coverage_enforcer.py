"""Automated test suite verifying the coverage enforcer and README updater."""
from __future__ import annotations

import os
import xml.etree.ElementTree as ET
import pytest

from scripts.verify_coverage import (
    collapse_line_ranges,
    get_source_snippet,
    normalize_coverage_filename,
    verify_all_coverage,
)
from scripts.update_readme_coverage import update_readme_and_svg


def test_normalize_coverage_filename():
    """Verify filename normalization handles relative, absolute, and bare paths."""
    assert normalize_coverage_filename("connection.py") == "OWNd/connection.py"
    assert normalize_coverage_filename("OWNd/message.py") == "OWNd/message.py"
    assert normalize_coverage_filename(r"transport\tcp.py") == "OWNd/transport/tcp.py"


def test_collapse_line_ranges():
    """Verify conversion of line number lists into compact ranges."""
    assert collapse_line_ranges([]) == ""
    assert collapse_line_ranges(["5"]) == "5"
    assert collapse_line_ranges(["1", "2", "3"]) == "1-3"
    assert collapse_line_ranges(["10", "11", "15", "16", "17", "20"]) == "10-11, 15-17, 20"
    assert collapse_line_ranges(["668", "667"]) == "667-668"


def test_get_source_snippet():
    """Verify source code line retrieval."""
    snippet = get_source_snippet("OWNd/profiles.py", 1)
    assert snippet != ""
    assert get_source_snippet("nonexistent_file.py", 999) == ""


def test_verify_all_coverage_missing_xml():
    """Verify return code when coverage.xml is missing."""
    assert verify_all_coverage("/path/does/not/exist.xml") == 1


def test_verify_all_coverage_success(tmp_path):
    """Verify that meeting coverage requirements passes."""
    xml_file = tmp_path / "coverage.xml"

    from scripts.verify_coverage import OWND_DIR, REPO_ROOT, EXCLUDED_MODULES

    disk_files = []
    for root_dir, _, files in os.walk(OWND_DIR):
        for f in files:
            if f.endswith(".py"):
                full_path = os.path.join(root_dir, f)
                rel_path = os.path.relpath(full_path, REPO_ROOT).replace("\\", "/")
                if rel_path not in EXCLUDED_MODULES:
                    disk_files.append(rel_path)

    root = ET.Element("coverage")
    pkg = ET.SubElement(root, "package")
    for df in disk_files:
        cls = ET.SubElement(pkg, "class", attrib={"filename": df, "line-rate": "1.0"})
        lines = ET.SubElement(cls, "lines")
        ET.SubElement(lines, "line", number="1", hits="1")

    ET.ElementTree(root).write(str(xml_file))

    summary_file = tmp_path / "summary.md"
    monkeypatch_env = {"GITHUB_STEP_SUMMARY": str(summary_file)}
    with pytest.MonkeyPatch.context() as mp:
        for k, v in monkeypatch_env.items():
            mp.setenv(k, v)
        assert verify_all_coverage(str(xml_file), min_threshold=90.0) == 0

    assert "Test Coverage Enforced" in summary_file.read_text(encoding="utf-8")


def test_verify_all_coverage_detects_uncovered_lines(tmp_path):
    """Verify that any module below threshold causes failure with line numbers."""
    xml_file = tmp_path / "coverage.xml"
    summary_file = tmp_path / "summary.md"

    root = ET.Element("coverage")
    pkg = ET.SubElement(root, "package")
    cls = ET.SubElement(pkg, "class", attrib={"filename": "OWNd/connection.py", "line-rate": "0.40"})
    lines = ET.SubElement(cls, "lines")
    ET.SubElement(lines, "line", number="10", hits="0")
    ET.SubElement(lines, "line", number="11", hits="0")
    ET.SubElement(lines, "line", number="12", hits="1")

    ET.ElementTree(root).write(str(xml_file))

    with pytest.MonkeyPatch.context() as mp:
        mp.setenv("GITHUB_STEP_SUMMARY", str(summary_file))
        assert verify_all_coverage(str(xml_file), min_threshold=90.0) == 1

    summary_content = summary_file.read_text(encoding="utf-8")
    assert "Test Coverage Enforcement Failed" in summary_content
    assert "connection.py" in summary_content
    assert "10-11" in summary_content


def test_update_readme_and_svg(tmp_path):
    """Verify update_readme_and_svg generates SVG and updates README."""
    xml_file = tmp_path / "coverage.xml"
    svg_file = tmp_path / "coverage.svg"
    readme_file = tmp_path / "README.md"
    readme_file.write_text("# Test\n\n[![Ruff](test)](test)\n", encoding="utf-8")

    root = ET.Element("coverage", attrib={"line-rate": "0.95"})
    pkg = ET.SubElement(root, "package")
    cls = ET.SubElement(pkg, "class", attrib={"filename": "OWNd/profiles.py", "line-rate": "0.95"})
    lines = ET.SubElement(cls, "lines")
    ET.SubElement(lines, "line", number="1", hits="1")
    ET.ElementTree(root).write(str(xml_file))

    with pytest.MonkeyPatch.context() as mp:
        mp.setattr("scripts.update_readme_coverage.COVERAGE_XML", str(xml_file))
        mp.setattr("scripts.update_readme_coverage.COVERAGE_SVG", str(svg_file))
        mp.setattr("scripts.update_readme_coverage.README_MD", str(readme_file))
        update_readme_and_svg()

    assert svg_file.exists()
    assert "95%" in svg_file.read_text(encoding="utf-8")
    updated_readme = readme_file.read_text(encoding="utf-8")
    assert "START_COVERAGE_TABLE" in updated_readme
    assert "OWNd/profiles.py" in updated_readme
