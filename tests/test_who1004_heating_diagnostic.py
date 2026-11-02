"""WHO 1004: thermoregulation autodiagnostic masks, fault counts and requests.

The physical frames are the three WHO 1004 frames an H/L4684 6.0.11 with a
3550 central unit pushed once the F430/4 channel ``66#1`` of zone 66 came
back online (MyHOME#839, fixture ``tests/fixtures/traces/issue_466/
myhome_trace_HL4684_all_2026-11-01T11-30-19.json``, 11:29:57Z-11:29:58Z):
``*#1004*66*11*111111111111111111111111##`` (master probe 66, 24-bit mask),
``*#1004*#66*22*1111111111111111##`` (zone 66, 16-bit mask) and
``*#1004*#0*11*111111111111111111111111##`` (central unit, 24-bit mask).
The WHERE grammar is ``OPN_ThermoWhereTransl`` (``libwhere.so``), the
dimensions follow ``libdiag.so`` and the Encyclopedia Machine KB
(``ownkb:chunk:r000204``-``r000209``, ``ownkb:claim:c004423``,
``ownkb:claim:c004429``-``c004448``). No WHO 1004 frame is in the firmware
oracle index; the bit meanings are not interpreted. The frames below are
test inputs only: nothing here reaches a gateway.
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

MASK24 = "111111111111111111111111"
MASK16 = "1111111111111111"
PROBE_FRAME = f"*#1004*66*11*{MASK24}##"
ZONE_FRAME = f"*#1004*#66*22*{MASK16}##"
CENTRAL_FRAME = f"*#1004*#0*11*{MASK24}##"
PHYSICAL_FRAMES = (PROBE_FRAME, ZONE_FRAME, CENTRAL_FRAME)


def _assert_nothing_decoded(message: OWNHeatingDiagnosticEvent) -> None:
    assert message.diagnostic_mask is None
    assert message.cleared_bits is None
    assert message.has_fault is None
    assert message.non_responding_units is None
    assert message.faulty_units is None


@pytest.mark.parametrize(
    ("frame", "scope", "zone", "where", "mask", "subject"),
    [
        (PROBE_FRAME, "probe", 66, "66", MASK24, "Thermoregulation probe 66"),
        (ZONE_FRAME, "zone", 66, "#66", MASK16, "Thermoregulation zone 66"),
        (CENTRAL_FRAME, "central", None, "#0", MASK24, "Thermoregulation central unit #0"),
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
    assert message.probe_number is None
    assert message.actuator_number is None
    assert message.dimension_value == [mask]
    assert message.diagnostic_mask == mask
    assert message.cleared_bits == ()
    assert message.has_fault is False
    assert message.non_responding_units is None
    assert message.faulty_units is None
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

    zone = OWNMessage.parse("*#1004*#3*22*0111111111111110##")
    assert isinstance(zone, OWNHeatingDiagnosticEvent)
    assert zone.scope == "zone"
    assert zone.zone_number == 3
    assert zone.cleared_bits == (1, 16)
    assert zone.has_fault is True


@pytest.mark.parametrize(
    ("frame", "scope", "zone", "probe", "actuator", "subject"),
    [
        # OPN_ThermoWhereTransl: central unit, zone through the central unit,
        # master probe, slave probe NZZ, external probe N00, actuator Z#N.
        (f"*#1004*#0*7*{MASK24}##", "central", None, None, None, "Thermoregulation central unit #0"),
        (f"*#1004*#0#2*8*{MASK24}##", "central", None, None, None, "Thermoregulation central unit #0#2"),
        (f"*#1004*#0#01*12*{MASK24}##", "central", None, None, None, "Thermoregulation central unit #0#01"),
        (f"*#1004*#0#99*11*{MASK24}##", "central", None, None, None, "Thermoregulation central unit #0#99"),
        (f"*#1004*#1*21*{MASK16}##", "zone", 1, None, None, "Thermoregulation zone 1"),
        (f"*#1004*#99*22*{MASK16}##", "zone", 99, None, None, "Thermoregulation zone 99"),
        (f"*#1004*#66#2*21*{MASK16}##", "zone", 66, None, None, "Thermoregulation zone 66 of central unit 2"),
        (f"*#1004*#66#99*22*{MASK16}##", "zone", 66, None, None, "Thermoregulation zone 66 of central unit 99"),
        (f"*#1004*1*7*{MASK24}##", "probe", 1, None, None, "Thermoregulation probe 1"),
        (f"*#1004*99*12*{MASK24}##", "probe", 99, None, None, "Thermoregulation probe 99"),
        (f"*#1004*101*8*{MASK24}##", "slave_probe", 1, 1, None, "Thermoregulation zone 1 slave probe 1"),
        (f"*#1004*866*11*{MASK24}##", "slave_probe", 66, 8, None, "Thermoregulation zone 66 slave probe 8"),
        (f"*#1004*899*7*{MASK24}##", "slave_probe", 99, 8, None, "Thermoregulation zone 99 slave probe 8"),
        (f"*#1004*100*7*{MASK24}##", "external_probe", None, None, None, "Thermoregulation external probe 100"),
        (f"*#1004*900*11*{MASK24}##", "external_probe", None, None, None, "Thermoregulation external probe 900"),
        (f"*#1004*66#1*7*{MASK24}##", "actuator", 66, None, 1, "Thermoregulation zone 66 actuator 1"),
        (f"*#1004*1#9*12*{MASK24}##", "actuator", 1, None, 9, "Thermoregulation zone 1 actuator 9"),
    ],
)
def test_where_scopes(
    frame: str, scope: str, zone: int | None, probe: int | None, actuator: int | None, subject: str
) -> None:
    message = OWNMessage.parse(frame)
    assert isinstance(message, OWNHeatingDiagnosticEvent)
    assert message.scope == scope
    assert message.zone_number == zone
    assert message.probe_number == probe
    assert message.actuator_number == actuator
    assert message.diagnostic_mask is not None
    assert message.has_fault is False
    assert message.human_readable_log.startswith(f"{subject} autodiagnostic mask is ")
    # WHO 1004 is not in OWNMessage.interface: ``#0#2`` is a central unit, not a bus interface.
    assert message.interface is None


@pytest.mark.parametrize(
    ("frame", "unique_id"),
    [
        (f"*#1004*#0*11*{MASK24}##", "1004-#0"),
        (f"*#1004*#0#1*11*{MASK24}##", "1004-#0#1"),
        (f"*#1004*#0#2*11*{MASK24}##", "1004-#0#2"),
        (f"*#1004*#66*22*{MASK16}##", "1004-#66"),
        (f"*#1004*#66#2*22*{MASK16}##", "1004-#66#2"),
        (f"*#1004*66*11*{MASK24}##", "1004-66"),
        (f"*#1004*66#1*11*{MASK24}##", "1004-66#1"),
        (f"*#1004*166*11*{MASK24}##", "1004-166"),
        ("*#1004*#0#2*21##", "1004-#0#2"),
        ("*#1004*66#1*7##", "1004-66#1"),
        ("*#1004**11##", "1004"),
    ],
)
def test_unique_id_carries_the_full_where(frame: str, unique_id: str) -> None:
    """``_where_param`` is kept: ``#0`` / ``#0#1`` / ``#0#2``, ``#66`` / ``#66#2`` and ``66`` / ``66#1`` differ."""
    message = OWNMessage.parse(frame)
    assert isinstance(message, (OWNHeatingDiagnosticEvent, OWNHeatingDiagnosticCommand))
    assert message.unique_id == unique_id
    assert message.interface is None


def test_unique_id_distinguishes_central_units_zones_and_actuators() -> None:
    ids = {
        OWNMessage.parse(frame).unique_id
        for frame in (
            f"*#1004*#0*11*{MASK24}##",
            f"*#1004*#0#1*11*{MASK24}##",
            f"*#1004*#0#2*11*{MASK24}##",
            f"*#1004*#66*22*{MASK16}##",
            f"*#1004*#66#2*22*{MASK16}##",
            f"*#1004*66*11*{MASK24}##",
            f"*#1004*66#1*11*{MASK24}##",
        )
    }
    assert len(ids) == 7


@pytest.mark.parametrize(
    "frame",
    [
        f"*#1004*0*11*{MASK24}##",  # zone 0 is no probe
        f"*#1004*066*11*{MASK24}##",  # leading zero
        f"*#1004*901*11*{MASK24}##",  # slave probe N is 1..8
        f"*#1004*1000*11*{MASK24}##",
        f"*#1004*66#0*11*{MASK24}##",  # actuator N is 1..9
        f"*#1004*66#10*11*{MASK24}##",
        f"*#1004*100#1*11*{MASK24}##",  # an external probe has no actuators
        f"*#1004*#100*22*{MASK16}##",
        f"*#1004*#00*11*{MASK24}##",  # #00 names no central unit
        f"*#1004*#0#0*11*{MASK24}##",
        f"*#1004*#0#100*11*{MASK24}##",
        f"*#1004*#66#0*22*{MASK16}##",
        f"*#1004*#66#1#2*22*{MASK16}##",  # too many parameters
        f"*#1004*66#1#2*11*{MASK24}##",
        f"*#1004**11*{MASK24}##",  # empty WHERE
    ],
)
def test_unrecognized_where_fails_closed(frame: str) -> None:
    message = OWNMessage.parse(frame)
    assert isinstance(message, OWNHeatingDiagnosticEvent)
    assert message.scope is None
    assert message.zone_number is None
    assert message.probe_number is None
    assert message.actuator_number is None
    _assert_nothing_decoded(message)
    assert message.human_readable_log == frame


@pytest.mark.parametrize(
    "frame",
    [
        f"*#1004*66*11*{MASK16}##",  # 16 bits on DIMENSION 11
        f"*#1004*66*8*{MASK16}##",  # 16 bits on DIMENSION 8
        f"*#1004*#66*22*{MASK24}##",  # 24 bits on DIMENSION 22
        f"*#1004*#66*21*{MASK24}##",  # 24 bits on DIMENSION 21
        f"*#1004*66*11*{MASK24}*5##",  # a trailing value
        "*#1004*66*11*111111111111111111111112##",  # not binary
        "*#1004*66*11*1##",
        "*#1004*66*11*##",
        f"*#1004*66*13*{MASK24}##",  # DIMENSION 13 is a generic device id, raw only
        f"*#1004*#0*20*{MASK16}##",  # DIMENSION 20 is a request-only trigger
        f"*#1004*#0*20*{MASK24}##",
        f"*#1004*66*0*{MASK24}##",
        # A mask dimension the scope does not report.
        f"*#1004*66*21*{MASK16}##",  # 16-bit zone masks only on #Z
        f"*#1004*66*22*{MASK16}##",
        f"*#1004*#0*21*{MASK16}##",  # #0 is a central unit, not a zone
        f"*#1004*#0*22*{MASK16}##",
        f"*#1004*#0#2*22*{MASK16}##",
        f"*#1004*66#1*22*{MASK16}##",
        f"*#1004*#66*7*{MASK24}##",  # 24-bit device masks never on #Z
        f"*#1004*#66*8*{MASK24}##",
        f"*#1004*#66*11*{MASK24}##",
        f"*#1004*#66*12*{MASK24}##",
    ],
)
def test_other_value_shapes_have_no_mask(frame: str) -> None:
    message = OWNMessage.parse(frame)
    assert isinstance(message, OWNHeatingDiagnosticEvent)
    assert message.who == 1004
    assert message.scope is not None
    _assert_nothing_decoded(message)
    assert message.dimension_value == frame[:-2].split("*")[4:]
    assert message.human_readable_log == frame


@pytest.mark.parametrize("dimension", [7, 8, 11, 12])
@pytest.mark.parametrize(
    ("where", "scope"),
    [("#0", "central"), ("#0#2", "central"), ("66", "probe"), ("166", "slave_probe"), ("100", "external_probe"), ("66#1", "actuator")],
)
def test_24_bit_masks_on_the_central_unit_and_addressed_devices(dimension: int, where: str, scope: str) -> None:
    message = OWNMessage.parse(f"*#1004*{where}*{dimension}*111111111111111111111110##")
    assert isinstance(message, OWNHeatingDiagnosticEvent)
    assert message.scope == scope
    assert message.diagnostic_mask == "111111111111111111111110"
    assert message.cleared_bits == (24,)
    assert message.has_fault is True


@pytest.mark.parametrize("dimension", [21, 22])
@pytest.mark.parametrize("where", ["#1", "#66", "#99", "#66#2"])
def test_16_bit_masks_on_a_zone(dimension: int, where: str) -> None:
    message = OWNMessage.parse(f"*#1004*{where}*{dimension}*1111111111111110##")
    assert isinstance(message, OWNHeatingDiagnosticEvent)
    assert message.scope == "zone"
    assert message.diagnostic_mask == "1111111111111110"
    assert message.cleared_bits == (16,)
    assert message.has_fault is True


@pytest.mark.parametrize(
    ("frame", "non_responding", "faulty", "log"),
    [
        (
            "*#1004*#0*23*0*0##",
            0,
            0,
            "Thermoregulation central unit #0 reports 0 non-responding unit(s) and 0 faulty unit(s).",
        ),
        (
            "*#1004*#0*23*2*1##",
            2,
            1,
            "Thermoregulation central unit #0 reports 2 non-responding unit(s) and 1 faulty unit(s).",
        ),
        (
            "*#1004*#0#2*23*12*105##",
            12,
            105,
            "Thermoregulation central unit #0#2 reports 12 non-responding unit(s) and 105 faulty unit(s).",
        ),
    ],
)
def test_dimension_23_fault_counts(frame: str, non_responding: int, faulty: int, log: str) -> None:
    message = OWNMessage.parse(frame)
    assert isinstance(message, OWNHeatingDiagnosticEvent)
    assert message.scope == "central"
    assert message.zone_number is None
    assert message.non_responding_units == non_responding
    assert message.faulty_units == faulty
    assert message.diagnostic_mask is None
    assert message.has_fault is None
    assert message.human_readable_log == log


@pytest.mark.parametrize(
    "frame",
    [
        "*#1004*#0*23*2##",  # one value
        "*#1004*#0*23*2*1*0##",  # three values
        "*#1004*#0*23*##",
        "*#1004*#0*23**1##",  # an empty count
        "*#1004*#0*23*2*1*##",  # a trailing empty value
        "*#1004*66*23*2*1##",  # DIMENSION 23 of a probe is not the summary
        "*#1004*#66*23*2*1##",  # nor of a zone
        "*#1004*66#1*23*2*1##",
    ],
)
def test_dimension_23_other_shapes_have_no_counts(frame: str) -> None:
    message = OWNMessage.parse(frame)
    assert isinstance(message, OWNHeatingDiagnosticEvent)
    _assert_nothing_decoded(message)
    assert message.human_readable_log == frame


def test_status_shaped_who_1004_frame_has_nothing_decoded() -> None:
    message = OWNMessage.parse("*1004*4*66##")
    assert isinstance(message, OWNHeatingDiagnosticEvent)
    assert message.scope == "probe"
    assert message.zone_number == 66
    _assert_nothing_decoded(message)
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
    for frame in ("*#1004*66*7##", "*#1004*#0*21##", "*#1004*#66*21##", "*#1004*#0*23##", "*#1004*66##"):
        message = OWNMessage.parse(frame)
        assert type(message) is OWNHeatingDiagnosticCommand, frame
        assert isinstance(message, OWNCommand)
        assert not isinstance(message, OWNHeatingDiagnosticEvent)
        assert message.who == 1004
        assert OWNCommand.parse(frame).__class__ is OWNHeatingDiagnosticCommand


@pytest.mark.parametrize(
    ("kwargs", "frame", "log"),
    [
        (
            {},
            "*#1004*#0*7##",
            "Requesting autodiagnostic mask (dimension 7) of thermoregulation central unit #0.",
        ),
        ({"dimension": 8}, "*#1004*#0*8##", "Requesting autodiagnostic mask (dimension 8) of thermoregulation central unit #0."),
        (
            {"where": "#0#2", "dimension": 11},
            "*#1004*#0#2*11##",
            "Requesting autodiagnostic mask (dimension 11) of thermoregulation central unit #0#2.",
        ),
        ({"where": " #0 ", "dimension": "12"}, "*#1004*#0*12##", "Requesting autodiagnostic mask (dimension 12) of thermoregulation central unit #0."),
        ({"where": "#0#01"}, "*#1004*#0#01*7##", "Requesting autodiagnostic mask (dimension 7) of thermoregulation central unit #0#01."),
    ],
)
def test_request_central_diagnostic(kwargs: dict[str, object], frame: str, log: str) -> None:
    command = OWNHeatingDiagnosticCommand.request_central_diagnostic(**kwargs)  # type: ignore[arg-type]
    assert isinstance(command, OWNHeatingDiagnosticCommand)
    assert str(command) == frame
    assert command.human_readable_log == log
    assert command.is_valid
    assert OWNMessage.parse(frame).unique_id == command.unique_id


@pytest.mark.parametrize(
    ("where", "kwargs", "frame", "log"),
    [
        (66, {}, "*#1004*66*7##", "Requesting autodiagnostic mask (dimension 7) of thermoregulation device 66."),
        ("1", {"dimension": 8}, "*#1004*1*8##", "Requesting autodiagnostic mask (dimension 8) of thermoregulation device 1."),
        (" 99 ", {"dimension": 11}, "*#1004*99*11##", "Requesting autodiagnostic mask (dimension 11) of thermoregulation device 99."),
        (101, {"dimension": "12"}, "*#1004*101*12##", "Requesting autodiagnostic mask (dimension 12) of thermoregulation device 101."),
        ("899", {}, "*#1004*899*7##", "Requesting autodiagnostic mask (dimension 7) of thermoregulation device 899."),
        (100, {}, "*#1004*100*7##", "Requesting autodiagnostic mask (dimension 7) of thermoregulation device 100."),
        ("900", {}, "*#1004*900*7##", "Requesting autodiagnostic mask (dimension 7) of thermoregulation device 900."),
        ("66#1", {"dimension": 11}, "*#1004*66#1*11##", "Requesting autodiagnostic mask (dimension 11) of thermoregulation device 66#1."),
        ("1#9", {}, "*#1004*1#9*7##", "Requesting autodiagnostic mask (dimension 7) of thermoregulation device 1#9."),
    ],
)
def test_request_device_diagnostic(where: int | str, kwargs: dict[str, object], frame: str, log: str) -> None:
    command = OWNHeatingDiagnosticCommand.request_device_diagnostic(where, **kwargs)  # type: ignore[arg-type]
    assert isinstance(command, OWNHeatingDiagnosticCommand)
    assert str(command) == frame
    assert command.human_readable_log == log
    assert command.is_valid
    # The request matches the reply the device would push for the same address.
    assert OWNMessage.parse(frame).unique_id == command.unique_id


@pytest.mark.parametrize(
    "where",
    [0, 1000, -1, "066", "#0", "#0#1", "#66", "#66#2", "66#0", "66#10", "100#1", "901", "", " ", None, "x", 1.5, True, False, b"66"],
)
def test_request_device_diagnostic_rejects_non_device_addresses(where: object) -> None:
    with pytest.raises(ValueError, match="Device diagnostic request needs a device address Z, NZZ, N00 or Z#N"):
        OWNHeatingDiagnosticCommand.request_device_diagnostic(where)  # type: ignore[arg-type]


def test_request_device_diagnostic_rejects_the_zone_zero_of_an_external_probe_shape() -> None:
    # 100, 200, ... 900 are external probes; 0 is nothing.
    for where in ("0", "000", "00"):
        with pytest.raises(ValueError):
            OWNHeatingDiagnosticCommand.request_device_diagnostic(where)


@pytest.mark.parametrize("dimension", [0, 6, 9, 10, 13, 20, 21, 22, 23, -7, "x", "", None, 7.0, 1.5, True, False, [7]])
def test_builders_reject_dimensions_libdiag_does_not_register(dimension: object) -> None:
    with pytest.raises(ValueError, match="Central unit diagnostic request needs a dimension of 7, 8, 11 or 12"):
        OWNHeatingDiagnosticCommand.request_central_diagnostic(dimension=dimension)  # type: ignore[arg-type]
    with pytest.raises(ValueError, match="Device diagnostic request needs a dimension of 7, 8, 11 or 12"):
        OWNHeatingDiagnosticCommand.request_device_diagnostic(66, dimension=dimension)  # type: ignore[arg-type]


def test_central_requests() -> None:
    assert str(OWNHeatingDiagnosticCommand.request_zones_with_failures()) == "*#1004*#0*20##"
    assert str(OWNHeatingDiagnosticCommand.request_zones_with_failures("#0#2")) == "*#1004*#0#2*20##"
    assert str(OWNHeatingDiagnosticCommand.request_fault_counts()) == "*#1004*#0*23##"
    assert str(OWNHeatingDiagnosticCommand.request_fault_counts(" #0#01 ")) == "*#1004*#0#01*23##"
    assert OWNHeatingDiagnosticCommand.request_zones_with_failures().human_readable_log == (
        "Requesting zones with failures of thermoregulation central unit #0."
    )
    assert OWNHeatingDiagnosticCommand.request_fault_counts("#0#2").human_readable_log == (
        "Requesting fault counts of thermoregulation central unit #0#2."
    )
    for command in (
        OWNHeatingDiagnosticCommand.request_zones_with_failures(),
        OWNHeatingDiagnosticCommand.request_fault_counts(),
    ):
        assert isinstance(command, OWNHeatingDiagnosticCommand)
        assert command.is_valid
        assert OWNCommand.parse(str(command)).__class__ is OWNHeatingDiagnosticCommand
    # The reply to *23## comes back on the same unique_id.
    assert OWNMessage.parse("*#1004*#0#2*23*0*0##").unique_id == (
        OWNHeatingDiagnosticCommand.request_fault_counts("#0#2").unique_id
    )


@pytest.mark.parametrize("where", ["0", "66", "#66", "#66#1", "#00", "#0#0", "#0#100", "66#1", "", None, 0, True])
def test_central_requests_reject_non_central_addresses(where: object) -> None:
    with pytest.raises(ValueError, match="Central unit diagnostic request needs a central unit address"):
        OWNHeatingDiagnosticCommand.request_central_diagnostic(where)  # type: ignore[arg-type]
    with pytest.raises(ValueError, match="Zones with failures request needs a central unit address"):
        OWNHeatingDiagnosticCommand.request_zones_with_failures(where)  # type: ignore[arg-type]
    with pytest.raises(ValueError, match="Fault counts request needs a central unit address"):
        OWNHeatingDiagnosticCommand.request_fault_counts(where)  # type: ignore[arg-type]


@pytest.mark.parametrize(
    ("where", "frame", "log"),
    [
        ("#0", "*#1004*#0*21##", "Requesting zone autodiagnostic mask of thermoregulation #0."),
        ("#0#2", "*#1004*#0#2*21##", "Requesting zone autodiagnostic mask of thermoregulation #0#2."),
        (66, "*#1004*#66*21##", "Requesting zone autodiagnostic mask of thermoregulation #66."),
        ("1", "*#1004*#1*21##", "Requesting zone autodiagnostic mask of thermoregulation #1."),
        (" 99 ", "*#1004*#99*21##", "Requesting zone autodiagnostic mask of thermoregulation #99."),
        ("#66", "*#1004*#66*21##", "Requesting zone autodiagnostic mask of thermoregulation #66."),
        ("#66#2", "*#1004*#66#2*21##", "Requesting zone autodiagnostic mask of thermoregulation #66#2."),
        (" #1#99 ", "*#1004*#1#99*21##", "Requesting zone autodiagnostic mask of thermoregulation #1#99."),
    ],
)
def test_request_zone_diagnostic(where: int | str, frame: str, log: str) -> None:
    command = OWNHeatingDiagnosticCommand.request_zone_diagnostic(where)
    assert isinstance(command, OWNHeatingDiagnosticCommand)
    assert str(command) == frame
    assert command.human_readable_log == log
    assert command.is_valid
    assert OWNCommand.parse(frame).__class__ is OWNHeatingDiagnosticCommand
    # The 16-bit reply of the zone comes back on the same unique_id.
    assert OWNMessage.parse(frame.replace("*21##", f"*21*{MASK16}##")).unique_id == command.unique_id


def test_request_zone_diagnostic_defaults_to_the_central_unit() -> None:
    assert str(OWNHeatingDiagnosticCommand.request_zone_diagnostic()) == "*#1004*#0*21##"


@pytest.mark.parametrize(
    "where",
    [0, 100, -1, "0", "066", "#00", "#0#0", "#0#100", "#100", "#066", "#66#0", "#66#1#2", "66#1", "101", "100", "##66", "", " ", None, "x", 1.5, True, False],
)
def test_request_zone_diagnostic_rejects_other_addresses(where: object) -> None:
    with pytest.raises(ValueError, match=r"Zone diagnostic request needs '#0', '#0#C', a zone 1..99, '#Z' or '#Z#C'"):
        OWNHeatingDiagnosticCommand.request_zone_diagnostic(where)  # type: ignore[arg-type]


def test_no_builder_emits_a_dimension_22_request() -> None:
    """``libdiag.so`` registers no ``R22P0``: DIMENSION 22 is pushed by the gateway only."""
    assert not hasattr(OWNHeatingDiagnosticCommand, "request_zone_actuator_diagnostic")
    builders = [
        OWNHeatingDiagnosticCommand.request_central_diagnostic(),
        OWNHeatingDiagnosticCommand.request_device_diagnostic(66),
        OWNHeatingDiagnosticCommand.request_zones_with_failures(),
        OWNHeatingDiagnosticCommand.request_zone_diagnostic(66),
        OWNHeatingDiagnosticCommand.request_fault_counts(),
    ]
    assert {str(b).rsplit("*", 1)[-1] for b in builders} == {"7##", "20##", "21##", "23##"}
    assert not any(str(b).endswith("*22##") for b in builders)


def test_who_1004_dimension_22_is_not_the_who_4_crash_guard() -> None:
    """``is_who4_dimension_22`` anchors on WHO 4: WHO 1004 DIMENSION 22 is a different frame."""
    assert not is_who4_dimension_22("*#1004*#66*22##")
    assert not is_who4_dimension_22(ZONE_FRAME)
    assert not is_who4_dimension_22(str(OWNHeatingDiagnosticCommand.request_zone_diagnostic(66)))
    # So OWNCommandSession.send, the transports and send_to_gateway would not refuse it.
    assert not is_who4_dimension_22_crash_form("*#1004*#66*22##")
    assert not is_who4_dimension_22_crash_form(ZONE_FRAME)
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
    assert OWNMessage.parse(f"*#1004*#0#2*11*{MASK24}##").interface is None
    assert OWNMessage.parse(f"*#1004*#66#2*22*{MASK16}##").interface is None
    assert OWNMessage.parse(f"*#1004*#0#2*11*{MASK24}##").event_content["where parameters"] == ["2"]
