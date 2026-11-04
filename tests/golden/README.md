# OpenWebNet Golden Corpus Conformance Suite

A declarative conformance suite of OpenWebNet frames providing cross-framework verification across Home Assistant (`MyHOME` / `OWNd`), openHAB (`openwebnet4j` & `org.openhab.binding.openwebnet`), and official Legrand OpenWebNet specifications via `openwebnet-mcp`.

## The Three Authorities Triad

| Layer | Source | Role |
|---|---|---|
| **Judge** | Official Legrand PDFs via `openwebnet-mcp` | Validates whether a frame is syntactically legal (its semantics are not authoritative; see Provenance below) |
| **Oracle** | `openwebnet4j` & openHAB binding (by Massimo Valla) | Provides mature reference factory outputs and empirical test vectors |
| **Firmware Translation Oracle** | `own-firmware-oracle` (`tests/golden/firmware_oracle.json`) | Provides hash-pinned empirical verdicts, gateway reply codes, and bus frames from real emulated BTicino/Legrand gateway binaries |
| **SUT** | `OWNd` / `custom_components/myhome` | System Under Test: verified against judge and oracle |

## Provenance: which fixtures may change

Only `community-plant-capture` fixtures were recorded from a real bus. They are facts: never edit their frame, `what`, `where` or dimension values. If OWNd disagrees with a capture, OWNd is wrong.

Every other source (`legrand-spec`, `encyclopedia`, `openwebnet4j`, `public-readme`, `mcp-draft`) is a reading of a document or of another implementation, and can be wrong. Such a fixture may be corrected, but only in a commit that names the source it now follows (page and commit) and explains what was wrong.

- `mcp_valid: true` means openwebnet-mcp accepted the **grammar**. It is not evidence of meaning: the judge's WHO 15 catalog described `*15*1*11#2##` as "short press on button 2", which is how three wrong CEN fixtures entered this corpus (corrected in OpenWebNet-HA/OWNd#49). Its WHO 25 catalog did the same for `*25*21#1*12##`, `*25*22#1*12##` and `*25*24#1*12##`: `12` is not a CEN+ Object (`WHERE` is `2` + Object 0..2047). Those were replaced by a capture in the same PR.
- A `builder:` block proves the builder matches the fixture, not that either is right. When both are written in the same change from the same reading, the test only compares the code with itself. Prefer builder parity against a capture or an independent source such as `openwebnet4j`.
- When a capture arrives for a frame that so far exists only as a spec-derived fixture, add the capture and keep the spec entry only if it agrees.

## Supported Subsystems Catalog (118 Fixtures)

- **Signaling (`who00_signaling.yaml`)**: Gateway ACK (`*#*1##`) and NACK (`*#*0##`).
- **WHO=0 Scenarios (`who00_scenario.yaml`)**: Basic scenario execution and stop.
- **WHO=1 Lighting (`who01_lighting.yaml`)**: Point-to-point ON/OFF, status requests, local bus routing (`0311#4#01`), group broadcast, speed transitions (`*1*1#5*12##`), and dimension writes.
- **WHO=2 Automation (`who02_automation.yaml`)**: Shutter UP/DOWN/STOP, local bus routing (`21#4#01`; the firmware refuses a one-digit interface), absolute position percentages, and slat tilt angles. Records tagged `scope` pin OWNd's general / area / group classification; an MH201 capture (MyHOME#433) adds an area-1 stop echo (`*2*0*1##`) and the per-actuator end-of-run stop that closes a general UP: a scope command never gets a stop of its own (WHO_2.pdf §3.0.1). A group run from the MyHOME MH201 plant fixture (`*2*0*#1##`, `*2*2*#1##`) shows the same rule for groups, with each position-reporting actuator also echoing the command right away.
- **WHO=4 Thermoregulation (`who04_thermo.yaml`)**: Measured temperature queries (`21.5°C`), setpoint writes, Antifreeze/Protection modes, and negative temperature probe status (`-4.8°C`). Two MyHomeServer1 + Home+Control plants (MyHOME#429) add dimension 7, which carries the zone state and setpoint on those plants and is not in `WHO_4 2.pdf`: cooling and heating setpoints, protection (the zone is OFF: `*4*202*Z##` in cooling, `*4*102*Z##` antifreeze at 7.0 °C in heating), the 35.0 °C protection value sent just before a real setpoint, MyHomeServer1's `*#4*Z*#7*...##` program writes, and the dimension 5 re-assert.
- **WHO=5 Burglar Alarm (`who05_alarm.yaml`)**: Status requests and silent alarm events across zones and central units.
- **WHO=9 Auxiliary (`who09_auxiliary.yaml`)**: Activation and deactivation of AUX relay channels.
- **WHO=13 Gateway Management (`who13_gateway.yaml`)**: Firmware versions and gateway internal datetime responses.
- **WHO=15 CEN Pushbuttons (`who15_cen.yaml`)**: Pressure, short release, long release and extended pressure (`*15*BUTTON[#1|#2|#3]*WHERE##`), with a four-digit source address captured on an MH200N + MyHomeServer1 bus (`0512`, MyHOME#624).
- **WHO=18 Energy Management (`who18_energy.yaml`)**: Instantaneous active power and cumulative energy totalizers.
- **WHO=25 CEN+ / Dry Contacts (`who25_cen_plus.yaml`)**: CEN+ short press, hold start, hold repeat and release (`*25*21..24#PUSHBUTTON*2OBJECT##`, captured on an MH201) and a dry-contact event captured on an H4890 (`*25*31#1*339##`; on the bus, dry-contact WHEREs start with `3`).

## Directory Structure

```text
tests/golden/
  README.md                     # This documentation
  SOURCE.yaml                   # Provenance manifest of authorities
  schema.json                   # JSON Schema (Draft-07) for frame records
  frames/
    who00_signaling.yaml        # Bus signaling (ACK/NACK)
    who00_scenario.yaml         # WHO=0 Basic Scenarios
    who01_lighting.yaml         # WHO=1 Lighting
    who02_automation.yaml       # WHO=2 Covers & Shutters
    who04_thermo.yaml           # WHO=4 Heating & Cooling
    who05_alarm.yaml            # WHO=5 Burglar Alarm
    who09_auxiliary.yaml        # WHO=9 Auxiliary Relays
    who13_gateway.yaml          # WHO=13 Gateway Management
    who15_cen.yaml              # WHO=15 CEN Scenario Buttons
    who18_energy.yaml           # WHO=18 Energy Management
    who25_cen_plus.yaml         # WHO=25 CEN+ & Dry Contacts
tools/golden/
  validate_corpus.py            # Corpus schema validator
  harvest_4j_fixtures.py        # Oracle test harvester & divergence detector
  HARVEST_REPORT.md             # Harvest analysis report
tests/golden/
  corpus.json                   # Zero-dependency standard library runtime cache
  firmware_oracle.json          # Hash-pinned empirical verdict index from own-firmware-oracle
tests/
  test_golden_conformance.py    # Pytest suite running conformance tests
  test_firmware_oracle_conformance.py # Pytest suite testing parser resilience against real firmware
docs/
  protocol_conformance_matrix.md # Verifiable truth matrix across all 11 subsystems
```

## Firmware Oracle Dataset (`tests/golden/firmware_oracle.json`)

The firmware oracle fixture captures empirical OpenWebNet protocol execution across the BTicino/Legrand gateway fleet generated by `own-firmware-oracle`.

- **Schema Version**: `1.1.0` (Format `1.0.0`)
- **Digest Pin**: `verdicts_sha256`: `e9278a04d546fb6bb41fbca64a168fbdb4964f784fb1f8f00f4c45c5d721f020`
- **Total Unique Input Frames**: 509 frames across 22 test suites
- **Total Verdict Rows**: 6,500 empirical verdicts across 12 emulated gateways (540–544 rows each)
- **Fleet Emulation Status**:
  - **12 Emulated**: `F450` (020010), `F453` (010100), `F453AV` (030014), `F454` (020051), `F459` (020105), `F460` (020012), `F461` (020011), `H4684` (020054), `MH200` (020102), `MH200N` (010108), `MH202` (010024), `MyHomeServer1` (028206).
  - **5 Catalogued**: `3550` (030020), `F455` (010102), `L4561N` (040006), `L4686SDK` (012001), `MH201` (030644).

### Key Architectural Behaviors & Empirical Insights

1. **Deterministic Emulation & Zero Crashes**: With `own-firmware-oracle`, all 12 emulated gateways complete execution with **0 crashes and 0 timeouts** across all 6,500 verdict rows.
2. **NACK with SCS Bus Forwarding**: 1,081 rows return NACK at the command session while echoing the telegram onto the SCS bus (predominantly `F460`, `F461`, and `MyHomeServer1` with 228 rows each, `MH202` with 70 rows, `F453`, `F453AV`, and `MH200N` with 53 rows each, `F454` and `F459` with 51 rows each, `MH200` with 24 rows, `H4684` with 23 rows, and `F450` with 19 rows).
3. **PIC Bus Dispatch vs Actuator Replies**: In energy management, requests like `*#18*51*51##` are accepted (`ack`, `out`) and dispatched to the PIC serial bus (`$06D1A1023350150000\r`). On physical plants with active energy meters, an actuator responds with the dimension value (`*#18*51*51*23791364##`); in the emulator, the forward is verified while no actuator is attached.

## Running Conformance Verification

To validate all YAML fixtures against `schema.json` and synchronize `corpus.json`:
```bash
python tools/golden/validate_corpus.py
```

To run the automated pytest conformance suite:
```bash
python -m pytest tests/test_golden_conformance.py tests/test_firmware_oracle_conformance.py -v
```
