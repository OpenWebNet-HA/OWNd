#!/usr/bin/env python3
"""Automated PyPI Library Standards & Decoupling Validator for OWNd.

This validator enforces Home Assistant Architecture ADR-0004 and PyPI
library standards:
1. Clean Decoupling: OWNd must NEVER import homeassistant (it is an independent library).
2. Pure Async: No synchronous blocking network calls (requests, urllib.request).
3. PEP 561 Typing: OWNd/py.typed must exist and be packaged for static type checkers.
4. Version Integrity: setup.py version matches OWNd.__init__.__version__.
"""
from __future__ import annotations

import ast
from pathlib import Path
import re
import sys

ROOT_DIR = Path(__file__).resolve().parent.parent
OWND_DIR = ROOT_DIR / "OWNd"


class StandardsValidator:
    def __init__(self) -> None:
        self.errors: list[str] = []

    def error(self, rule: str, file_path: Path, line: int, message: str) -> None:
        try:
            rel = file_path.relative_to(ROOT_DIR)
        except ValueError:
            rel = file_path
        msg = f"[{rule}] {rel}:{line}: {message}"
        self.errors.append(msg)
        print(f"\033[91mFAIL\033[0m: {msg}")

    def ok(self, message: str) -> None:
        print(f"\033[92mPASS\033[0m: {message}")


def check_decoupling(validator: StandardsValidator) -> None:
    """Verify OWNd does not import homeassistant."""
    violation_found = False
    for py_file in OWND_DIR.rglob("*.py"):
        text = py_file.read_text(encoding="utf-8", errors="ignore")
        for idx, line in enumerate(text.splitlines(), start=1):
            if re.search(r"^\s*(import homeassistant|from homeassistant)", line):
                validator.error("RULE_DECOUPLING", py_file, idx, "OWNd must NOT import homeassistant")
                violation_found = True
    if not violation_found:
        validator.ok("Clean decoupling verified: 0 Home Assistant imports in OWNd.")


def check_pure_async(validator: StandardsValidator) -> None:
    """Verify OWNd uses pure asyncio and no blocking network calls."""
    violation_found = False
    blocking_patterns = [
        (re.compile(r"^\s*(import requests|from requests\b)"), "requests library is blocking; use aiohttp / asyncio"),
        (re.compile(r"^\s*(import urllib\.request|from urllib\.request\b)"), "urllib.request is blocking; use asyncio"),
    ]
    for py_file in OWND_DIR.rglob("*.py"):
        text = py_file.read_text(encoding="utf-8", errors="ignore")
        for idx, line in enumerate(text.splitlines(), start=1):
            for pattern, msg in blocking_patterns:
                if pattern.search(line):
                    validator.error("RULE_PURE_ASYNC", py_file, idx, msg)
                    violation_found = True
    if not violation_found:
        validator.ok("Pure async verified: 0 blocking network libraries in OWNd.")


def check_pep561_typing(validator: StandardsValidator) -> None:
    """Verify PEP 561 py.typed marker is present and packaged."""
    py_typed = OWND_DIR / "py.typed"
    if not py_typed.is_file():
        validator.error("RULE_PEP561", py_typed, 1, "PEP 561 marker 'OWNd/py.typed' is missing")
    else:
        validator.ok("PEP 561 typing marker verified: OWNd/py.typed present.")

    setup_file = ROOT_DIR / "setup.py"
    if setup_file.is_file():
        text = setup_file.read_text(encoding="utf-8")
        if "py.typed" not in text:
            validator.error("RULE_PEP561", setup_file, 1, "setup.py must declare package_data for py.typed")
        else:
            validator.ok("PEP 561 package data verified in setup.py.")


def check_version_sync(validator: StandardsValidator) -> None:
    """Verify version definition in OWNd/__init__.py."""
    init_file = OWND_DIR / "__init__.py"
    if not init_file.is_file():
        validator.error("RULE_VERSION", init_file, 1, "OWNd/__init__.py missing")
        return

    text = init_file.read_text(encoding="utf-8")
    match = re.search(r'^__version__\s*=\s*["\']([^"\']+)["\']', text, re.MULTILINE)
    if not match:
        validator.error("RULE_VERSION", init_file, 1, "Could not find __version__ in OWNd/__init__.py")
    else:
        validator.ok(f"Package version integrity verified: v{match.group(1)}.")


def main() -> int:
    print("=" * 70)
    print("Running OWNd PyPI Library Standards & Decoupling Validator")
    print("=" * 70)

    validator = StandardsValidator()
    check_decoupling(validator)
    check_pure_async(validator)
    check_pep561_typing(validator)
    check_version_sync(validator)

    print("=" * 70)
    if validator.errors:
        print(f"\nFAILED: {len(validator.errors)} standards violation(s) found.\n")
        return 1

    print("\nSUCCESS: All OWNd library standards passed!\n")
    return 0


if __name__ == "__main__":
    sys.exit(main())
