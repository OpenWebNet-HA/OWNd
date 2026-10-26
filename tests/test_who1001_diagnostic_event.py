"""WHO 1001 Dimension 11: lighting actuator autodiagnostic mask.

own-firmware-oracle ``what19`` (input ``*#1*74##``): F453, F453AV, F459, F460,
F461, MH200N and MyHomeServer1 emit ``*1*19*74##`` then
``*#1001*74*11*111110111111111111110111##``; MH202 the mask only; F454, H4684
and MH200 ``*1*19*74##`` only; F450 ``nack``/``silent``. A physical MH200
capture (findings/MH200N/what19.md, EVID-MH200-WHAT19-FAULT) agrees. The bit
meanings are marked Open there, so nothing is interpreted.
"""

from __future__ import annotations

import pytest

from OWNd.message import OWNCommand, OWNEvent, OWNLightingDiagnosticEvent, OWNMessage


def test_lighting_autodiagnostic_mask_parses() -> None:
    message = OWNMessage.parse("*#1001*74*11*111110111111111111110111##")

    assert isinstance(message, OWNLightingDiagnosticEvent)
    assert isinstance(message, OWNEvent)
    assert message.who == 1001
    assert message.where == "74"
    assert message.dimension == 11
    assert message.dimension_value == ["111110111111111111110111"]
    assert message.diagnostic_mask == "111110111111111111110111"
    assert message.cleared_bits == (6, 21)
    assert message.human_readable_log == (
        "Light 74 autodiagnostic mask is 111110111111111111110111 (cleared bits: 6, 21)."
    )


def test_lighting_autodiagnostic_all_bits_set() -> None:
    message = OWNMessage.parse("*#1001*74*11*111111111111111111111111##")

    assert isinstance(message, OWNLightingDiagnosticEvent)
    assert message.cleared_bits == ()
    assert message.human_readable_log.endswith("(cleared bits: none).")


@pytest.mark.parametrize(
    ("frame", "expected_class"),
    [
        # A trailing value: not the mask shape.
        ("*#1001*74*11*101*5##", OWNLightingDiagnosticEvent),
        # Another dimension.
        ("*#1001*74*12*5##", OWNLightingDiagnosticEvent),
        # Not 24 bits: one bit, 23 bits, 26 bits.
        ("*#1001*74*11*1##", OWNLightingDiagnosticEvent),
        ("*#1001*74*11*11111011111111111111011##", OWNLightingDiagnosticEvent),
        ("*#1001*74*11*00000000000000000000000000##", OWNLightingDiagnosticEvent),
        # 24 characters that are not all bits.
        ("*#1001*74*11*111110111111111111110112##", OWNLightingDiagnosticEvent),
        # A status/dimension request (no value) is a command, not an event.
        ("*#1001*74*11##", OWNCommand),
        ("*#1001*74##", OWNCommand),
    ],
)
def test_other_who_1001_shapes_have_no_mask(frame: str, expected_class: type) -> None:
    message = OWNMessage.parse(frame)

    assert type(message) is expected_class
    assert message.who == 1001
    if isinstance(message, OWNLightingDiagnosticEvent):
        assert message.diagnostic_mask is None
        assert message.cleared_bits is None
        assert "autodiagnostic" not in message.human_readable_log


@pytest.mark.parametrize(
    "frame",
    [
        "*#1001*74*11*1011#1##",  # a parameter inside the value
        "*#1001*74*11*10x1##",  # not digits: no OpenWebNet frame at all
    ],
)
def test_malformed_who_1001_frames_do_not_parse(frame: str) -> None:
    assert OWNMessage.parse(frame) is None


def test_who_1001_status_request_is_not_a_diagnostic_event() -> None:
    request = OWNMessage.parse("*#1001*74##")

    assert type(request) is OWNCommand
    assert not isinstance(request, OWNLightingDiagnosticEvent)
    assert request.who == 1001
