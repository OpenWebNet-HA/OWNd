"""WHO 13 clock echoes and replies with timezone values OWNd cannot map.

own-firmware-oracle ``who13-clock``: ``*#13**#0*14*30*00*0530##`` is ACKed and
echoed on the event session by F450, F453, F453AV, F460, F461, H4684, MH200,
MH200N and MH202 (F454 and F459 NACK it; MyHomeServer1 is silent);
``…*124##`` is ACKed by those nine plus F454 (no echo) and F459.
``who13-clock-readback``: the F450 reports the stored ``0530`` on later reads.
OWNd raised ``ValueError`` on both; the exception left the event session.

The values' layout and meaning are unverified, so ``timezone`` is ``None``
(unknown), never ``""`` (local time); ``raw_timezone`` keeps the value. The
accepted classes are bounded: a four-digit value with a sign digit
(``0000``..``1999``), and ``124``..``199`` (the first negative offset
``datetime.timezone`` cannot hold is ``-24:00``). Only ``0530`` and ``124``
were measured. MyHOME ``tests/test_gateway_regressions.py``
requires ``099`` and ``200`` to stay invalid.
"""

from __future__ import annotations

import datetime as dt

import pytest

from OWNd.message import OWNGatewayCommand, OWNGatewayEvent, OWNMessage


@pytest.mark.parametrize(
    ("frame", "raw_timezone"),
    [
        ("*#13**#0*14*30*00*0530##", "0530"),
        ("*#13**#0*14*30*00*124##", "124"),
        ("*#13**#22*14*30*00*0530*03*21*10*2026##", "0530"),
        ("*#13**#22*14*30*00*124*03*21*10*2026##", "124"),
    ],
)
def test_clock_echo_with_unmapped_timezone_parses(frame: str, raw_timezone: str) -> None:
    message = OWNMessage.parse(frame)

    assert isinstance(message, OWNGatewayCommand)
    assert message.raw_timezone == raw_timezone
    assert message.timezone is None
    assert message.is_timezone_unconfigured is False
    assert message.time is not None
    assert message.time.replace(tzinfo=None) == dt.time(14, 30, 0)
    assert message.time.tzinfo is None


def test_clock_echo_with_unmapped_timezone_keeps_the_date() -> None:
    message = OWNMessage.parse("*#13**#22*14*30*00*0530*03*21*10*2026##")

    assert isinstance(message, OWNGatewayCommand)
    assert message.date == dt.date(2026, 10, 21)
    assert message.datetime == dt.datetime(2026, 10, 21, 14, 30, 0)


@pytest.mark.parametrize("raw", ["0530", "124"])
def test_clock_reply_with_unmapped_timezone_parses(raw: str) -> None:
    """The F450 read-back of a stored ``0530`` (``who13-clock-readback``)."""
    message = OWNMessage.parse(f"*#13**0*14*30*00*{raw}##")

    assert isinstance(message, OWNGatewayEvent)
    assert message.raw_timezone == raw
    assert message.timezone is None
    assert message.time == dt.time(14, 30, 0)


@pytest.mark.parametrize("raw", ["0530", "124"])
def test_datetime_reply_with_unmapped_timezone_parses(raw: str) -> None:
    message = OWNMessage.parse(f"*#13**22*14*30*00*{raw}*03*21*10*2026##")

    assert isinstance(message, OWNGatewayEvent)
    assert message.timezone is None
    assert message.raw_timezone == raw
    assert message.datetime == dt.datetime(2026, 10, 21, 14, 30, 0)


@pytest.mark.parametrize("raw", ["0000", "1999", "1240", "125", "199"])
def test_same_classes_at_their_boundaries_are_unmapped(raw: str) -> None:
    """Members of the two classes that were not measured: still ``None``."""
    message = OWNMessage.parse(f"*#13**0*14*30*00*{raw}##")

    assert isinstance(message, OWNGatewayEvent)
    assert message.timezone is None


@pytest.mark.parametrize(
    "raw",
    [
        "200",  # MyHOME test_gateway_regressions: must stay invalid
        "099",  # MyHOME test_gateway_regressions: must stay invalid
        "024",  # +24:00 is not a datetime.timezone offset
        "2",
        "12",
        "2000",  # no sign digit
        "9999",
        "2400",
        "05300",  # five digits
        "00530",
    ],
)
def test_other_malformed_timezones_are_still_rejected(raw: str) -> None:
    with pytest.raises(ValueError):
        OWNMessage.parse(f"*#13**0*14*30*00*{raw}##")


@pytest.mark.parametrize(
    ("raw", "offset"),
    [
        ("000", "+00:00"),
        ("001", "+01:00"),
        ("002", "+02:00"),
        ("102", "-02:00"),
        ("013", "+13:00"),
        ("123", "-23:00"),  # the last offset datetime.timezone can hold
    ],
)
def test_whole_hour_timezones_still_decode(raw: str, offset: str) -> None:
    message = OWNMessage.parse(f"*#13**0*14*30*00*{raw}##")

    assert isinstance(message, OWNGatewayEvent)
    assert message.timezone == offset


@pytest.mark.parametrize("raw", ["999", ""])
def test_unset_timezone_is_still_local_time(raw: str) -> None:
    message = OWNMessage.parse(f"*#13**0*14*30*00*{raw}##")

    assert isinstance(message, OWNGatewayEvent)
    assert message.timezone == ""
    assert message.is_timezone_unconfigured is (raw == "999")
