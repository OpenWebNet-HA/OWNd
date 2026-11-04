"""The unpublished bare WHO 22 power frame is refused by the send layer; the published forms are not."""

from unittest.mock import AsyncMock, patch

import pytest

from OWNd.connection import OWNCommandSession, OWNGateway
from OWNd.exceptions import OWNProtocolError
from OWNd.message import OWNCommand, OWNSoundDiffusionCommand, is_who22_bare_power_frame
from OWNd.transport.serial import AsyncSerialTransport


@pytest.mark.parametrize(
    "frame",
    ["*22*1*2#1##", "*22*0*2#1##", "*22*1*3#1#1##", "*22*0*4#1##", "*22*1*6##", "*22*0*6##"],
)
def test_bare_power_frame_is_detected_on_every_target(frame: str) -> None:
    # Oracle suite sound-who22-bare-power: nack/crash on F453, F453AV, F454, F459, F460, F461,
    # MH200N and MyHomeServer1 for all of these (tests/golden/firmware_oracle.json).
    assert is_who22_bare_power_frame(frame) is True
    parsed = OWNCommand.parse(frame)  # the parser stays permissive
    assert parsed is not None
    assert is_who22_bare_power_frame(parsed) is True


@pytest.mark.parametrize(
    "frame",
    [
        "*22*1#4#1*2#1##",  # WHO 22 PDF 3.1.2: *22*1#<mmtype>#<area>*2#<sourceID>##
        "*22*0#4#1*2#1##",  # 3.1.1
        "*22*0#4#1*3#1#1##",  # 3.2.1, speaker target
        "*22*1#4#1*6##",
        "*22*34*3#1#1##",  # another WHAT
        "*22*10*3#1#1##",  # WHAT 10, not 1 followed by *
        "*#22*3#1#1*1##",  # a dimension request
        "*16*3*101##",  # WHO 16 power (what MyHOME sends), untouched
        "*22*1*##",  # empty WHERE
        "",
    ],
)
def test_other_frames_are_not_detected(frame: str) -> None:
    assert is_who22_bare_power_frame(frame) is False


def test_builders_are_unchanged_and_the_bare_form_is_detected() -> None:
    # The builders keep their frames; only the send layer refuses the bare form.
    on = OWNSoundDiffusionCommand.turn_on("2#1")
    off = OWNSoundDiffusionCommand.turn_off("6")
    assert str(on) == "*22*1*2#1##" and str(off) == "*22*0*6##"
    assert is_who22_bare_power_frame(on) and is_who22_bare_power_frame(off)
    published = [
        OWNSoundDiffusionCommand.turn_on_with_source("3#2#1", 1),
        OWNSoundDiffusionCommand.turn_off_atomic("3#2#1"),
        OWNSoundDiffusionCommand.route_source("3#2#1", 7),
    ]
    assert [str(m) for m in published] == ["*22*1#4#1*3#2#1##", "*22*0#4#0*3#2#1##", "*22*35#4#1#7*3#2#1##"]
    assert not any(is_who22_bare_power_frame(m) for m in published)


def _gateway() -> OWNGateway:
    return OWNGateway(
        {"address": "192.0.2.10", "port": 20000, "password": "12345", "modelName": "F461", "serialNumber": "x", "UDN": "x"}
    )


@pytest.mark.asyncio
@pytest.mark.parametrize("frame", ["*22*1*2#1##", "*22*0*6##"])
async def test_command_session_refuses_the_bare_frame_before_connecting(frame: str) -> None:
    session = OWNCommandSession(gateway=_gateway())
    assert await session.send(frame) is None
    assert isinstance(session._last_error, OWNProtocolError)
    assert session._last_error.reason == "destructive_frame"
    assert "WHO 22 power frame" in str(session._last_error)
    with pytest.raises(OWNProtocolError) as excinfo:
        await session.send(frame, raise_on_error=True)
    assert excinfo.value.reason == "destructive_frame"


@pytest.mark.asyncio
async def test_send_to_gateway_refuses_the_bare_builder_output() -> None:
    gateway = _gateway()
    message = OWNSoundDiffusionCommand.turn_on("2#1")
    with pytest.raises(OWNProtocolError) as excinfo:
        await OWNCommandSession.send_to_gateway(message, gateway, raise_on_error=True)
    assert excinfo.value.reason == "destructive_frame"
    assert await OWNCommandSession.send_to_gateway(message, gateway) is None


@pytest.mark.asyncio
@pytest.mark.parametrize("frame", ["*22*1#4#2*3#2#1##", "*22*0#4#2*3#2#1##"])
async def test_published_forms_pass_the_send_paths_guard(frame: str) -> None:
    # Mirrors the WHO 4 dimension 22 guard tests: no socket is opened, the send
    # paths are followed up to the write. A published form must reach _locked_send
    # (the guard let it through) and must never be recorded as a destructive refusal.
    session = OWNCommandSession(gateway=_gateway())
    with (
        patch.object(OWNCommandSession, "connect", new_callable=AsyncMock),
        patch.object(OWNCommandSession, "_locked_send", new_callable=AsyncMock, return_value=True) as locked_send,
    ):
        assert await session.send(frame) is True
        locked_send.assert_called_once()
        assert getattr(session._last_error, "reason", None) != "destructive_frame"

    message = OWNCommand.parse(frame)
    assert message is not None
    with (
        patch.object(OWNCommandSession, "connect", new_callable=AsyncMock),
        patch.object(OWNCommandSession, "_locked_send", new_callable=AsyncMock, return_value=True) as locked_send,
    ):
        assert await OWNCommandSession.send_to_gateway(message, _gateway(), raise_on_error=True) is True
        locked_send.assert_called_once()


class _Writer:
    def __init__(self) -> None:
        self.written: list[bytes] = []

    def write(self, data: bytes) -> None:
        self.written.append(data)

    async def drain(self) -> None:
        return None

    def close(self) -> None:
        return None


@pytest.mark.asyncio
async def test_serial_transport_refuses_the_bare_frame_and_keeps_the_who4_guard() -> None:
    transport = AsyncSerialTransport(port="/dev/null")
    writer = _Writer()
    transport._writer = writer  # type: ignore[assignment]
    transport._connected = True

    assert await transport.send("*22*1*2#1##") is None
    assert writer.written == []
    assert isinstance(transport.last_error, OWNProtocolError)
    assert transport.last_error.reason == "destructive_frame"
    assert "WHO 22 power frame" in str(transport.last_error)
    with pytest.raises(OWNProtocolError, match="WHO 22 power frame"):
        await transport.send(OWNSoundDiffusionCommand.turn_off("6"), raise_on_error=True)
    with pytest.raises(OWNProtocolError, match="dimension 22"):
        await transport.send("*#4*#0*22##", raise_on_error=True)
    assert writer.written == []
