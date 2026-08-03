"""Regression tests for OWNGateway's discovery-info string normalization.

Some UPnP/SSDP XML descriptions yield a list instead of a plain string for
fields like manufacturer/modelNumber (e.g. a repeated tag). HA's device
registry rejects non-string values there, so OWNGateway.__init__ collapses
list/tuple values down to their first element via _as_str().
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from OWNd.connection import OWNGateway


def test_as_str_passes_through_plain_string():
    assert OWNGateway._as_str("BTicino S.p.A.") == "BTicino S.p.A."


def test_as_str_collapses_list_to_first_element():
    assert OWNGateway._as_str(["BTicino S.p.A.", "BTicino S.p.A."]) == "BTicino S.p.A."


def test_as_str_collapses_empty_list_to_none():
    assert OWNGateway._as_str([]) is None


def test_as_str_passes_through_none():
    assert OWNGateway._as_str(None) is None


def test_gateway_normalizes_list_valued_discovery_fields():
    gateway = OWNGateway(
        {
            "manufacturer": ["BTicino S.p.A.", "BTicino S.p.A."],
            "modelNumber": ["1.2.3"],
            "friendlyName": "F454",
        }
    )
    assert gateway.manufacturer == "BTicino S.p.A."
    assert gateway.model_number == "1.2.3"
    assert gateway.friendly_name == "F454"


if __name__ == "__main__":
    test_as_str_passes_through_plain_string()
    test_as_str_collapses_list_to_first_element()
    test_as_str_collapses_empty_list_to_none()
    test_as_str_passes_through_none()
    test_gateway_normalizes_list_valued_discovery_fields()
    print("OK")
