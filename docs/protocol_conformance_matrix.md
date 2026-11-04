# OpenWebNet Protocol Conformance & Capability Matrix

> **Authoritative Specification & Verification Baseline**  
> *Last Updated: September 11, 2026*  
> *Corpus Version: 1.0.0 (58 Fixtures, 11 Subsystems, 137 Automated Conformance Assertions)*

This document serves as the **verifiable truth** for OpenWebNet protocol conformance across the Home Assistant (`OpenWebNet-HA/MyHOME`) and Python protocol driver (`OpenWebNet-HA/OWNd`) ecosystem.

---

## 1. The Three-Authority Triad

To prevent divergence and eliminate guesswork, every protocol frame and capability is evaluated against three distinct authorities:

| Authority | Reference Implementation | Role & Authority |
|---|---|---|
| **1. The Judge** | Legrand OpenWebNet Official Specification Manuals (interrogated via `openwebnet-mcp`) | **Legal Grammar**: Defines whether a frame syntax, dimension boundary, or parameter structure is strictly valid per Legrand standards. |
| **2. The Oracle** | `openwebnet4j` & openHAB OpenWebNet Binding (by Massimo Valla) | **Wire Baseline**: Provides empirical on-wire factory strings, real-world edge cases, and 10+ years of mature production testing. |
| **3. The SUT** | `OWNd` protocol engine & `custom_components/myhome` runtime | **System Under Test**: Must parse, validate, roundtrip serialize, and build frames with 100% fidelity. |

---

## 2. Subsystem Conformance & Capability Matrix

| WHO | Subsystem | Verified Operations | Canonical Frame Examples | Judge (Legrand PDF) | Oracle (openwebnet4j) | Runtime Status |
|:---:|---|---|---|:---:|:---:|:---:|
| **-** | **Signaling** | Gateway ACK / NACK | `*#*1##`, `*#*0##` | Valid | Matched | **VERIFIED (100%)** |
| **0** | **Scenarios** | Execute, Stop, Start | `*0*1*1##`, `*0*2*1##` | Valid | Matched | **VERIFIED (100%)** |
| **1** | **Lighting** | ON/OFF, Status, Speed Dimming, Private Bus (`#4#01`), Dimension writes | `*1*1*0311#4#01##`, `*1*1#5*12##`, `*#1*31*#1*150*5##` | Valid | Matched | **VERIFIED (100%)** |
| **2** | **Automation** | Shutter UP/DOWN/STOP, Bus Routing (`#4#01`), Slat Tilt, Position % | `*2*1*31#4#01##`, `*#2*31*#11#001*100##`, `*2*2*12##` | Valid | Matched | **VERIFIED (100%)** |
| **4** | **Thermoregulation** | Probe queries (`21.5°C`), Setpoints, Antifreeze, Negative Temp (`-4.8°C`) | `*#4*1*0*0215##`, `*#4*6*12*1048*3##`, `*#4*1*#14*0200*1##` | Valid | Matched | **VERIFIED (100%)** |
| **5** | **Burglar Alarm** | Zone status, CU status, Silent alarms, System arm/disarm | `*5*1*1##`, `*#5*1##`, `*5*2*2##` | Valid | Matched | **VERIFIED (100%)** |
| **9** | **Auxiliary** | Relay ON/OFF commands across auxiliary channels | `*9*1*1##`, `*9*0*1##` | Valid | Matched | **VERIFIED (100%)** |
| **13** | **Gateway Mgmt** | Firmware version, Gateway internal datetime requests | `*#13*0*0##`, `*#13*0*22##` | Valid | Matched | **VERIFIED (100%)** |
| **15** | **CEN Scenarios** | Press, short release, long release, extended hold | `*15*01*73##`, `*15*01#1*73##`, `*15*01#2*0110##`, `*15*01#3*0110##` | Valid | Matched | **VERIFIED (100%)** |
| **18** | **Energy Mgmt** | Instantaneous active power (W), Cumulative energy (kWh) | `*#18*51*113##`, `*#18*51*51##`, `*#18*51*52#26#9##` | Valid | Matched | **VERIFIED (100%)** |
| **25** | **CEN+ / Dry Contacts**| Short press; start, hold and release of an extended press; WHERE `2` + object 0–2047 | `*25*21#1*21##`, `*25*22#1*21##`, `*25*23#1*21##`, `*25*24#1*21##` | Valid | Matched | **VERIFIED (100%)** |

Sources for the examples changed in [OWNd#77](https://github.com/OpenWebNet-HA/OWNd/issues/77). The MyHomeServer1 firmware, run on an emulated bus, produces a bus frame for each of them and refuses the examples they replace. The WHO 15 press and short release (`*15*01*73##`, `*15*01#1*73##`) were captured on an MH200N + MyHomeServer1 bus in [MyHOME#541](https://github.com/OpenWebNet-HA/MyHOME/issues/541). Long release and extended hold (`#2`, `#3`) rest on the firmware alone. The WHO 25 examples are an MH201 capture from [MyHOME#418](https://github.com/OpenWebNet-HA/MyHOME/issues/418). The energy request `*#18*51*52#26#9##` was accepted by a real MyHomeServer1.

---

## 3. Key Architectural Truths & Design Decisions

### 3.1 String Preservation for Hardware Addresses
- **Observation**: Addresses such as `0311` (Lighting PTP) and `0110` (CEN) begin with leading zeros.
- **Verifiable Truth**: Addresses **must never be converted to integers** (`311` or `1`). In OpenWebNet, leading zeros denote specific address spaces and module wiring. OWNd strictly enforces string types for `where` across all subsystems.

### 3.2 Private Bus Routing (`#4#bus`)
- **Observation**: Installations with multiple physical SCS buses behind an F454 or 3486 gateway use interface routing (e.g. `*1*1*0311#4#01##`).
- **Verifiable Truth**: The interface routing suffix `#4#<interface>` is an addressing qualifier, not a dimension parameter. OWNd extracts this cleanly into `parsed.interface = '01'` and `parsed.where = '0311'`, preserving 100% roundtrip wire string equality.

### 3.3 Strict Standards vs. Tolerant Synthesis (The Alarm WHERE Omission)
- **Observation**: In `openwebnet4j`, frame `*5*7*##` (Alarm) synthesizes `WHERE = '0'` when the address is omitted.
- **Verifiable Truth**: Official Legrand specification PDFs require a target address for WHERE in WHO=5 command frames. `openwebnet-mcp` rejects `*5*7*##` as malformed syntax. OWNd conforms strictly to the standard by returning `None` for omitted mandatory fields.

### 3.4 Extended Thermoregulation (Dimension 12 Negative Temperatures)
- **Observation**: Physical temperature probes in outdoor zones report negative temperatures via Dimension 12: `*#4*6*12*1048*3##`.
- **Verifiable Truth**: The value parameter `1048` represents `-4.8°C` (the initial `1` indicates negative sign; `048` is tenths of a degree). OWNd decodes this mathematically into `_measured_temperature = -4.8`.

---

## 4. Independent Local Verification

Any contributor or user can independently verify this entire conformance suite with **zero third-party dependencies** directly against the Python standard library:

```bash
# Run 137 automated assertions against the golden corpus
python -m pytest tests/test_golden_conformance.py

# Run standalone schema & frame uniqueness validation
python tools/golden/validate_corpus.py
```
