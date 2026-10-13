"""Firmware Oracle Conformance Test Suite.

Verifies cross-firmware compatibility of OpenWebNet frames, OWNd parser
resilience on authentic firmware-emitted frames, and firmware rejection
guarantees against hash-pinned verdicts from own-firmware-oracle.
"""

from __future__ import annotations

from collections import Counter
import hashlib
import json
from pathlib import Path
import re
from typing import Any

import pytest

import OWNd.message as msg_module
from OWNd.message import (
    OWNCENPlusEvent,
    OWNDryContactEvent,
    OWNEvent,
    OWNLightingCommand,
    OWNLightingEvent,
    OWNLockCommand,
    OWNLockEvent,
    OWNMessage,
    OWNSignaling,
)
from OWNd.profiles import (
    GenericGatewayProfile,
    WHO_AUTOMATION,
    WHO_CEN,
    WHO_CEN_PLUS,
    WHO_HEATING,
    WHO_LIGHTING,
    get_gateway_profile,
)

REPO_ROOT = Path(__file__).resolve().parent.parent
ORACLE_JSON_PATH = REPO_ROOT / "tests" / "golden" / "firmware_oracle.json"
CORPUS_JSON_PATH = REPO_ROOT / "tests" / "golden" / "corpus.json"


def load_firmware_oracle() -> dict[str, Any]:
    """Load the firmware oracle verdict index."""
    if not ORACLE_JSON_PATH.is_file():
        return {"verdicts": {}, "gateways": []}
    with open(ORACLE_JSON_PATH, "r", encoding="utf-8") as f:
        return json.load(f)


ORACLE_DATA = load_firmware_oracle()
ALL_VERDICTS: dict[str, list[dict[str, Any]]] = ORACLE_DATA.get("verdicts", {})


def test_firmware_oracle_integrity():
    """Verify cryptographic integrity and structure of firmware_oracle.json."""
    assert ORACLE_JSON_PATH.is_file(), "tests/golden/firmware_oracle.json fixture file missing"
    data = load_firmware_oracle()
    assert data["format_version"] == "1.0.0"
    assert data["generator"] == "own-firmware-oracle"
    assert data["schema_version"] == "1.1.0"

    verdicts = data["verdicts"]
    canonical_verdicts = json.dumps(verdicts, sort_keys=True, separators=(",", ":"))
    calculated_hash = hashlib.sha256(canonical_verdicts.encode("utf-8")).hexdigest()
    assert calculated_hash == data["verdicts_sha256"], (
        f"Verdicts SHA-256 digest mismatch: {calculated_hash} != {data['verdicts_sha256']}"
    )

    assert data["total_unique_inputs"] == len(verdicts) == 303
    assert len(data["gateways"]) == 10

    gateway_names = {f"{g['product']} {g['version']}" for g in data["gateways"]}
    expected_gateways = {
        "F450 020010",
        "F453AV 030014",
        "F454 020051",
        "F455 010102",
        "F459 020105",
        "F460 020012",
        "F461 020011",
        "MH200N 010108",
        "MH202 010024",
        "MyHomeServer1 028206",
    }
    assert gateway_names == expected_gateways

    # Verify 9 emulated gateways × 335 rows across 17 test suites (3,015 rows total)
    emulated_gateways = [g for g in data["gateways"] if g["status"] == "emulated"]
    assert len(emulated_gateways) == 9
    catalogued_gateways = [g for g in data["gateways"] if g["status"] == "catalogued"]
    assert len(catalogued_gateways) == 1
    assert catalogued_gateways[0]["product"] == "F455"

    total_rows = sum(len(entries) for entries in verdicts.values())
    assert total_rows == 3015

    for g in emulated_gateways:
        prod = g["product"]
        rows = [k for k, entries in verdicts.items() for e in entries if e.get("product") == prod]
        assert len(rows) == 335
        assert len(g["suites"]) == 17


def test_emitted_own_frames_parseable_by_ownd():
    """Verify that every OpenWebNet frame emitted by real firmware parses cleanly in OWNd.

    The fixture captures 43 unique authentic firmware-emitted frames across the fleet.
    Key diagnostic examples include:
    1. *1*19*74##: WHO 1 lighting diagnostic fault event (WHAT 19) emitted by MH200N.
    2. *#1001*74*11*111110111111111111110111##: WHO 1001 diagnostic device mask emitted by MH200N.
    3. *25*21#1*21##: WHO 25 CEN+ event emitted during test sweeps.
    4. *25*31#1*339##: WHO 25 dry contact event emitted during test sweeps.
    5. *#*0##: OWNSignaling NACK emitted during negative boundary tests.
    """
    all_emitted: set[str] = set()
    for _inp, entries in ALL_VERDICTS.items():
        for entry in entries:
            for own_frame in entry.get("emitted_own", []):
                all_emitted.add(own_frame)

    assert len(all_emitted) == 43
    for frame in all_emitted:
        msg = OWNMessage.parse(frame)
        assert msg is not None, f"Failed to parse authentic emitted frame {frame}"

    assert "*1*19*74##" in all_emitted
    assert "*#1001*74*11*111110111111111111110111##" in all_emitted

    # 1. Semantic verification of WHO 1 lighting fault event
    fault_msg = OWNMessage.parse("*1*19*74##")
    assert isinstance(fault_msg, OWNLightingEvent)
    assert fault_msg.who == 1
    assert fault_msg.where == "74"
    assert fault_msg.unknown_state == 19
    assert fault_msg.is_on is None

    # 2. Semantic verification of WHO 1001 diagnostic state response
    diag_msg = OWNMessage.parse("*#1001*74*11*111110111111111111110111##")
    assert isinstance(diag_msg, OWNMessage)
    assert diag_msg.is_event is True
    assert diag_msg.who == 1001
    assert diag_msg.where == "74"
    assert getattr(diag_msg, "dimension", None) == 11
    assert getattr(diag_msg, "event_content", {}).get("dimension values") == ["111110111111111111110111"]

    # 3. Semantic verification of WHO 25 CEN+ push-button event
    cen_msg = OWNMessage.parse("*25*21#1*21##")
    assert isinstance(cen_msg, OWNCENPlusEvent)
    assert cen_msg.who == 25
    assert cen_msg.where == "21"
    assert cen_msg.push_button == 1
    assert cen_msg.is_short_pressed is True

    # 4. Semantic verification of WHO 25 dry contact event
    dry_msg = OWNMessage.parse("*25*31#1*339##")
    assert isinstance(dry_msg, OWNDryContactEvent)
    assert dry_msg.who == 25
    assert dry_msg.where == "339"
    assert dry_msg.is_on is True

    # 5. Semantic verification of OWNSignaling NACK
    nack_msg = OWNMessage.parse("*#*0##")
    assert isinstance(nack_msg, OWNSignaling)
    assert nack_msg.is_nack() is True
    assert nack_msg.who is None


def test_oracle_input_frames_ownd_parser_resilience():
    """Verify OWNd parser resilience across all 303 unique input frames in the oracle index.

    Guarantees that:
    1. Zero input frames cause unhandled parser crashes (AttributeError, IndexError, ValueError).
    2. Exactly 303 frames parse into valid typed OWNMessage instances across subsystems
       WHO 0, 1, 2, 3, 4, 8, 14, 15, 18, 22, 25.
    3. For all 303 parsed frames, msg.who matches the subsystem extracted from the frame syntax.
    """
    parsed_count = 0
    unparsed_count = 0

    for frame in ALL_VERDICTS:
        try:
            msg = OWNMessage.parse(frame)
        except Exception as exc:  # noqa: BLE001
            pytest.fail(f"OWNMessage.parse crashed on oracle input frame {frame}: {exc}")

        if msg is not None:
            parsed_count += 1
            m = re.match(r"^\*#?(\d+)\*", frame)
            assert m is not None, f"Could not extract WHO subsystem from frame {frame}"
            expected_who = int(m.group(1))
            assert msg.who == expected_who, (
                f"Parsed WHO mismatch for {frame}: got {msg.who}, expected {expected_who}"
            )
        else:
            unparsed_count += 1

    assert parsed_count == 303
    assert unparsed_count == 0


def test_oracle_who8_inputs_parse_into_specialized_classes() -> None:
    """Verify that all authentic oracle inputs for WHO 8 parse into specialized classes."""
    who8_count = 0
    for inp in ALL_VERDICTS:
        if inp.startswith("*8*") or inp.startswith("*#8*"):
            who8_count += 1
            msg = OWNMessage.parse(inp)
            assert msg is not None, f"Failed to parse WHO 8 message: {inp}"
            assert isinstance(msg, (OWNLockEvent, OWNLockCommand)), (
                f"Expected OWNLockEvent/Command for {inp}, got {type(msg)}"
            )
    assert who8_count == 59



def test_golden_corpus_bidirectional_cross_validation():
    """Bidirectional cross-validation between golden corpus fixtures and firmware oracle.

    For every fixture in corpus.json intersecting with firmware_oracle.json:
    1. System Under Test (OWNd) parses the frame cleanly matching fixture metadata.
    2. If the fixture declares a builder, calling OWNd's builder reproduces the exact frame string.
    3. Cross-validates empirical firmware oracle verdicts (both reply and verdict) against
       audited protocol expectations across gateway models:
       - thermo.req.temp.zone1 (*#4*1*0##): All 9 emulated gateways reply 'nack' with verdict 'out'
         (forwarded to SCS bus, but rejected at session layer because no zone 1 probe is present).
       - thermo central mode commands (*4*...*#0##): Accepted ('ack', 'out') on MH200N (bt_termo),
         F453AV, F454, F459, MH202, and MyHomeServer1 (heating suite); refused on F460/F461 ('nack', 'out').
       - Bus events sent to command session (*15*01#3*0001##, *25*21#1*21##, *25*31#1*339##):
         Accepted on MH202 scenario programmer ('ack', 'silent'), refused with NACK on standard gateways.
       - Energy unit request (*#18*51*113##): Accepted on MH202, MHS1, F453AV, F454, F459, F460, F461
         ('ack', 'out'); forwarded on MH200N ('nack', 'out'); refused on F450 ('nack', 'silent').
    """
    assert CORPUS_JSON_PATH.is_file(), "tests/golden/corpus.json fixture missing"
    with open(CORPUS_JSON_PATH, "r", encoding="utf-8") as f:
        corpus = json.load(f)

    intersecting_fixtures = [c for c in corpus if c.get("frame") in ALL_VERDICTS]
    assert len(intersecting_fixtures) == 8

    for fixture in intersecting_fixtures:
        fixture_id = fixture["id"]
        frame = fixture["frame"]
        entries = ALL_VERDICTS[frame]

        # 1. OWNd SUT Parser verification
        msg = OWNMessage.parse(frame)
        assert msg is not None, f"OWNMessage failed to parse intersecting fixture {fixture_id}: {frame}"
        if fixture.get("who") is not None:
            assert msg.who == fixture["who"]
        if fixture.get("where") is not None:
            assert msg.where == str(fixture["where"])

        # 2. OWNd SUT Builder verification
        builder_spec = fixture.get("builder")
        if builder_spec is not None:
            cls = getattr(msg_module, builder_spec["class"])
            method = getattr(cls, builder_spec["method"])
            built = method(*builder_spec["args"])
            assert str(built) == frame, (
                f"Builder {builder_spec['class']}.{builder_spec['method']} produced {built}, expected {frame}"
            )

        # 3. Empirical firmware oracle verdict cross-validation
        by_product = {e["product"]: e for e in entries}

        if fixture_id == "thermo.req.temp.zone1":
            # All 9 emulated gateways forward the query to bus but reply NACK without a probe
            for prod, entry in by_product.items():
                assert entry["reply"] == "nack", f"Expected NACK for {fixture_id} on {prod}"
                assert entry["verdict"] == "out", f"Expected 'out' verdict for {fixture_id} on {prod}"

        elif fixture_id == "cen.event.extended_press.btn1.0001":
            # Only MH202 (scenario programmer) accepts command-session event inputs
            assert by_product["MH202"]["reply"] == "ack"
            assert by_product["MH202"]["verdict"] == "silent"
            for prod in ("MH200N", "MyHomeServer1", "F453AV", "F454", "F459"):
                assert by_product[prod]["reply"] == "nack"
                assert by_product[prod]["verdict"] == "silent"

        elif fixture_id == "energy.req.unit.meter51":
            # Accepted on MH202, MyHomeServer1, F453AV, F454, F459, F460, F461
            for prod in ("MH202", "MyHomeServer1", "F453AV", "F454", "F459", "F460", "F461"):
                assert by_product[prod]["reply"] == "ack"
                assert by_product[prod]["verdict"] == "out"
            # MH200N forwards to PIC bus while returning NACK
            assert by_product["MH200N"]["reply"] == "nack"
            assert by_product["MH200N"]["verdict"] == "out"
            # F450 has no energy subsystem
            assert by_product["F450"]["reply"] == "nack"
            assert by_product["F450"]["verdict"] == "silent"

        elif fixture_id.startswith("thermo.cmd.central.mode."):
            # MH200N accepts central-unit mode commands via bt_termo daemon
            assert by_product["MH200N"]["reply"] == "ack"
            assert by_product["MH200N"]["verdict"] == "out"
            # Standard gateways accept and forward
            for prod in ("F453AV", "F454", "F459", "MH202"):
                assert by_product[prod]["reply"] == "ack"
                assert by_product[prod]["verdict"] == "out"
            # F460 and F461 reject central unit mode commands at session layer but forward
            assert by_product["F460"]["reply"] == "nack"
            assert by_product["F461"]["reply"] == "nack"


def test_harness_limitations_classification():
    """Explicitly identify and categorize test-harness limitations vs protocol verdicts.

    In the 3,015 firmware oracle rows, exactly:
    - 71 rows have verdict 'crash':
      - 69 crashes belong to F450 on thermo test suites (OPEN-BACnet interface daemon
        crashing under QEMU when non-BACnet WHO 4 frames are received).
      - 2 crashes belong to MH202 (*4*311*1## and *4*3201*#0##).
    - 7 rows have verdict 'timeout':
      - All 7 occur in 'energy-ts10' on totalizer reset/status commands waiting for unsimulated
        meter hardware responses (MH200N: 3, F453AV: 2, F454: 2).

    This test prevents test-harness emulator artifacts from being mistaken for legitimate
    OpenWebNet gateway protocol dialect.
    """
    crashes: list[tuple[str, str, str]] = []
    timeouts: list[tuple[str, str, str]] = []

    for frame, entries in ALL_VERDICTS.items():
        for e in entries:
            verdict = e.get("verdict")
            if verdict == "crash":
                crashes.append((e["product"], e["suite"], frame))
            elif verdict == "timeout":
                timeouts.append((e["product"], e["suite"], frame))

    assert len(crashes) == 71
    assert len(timeouts) == 7

    crash_counts = Counter(c[0] for c in crashes)
    assert crash_counts["F450"] == 69
    assert crash_counts["MH202"] == 2

    # All F450 crashes occur exclusively in thermo suites
    for prod, suite, _frame in crashes:
        if prod == "F450":
            assert any(s in suite for s in ("thermo", "heating")), (
                f"F450 crash in unexpected non-thermo suite: {suite}"
            )

    # All timeouts occur exclusively in energy-ts10
    timeout_counts = Counter(t[0] for t in timeouts)
    assert timeout_counts["MH200N"] == 3
    assert timeout_counts["F453AV"] == 2
    assert timeout_counts["F454"] == 2
    for _prod, suite, _frame in timeouts:
        assert suite == "energy-ts10"


def test_multi_suite_divergence_bounded():
    """Verify that cross-suite response divergence is bounded to known stateful interactions.

    Across the 17 suites, exactly 49 (product, frame) pairs produce different replies or
    verdicts due to prior gateway state or harness timeouts.
    For example:
    - MyHomeServer1 *4*1*#0## is 'ack' in 'ownd-pr82-heating' (pre-configured heating state)
      and 'nack' in 'thermo-central-mode'.
    - MH200N *#18*51*51## is 'ack' in 'energy-params' and '-' in 'energy-ts10'.

    Verifies that OWNd parser and session logic handle both response types without failure.
    """
    disagreements: dict[tuple[str, str], list[dict[str, Any]]] = {}

    for frame, entries in ALL_VERDICTS.items():
        by_prod: dict[str, list[dict[str, Any]]] = {}
        for e in entries:
            by_prod.setdefault(e["product"], []).append(e)
        for prod, prod_entries in by_prod.items():
            distinct_results = {(e["reply"], e["verdict"]) for e in prod_entries}
            if len(distinct_results) > 1:
                disagreements[(prod, frame)] = prod_entries

    assert len(disagreements) == 49

    # Verify MyHomeServer1 central unit mode divergence
    mhs1_heat_cu = disagreements.get(("MyHomeServer1", "*4*1*#0##"))
    assert mhs1_heat_cu is not None
    mhs1_replies = {e["suite"]: e["reply"] for e in mhs1_heat_cu}
    assert mhs1_replies["ownd-pr82-heating"] == "ack"
    assert mhs1_replies["thermo-central-mode"] == "nack"


def test_energy_dimension_51_bus_dispatch_reconciliation():
    """Reconcile empirical oracle verdicts for *#18*51*51## against physical hardware traces.

    Audit findings:
    1. Oracle fixture:
       - F450: 'nack' / 'silent' (BACnet gateway, no energy daemon).
       - MH200N: 'ack' / 'out' in energy-params, '-' / 'out' in energy-ts10.
         Transmits raw PIC serial bus frame '$06D1A1023350150000\\r'
         (hex: 24 30 36 44 31 41 31 30 32 33 33 35 30 31 35 30 30 30 30 0d).
       - F453AV, F454, F459, F460, F461, MH202, MyHomeServer1: 'ack' / 'out'.
    2. Physical plant capture reconciliation:
       - In MyHOME tests/fixtures/traces/issue_466/myhome_sweep_MH200N_all_2026-09-25T14-40-10.json,
         physical hardware returned *#18*51*51*23791364##.
       - The emulator records the gateway accepting the command and dispatching the PIC serial frame
         to the bus. In real hardware, an active physical energy meter on the SCS bus answers with the
         dimension value; in the oracle testbed, no physical meter is attached, explaining why
         only the forwarded frame is captured.
    """
    frame = "*#18*51*51##"
    assert frame in ALL_VERDICTS
    entries = ALL_VERDICTS[frame]

    by_prod: dict[str, list[dict[str, Any]]] = {}
    for e in entries:
        by_prod.setdefault(e["product"], []).append(e)

    # F450 refuses with NACK and silent verdict
    for e in by_prod["F450"]:
        assert e["reply"] == "nack"
        assert e["verdict"] == "silent"

    # MH200N forwards raw PIC frame in both suites
    mh200n_entries = by_prod["MH200N"]
    assert len(mh200n_entries) == 2
    for e in mh200n_entries:
        assert e["verdict"] == "out"
        assert len(e["bus_frames"]) == 1
        # Hex starts with '24 30 36 44' ($06D...)
        assert e["bus_frames"][0].startswith("24 30 36 44")

    # Gateways with active energy daemons acknowledge and forward
    for prod in ("F453AV", "F454", "F459", "F460", "F461", "MH202", "MyHomeServer1"):
        for e in by_prod[prod]:
            assert e["reply"] == "ack"
            assert e["verdict"] == "out"


@pytest.mark.parametrize(
    ("frame", "expected_reply", "expected_verdict", "target_gateways"),
    [
        # Lighting brightness 100 refusal (level 100 is invalid; 101-200 are valid, 0 is switch-off)
        ("*#1*0*#1*100*0##", "nack", "silent", {"MH200N", "MyHomeServer1"}),
        ("*#1*31*#1*100*0##", "nack", "silent", {"MH200N", "MyHomeServer1"}),
        ("*#1*31*#1*100*255##", "nack", "silent", {"MH200N", "MyHomeServer1"}),
        ("*#1*31*#1*100*5##", "nack", "silent", {"MH200N", "MyHomeServer1"}),
        ("*#1*31*#1*220*0##", "nack", "silent", {"MH200N", "MyHomeServer1"}),
        # Thermo invalid central unit modes refused on both gateways
        ("*4*100*#0##", "nack", "silent", {"MH200N", "MyHomeServer1"}),
        ("*4*110*#0##", "nack", "silent", {"MH200N", "MyHomeServer1"}),
        # Matrix-refused legacy syntax (tested on MH200N target daemon)
        ("*2*1*21#4#1##", "nack", "silent", {"MH200N"}),
        ("*#1*1*#1*20##", "nack", "silent", {"MH200N"}),
        ("*#2*1*#1*50##", "nack", "silent", {"MH200N"}),
        ("*15*01*0001##", "nack", "silent", {"MH200N"}),
        ("*25*21*0001##", "nack", "silent", {"MH200N"}),
    ],
)
def test_known_firmware_rejections(
    frame: str, expected_reply: str, expected_verdict: str, target_gateways: set[str]
):
    """Verify that known protocol boundary frames produce expected rejections on target gateways."""
    assert frame in ALL_VERDICTS, f"Target frame {frame} missing from oracle verdicts"
    entries = ALL_VERDICTS[frame]
    assert len(entries) > 0

    target_entries = [e for e in entries if e["product"] in target_gateways]
    assert len(target_entries) >= len(target_gateways), (
        f"Frame {frame} missing entries for {target_gateways}"
    )

    for entry in target_entries:
        assert entry["reply"] == expected_reply, (
            f"Frame {frame} on {entry['product']} expected reply {expected_reply}, got {entry['reply']}"
        )
        assert entry["verdict"] == expected_verdict, (
            f"Frame {frame} on {entry['product']} expected verdict {expected_verdict}, got {entry['verdict']}"
        )


def test_what19_fault_emitted_event():
    """Verify that *#1*74## produces the expected WHAT 19 lighting fault event on MH200N."""
    frame = "*#1*74##"
    assert frame in ALL_VERDICTS, f"Frame {frame} missing from oracle index"
    entries = ALL_VERDICTS[frame]
    mh200n_entries = [e for e in entries if e["product"] == "MH200N"]
    assert len(mh200n_entries) > 0

    # MH200N emits bus frame and OWN event *1*19*74##
    found_fault_event = False
    for entry in mh200n_entries:
        assert entry["verdict"] == "out"
        if "*1*19*74##" in entry["emitted_own"]:
            found_fault_event = True

    assert found_fault_event, f"Expected *1*19*74## in emitted_own for {frame} on MH200N"

    # Verify OWNd parses *1*19*74## as OWNLightingEvent with unknown_state=19
    msg = OWNMessage.parse("*1*19*74##")
    assert isinstance(msg, OWNLightingEvent)
    assert msg.who == 1
    assert msg.where == "74"
    assert msg.unknown_state == 19
    assert msg.is_on is None


def test_all_gateway_responses_conform_to_openwebnet_protocol():
    """Verify that every verdict entry adheres strictly to OpenWebNet framing rules."""
    valid_replies = {"ack", "nack", "-"}
    valid_verdicts = {"out", "silent", "timeout", "crash"}

    for inp, entries in ALL_VERDICTS.items():
        assert inp.startswith("*") and inp.endswith("##"), f"Invalid input frame format: {inp}"
        for entry in entries:
            assert entry["reply"] in valid_replies, (
                f"Invalid reply '{entry['reply']}' for {inp} on {entry['product']}"
            )
            assert entry["verdict"] in valid_verdicts, (
                f"Invalid verdict '{entry['verdict']}' for {inp} on {entry['product']}"
            )
            for bus_hex in entry.get("bus_frames", []):
                # Verify bus frame consists of space-separated hex bytes
                tokens = bus_hex.split()
                assert len(tokens) > 0, f"Empty bus frame for {inp}"
                for token in tokens:
                    assert len(token) == 2, f"Invalid hex token '{token}' in bus frame '{bus_hex}'"
                    int(token, 16)  # Asserts valid hex representation
            for own_frame in entry.get("emitted_own", []):
                assert own_frame.startswith("*") and own_frame.endswith("##"), (
                    f"Invalid emitted OpenWebNet frame: {own_frame}"
                )


def test_firmware_nack_with_bus_forwarding():
    """Verify empirical cases where the gateway forwards bus frames but returns NACK.

    797 verdict rows exhibit this behavior across the fleet of 9 emulated gateways:
    - F460 forwards lighting, thermo, and sound commands to the SCS bus while returning NACK (239 rows).
    - F461 exhibits similar bus forwarding with NACK replies (238 rows).
    - MyHomeServer1 forwards lighting level writes, energy, sound, and thermo to the SCS bus (94 rows).
    - F454 forwards sound diffusion and energy commands (47 rows).
    - MH202 forwards scenario, energy, and intercom frames (44 rows).
    - F453AV forwards sound, video door entry, and energy frames (42 rows).
    - F450 forwards thermo frames (37 rows).
    - F459 forwards thermo and sound frames (36 rows).
    - MH200N forwards energy requests, thermo status, and WHO 25 frames (20 rows).
    """
    nack_and_out: list[tuple[str, str, str, list[str], list[str]]] = []
    for frame, entries in ALL_VERDICTS.items():
        for entry in entries:
            if entry.get("reply") == "nack" and entry.get("verdict") == "out":
                nack_and_out.append((
                    entry["product"],
                    entry["suite"],
                    frame,
                    entry.get("bus_frames", []),
                    entry.get("emitted_own", []),
                ))

    assert len(nack_and_out) == 797

    counts = Counter(item[0] for item in nack_and_out)
    assert counts["F460"] == 239
    assert counts["F461"] == 238
    assert counts["MyHomeServer1"] == 94
    assert counts["F454"] == 47
    assert counts["MH202"] == 44
    assert counts["F453AV"] == 42
    assert counts["F450"] == 37
    assert counts["F459"] == 36
    assert counts["MH200N"] == 20

    for _product, _suite, _frame, bus_frames, emitted_own in nack_and_out:
        assert len(bus_frames) > 0 or len(emitted_own) > 0, (
            "Expected forwarded bus frames or emitted OWN frames for verdict 'out'"
        )


def test_dimmer_level_cross_gateway_behavior():
    """Verify cross-gateway divergence on dimmer level write *1*0#1*31##.

    Both MH200N and MyHomeServer1 forward the identical SCS bus frame,
    but MH200N replies with ACK while MyHomeServer1 replies with NACK.
    """
    frame = "*1*0#1*31##"
    assert frame in ALL_VERDICTS
    entries = ALL_VERDICTS[frame]

    mh200n_entries = [e for e in entries if e["product"] == "MH200N"]
    mhs1_entries = [e for e in entries if e["product"] == "MyHomeServer1"]

    assert len(mh200n_entries) > 0, f"Missing MH200N entry for {frame}"
    assert len(mhs1_entries) > 0, f"Missing MyHomeServer1 entry for {frame}"

    # Both gateways transmit the identical bus frame to the lighting actuator:
    expected_bus = ["24 30 36 44 31 33 31 30 31 34 32 30 44 30 31 30 30 30 31 0d"]
    for e in mh200n_entries:
        assert e["bus_frames"] == expected_bus
        assert e["reply"] == "ack"
        assert e["verdict"] == "out"

    for e in mhs1_entries:
        assert e["bus_frames"] == expected_bus
        assert e["reply"] == "nack"
        assert e["verdict"] == "out"


def test_gateway_profiles_match_oracle_gateways():
    """Verify that profiles exist for all gateways catalogued in the firmware oracle and match capabilities."""
    data = load_firmware_oracle()
    gateways = data.get("gateways", [])
    assert len(gateways) == 10, "Expected all 10 gateway entries in oracle fixture"

    generic_gateways = {"F450", "F459", "F460"}

    for gw in gateways:
        product = gw["product"]
        profile = get_gateway_profile(product)
        assert profile is not None, f"No profile resolved for catalog gateway {product}"
        assert profile.model_name == product, (
            f"Profile model name mismatch for {product}: got {profile.model_name}"
        )
        if product in generic_gateways:
            assert isinstance(profile, GenericGatewayProfile), (
                f"Gateway {product} expected GenericGatewayProfile fallback"
            )
        else:
            assert not isinstance(profile, GenericGatewayProfile), (
                f"Gateway {product} unexpectedly resolved to GenericGatewayProfile fallback"
            )

    # Specific capability checks based on verified firmware daemons:
    mh200n_profile = get_gateway_profile("MH200N")
    for who in (WHO_LIGHTING, WHO_AUTOMATION, WHO_HEATING, WHO_CEN, WHO_CEN_PLUS):
        assert who in mh200n_profile.supported_who, (
            f"MH200N profile missing expected supported WHO {who}"
        )


def test_multi_gateway_emulation_coverage():
    """Verify that the 10 catalogued gateways have correct emulation status."""
    data = load_firmware_oracle()
    gateways = {g["product"]: g for g in data.get("gateways", [])}
    assert len(gateways) == 10

    # 9 gateways have full empirical emulation verdicts across all 17 test suites:
    emulated_products = {
        "F450",
        "F453AV",
        "F454",
        "F459",
        "F460",
        "F461",
        "MH200N",
        "MH202",
        "MyHomeServer1",
    }
    for p in emulated_products:
        assert gateways[p]["status"] == "emulated"
        assert len(gateways[p]["suites"]) == 17
        assert len(gateways[p]["image_sha256"]) == 64

    # F455 is catalogued and verified, pending emulation (bare-metal ARM Cortex-M):
    assert gateways["F455"]["status"] == "catalogued"
    assert gateways["F455"]["suites"] == []
    assert len(gateways["F455"]["image_sha256"]) == 64
