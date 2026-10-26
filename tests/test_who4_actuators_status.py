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

Bus-interface routed addresses (``Z#4#NN``, ``#Z#4#NN``, ``Z#N#4#NN``) are
accepted since the MyHOME#792 review as spec-legal grammar, not because any
firmware honours them: own-firmware-oracle#65 (``thermo-zone-requests``,
decoded ``scs_bus_hex``) shows the seven ``out`` images emit unrouted local-bus
queries (``$04A9023010`` / ``$004A9023010`` for local zone 2 on F450, F454,
F459, F460, F461, MyHomeServer1; ``$0499843110`` for local zone 4 actuator 1
on MH202 010024) instead of forwarding ``#4#NN`` across an F422, and F453,
F453AV, H4684, MH200, MH200N drop the frame. MyHOME#816 therefore withholds
``#4#NN`` WHO 4 status polls unless ``supports_interface_zone_requests`` is
``True``. The MH202 010024 daemon crashes on the dimensionless forms
``*#4*Z#N##`` (``N`` 1..9) and ``*#4*Z#4#01..09##``, which this builder never
emits: it only builds the dimension-20 form.
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
        # (WHO 4 WHERE table; ``_zone_address_and_name`` documents ``#Z#C``).
        # Accepted on purpose; not seen live (the plant has no central unit).
        ("#2#1", "*#4*#2#1*20##"),
        ("22", "*#4*22*20##"),
        # ``Z#0`` / ``0#0``: all actuators of a zone / of every zone
        # (Encyclopedia WHERE table; the forms F453, F453AV and MH200N put on
        # the SCS bus in own-firmware-oracle ``thermo-zone-requests``).
        ("2#0", "*#4*2#0*20##"),
        ("0#0", "*#4*0#0*20##"),
        ("0", "*#4*0*20##"),
        ("99", "*#4*99*20##"),
        ("#0#4", "*#4*#0#4*20##"),
        ("#99#9", "*#4*#99#9*20##"),
        ("01", "*#4*01*20##"),
        # Bus-interface routed forms (``#4#NN``, two-digit interface): zone,
        # zone through the central unit, one actuator of a zone.
        ("3#4#01", "*#4*3#4#01*20##"),
        (" 3#4#01 ", "*#4*3#4#01*20##"),
        ("#3#4#01", "*#4*#3#4#01*20##"),
        ("2#1#4#01", "*#4*2#1#4#01*20##"),
        ("12#4#15", "*#4*12#4#15*20##"),
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
    # ``where`` keeps only the token before the first ``#``; the actuator
    # and interface tokens live in ``where_param`` and must round-trip too.
    assert parsed.where_param == command.where_param
    assert command.human_readable_log == (
        f"Requesting climate actuator status update for {str(where).strip()}."
    )


@pytest.mark.parametrize(
    "where",
    [
        "",
        " ",
        "2*22",
        "2*22#",
        "#0*22",
        "2##",
        "*",
        "a",
        "##0",
        "2#1#4",
        "٢",
        None,
        # Zones are 0..99: three digits address a secondary probe (``PZZ``,
        # no actuators, NACK on an F461) or nothing at all.
        "105",
        "101",
        "899",
        "001",
        "99999",
        "#105",
        "105#4#01",
        # A 4-zone central unit has zones 1..4; ``#0#0`` is not an address.
        "#0#0",
        "#0#5",
        "#0#9",
        "#01",
        "#00",
        # The actuator index is one digit (``0..9``).
        "2#10",
        "2#999",
        "#0#10",
        "2#10#4#01",
        # ``bool`` is an ``int`` subclass; negative numbers are not zones.
        True,
        False,
        -1,
        # Routing suffix: the interface is exactly two digits after ``#4#``.
        "3#4#1",
        "3#4#001",
        "#3#4#1",
        "#3#4#001",
        "2#1#4#1",
        "2#1#4#001",
        "3#4#",
        "3#4#0a",
        "3#4#01#",
        "3#3#01",
        "3#4#01#4#01",
        "3#4#01*22",
        "*#4#01",
    ],
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
