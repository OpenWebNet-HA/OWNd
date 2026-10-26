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
    OWNGatewayEvent,
    OWNLightingCommand,
    OWNLightingDiagnosticEvent,
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

    assert data["total_unique_inputs"] == len(verdicts) == 509
    assert len(data["gateways"]) == 17

    gateway_names = {f"{g['product']} {g['version']}" for g in data["gateways"]}
    expected_gateways = {
        "3550 030020",
        "F450 020010",
        "F453 010100",
        "F453AV 030014",
        "F454 020051",
        "F455 010102",
        "F459 020105",
        "F460 020012",
        "F461 020011",
        "H4684 020054",
        "L4561N 040006",
        "L4686SDK 012001",
        "MH200 020102",
        "MH200N 010108",
        "MH201 030644",
        "MH202 010024",
        "MyHomeServer1 028206",
    }
    assert gateway_names == expected_gateways

    # Verify 12 emulated gateways × 540-544 rows across 22 test suites (6,500 rows total)
    emulated_gateways = [g for g in data["gateways"] if g["status"] == "emulated"]
    assert len(emulated_gateways) == 12
    catalogued_gateways = [g for g in data["gateways"] if g["status"] == "catalogued"]
    assert len(catalogued_gateways) == 5
    assert {g["product"] for g in catalogued_gateways} == {
        "3550",
        "F455",
        "L4561N",
        "L4686SDK",
        "MH201",
    }

    total_rows = sum(len(entries) for entries in verdicts.values())
    assert total_rows == 6500

    for g in emulated_gateways:
        prod = g["product"]
        rows = [k for k, entries in verdicts.items() for e in entries if e.get("product") == prod]
        assert len(rows) in (540, 544)
        assert len(g["suites"]) == 22


def test_emitted_own_frames_parseable_by_ownd():
    """Verify that every OpenWebNet frame emitted by real firmware parses cleanly in OWNd.

    The fixture captures 140 unique authentic firmware-emitted frames across the fleet.
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

    assert len(all_emitted) == 140
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
    assert isinstance(diag_msg, OWNLightingDiagnosticEvent)
    assert diag_msg.is_event is True
    assert diag_msg.who == 1001
    assert diag_msg.where == "74"
    assert diag_msg.dimension == 11
    assert diag_msg.diagnostic_mask == "111110111111111111110111"
    assert diag_msg.cleared_bits == (6, 21)

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

    # 6. Semantic verification of H4684 and MH200 WHO 13 gateway identification frames
    h4684_dev = OWNMessage.parse("*#13**15*13##")
    assert isinstance(h4684_dev, OWNGatewayEvent)
    assert h4684_dev.device_type == "H4684"
    assert h4684_dev.device_type_code == "13"
    h4684_fw = OWNMessage.parse("*#13**16*2*0*54##")
    assert isinstance(h4684_fw, OWNGatewayEvent)
    assert h4684_fw.firmware_version == "2.0.54"
    mh200_dev = OWNMessage.parse("*#13**15*4##")
    assert isinstance(mh200_dev, OWNGatewayEvent)
    assert mh200_dev.device_type == "MH200"
    assert mh200_dev.device_type_code == "4"
    mh200_fw = OWNMessage.parse("*#13**16*2*1*2##")
    assert isinstance(mh200_fw, OWNGatewayEvent)
    assert mh200_fw.firmware_version == "2.1.2"


def test_oracle_input_frames_ownd_parser_resilience():
    """Verify OWNd parser resilience across all 509 unique input frames in the oracle index.

    Guarantees that:
    1. Zero input frames cause unhandled parser crashes (AttributeError, IndexError, ValueError).
    2. All 509 frames parse into valid typed OWNMessage instances across all subsystems.
    3. For all 509 parsed frames, msg.who matches the subsystem extracted from the frame syntax.
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
            m = re.match(r"^\*#?(\d+)(?:\*|##)", frame)
            assert m is not None, f"Could not extract WHO subsystem from frame {frame}"
            expected_who = int(m.group(1))
            assert msg.who == expected_who, (
                f"Parsed WHO mismatch for {frame}: got {msg.who}, expected {expected_who}"
            )
        else:
            unparsed_count += 1

    assert parsed_count == 509
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
    """Bidirectional cross-validation between golden corpus fixtures and firmware oracle."""
    assert CORPUS_JSON_PATH.is_file(), "tests/golden/corpus.json fixture missing"
    with open(CORPUS_JSON_PATH, "r", encoding="utf-8") as f:
        corpus = json.load(f)

    intersecting_fixtures = [c for c in corpus if c.get("frame") in ALL_VERDICTS]
    assert len(intersecting_fixtures) >= 8

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
            for prod, entry in by_product.items():
                if prod == "MH202":
                    assert entry["reply"] == "ack"
                else:
                    assert entry["reply"] == "nack", f"Expected NACK for {fixture_id} on {prod}"
                assert entry["verdict"] == "out", f"Expected 'out' verdict for {fixture_id} on {prod}"

        elif fixture_id == "cen.event.extended_press.btn1.0001":
            assert by_product["MH202"]["reply"] == "ack"
            assert by_product["MH202"]["verdict"] == "out"
            for prod, entry in by_product.items():
                if prod != "MH202":
                    assert entry["reply"] == "nack"
                    assert entry["verdict"] == "silent"

        elif fixture_id == "energy.req.unit.meter51":
            for prod in ("MH202", "MyHomeServer1", "F453", "F453AV", "F454", "F459", "F460", "F461", "MH200N"):
                assert by_product[prod]["reply"] == "ack"
                assert by_product[prod]["verdict"] == "out"
            for prod in ("F450", "H4684", "MH200"):
                assert by_product[prod]["reply"] == "nack"
                assert by_product[prod]["verdict"] == "silent"

        elif fixture_id.startswith("thermo.cmd.central.mode."):
            assert by_product["MH200N"]["reply"] == "ack"
            assert by_product["MH200N"]["verdict"] == "out"
            for prod in ("F453", "F453AV", "F454", "F459", "MH202"):
                assert by_product[prod]["reply"] == "ack"
                assert by_product[prod]["verdict"] == "out"
            assert by_product["F460"]["reply"] == "nack"
            assert by_product["F460"]["verdict"] == "out"
            assert by_product["F461"]["reply"] == "nack"
            assert by_product["F461"]["verdict"] == "out"


def test_harness_limitations_classification():
    """Explicitly identify and categorize test-harness limitations vs protocol verdicts.

    With the upstream fix in own-firmware-oracle#48 (pruning boot-exiting translators and creating
    /var/volatile/tmp/upnp), MH202 and F450 no longer segfault or crash. Across all 6,500 empirical
    verdict rows for the 12 emulated gateways in the fleet, exactly 0 crashes and 0 timeouts are recorded.
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

    assert len(crashes) == 0
    assert len(timeouts) == 0


def test_multi_suite_divergence_bounded():
    """Verify that cross-suite response divergence is bounded across suites."""
    disagreements: dict[tuple[str, str], list[dict[str, Any]]] = {}

    for frame, entries in ALL_VERDICTS.items():
        by_prod: dict[str, list[dict[str, Any]]] = {}
        for e in entries:
            by_prod.setdefault(e["product"], []).append(e)
        for prod, prod_entries in by_prod.items():
            distinct_results = {(e["reply"], e["verdict"]) for e in prod_entries}
            if len(distinct_results) > 1:
                disagreements[(prod, frame)] = prod_entries

    assert len(disagreements) == 0


def test_energy_dimension_51_bus_dispatch_reconciliation():
    """Reconcile empirical oracle verdicts for *#18*51*51## against physical hardware traces."""
    frame = "*#18*51*51##"
    assert frame in ALL_VERDICTS
    entries = ALL_VERDICTS[frame]

    by_prod: dict[str, list[dict[str, Any]]] = {}
    for e in entries:
        by_prod.setdefault(e["product"], []).append(e)

    # Gateways without energy daemons refuse with NACK and silent verdict
    for prod in ("F450", "H4684", "MH200"):
        for e in by_prod[prod]:
            assert e["reply"] == "nack"
            assert e["verdict"] == "silent"

    # MH200N forwards raw PIC frame in both suites
    mh200n_entries = by_prod["MH200N"]
    assert len(mh200n_entries) == 2
    for e in mh200n_entries:
        assert e["verdict"] == "out"
        assert len(e["bus_frames"]) == 1
        assert e["bus_frames"][0].startswith("24 30 36 44")

    # Gateways with active energy daemons acknowledge and forward
    for prod in ("F453", "F453AV", "F454", "F459", "F460", "F461", "MH202", "MyHomeServer1"):
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

    # Verify OWNd parses *1*19*74## as OWNLightingEvent with unknown_state=19 and anomaly flag
    msg = OWNMessage.parse("*1*19*74##")
    assert isinstance(msg, OWNLightingEvent)
    assert msg.who == 1
    assert msg.where == "74"
    assert msg.unknown_state == 19
    assert msg.is_on is None
    assert msg.is_anomaly is True


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
    """Verify empirical cases where the gateway forwards bus frames but returns NACK."""
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

    assert len(nack_and_out) == 1081

    counts = Counter(item[0] for item in nack_and_out)
    assert counts["F460"] == 228
    assert counts["F461"] == 228
    assert counts["MyHomeServer1"] == 228
    assert counts["MH202"] == 70
    assert counts["F453"] == 53
    assert counts["F453AV"] == 53
    assert counts["MH200N"] == 53
    assert counts["F454"] == 51
    assert counts["F459"] == 51
    assert counts["MH200"] == 24
    assert counts["H4684"] == 23
    assert counts["F450"] == 19

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
    from scripts.sync_documentation import verify_gateway_profiles_oracle

    data = load_firmware_oracle()
    gateways = data.get("gateways", [])
    assert len(gateways) == 17, "Expected all 17 gateway entries in oracle fixture"

    generic_gateways = {"3550", "F450", "F459", "F460", "L4561N", "L4686SDK"}

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

    assert verify_gateway_profiles_oracle(ORACLE_JSON_PATH) == []


def test_multi_gateway_emulation_coverage():
    """Verify that the 17 catalogued gateways have correct emulation status."""
    data = load_firmware_oracle()
    gateways = {g["product"]: g for g in data.get("gateways", [])}
    assert len(gateways) == 17

    # 12 gateways have full empirical emulation verdicts across all 22 test suites:
    emulated_products = {
        "F450",
        "F453",
        "F453AV",
        "F454",
        "F459",
        "F460",
        "F461",
        "H4684",
        "MH200",
        "MH200N",
        "MH202",
        "MyHomeServer1",
    }
    for p in emulated_products:
        assert gateways[p]["status"] == "emulated"
        assert len(gateways[p]["suites"]) == 22
        assert len(gateways[p]["image_sha256"]) == 64

    # Catalogued auxiliary/bare-metal packages pending emulation:
    for p in ("3550", "F455", "L4561N", "L4686SDK", "MH201"):
        assert gateways[p]["status"] == "catalogued"
        assert gateways[p]["suites"] == []
        assert len(gateways[p]["image_sha256"]) == 64

