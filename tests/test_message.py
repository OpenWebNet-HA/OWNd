"""Regression tests for the dimension-index guard (`OWNMessage._dim`).

The F454 sometimes omits the trailing timezone field on its time broadcast
(dimension 0) frames. Before the fix this crashed with IndexError on
`self._dimension_value[3]`. These tests pin the frame formats that triggered
it, straight from the field log.
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from OWNd.message import OWNMessage, OWNGatewayCommand, OWNGatewayEvent


def test_gateway_event_missing_timezone_defaults_empty():
    message = OWNMessage.parse("*#13**0*10*30*45##")
    assert isinstance(message, OWNGatewayEvent)
    assert message._hour == "10"
    assert message._minute == "30"
    assert message._second == "45"
    assert message._timezone == ""


def test_gateway_event_with_timezone_positive_offset():
    message = OWNMessage.parse("*#13**0*10*30*45*004##")
    assert message._timezone == "+04:00"


def test_gateway_event_with_timezone_negative_offset():
    message = OWNMessage.parse("*#13**0*10*30*45*104##")
    assert message._timezone == "-04:00"


def test_gateway_command_missing_timezone_defaults_empty():
    message = OWNMessage.parse("*#13**#0*10*30*45##")
    assert isinstance(message, OWNGatewayCommand)
    assert message._timezone == ""


def test_gateway_command_with_timezone():
    message = OWNMessage.parse("*#13**#0*10*30*45*004##")
    assert message._timezone == "+04:00"


if __name__ == "__main__":
    test_gateway_event_missing_timezone_defaults_empty()
    test_gateway_event_with_timezone_positive_offset()
    test_gateway_event_with_timezone_negative_offset()
    test_gateway_command_missing_timezone_defaults_empty()
    test_gateway_command_with_timezone()
    print("OK")
