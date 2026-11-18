"""OpenZigBee protocol, profile, context-gating, and parse-equivalence tests."""
from __future__ import annotations

import json
from pathlib import Path

import pytest

from OWNd.connection import OWNGateway
from OWNd.exceptions import OWNNackError
from OWNd.message import (
    OWNCommand,
    OWNEvent,
    OWNGatewayCommand,
    OWNGatewayEvent,
    OWNLightingEvent,
    OWNMessage,
    OWNSignaling,
    ZIGBEE_DEVICE_TYPES,
    normalize_where,
)
from OWNd.profiles import (
    F454Profile,
    GatewayProfile,
    Legrand3578Profile,
    WHO_AUTOMATION,
    WHO_GATEWAY,
    WHO_LIGHTING,
    _PROFILES,
    get_gateway_profile,
)

REPO_ROOT = Path(__file__).resolve().parent.parent


def test_legrand_3578_profile_and_aliases() -> None:
    """Verify Legrand3578Profile fields, defaults, firmware formatting, and aliases."""
    default_gateway = GatewayProfile("TCP")
    assert default_gateway.transport_type == "tcp"
    assert default_gateway.address_family == "scs"
    assert default_gateway.default_baudrate is None
    assert default_gateway.command_session_idle_timeout is None

    profile = Legrand3578Profile()
    assert profile == _PROFILES["3578"]
    assert profile.model_name == "3578"
    assert profile.transport_type == "serial"
    assert profile.address_family == "zigbee"
    assert profile.default_baudrate == 19200
    assert profile.command_session_idle_timeout is None
    assert profile.requires_password is False
    assert profile.supports_audio is False
    assert profile.supported_who == frozenset({WHO_LIGHTING, WHO_AUTOMATION, WHO_GATEWAY})
    assert profile.keepalive_summary == "Serial link"
    assert profile.features_summary == "USB/Serial 19200 8N1, ZigBee #9 addressing"
    assert profile.firmware_version is None

    assert Legrand3578Profile((1, 2, 4)).firmware_version == "1.2.4"
    assert Legrand3578Profile("1.2.3").firmware_version == "1.2.3"
    assert Legrand3578Profile("").firmware_version is None

    for alias in (
        "3578",
        "088328",
        "003578",
        "03578",
        "BTicino 3578",
        "Legrand 3578",
        "Legrand 088328",
        "openzigbee",
        "zigbee",
    ):
        resolved = get_gateway_profile(alias, "1.2.4")
        assert isinstance(resolved, Legrand3578Profile), alias
        assert resolved.firmware_version == "1.2.4"


def test_busy_nack_signaling_and_exception() -> None:
    """Verify *#*6## BUSY NACK signaling and OWNNackError.busy."""
    sig = OWNMessage.parse("*#*6##")
    assert isinstance(sig, OWNSignaling)
    assert sig.is_valid is True
    assert sig.is_busy_nack() is True
    assert sig.is_nack() is False
    assert sig.is_ack() is False
    assert sig.human_readable_log == "BUSY NACK."

    ack = OWNMessage.parse("*#*1##")
    assert isinstance(ack, OWNSignaling)
    assert ack.is_busy_nack() is False

    err_default = OWNNackError("nack", frame="*1*1*12##")
    assert err_default.busy is False
    assert err_default.reason == "nack"

    err_busy = OWNNackError("busy", frame="*1*1*12##", reason="busy_nack", busy=True)
    assert err_busy.busy is True
    assert err_busy.reason == "busy_nack"


def test_who13_zigbee_commands_and_builders() -> None:
    """Verify WHO 13 empty-WHERE commands, builders, and invalid variants."""
    builders = [
        (OWNGatewayCommand.keep_connect(), "*13*60*##", "keep connect"),
        (OWNGatewayCommand.scan_network(), "*13*65*##", "Scanning ZigBee"),
        (OWNGatewayCommand.enable_supervisor(), "*13*66*##", "Enabling ZigBee"),
        (OWNGatewayCommand.disable_supervisor(), "*13*67*##", "Disabling ZigBee"),
    ]
    for cmd, expected_frame, log_fragment in builders:
        assert str(cmd) == expected_frame
        assert cmd.is_valid is True
        assert cmd.is_command is True
        assert cmd.who == 13
        assert cmd.where == ""
        assert log_fragment in cmd.human_readable_log

        parsed = OWNMessage.parse(expected_frame)
        assert isinstance(parsed, OWNGatewayCommand)
        assert parsed.is_valid is True
        assert parsed.where == ""

        cmd_parsed = OWNCommand.parse(expected_frame)
        assert isinstance(cmd_parsed, OWNGatewayCommand)
        assert cmd_parsed.is_valid is True

    assert str(OWNGatewayCommand.request_product_count()) == "*#13**67##"
    info_cmd = OWNGatewayCommand.get_product_info(4)
    assert str(info_cmd) == "*#13**66*4##"
    assert "index 4" in info_cmd.human_readable_log

    for bad_idx in (-1, True, "0"):
        with pytest.raises(ValueError, match="non-negative integer"):
            OWNGatewayCommand.get_product_info(bad_idx)  # type: ignore[arg-type]

    for invalid_frame in ("*1*1*##", "*2*1*##", "*13*99*##"):
        assert OWNMessage.parse(invalid_frame) is None


def test_who13_zigbee_event_decoders() -> None:
    """Verify DIM 12 EUI-64, DIM 16 firmware tuple, DIM 66 product info, and DIM 67 count."""
    assert ZIGBEE_DEVICE_TYPES[256] == "On/Off Switch"

    # 8-octet EUI-64 vs 6-octet MAC
    eui_evt = OWNMessage.parse("*#13**12*0*3*80*0*0*1*2*3##")
    assert isinstance(eui_evt, OWNGatewayEvent)
    assert eui_evt.ieee_address == "00:03:50:00:00:01:02:03"
    assert eui_evt.mac_address is None

    mac_evt = OWNMessage.parse("*#13**12*0*3*80*0*18*52##")
    assert isinstance(mac_evt, OWNGatewayEvent)
    assert mac_evt.mac_address == "00:03:50:00:12:34"
    assert mac_evt.ieee_address is None
    assert (
        OWNMessage.parse("*#13**12*256*3*80*0*7*119##").mac_address  # type: ignore[union-attr]
        == "100:03:50:00:07:77"
    )

    # 7-octet or >255 octet leaves both None
    bad_len = OWNMessage.parse("*#13**12*0*3*80*0*0*1*2##")
    assert isinstance(bad_len, OWNGatewayEvent)
    assert bad_len.mac_address is None and bad_len.ieee_address is None

    bad_octet = OWNMessage.parse("*#13**12*0*3*80*0*0*1*2*300##")
    assert isinstance(bad_octet, OWNGatewayEvent)
    assert bad_octet.ieee_address is None

    # DIM 16 tuple
    fw_evt = OWNMessage.parse("*#13**16*1*2*4##")
    assert isinstance(fw_evt, OWNGatewayEvent)
    assert fw_evt.firmware_version == "1.2.4"
    assert fw_evt.firmware_version_tuple == (1, 2, 4)

    fw_partial = OWNMessage.parse("*#13**16*1**4##")
    assert isinstance(fw_partial, OWNGatewayEvent)
    assert fw_partial.firmware_version_tuple is None

    # DIM 66 product info (reachable, '#' param variant, unknown type, unreachable)
    dim66 = OWNMessage.parse("*#13*702053501#9*66*0*256##", gateway=Legrand3578Profile())
    assert isinstance(dim66, OWNGatewayEvent)
    assert dim66.zigbee_product_index == 0
    assert dim66.zigbee_device_type_code == 256
    assert dim66.zigbee_device_type == "On/Off Switch"
    assert dim66.is_zigbee_product_unreachable is False

    dim66_hash = OWNMessage.parse("*#13*702053502#9*66#2*512##")
    assert isinstance(dim66_hash, OWNGatewayEvent)
    assert dim66_hash.zigbee_product_index == 2
    assert dim66_hash.zigbee_device_type == "Shutter Control"

    dim66_unknown = OWNMessage.parse("*#13*702053502#9*66*1*9999##")
    assert isinstance(dim66_unknown, OWNGatewayEvent)
    assert dim66_unknown.zigbee_device_type == "Unknown (9999)"

    dim66_unreach = OWNMessage.parse("*#13**66*0##")
    assert isinstance(dim66_unreach, OWNGatewayEvent)
    assert dim66_unreach.is_zigbee_product_unreachable is True
    assert dim66_unreach.zigbee_device_type_code == 0
    assert dim66_unreach.zigbee_device_type is None
    assert dim66_unreach.zigbee_product_index is None

    # DIM 67 count
    dim67 = OWNMessage.parse("*#13**67*12##")
    assert isinstance(dim67, OWNGatewayEvent)
    assert dim67.network_product_count == 12


def test_zigbee_context_gated_properties_and_scopes() -> None:
    """Verify unicast, broadcast, bare broadcast, group, and wired #9 separation."""
    zb_profile = Legrand3578Profile()
    zb_gateway = OWNGateway({"address": "/dev/ttyUSB0", "modelName": "3578"})
    scs_profile = F454Profile()

    # Unicast (<ADDR><UNIT>#9) including 100#9 collision with SCS Area 10
    msg_uni = OWNMessage.parse("*1*1*12345601#9##", gateway=zb_profile)
    assert msg_uni is not None
    assert msg_uni.is_zigbee is True
    assert msg_uni.zigbee_where == "12345601#9"
    assert msg_uni.zigbee_device_id == "123456"
    assert msg_uni.zigbee_unit == "01"
    assert msg_uni.unique_id == "1-12345601#9"
    assert msg_uni.is_area is False
    assert msg_uni.is_group is False
    assert msg_uni.is_general is False

    msg_100 = OWNMessage.parse("*1*1*100#9##", gateway=zb_gateway)
    assert msg_100 is not None
    assert msg_100.is_zigbee is True
    assert msg_100.zigbee_where == "100#9"
    assert msg_100.zigbee_device_id == "1"
    assert msg_100.zigbee_unit == "00"
    assert msg_100.is_area is False

    # Broadcast 0#<UNIT>#9
    msg_bcast_u = OWNMessage.parse("*1*1*0#01#9##", gateway=zb_profile)
    assert msg_bcast_u is not None
    assert msg_bcast_u.is_zigbee is True
    assert msg_bcast_u.zigbee_where == "0#01#9"
    assert msg_bcast_u.zigbee_device_id is None
    assert msg_bcast_u.zigbee_unit == "01"
    assert msg_bcast_u.is_general is False

    msg_bcast_00 = OWNMessage.parse("*1*1*0#00#9##", gateway=zb_profile)
    assert msg_bcast_00 is not None
    assert msg_bcast_00.is_zigbee is True
    assert msg_bcast_00.is_general is True

    # Bare broadcast 0#9
    msg_bare_bcast = OWNMessage.parse("*2*0*0#9##", gateway=zb_profile)
    assert msg_bare_bcast is not None
    assert msg_bare_bcast.is_zigbee is True
    assert msg_bare_bcast.zigbee_where == "0#9"
    assert msg_bare_bcast.zigbee_device_id is None
    assert msg_bare_bcast.zigbee_unit is None
    assert msg_bare_bcast.is_general is True

    # Group #<G>#9
    msg_grp = OWNMessage.parse("*1*1*#25#9##", gateway=zb_profile)
    assert msg_grp is not None
    assert msg_grp.is_zigbee is True
    assert msg_grp.zigbee_where == "#25#9"
    assert msg_grp.zigbee_device_id is None
    assert msg_grp.zigbee_unit is None
    assert msg_grp.is_group is True
    assert msg_grp.group == 25
    assert msg_grp.is_area is False
    assert msg_grp.is_general is False
    assert msg_grp.unique_id == "1-#25#9"

    # Out-of-range group #0#9 / #65536#9, wired #0, and empty WHERE *#13## stay is_zigbee=False
    assert OWNMessage.parse("*1*1*#0#9##", gateway=zb_profile).is_zigbee is False  # type: ignore[union-attr]
    assert OWNMessage.parse("*1*1*#65536#9##", gateway=zb_profile).is_zigbee is False  # type: ignore[union-attr]
    assert OWNMessage.parse("*1*1*0##", gateway=zb_profile).is_zigbee is False  # type: ignore[union-attr]
    assert OWNMessage.parse("*#13##", gateway=zb_profile).is_zigbee is False  # type: ignore[union-attr]

    # Context-free / SCS / string gateway -> is_zigbee always False
    for ctx in (None, scs_profile, "/dev/ttyUSB0"):
        non_zb = OWNMessage.parse("*1*1*12345601#9##", gateway=ctx)
        assert non_zb is not None
        assert non_zb.is_zigbee is False
        assert non_zb.zigbee_where is None
        assert non_zb.zigbee_device_id is None
        assert non_zb.zigbee_unit is None
        assert non_zb.unique_id == "1-12345601"


@pytest.mark.parametrize(
    "frame",
    [
        "*4*1*012#9##",
        "*4*1*1#9##",
        "*22*1*2#9##",
        "*1*1*#9##",
    ],
)
def test_wired_scs_hash9_collisions_never_misclassified_as_zigbee(frame: str) -> None:
    """Verify wired #9 bus-interface / SCS group frames stay non-ZigBee in all contexts."""
    for ctx in (None, F454Profile(), Legrand3578Profile()):
        msg = OWNMessage.parse(frame, gateway=ctx)
        assert msg is not None, frame
        assert msg.is_zigbee is False, (frame, ctx)
        assert msg.zigbee_where is None
        assert msg.zigbee_device_id is None
        assert msg.zigbee_unit is None

    wired_grp = OWNMessage.parse("*1*1*#9##", gateway=Legrand3578Profile())
    assert wired_grp is not None
    assert wired_grp.is_group is True
    assert wired_grp.group == 9
    assert wired_grp.unique_id == "1-#9"


def test_lighting_what32_toggle_and_normalize_where() -> None:
    """Verify WHAT 32 toggle event and normalize_where #9 preservation."""
    assert normalize_where("00123401#9") == "00123401#9"
    assert normalize_where("0021#4#9") == "21#4#9"
    assert normalize_where("0021") == "21"

    toggle = OWNEvent.parse("*1*32*12345601#9##", gateway=Legrand3578Profile())
    assert isinstance(toggle, OWNLightingEvent)
    assert toggle.is_toggle is True
    assert toggle.is_on is None
    assert toggle.unknown_state is None
    assert toggle.is_sensor is False
    assert "WHAT 32" in toggle.human_readable_log

    non_toggle = OWNLightingEvent("*1*1*12##")
    assert non_toggle.is_toggle is False
    assert non_toggle.is_on is True


def test_golden_corpus_context_free_parse_equivalence() -> None:
    """Verify every existing golden fixture with gateway=None parses identically to 2.0.1."""
    corpus = json.loads((REPO_ROOT / "tests" / "golden" / "corpus.json").read_text(encoding="utf-8"))
    for fixture in corpus:
        frame = fixture["frame"]
        parsed = OWNMessage.parse(frame)
        assert parsed is not None, frame
        assert parsed.is_zigbee is False, frame
        assert parsed.zigbee_where is None
        assert parsed.zigbee_device_id is None
        assert parsed.zigbee_unit is None
        assert parsed.who == fixture.get("who")
        if parsed.who is not None:
            assert parsed.where == fixture.get("where")
            assert parsed.dimension == fixture.get("dimension")
        if fixture.get("roundtrip") is True:
            assert str(parsed) == frame
