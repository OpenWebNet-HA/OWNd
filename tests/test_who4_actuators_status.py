"""``OWNHeatingCommand.actuators_status`` builds DIMENSION 20 (``*#4*WHERE*20##``).

A live F461 2.0.11 (2026-10-23, MyHOME#799 ``f461_live_2026-10-23`` run 1)
answers ``*#4*2*20##`` with ``*#4*2#1*20*0##`` on the command session and
``*#4*2#2*20*5##`` on the event session, one frame per actuator, and
``*#4*#0*20##`` with both on the command session. A live MyHomeServer1
3.87.13 (MyHOME#799 ``myhomeserver1_live_2026-10-24`` run 2) answers
``*#4*35*20##`` with ``*#4*35#1*20*0##``.

Dimension 20 values (WHO 4 spec, ``OWNHeatingEvent``): 0 off, 1 on, 2 opened,
3 closed, 4 stop, 5 fan coil off, 6-8 fan speeds, 9 fan auto;
``_actuator_active_states`` is ``1, 2, 6, 7, 8, 9``, so value 5 is inactive.
"""

from __future__ import annotations

import re

import pytest

from OWNd.message import OWNHeatingCommand, OWNHeatingEvent, OWNMessage

# WHO 4 DIMENSION 22 crashes the gateway's thermoregulation daemon; the
# builder must not let an address smuggle it in.
_DIMENSION_22 = re.compile(r"\*#4\*[^*]*\*#?0*22(?:[#*]|$)")


@pytest.mark.parametrize(
    ("where", "frame"),
    [
        ("2", "*#4*2*20##"),
        (2, "*#4*2*20##"),
        ("#2", "*#4*#2*20##"),
        ("2#1", "*#4*2#1*20##"),
        ("#0", "*#4*#0*20##"),
        ("#0#1", "*#4*#0#1*20##"),
        # ``#Z#N``: actuator N of zone Z addressed through the central unit
        # (WHO 4 WHERE table; ``_normalize_zone`` documents ``#Z#C``). Accepted
        # on purpose; not seen live (the plant has no central unit).
        ("#2#1", "*#4*#2#1*20##"),
        ("22", "*#4*22*20##"),
    ],
)
def test_actuators_status_builds_dimension_20(where: str | int, frame: str) -> None:
    command = OWNHeatingCommand.actuators_status(where)

    assert str(command) == frame
    assert command.is_dimension_request
    assert command.dimension == 20
    assert _DIMENSION_22.search(str(command)) is None

    parsed = OWNMessage.parse(frame)
    assert isinstance(parsed, OWNHeatingCommand)
    assert str(parsed) == frame
    assert parsed.dimension == 20
    assert parsed.where == command.where


@pytest.mark.parametrize(
    "where",
    ["", " ", "2*22", "2*22#", "#0*22", "2##", "*", "a", "##0", "2#1#4", "٢", None],
)
def test_actuators_status_refuses_bad_addresses(where: object) -> None:
    with pytest.raises(ValueError):
        OWNHeatingCommand.actuators_status(where)  # type: ignore[arg-type]


@pytest.mark.parametrize(
    ("reply", "actuator", "active", "fan_on"),
    [
        ("*#4*2#1*20*0##", "1", False, None),
        # value 5 = fan coil OFF: ``_fan_mode = 5 - 5 = 0`` -> fan_on False,
        # is_active False (master behaviour, pinned unchanged).
        ("*#4*2#2*20*5##", "2", False, False),
        ("*#4*35#1*20*0##", "1", False, None),
    ],
)
def test_actuators_status_replies_from_the_f461(
    reply: str, actuator: str, active: bool, fan_on: bool | None
) -> None:
    event = OWNMessage.parse(reply)

    assert isinstance(event, OWNHeatingEvent)
    assert event.zone == int(reply.split("*")[2].split("#")[0])
    assert event._actuator == actuator
    assert event.is_active() is active
    assert event.fan_on is fan_on
