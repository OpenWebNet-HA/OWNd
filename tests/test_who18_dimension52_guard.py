"""WHO 18 DIMENSION 52 with a four-digit year is refused by the send layer (crashes F460 / F461)."""

import pytest

from OWNd.connection import OWNCommandSession, OWNGateway
from OWNd.exceptions import OWNProtocolError
from OWNd.message import OWNCommand, is_who18_dimension_52_four_digit_year


@pytest.mark.parametrize(
    "frame",
    [
        "*#18*51*52#2026#10##",  # crash row, F460 / F461 (findings/audit-crash-frames.md)
        "*#18*51*52#2026#10*100##",  # value-field form, also a crash row
        "*#18*71#0*52#2026#1##",  # actuator WHERE, single-digit month
        "*#18*5255*52#2026#12##",
    ],
)
def test_four_digit_year_dimension_52_is_detected(frame: str) -> None:
    assert is_who18_dimension_52_four_digit_year(frame) is True
    parsed = OWNCommand.parse(frame)  # the parser stays permissive (decision D1)
    assert parsed is not None
    assert is_who18_dimension_52_four_digit_year(parsed) is True


@pytest.mark.parametrize(
    "frame",
    [
        "*#18*51*52#26#9##",  # two-digit year: the documented form, went out without a crash
        "*#18*51*52#26#9*100##",
        "*#18*51*51#2026##",  # other dimension
        "*#18*51*511#10#2##",  # dimension 511, not 52
        "*#4*2*22##",  # other WHO (its own guard)
        "*18*26*51##",  # a WHO 18 command, not a dimension request
        "*#18*51*52##",  # no parameters
        "",
    ],
)
def test_other_frames_are_not_detected(frame: str) -> None:
    assert is_who18_dimension_52_four_digit_year(frame) is False


def _gateway() -> OWNGateway:
    return OWNGateway(
        {"address": "192.0.2.10", "port": 20000, "password": "12345", "modelName": "F461", "serialNumber": "x", "UDN": "x"}
    )


@pytest.mark.asyncio
@pytest.mark.parametrize("frame", ["*#18*51*52#2026#10##", "*#18*51*52#2026#10*100##"])
async def test_command_session_refuses_four_digit_year_before_connecting(frame: str) -> None:
    # Mirrors the WHO 4 dimension 22 guard: refused in the send layer, never written, no socket opened.
    session = OWNCommandSession(gateway=_gateway())
    assert await session.send(frame) is None
    assert isinstance(session._last_error, OWNProtocolError)
    assert session._last_error.reason == "destructive_frame"
    assert "four-digit year" in str(session._last_error)
    with pytest.raises(OWNProtocolError) as excinfo:
        await session.send(frame, raise_on_error=True)
    assert excinfo.value.reason == "destructive_frame"


@pytest.mark.asyncio
async def test_send_to_gateway_refuses_four_digit_year_without_connecting() -> None:
    gateway = _gateway()
    message = OWNCommand.parse("*#18*51*52#2026#10##")
    assert message is not None
    with pytest.raises(OWNProtocolError) as excinfo:
        await OWNCommandSession.send_to_gateway(message, gateway, raise_on_error=True)
    assert excinfo.value.reason == "destructive_frame"
    assert await OWNCommandSession.send_to_gateway(message, gateway) is None


@pytest.mark.asyncio
async def test_two_digit_year_is_not_refused_by_the_guard() -> None:
    # The documented form is not a destructive frame; the guard must not touch it
    # (it may still fail later for want of a real gateway, which is not a refusal).
    session = OWNCommandSession(gateway=_gateway())
    assert is_who18_dimension_52_four_digit_year("*#18*51*52#26#9##") is False
    assert session._last_error is None
