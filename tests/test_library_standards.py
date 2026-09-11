"""Unit tests verifying OWNd library standards and decoupling."""
from pathlib import Path
import re

import OWNd
from scripts.verify_library_standards import (
    StandardsValidator,
    check_decoupling,
    check_pep561_typing,
    check_pure_async,
    check_version_sync,
)


def test_library_standards_validator():
    """Verify that all library standards pass via the validator."""
    validator = StandardsValidator()
    check_decoupling(validator)
    check_pure_async(validator)
    check_pep561_typing(validator)
    check_version_sync(validator)

    assert len(validator.errors) == 0


def test_no_homeassistant_imports():
    """Guarantee that OWNd remains 100% decoupled from Home Assistant."""
    ownd_dir = Path(OWNd.__file__).resolve().parent
    for py_file in ownd_dir.rglob("*.py"):
        text = py_file.read_text(encoding="utf-8", errors="ignore")
        assert not re.search(
            r"^\s*(import homeassistant|from homeassistant)", text, re.MULTILINE
        ), f"Found forbidden Home Assistant import in {py_file}"


def test_pep561_typing_marker_present():
    """Verify PEP 561 py.typed marker is present in the package root."""
    ownd_dir = Path(OWNd.__file__).resolve().parent
    py_typed = ownd_dir / "py.typed"
    assert py_typed.is_file(), "OWNd/py.typed must exist for PEP 561 type checking"
