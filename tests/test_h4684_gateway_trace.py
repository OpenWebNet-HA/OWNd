"""Synthetic Trace and Gateway Identification Tests for H4684 / LGRH4684.

Verifies deterministic replay of gateway model identification frames synthesized
from static disassembly of Legrand/BTicino bt_device daemon (firmware 2.0.54,
catalogued in own-firmware-oracle PR #26):

1. WHO 13 Dimension 15 device type resolution (*#13**15*<TYPE>##):
   - Code 13 (official 2006 table & bt_device VA 0x02003264) -> H4684
   - Code 20 (bt_device Legrand variant VA 0x02003310) -> LGRH4684
   - Code 23 (legacy scan compatibility) -> H4684

2. WHO 1013 Dimension 1 diagnostic object model resolution (*#1013**1*<MODEL>*...##):
   - Code 19 (bt_device primary dispatch VA 0x02003268) -> H4684
   - Code 26 (bt_device Legrand primary dispatch VA 0x02003314) -> LGRH4684
   - Code 29 (MHCatalogue.db AS_ITEM_SYSTEM modobj) -> H4684

3. Profile mapping:
   - H4684 and aliases (L4684, N4684, NT4684, LGRH4684, LGR4684) resolve to H4684Profile.

Independent Firmware Reproduction:
   - Source: Version_2_0.zip (SHA-256: 41511712796cee61704f9d9cd1c85a14ce4fd6c8f5cea3b529d92117daf60e17)
   - Extracted binary: bt_device (SHA-256: 5b0768d672719f2952a14d898c825266b02703b6db407c0c0ad3bc8a9712b246)
   - Disassembly dispatch: VA 0x02003194 switches on caller selector r4:
     * r4 == 0 (WHO 13): returns string "13" (H4684) or "20" (LGRH4684)
     * r4 != 0 (WHO 1013): returns string "19" (H4684) or "26" (LGRH4684)
"""

from __future__ import annotations

import pytest

from OWNd.message import (
    OWNCommand,
    OWNEvent,
    OWNGatewayCommand,
    OWNGatewayDiagnosticCommand,
    OWNGatewayDiagnosticEvent,
    OWNGatewayEvent,
)
from OWNd.profiles import H4684Profile, get_gateway_profile


def test_h4684_synthetic_identification_trace_sequence():
    """Replay complete gateway identification sequence for BTicino H4684."""
    # Step 1: Client queries device type on WHO 13
    cmd_dev = OWNGatewayCommand.request_device_type()
    assert str(cmd_dev) == "*#13**15##"

    # Step 2: Gateway emits WHO 13 dimension 15 device type 13
    evt_dev = OWNEvent.parse("*#13**15*13##")
    assert isinstance(evt_dev, OWNGatewayEvent)
    assert evt_dev.device_type == "H4684"

    # Step 3: Client queries firmware version
    cmd_fw = OWNGatewayCommand.request_firmware_version()
    assert str(cmd_fw) == "*#13**16##"

    # Step 4: Gateway emits firmware version 2.0.54
    evt_fw = OWNEvent.parse("*#13**16*2*0*54##")
    assert isinstance(evt_fw, OWNGatewayEvent)
    assert evt_fw.firmware_version == "2.0.54"

    # Step 5: Client queries diagnostic object model on WHO 1013
    cmd_diag = OWNGatewayDiagnosticCommand.request_diagnostic_object_model()
    assert str(cmd_diag) == "*#1013**1##"

    # Step 6: Gateway emits 4-part WHO 1013 dimension 1 diagnostic response
    evt_diag = OWNEvent.parse("*#1013**1*19*15*5*0##")
    assert isinstance(evt_diag, OWNGatewayDiagnosticEvent)
    assert evt_diag.device_type == "H4684"
    assert evt_diag.object_model == "19"
    assert evt_diag.n_conf == "15"
    assert evt_diag.brand == "5"
    assert evt_diag.line == "0"

    # Step 7: Gateway profile binding
    profile = get_gateway_profile(evt_diag.device_type)
    assert isinstance(profile, H4684Profile)
    assert profile.model_name == "H4684"


def test_lgrh4684_synthetic_identification_trace_sequence():
    """Replay complete gateway identification sequence for Legrand LGRH4684."""
    # Step 1: Gateway emits WHO 13 dimension 15 device type 20
    evt_dev = OWNEvent.parse("*#13**15*20##")
    assert isinstance(evt_dev, OWNGatewayEvent)
    assert evt_dev.device_type == "LGRH4684"

    # Step 2: Gateway emits WHO 1013 dimension 1 diagnostic response (code 26)
    evt_diag = OWNEvent.parse("*#1013**1*26*15*5*0##")
    assert isinstance(evt_diag, OWNGatewayDiagnosticEvent)
    assert evt_diag.device_type == "LGRH4684"
    assert evt_diag.object_model == "26"
    assert evt_diag.n_conf == "15"
    assert evt_diag.brand == "5"
    assert evt_diag.line == "0"

    # Step 3: Resolves to H4684Profile via alias
    profile = get_gateway_profile(evt_diag.device_type)
    assert isinstance(profile, H4684Profile)
    assert profile.model_name == "H4684"


def test_h4684_catalogue_backward_compatibility():
    """Verify MHCatalogue.db modobj code 29, Nmap code 23, and MH201 code 10."""
    evt_cat = OWNEvent.parse("*#1013**1*29##")
    assert isinstance(evt_cat, OWNGatewayDiagnosticEvent)
    assert evt_cat.device_type == "H4684"
    assert evt_cat.object_model == "29"

    evt_nmap = OWNEvent.parse("*#13**15*23##")
    assert isinstance(evt_nmap, OWNGatewayEvent)
    assert evt_nmap.device_type == "H4684"

    evt_mh201 = OWNEvent.parse("*#1013**1*10##")
    assert isinstance(evt_mh201, OWNGatewayDiagnosticEvent)
    assert evt_mh201.device_type == "MH201"
    assert evt_mh201.object_model == "10"


def test_h4684_qemu_oracle_trace_corpus_outputs():
    """Verify exact frames emitted by H4684 020054 in own-firmware-oracle trace-corpus."""
    cmd_diag_where0 = OWNGatewayDiagnosticCommand.request_diagnostic_object_model("0")
    assert str(cmd_diag_where0) == "*#1013*0*1##"
    assert isinstance(OWNCommand.parse("*#1013*0*1##"), OWNGatewayDiagnosticCommand)

    evt_dev = OWNEvent.parse("*#13**15*13##")
    assert isinstance(evt_dev, OWNGatewayEvent)
    assert evt_dev.device_type == "H4684"
    assert evt_dev.device_type_code == "13"

    evt_fw = OWNEvent.parse("*#13**16*2*0*54##")
    assert isinstance(evt_fw, OWNGatewayEvent)
    assert evt_fw.firmware_version == "2.0.54"

    evt_kernel = OWNEvent.parse("*#13**23*2*0*5##")
    assert isinstance(evt_kernel, OWNGatewayEvent)
    assert evt_kernel.kernel_version == "2.0.5"

    evt_distro = OWNEvent.parse("*#13**24*3*0*0##")
    assert isinstance(evt_distro, OWNGatewayEvent)
    assert evt_distro.distribution_version == "3.0.0"

    evt_diag = OWNEvent.parse("*#1013**1*19##")
    assert isinstance(evt_diag, OWNGatewayDiagnosticEvent)
    assert evt_diag.device_type == "H4684"
    assert evt_diag.object_model == "19"

