"""WHO 13 value fields are ASCII digits only; clock values keep raising as before (OWNd#161 review).

``str.isdigit`` and ``int`` accept fullwidth digits, which are not on the bus
(Encyclopedia ``protocol/frame-syntax.md``). Dimensions 12 / 15 / 19 with such a
field now stay untyped (raw frame as log), as the Dimension 27 allowlist already
did; a fullwidth clock field raises the same ``ValueError`` as any malformed clock
value (#144: the sessions catch it). Every ASCII frame decodes exactly as before.
"""

from __future__ import annotations

import datetime

import pytest

from OWNd.message import OWNGatewayEvent, OWNMessage


@pytest.mark.parametrize(
    ("frame", "attribute"),
    [
        ("*#13**12*0*３*80*1*214*135##", "mac_address"),
        ("*#13**15*２３##", "device_type"),
        ("*#13**19*１*2*3*4##", "uptime"),
    ],
)
def test_fullwidth_digits_leave_the_dimension_untyped(frame: str, attribute: str) -> None:
    message = OWNMessage.parse(frame)
    assert isinstance(message, OWNGatewayEvent)
    assert getattr(message, attribute) is None
    assert message.human_readable_log == frame


@pytest.mark.parametrize(
    "frame",
    [
        "*#13**1*03*26*10*\uff12\uff10\uff12\uff16##",
        "*#13**#1*03*26*10*\uff12\uff10\uff12\uff16##",
        "*#13**0*\uff11\uff12*00*00*002##",
        "*#13**#0*\uff11\uff12*00*00*002##",
        "*#13**0*12*00*00*0\uff10\uff11##",
        "*#13**22*12*00*00*0\uff10\uff11*01*01*01*2026##",
        "*#13**22*\uff11\uff12*00*00*001*01*01*01*2026##",
        "*#13**22*12*00*00*001*01*01*01*\uff12\uff10\uff12\uff16##",
        "*#13**#22*12*00*00*001*01*\uff10\uff11*01*2026##",
    ],
)
def test_fullwidth_clock_fields_raise_the_malformed_clock_error(frame: str) -> None:
    with pytest.raises(ValueError, match="Invalid gateway (date|time|datetime|timezone)"):
        OWNMessage.parse(frame)


def test_ascii_frames_decode_as_before() -> None:
    assert OWNMessage.parse("*#13**12*0*3*80*1*214*135##").mac_address == "00:03:50:01:d6:87"
    assert OWNMessage.parse("*#13**15*23##").device_type == "H4684"
    assert OWNMessage.parse("*#13**15*200##").device_type.startswith("F454 /")
    assert OWNMessage.parse("*#13**19*1*2*3*4##").uptime == datetime.timedelta(days=1, hours=2, minutes=3, seconds=4)
    assert OWNMessage.parse("*#13**1*03*26*10*2026##").human_readable_log == "Gateway's internal date is: 2026-10-26."
    assert OWNMessage.parse("*#13**0*17*45*24*999##").human_readable_log == "Gateway's internal time is: 17:45:24."
    assert OWNMessage.parse("*#13**22*22*59*16*999*01*26*10*2026##").human_readable_log == "Gateway's internal datetime is: 2026-10-26 22:59:16."
    assert OWNMessage.parse("*#13**0*20*54*00*002##").timezone == "+02:00"


def test_ascii_non_digit_tokens_never_reach_the_decoder() -> None:
    """The frame grammar admits digit tokens only, so an ASCII letter or sign is no frame at all."""
    for frame in ("*#13**15*abc##", "*#13**19* 1*2*3*4##", "*#13**19*+1*2*3*4##"):
        assert OWNMessage.parse(frame) is None


def test_empty_tokens_do_not_raise() -> None:
    """Empty value tokens never raised on master (the review's cases 1-4); pinned so it stays that way."""
    for frame in ("*#13**12*0**80*1*214*135##", "*#13**19**0*0*0##", "*#13**15*##"):
        message = OWNMessage.parse(frame)
        assert isinstance(message, OWNGatewayEvent)
        assert message.human_readable_log == frame
    for frame in ("*#13**1**01*01*2026##", "*#13**22*12*00*00*001**01*01*2026##"):
        message = OWNMessage.parse(frame)
        assert isinstance(message, OWNGatewayEvent)  # the weekday field is not decoded
