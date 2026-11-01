"""WHO 1004: thermoregulation autodiagnostic masks, counts and requests.

The physical frames are the three WHO 1004 frames an H/L4684 6.0.11 with a
3550 central unit pushed once the F430/4 channel ``66#1`` of zone 66 came
back online (MyHOME#839, fixture ``tests/fixtures/traces/issue_466/
myhome_trace_HL4684_all_2026-11-01T11-30-19.json``, 11:29:57Z-11:29:58Z):
``*#1004*66*11*111111111111111111111111##`` (probe 66, 24-bit mask),
``*#1004*#66*22*1111111111111111##`` (zone 66 actuators, 16-bit mask) and
``*#1004*#0*11*111111111111111111111111##`` (central unit, 24-bit mask).
Scopes and dimensions follow the Encyclopedia Machine KB record
``kb_who_04_thermoregulation_diagnostics``. No WHO 1004 frame is in the
firmware oracle index; the bit meanings are not known, so nothing is
interpreted. The frames below are test inputs only: nothing here reaches a
gateway.
"""

from __future__ import annotations

import pytest

from OWNd.message import (
    OWNCommand,
    OWNEvent,
    OWNHeatingDiagnosticCommand,
    OWNHeatingDiagnosticEvent,
    OWNHeatingEvent,
    OWNMessage,
    is_who4_dimension_22,
    is_who4_dimension_22_crash_form,
)
import OWNd.message as message_pkg

PROBE_FRAME = "*#1004*66*11*111111111111111111111111##"
ZONE_ACTUATORS_FRAME = "*#1004*#66*22*1111111111111111##"
CENTRAL_FRAME = "*#1004*#0*11*111111111111111111111111##"
PHYSICAL_FRAMES = (PROBE_FRAME, ZONE_ACTUATORS_FRAME, CENTRAL_FRAME)


@pytest.mark.parametrize(
    ("frame", "scope", "zone", "where", "mask", "subject"),
    [
        (PROBE_FRAME, "probe", 66, "66", "111111111111111111111111", "Thermoregulation probe 66"),
        (
            ZONE_ACTUATORS_FRAME,
            "zone_actuators",
            66,
            "#66",
            "1111111111111111",
            "Thermoregulation zone 66 actuators",
        ),
        (CENTRAL_FRAME, "central", None, "#0", "111111111111111111111111", "Thermoregulation central unit #0"),
    ],
)
def test_physical_hl4684_frames_parse(
    frame: str, scope: str, zone: int | None, where: str, mask: str, subject: str
) -> None:
    message = OWNMessage.parse(frame)

    assert isinstance(message, OWNHeatingDiagnosticEvent)
    assert isinstance(message, OWNEvent)
    assert not isinstance(message, OWNHeatingEvent)
    assert message.who == 1004
    assert message.where == where
    assert message.scope == scope
    assert message.zone_number == zone
    assert message.dimension_value == [mask]
    assert message.diagnostic_mask == mask
    assert message.cleared_bits == ()
    assert message.has_fault is False
    assert message.slave_count is None
    assert message.faulty_zone is None
    assert message.unique_id == f"1004-{where}"
    assert message.interface is None
    assert message.is_general is False
    assert message.human_readable_log == (
        f"{subject} autodiagnostic mask is {mask} (cleared bits: none)."
    )


@pytest.mark.parametrize("frame", PHYSICAL_FRAMES)
def test_event_parse_and_message_parse_agree(frame: str) -> None:
    via_event = OWNEvent.parse(frame)
    via_message = OWNMessage.parse(frame)

    assert type(via_event) is OWNHeatingDiagnosticEvent
    assert type(via_message) is OWNHeatingDiagnosticEvent
    assert str(via_event) == str(via_message) == frame
    assert via_event.event_content == via_message.event_content


def test_cleared_bits_and_fault_flag() -> None:
    message = OWNMessage.parse("*#1004*66*11*111110111111111111110111##")
    assert isinstance(message, OWNHeatingDiagnosticEvent)
    assert message.diagnostic_mask == "111110111111111111110111"
    assert message.cleared_bits == (6, 21)
    assert message.has_fault is True
    assert message.human_readable_log.endswith("(cleared bits: 6, 21).")

    actuators = OWNMessage.parse("*#1004*#3*22*0111111111111110##")
    assert isinstance(actuators, OWNHeatingDiagnosticEvent)
    assert actuators.scope == "zone_actuators"
    assert actuators.zone_number == 3
    assert actuators.cleared_bits == (1, 16)
    assert actuators.has_fault is True


def test_dimension_8_slave_probe_mask_on_a_probe() -> None:
    message = OWNMessage.parse("*#1004*7*8*111111111111111111111110##")
    assert isinstance(message, OWNHeatingDiagnosticEvent)
    assert message.scope == "probe"
    assert message.zone_number == 7
    assert message.diagnostic_mask == "111111111111111111111110"
    assert message.cleared_bits == (24,)
    assert message.has_fault is True


@pytest.mark.parametrize(
    ("frame", "scope", "zone"),
    [
        # 4695 central unit 2 (``#0#C``) and zone 66 under it (``#Z#C``).
        ("*#1004*#0#2*11*111111111111111111111111##", "central", None),
        ("*#1004*#0#01*11*111111111111111111111111##", "central", None),
        ("*#1004*#66#2*22*1111111111111111##", "zone_actuators", 66),
        ("*#1004*#1*22*1111111111111111##", "zone_actuators", 1),
        ("*#1004*#99*22*1111111111111111##", "zone_actuators", 99),
        ("*#1004*1*11*111111111111111111111111##", "probe", 1),
        ("*#1004*99*11*111111111111111111111111##", "probe", 99),
    ],
)
def test_where_scopes(frame: str, scope: str, zone: int | None) -> None:
    message = OWNMessage.parse(frame)
    assert isinstance(message, OWNHeatingDiagnosticEvent)
    assert message.scope == scope
    assert message.zone_number == zone
    assert message.diagnostic_mask is not None
    # WHO 1004 is not in OWNMessage.interface: ``#0#2`` is a central unit, not a bus interface.
    assert message.interface is None
    assert message.unique_id == f"1004-{message.where}"


@pytest.mark.parametrize(
    "frame",
    [
        "*#1004*0*11*111111111111111111111111##",  # zone 0 is no probe
        "*#1004*066*11*111111111111111111111111##",  # leading zero
        "*#1004*100*11*111111111111111111111111##",  # three digits
        "*#1004*#100*22*1111111111111111##",
        "*#1004*#00*11*111111111111111111111111##",  # #00 names no central unit
        "*#1004*#0#0*11*111111111111111111111111##",
        "*#1004*#66#1#4*22*1111111111111111##",  # too many parameters
        "*#1004*66#1*11*111111111111111111111111##",  # a probe takes no parameter
        "*#1004**11*111111111111111111111111##",  # empty WHERE
    ],
)
def test_unrecognized_where_fails_closed(frame: str) -> None:
    message = OWNMessage.parse(frame)
    assert isinstance(message, OWNHeatingDiagnosticEvent)
    assert message.scope is None
    assert message.zone_number is None
    assert message.diagnostic_mask is None
    assert message.cleared_bits is None
    assert message.has_fault is None
    assert message.slave_count is None
    assert message.faulty_zone is None
    assert "autodiagnostic mask" not in message.human_readable_log


@pytest.mark.parametrize(
    "frame",
    [
        "*#1004*66*11*1111111111111111##",  # 16 bits on DIMENSION 11
        "*#1004*66*8*1111111111111111##",  # 16 bits on DIMENSION 8
        "*#1004*#66*22*111111111111111111111111##",  # 24 bits on DIMENSION 22
        "*#1004*66*11*111111111111111111111111*5##",  # a trailing value
        "*#1004*66*11*111111111111111111111112##",  # not binary
        "*#1004*66*11*1##",
        "*#1004*66*11*##",
        "*#1004*66*13*1##",  # local offset failure: raw only
        "*#1004*#0*20*111111111111111111111111##",  # zone failure summary: raw only
        "*#1004*#66*23*1##",  # per-actuator status: raw only
        "*#1004*66*0*111111111111111111111111##",
        # A mask dimension the scope does not report.
        "*#1004*66*22*1111111111111111##",  # DIMENSION 22 on a probe
        "*#1004*#0*22*1111111111111111##",  # DIMENSION 22 on the central unit
        "*#1004*#0*8*111111111111111111111111##",  # DIMENSION 8 on the central unit
        "*#1004*#66*11*111111111111111111111111##",  # DIMENSION 11 on zone actuators
    ],
)
def test_other_value_shapes_have_no_mask(frame: str) -> None:
    message = OWNMessage.parse(frame)
    assert isinstance(message, OWNHeatingDiagnosticEvent)
    assert message.who == 1004
    assert message.scope is not None
    assert message.diagnostic_mask is None
    assert message.cleared_bits is None
    assert message.has_fault is None
    assert message.slave_count is None
    assert message.faulty_zone is None
    assert message.dimension_value == frame[:-2].split("*")[4:]
    assert message.human_readable_log == frame


@pytest.mark.parametrize(("value", "count"), [("0", 0), ("3", 3), ("8", 8)])
def test_dimension_7_slave_count(value: str, count: int) -> None:
    message = OWNMessage.parse(f"*#1004*66*7*{value}##")
    assert isinstance(message, OWNHeatingDiagnosticEvent)
    assert message.scope == "probe"
    assert message.slave_count == count
    assert message.diagnostic_mask is None
    assert message.human_readable_log == f"Thermoregulation probe 66 has {count} slave probe(s)."


@pytest.mark.parametrize(
    "frame",
    [
        "*#1004*66*7*9##",  # above 8
        "*#1004*66*7*10##",
        "*#1004*66*7*##",
        "*#1004*66*7*3*1##",  # a trailing value
        "*#1004*#0*7*3##",  # DIMENSION 7 of a central unit is not a slave count
        "*#1004*#66*7*3##",
    ],
)
def test_dimension_7_other_shapes_have_no_slave_count(frame: str) -> None:
    message = OWNMessage.parse(frame)
    assert isinstance(message, OWNHeatingDiagnosticEvent)
    assert message.slave_count is None
    assert message.human_readable_log == frame


@pytest.mark.parametrize(
    ("frame", "zone", "log"),
    [
        ("*#1004*#0*21*0##", 0, "Thermoregulation central unit #0 reports no faulty zone."),
        ("*#1004*#0*21*5##", 5, "Thermoregulation central unit #0 reports faulty zone 5."),
        ("*#1004*#0#2*21*99##", 99, "Thermoregulation central unit #0#2 reports faulty zone 99."),
    ],
)
def test_dimension_21_faulty_zone(frame: str, zone: int, log: str) -> None:
    message = OWNMessage.parse(frame)
    assert isinstance(message, OWNHeatingDiagnosticEvent)
    assert message.scope == "central"
    assert message.zone_number is None
    assert message.faulty_zone == zone
    assert message.human_readable_log == log


@pytest.mark.parametrize(
    "frame",
    [
        "*#1004*#0*21*100##",
        "*#1004*#0*21*##",
        "*#1004*#0*21*5*1##",
        "*#1004*66*21*5##",  # DIMENSION 21 of a probe is not a faulty-zone report
        "*#1004*#66*21*5##",
    ],
)
def test_dimension_21_other_shapes_have_no_faulty_zone(frame: str) -> None:
    message = OWNMessage.parse(frame)
    assert isinstance(message, OWNHeatingDiagnosticEvent)
    assert message.faulty_zone is None
    assert message.human_readable_log == frame


def test_status_shaped_who_1004_frame_has_nothing_decoded() -> None:
    message = OWNMessage.parse("*1004*4*66##")
    assert isinstance(message, OWNHeatingDiagnosticEvent)
    assert message.scope == "probe"
    assert message.zone_number == 66
    assert message.diagnostic_mask is None
    assert message.has_fault is None
    assert message.human_readable_log == "*1004*4*66##"


@pytest.mark.parametrize(
    "frame",
    [
        "*#1004*66*11*1011#1##",  # a parameter inside the value
        "*#1004*66*11*10x1##",  # not digits: no OpenWebNet frame at all
    ],
)
def test_malformed_who_1004_frames_do_not_parse(frame: str) -> None:
    assert OWNMessage.parse(frame) is None


def test_requests_parse_as_diagnostic_commands_not_events() -> None:
    for frame in ("*#1004*66*11##", "*#1004*#0*21##", "*#1004*#66*22##", "*#1004*66##"):
        message = OWNMessage.parse(frame)
        assert type(message) is OWNHeatingDiagnosticCommand, frame
        assert isinstance(message, OWNCommand)
        assert not isinstance(message, OWNHeatingDiagnosticEvent)
        assert message.who == 1004
        assert OWNCommand.parse(frame).__class__ is OWNHeatingDiagnosticCommand


@pytest.mark.parametrize(
    ("builder", "zone", "frame", "log"),
    [
        (
            OWNHeatingDiagnosticCommand.request_probe_diagnostic,
            66,
            "*#1004*66*11##",
            "Requesting autodiagnostic mask of thermoregulation probe 66.",
        ),
        (
            OWNHeatingDiagnosticCommand.request_probe_diagnostic,
            "1",
            "*#1004*1*11##",
            "Requesting autodiagnostic mask of thermoregulation probe 1.",
        ),
        (
            OWNHeatingDiagnosticCommand.request_probe_slave_count,
            " 99 ",
            "*#1004*99*7##",
            "Requesting slave probe count of thermoregulation probe 99.",
        ),
        (
            OWNHeatingDiagnosticCommand.request_probe_slave_diagnostic,
            7,
            "*#1004*7*8##",
            "Requesting slave probe autodiagnostic mask of thermoregulation probe 7.",
        ),
        (
            OWNHeatingDiagnosticCommand.request_zone_actuator_diagnostic,
            66,
            "*#1004*#66*22##",
            "Requesting autodiagnostic mask of thermoregulation zone 66 actuators.",
        ),
        (
            OWNHeatingDiagnosticCommand.request_zone_actuator_diagnostic,
            "#66",
            "*#1004*#66*22##",
            "Requesting autodiagnostic mask of thermoregulation zone 66 actuators.",
        ),
        (
            OWNHeatingDiagnosticCommand.request_zone_actuator_diagnostic,
            "#1",
            "*#1004*#1*22##",
            "Requesting autodiagnostic mask of thermoregulation zone 1 actuators.",
        ),
    ],
)
def test_zone_builders(builder, zone: int | str, frame: str, log: str) -> None:  # type: ignore[no-untyped-def]
    command = builder(zone)
    assert isinstance(command, OWNHeatingDiagnosticCommand)
    assert str(command) == frame
    assert command.human_readable_log == log
    assert command.is_valid
    # The request matches the reply the H/L4684 pushed for the same address.
    assert OWNMessage.parse(frame).unique_id == command.unique_id


@pytest.mark.parametrize(
    "builder",
    [
        OWNHeatingDiagnosticCommand.request_probe_diagnostic,
        OWNHeatingDiagnosticCommand.request_probe_slave_count,
        OWNHeatingDiagnosticCommand.request_probe_slave_diagnostic,
    ],
)
@pytest.mark.parametrize("zone", [0, 100, -1, "066", "#0", "#66", "#0#1", "66#1", "", " ", None, "x", 1.5, True])
def test_probe_builders_reject_bad_zones(builder, zone: object) -> None:  # type: ignore[no-untyped-def]
    with pytest.raises(ValueError, match="needs a zone number between 1 and 99"):
        builder(zone)


@pytest.mark.parametrize("zone", [0, 100, "#0", "#00", "#100", "#066", "#66#1", "#0#1", "##66", "", None])
def test_zone_actuator_builder_rejects_bad_zones(zone: object) -> None:
    with pytest.raises(ValueError, match=r"needs a zone number between 1 and 99 \(as Z or #Z\)"):
        OWNHeatingDiagnosticCommand.request_zone_actuator_diagnostic(zone)  # type: ignore[arg-type]


def test_central_builders() -> None:
    assert str(OWNHeatingDiagnosticCommand.request_central_diagnostic()) == "*#1004*#0*11##"
    assert str(OWNHeatingDiagnosticCommand.request_central_diagnostic("#0#2")) == "*#1004*#0#2*11##"
    assert str(OWNHeatingDiagnosticCommand.request_central_diagnostic(" #0 ")) == "*#1004*#0*11##"
    assert str(OWNHeatingDiagnosticCommand.request_faulty_zones()) == "*#1004*#0*21##"
    assert str(OWNHeatingDiagnosticCommand.request_faulty_zones("#0#01")) == "*#1004*#0#01*21##"
    assert OWNHeatingDiagnosticCommand.request_central_diagnostic().human_readable_log == (
        "Requesting autodiagnostic mask of thermoregulation central unit #0."
    )
    assert OWNHeatingDiagnosticCommand.request_faulty_zones("#0#2").human_readable_log == (
        "Requesting faulty zones of thermoregulation central unit #0#2."
    )


@pytest.mark.parametrize("where", ["0", "66", "#66", "#66#1", "#00", "#0#0", "#0#100", "", None])
def test_central_builders_reject_non_central_addresses(where: object) -> None:
    with pytest.raises(ValueError, match="Central unit diagnostic request needs a central unit address"):
        OWNHeatingDiagnosticCommand.request_central_diagnostic(where)  # type: ignore[arg-type]
    with pytest.raises(ValueError, match="Faulty zones request needs a central unit address"):
        OWNHeatingDiagnosticCommand.request_faulty_zones(where)  # type: ignore[arg-type]


def test_who_1004_dimension_22_is_not_the_who_4_crash_guard() -> None:
    """``is_who4_dimension_22`` anchors on WHO 4: WHO 1004 DIMENSION 22 is a different frame."""
    assert not is_who4_dimension_22("*#1004*#66*22##")
    assert not is_who4_dimension_22("*#1004*#66*22*1111111111111111##")
    assert not is_who4_dimension_22(str(OWNHeatingDiagnosticCommand.request_zone_actuator_diagnostic(66)))
    # So OWNCommandSession.send, the transports and send_to_gateway would not refuse it.
    assert not is_who4_dimension_22_crash_form("*#1004*#66*22##")
    assert not is_who4_dimension_22_crash_form("*#1004*#66*22*1111111111111111##")
    assert not is_who4_dimension_22_crash_form(b"*#1004*#66*22##")
    # The WHO 4 spelling of the same address stays a crash form.
    assert is_who4_dimension_22("*#4*#66*22##")
    assert is_who4_dimension_22_crash_form("*#4*#66*22##")


def test_who_1004_is_registered_and_exported_but_not_an_interface_who() -> None:
    from OWNd.message.base import _COMMAND_DISPATCH, _EVENT_DISPATCH

    assert _EVENT_DISPATCH[1004] is OWNHeatingDiagnosticEvent
    assert _COMMAND_DISPATCH[1004] is OWNHeatingDiagnosticCommand
    assert "OWNHeatingDiagnosticEvent" in message_pkg.__all__
    assert "OWNHeatingDiagnosticCommand" in message_pkg.__all__
    # ``#0#2`` is central unit 2, not bus interface 2: WHO 1004 is not in OWNMessage.interface.
    assert OWNMessage.parse("*#1004*#0#2*11*111111111111111111111111##").interface is None
    assert OWNMessage.parse("*#1004*#66#2*22*1111111111111111##").interface is None
    assert OWNMessage.parse("*#1004*#0#2*11*111111111111111111111111##").event_content["where parameters"] == ["2"]
