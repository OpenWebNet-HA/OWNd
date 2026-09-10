#!/usr/bin/env python3
"""Update README.md coverage table and coverage.svg from coverage.xml for OWNd.

Maintains live, automated documentation of test coverage across all OWNd modules.
Called locally and by the GitHub Actions CI workflow.
"""
from __future__ import annotations

import os
import re
import subprocess
import sys
import xml.etree.ElementTree as ET

REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
COVERAGE_XML = os.path.join(REPO_ROOT, "coverage.xml")
README_MD = os.path.join(REPO_ROOT, "README.md")
COVERAGE_SVG = os.path.join(REPO_ROOT, "coverage.svg")

START_MARKER = "<!-- START_COVERAGE_TABLE -->"
END_MARKER = "<!-- END_COVERAGE_TABLE -->"

COMPONENT_NOTES = {
    "OWNd/connection.py": "Hardened dual-session TCP engine, SHA-1/HMAC auth, keepalives & bounded read loops",
    "OWNd/discovery.py": "SSDP multicast and UPnP XML gateway discovery and descriptor parsing",
    "OWNd/message.py": "OpenWebNet frame parsers, encoders, and WHO dimension decoders",
    "OWNd/profiles.py": "Declarative hardware gateway models (F454, MH200N, MH201, MH202, MyHomeServer1)",
    "OWNd/transport/base.py": "Abstract transport layer and event listener notification contracts",
    "OWNd/transport/serial.py": "Async Serial/USB transport for Legrand 3578 interface with in-band demux",
    "OWNd/transport/tcp.py": "Dual-session TCP transport linking event and command channels",
    "OWNd/transport/__init__.py": "Transport subpackage exports",
    "OWNd/__init__.py": "Package initialization and version metadata",
}


def get_test_count() -> int:
    """Dynamically determine total test count from pytest collection."""
    try:
        res = subprocess.run(
            [sys.executable, "-m", "pytest", "--collect-only", "-q"],
            capture_output=True,
            text=True,
            cwd=REPO_ROOT,
            timeout=25,
        )
        m = re.search(r"(\d+)\s+tests?\s+collected", res.stdout)
        if m:
            return int(m.group(1))
    except Exception:
        pass
    return 75


def normalize_coverage_filename(fn: str) -> str:
    """Normalize filenames from coverage.xml to OWNd/... paths."""
    fn = fn.replace("\\", "/")
    if os.path.isabs(fn):
        try:
            fn = os.path.relpath(fn, REPO_ROOT).replace("\\", "/")
        except ValueError:
            pass
    if not fn.startswith("OWNd/"):
        fn = f"OWNd/{fn}"
    return fn


def update_readme_and_svg() -> None:
    if not os.path.exists(COVERAGE_XML):
        print(f"Error: {COVERAGE_XML} not found. Run pytest with --cov-report=xml first.")
        sys.exit(1)

    tree = ET.parse(COVERAGE_XML)
    root = tree.getroot()

    file_rates: dict[str, float] = {}
    for p in root.findall(".//package"):
        for c in p.findall(".//class"):
            raw_fn = c.attrib.get("filename", "")
            fn = normalize_coverage_filename(raw_fn)
            if fn in ("OWNd/__main__.py",):
                continue
            cr = float(c.attrib.get("line-rate", 0)) * 100
            file_rates[fn] = cr

    total_rate = float(root.attrib.get("line-rate", 0)) * 100
    rate_round = round(total_rate)

    test_count = get_test_count()
    print(f"Dynamically detected test count: {test_count} (Coverage: {total_rate:.1f}%)")

    # ── 1. Generate updated coverage.svg ─────────────────────────────────────
    color = "#4c1" if rate_round >= 80 else ("#dfb317" if rate_round >= 60 else "#e05d44")
    svg = f'''<svg xmlns="http://www.w3.org/2000/svg" width="98" height="20"><linearGradient id="b" x2="0" y2="100%"><stop offset="0" stop-color="#bbb" stop-opacity=".1"/><stop offset="1" stop-opacity=".1"/></linearGradient><mask id="a"><rect width="98" height="20" rx="3" fill="#fff"/></mask><g mask="url(#a)"><path fill="#555" d="M0 0h61v20H0z"/><path fill="{color}" d="M61 0h37v20H61z"/><path fill="url(#b)" d="M0 0h98v20H0z"/></g><g fill="#fff" text-anchor="middle" font-family="DejaVu Sans,Verdana,Geneva,sans-serif" font-size="11"><text x="30.5" y="15" fill="#010101" fill-opacity=".3">coverage</text><text x="30.5" y="14">coverage</text><text x="79.5" y="15" fill="#010101" fill-opacity=".3">{rate_round}%</text><text x="79.5" y="14">{rate_round}%</text></g></svg>'''
    with open(COVERAGE_SVG, "w", encoding="utf-8") as f:
        f.write(svg)
    print(f"Updated {COVERAGE_SVG} -> {rate_round}% ({color})")

    # Sort files: by rate descending, then filename
    sorted_files = sorted(file_rates.items(), key=lambda item: (-round(item[1], 1), item[0]))

    # ── 2. Build Markdown table ──────────────────────────────────────────────
    table_lines = [
        "| Component / Module | Coverage | Notes |",
        "|---|:---:|---|",
    ]

    for fn, rate in sorted_files:
        notes = COMPONENT_NOTES.get(fn, "Core OWNd library component")
        rate_str = f"**{round(rate)}%**" if round(rate) >= 90 else f"{round(rate)}%"
        table_lines.append(f"| [`{fn}`]({fn}) | {rate_str} | {notes} |")

    new_table_block = "\n".join(table_lines)

    # ── 3. Update README.md ──────────────────────────────────────────────────
    if not os.path.exists(README_MD):
        print(f"Error: {README_MD} not found.")
        sys.exit(1)

    with open(README_MD, "r", encoding="utf-8") as f:
        content = f.read()

    if START_MARKER in content and END_MARKER in content:
        pattern = re.compile(
            rf"{re.escape(START_MARKER)}.*?{re.escape(END_MARKER)}",
            re.DOTALL,
        )
        replacement = f"{START_MARKER}\n\n{new_table_block}\n\n{END_MARKER}"
        content = pattern.sub(replacement, content)
    else:
        # Append section if markers not yet present
        coverage_section = (
            f"\n\n## 📊 Code Coverage & Quality Assurance\n\n"
            f"OWNd maintains an automated unit test suite with strict line coverage tracking across all core modules:\n\n"
            f"{START_MARKER}\n\n{new_table_block}\n\n{END_MARKER}\n\n"
            f"> **Live Test Execution**: View detailed line-by-line coverage and test history on "
            f"[**Codecov (OpenWebNet-HA/OWNd)**](https://app.codecov.io/github/OpenWebNet-HA/OWNd) or "
            f"download the interactive coverage report from the "
            f"[**CI GitHub Actions run**](https://github.com/OpenWebNet-HA/OWNd/actions/workflows/ci.yml).\n"
        )
        content += coverage_section

    # Add coverage and Codecov badges under the title if missing
    if "coverage.svg" not in content:
        badge_lines = (
            "[![Coverage](coverage.svg)](https://app.codecov.io/github/OpenWebNet-HA/OWNd)\n"
            "[![Codecov](https://codecov.io/gh/OpenWebNet-HA/OWNd/branch/master/graph/badge.svg)]"
            "(https://app.codecov.io/github/OpenWebNet-HA/OWNd)\n"
        )
        content = re.sub(
            r"(\[!\[Ruff\]\(.*?\)\n)",
            r"\g<1>" + badge_lines,
            content,
        )

    with open(README_MD, "w", encoding="utf-8") as f:
        f.write(content)

    print(f"Updated {README_MD} coverage table successfully ({len(sorted_files)} modules, total {rate_round}%).")


if __name__ == "__main__":
    update_readme_and_svg()
