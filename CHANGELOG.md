# Changelog

All notable changes to `OWNd` are documented in this file.

## [Unreleased]

### Added
- **WHO 1 (`OWNLightingCommand`, `OWNLightingEvent`)**:
  - Automatic detection of legacy pre-`09W29` BTicino `F414` coarse-only dimmers via `DIMENSION 1` / `DIMENSION 4` transition speed `240` (`0xF0`, `DIMMER_SPEED_COARSE_ONLY`) with multi-gateway plant isolation (`gateway=` scoping on `OWNMessage.parse`, `OWNEvent.parse`, `OWNEventSession.get_next`, `is_coarse_dimmer_where`, `register_coarse_dimmer_where`, `clear_coarse_dimmer_wheres`, and `OWNLightingCommand.set_brightness`) (`#134`, `MyHOME#767`).
  - Canonical `libqtdevices` (`TS10_1_0_23`) coarse `WHAT 2..10` $\leftrightarrow$ fine `1..100%` conversion helpers (`COARSE_PRESET_TO_PERCENT`, `brightness_preset_to_percent`, `percent_to_brightness_preset`), `OWNLightingEvent.is_coarse_dimmer`, `OWNLightingEvent.brightness_preset_percent`, and `OWNLightingCommand.set_brightness(..., coarse=..., gateway=...)` (`#134`).
  - `WHAT 39` end of movement (`*1*39*WHERE##`) from WHO 1 motion detectors: `message_type` `motion_detected` with `motion` `False`, new `OWNLightingEvent.motion_end`, `is_sensor` `True`, `is_on` `None`. It was `unknown_state` `39` before (`MyHOME#777`).
- **WHO 4 (`OWNHeatingCommand.actuators_status`)**: Actuator status request `*#4*WHERE*20##` for a zone (`0..99`, `#Z`), one actuator (`2#1`; `N` is one digit, `2#0` for all actuators of the zone) or `#0` / `#0#N` (central unit); three-digit secondary probes (`105`) and multi-digit actuator indices (`2#10`) are refused. A live F461 2.0.11 answers it per actuator (`*#4*2#1*20*0##`, `*#4*2#2*20*5##`). The address may carry a bus-interface suffix (`3#4#01`, `#3#4#01`, `2#1#4#01`; two-digit interface) as spec-legal grammar, but callers must gate it on the profile's `supports_interface_zone_requests` (`MyHOME#816`): own-firmware-oracle#65 shows no emulated firmware routes `*#4*2#4#01*20##` across an F422; F450, F454, F459, F460, F461 and MyHomeServer1 truncate `WHERE` at the first `#` and poll local zone 2, MH202 010024 reads `#4#01` as local zone 4 actuator 1, and F453, F453AV, H4684, MH200, MH200N drop it. The MH202 010024 crash in that suite hits the dimensionless status forms `*#4*2#1##` and `*#4*2#4#01##`, which the builder never emits (`MyHOME#792` review).
- **WHO 1001 (`OWNLightingDiagnosticEvent`)**: Actuator autodiagnostic mask of lighting and automation actuators (`*#1001*WHERE*11*<mask>##` and `*#1001*WHERE*7*<mask>##`, DIMENSIONS 11 and 7 = `BITMASK_DIA_A`), exposed as sent (`diagnostic_mask`, `cleared_bits`) when the value is a single 24-character `0`/`1` string, `None` on a DIMENSION 7 / 11 value frame of another shape; bit meanings are not known. The frame is pushed after `*1*19*WHERE##` on a faulty actuator (own-firmware-oracle `what19` on eight emulated gateways; MyHOME fixtures `issue_619` F453AV, `issue_466` / `issue_733` MH200), pushed alongside normal `*1*0/1*WHERE##` sweep replies on an MH200N (`issue_434`, `issue_746`), answered on a direct `*#1001*WHERE*11##` read (live F461 2.0.11 and MyHomeServer1 3.87.13, 2026-10-24), and sent as DIMENSION 7 on `WHERE 0` by a MyHomeServer1 cover diagnostic (`issue_466`). Routed (`74#4#01`), 4-digit, `0` and empty WHERE forms parse; `interface` / `unique_id` cover WHO 1001. The README WHO catalog lists WHO 1001.

### Changed
- `OWNTransport.send()` takes the same `raise_on_error` keyword as `OWNCommandSession.send()` on `AsyncTcpTransport` and `AsyncSerialTransport`, and `OWNTransport.last_error` holds the error recorded by the last `send()`: a local refusal on both transports, and on the TCP transport everything its command session records (NACK, timeout, connection errors). Both transports now share one contract: `RuntimeError` when not connected, then a frame refused locally is logged at ERROR, kept in `last_error` and answered with `None`, or raised as `OWNProtocolError` with `raise_on_error=True`.
### Fixed
- **WHO 4 Dimension 22 without an actuator token is never sent**: Dimension 22 is the published split-unit IR control (`*#4*3#Z#N*22##` / `*#4*3#Z#N*#22*MOD*SP*VEL*SWING##`, WHO 4 specification pp. 66-68). Sent to a zone (`*#4*Z*22##`, `*#4*0ZZ*22##`), to every zone (`*#4*0*22##`) or to the central unit (`*#4*#0*22##`), as a read or a write, it crashes the thermoregulation daemon (`bt_termo`) on nine of the twelve emulated Linux IP gateways and reboots an F461 2.0.11 about three minutes later (own-firmware-oracle `thermo-dim22` suite and `tools/expected_divergences.yaml` crash frames, live F461 2.0.11). The published split forms and the actuator form `*#4*Z#N*22##` crashed none of the twelve gateways (ten forward them to the bus as a telegram to zone Z, actuator N; own-firmware-oracle `findings/thermo-dim22.md`), so their canonical spellings (`Z` 0..99, `N` 1..9) are sent; every other spelling (leading zeros, whitespace or `+` tokens, `#Z`, `#0#C`, `Z#4#IF`, `N` 0 or two digits, a dimension parameter) stays refused. `OWNCommandSession.send` (and so `AsyncTcpTransport.send` and `keepalive`), and `AsyncSerialTransport.send` refuse a crash form before anything is written, with the contract above and `reason="destructive_frame"`; `OWNCommandSession.send_to_gateway` refuses it before `connect()` (no socket, no handshake), logs it at ERROR and answers `None`, or raises `OWNProtocolError` with `raise_on_error=True` (the session it would have used is discarded, so no `last_error` is observable on that path). The detector `is_who4_dimension_22()` recognises every Dimension 22 spelling; the send paths refuse `is_who4_dimension_22_crash_form()`, both public, accepting `bytes`, and anchored to the first `*` of each frame, so a mid-frame WHERE `#4` / DIMENSION `#4` such as `*#2*#4*#11#001*22##` or `*#1*14*#4*1*22##` stays sendable. Parsing is unchanged: the frame can still be read from the bus.
- **`AsyncSerialTransport.send` validates outbound frames** like `OWNCommandSession.send`: an invalid or signaling frame (for example the single-`#` concatenation `*1*1*11#*#4*2*22##`) is refused with `reason="invalid_frame"` instead of being written to the port. The frame is serialised once, terminator included: the string checked is the string written.

## [2.0.0b11] - 2026-10-20

### Added
- **WHO 0 (`OWNScenarioEvent`)**: Decode `WHAT 40–46` programming and lock states (`#90`).
- **WHO 1 (`OWNLightingCommand`, `OWNLightingEvent`)**:
  - Presets, step dimming, fixed timers, and variable timer builders (`#93`).
  - `WHAT 19` anomaly / fault state modeling (`#115`).
  - Public APL normalization (`normalize_where`) and DALI / RGB / HSV / XY / colour-temperature accessors (`#123`).
- **WHO 3 (`OWNLoadEvent`, `OWNLoadCommand`)**: Load control parser, command builders, typed measurement properties for dimensions 1–4 (`voltage`, `current`, `power`, `energy`), and gateway profile gating (`#104`, `#124`).
- **WHO 4 (`OWNHeatingEvent`, `OWNHeatingCommand`)**: Consolidated firmware-validated heating support including season frames (`WHAT 0` / `WHAT 1`), central unit status (`WHAT 22–24`, `30–31`), holiday/vacation program handling (`WHAT 115#P`, `13DDD#P`, `3101–3103`), and F453AV / F461 live-plant conformance (`#83`, `#97`, `#116`, `#119`, `#120`).
- **WHO 6 & WHO 8 (`OWNDoorEntryEvent`, `OWNDoorEntryCommand`)**: Door entry, lock, camera, and intercom call dialects (`#100`).
- **WHO 13 & WHO 1013 (`OWNGatewayEvent`, `OWNGatewayCommand`)**:
  - Typed gateway clock, timezone, `kernel_version`, `distribution_version`, and diagnostic properties and builders (`#112`, closes `#111`).
  - H4684 / LGRH4684 / MH201 gateway identification profiles and WHO 1013 device diagnostic frame support (`#118`).
- **WHO 14 (`OWNActuatorLockEvent`, `OWNActuatorLockCommand`)**: Actuator lock and unlock (`WHAT 0` / `WHAT 1`) event parser and command builders (`#130`).
- **WHO 16 (`OWNSoundEvent`, `OWNSoundCommand`)**: Sound system media transport commands, tuner frequency/station decoding, and L4561N source selection (`#95`, `#123`).
- **WHO 17 (`OWNSceneCommand`)**: Complete scene command factory surface (`#99`).
- **WHO 18 (`OWNEnergyEvent`, `OWNEnergyCommand`)**:
  - Dimension `1200` automatic power-update stream lifecycle properties (`stream_duration`, `is_streaming_active`, `energy_type`), `stop_sending_instant_power`, and `request_active_power` / `get_instant_power` builders (`#92`, `#102`, `#107`).
  - Stop&Go (`F16EB`) automatic reset breaker commands and status flag dimensions `212`, `250`, `251–263` (`#113`, `#122`).
- **WHO 22 (`OWNSoundDiffusionEvent`, `OWNSoundDiffusionCommand`)**: Advanced sound diffusion 2.0 events and commands (power-on, atomic off, matrix routing, paging, keypad, 100 kHz tuner frequency, presets, 8-character RDS, and `MH200NProfile` support) (`#103`, `#127`).
- **WHO 25 (`OWNScenarioPlusEvent`, `OWNScenarioPlusCommand`)**: Scenario-plus `WHAT 11–15` parser and command builders (`#91`, `#106`).
- **Virtual-device expose support (`#129`)**:
  - Query and translation helpers on `OWNMessage` (`is_status_request`, `is_dimension_request`, `is_dimension_writing`, `is_dimension_reply`, `effective_what`) and per-WHO query properties (`is_brightness_query`, `is_shutter_status_query`, `is_temperature_query`, `is_clock_query`, `is_dimension_query`, `is_auto_update_command`).
  - Reply and write builders: `OWNLightingCommand.report_brightness`, `OWNAutomationCommand.report_shutter_level`, `OWNHeatingCommand.report_temperature` / `write_temperature` / `encode_temperature`, `OWNGatewayCommand.set_*` / `report_*` for time, date and datetime, and `OWNEnergyCommand.report_*` for dimensions `113`, `51`–`54` and `1200`.
  - `OWNHeatingEvent.probe_temperature` for 3-digit external probes.
  - `GatewayProfile` flags `supports_dimension_response_injection`, `supports_who4_command_injection` and `supports_who18_response_injection` (`bool | None`; `None` means unverified, only `F461Profile` sets them from live captures).
- **Typed exceptions (`#132`)**: `OWNError`, `OWNConnectionError`, `OWNTimeoutError`, `OWNAuthError`, `OWNNackError` and `OWNProtocolError` in `OWNd.exceptions`, re-exported from `OWNd` and `OWNd.connection`; `session.last_error`, opt-in `raise_on_error` on the connect, test and send APIs, and `on_auth_error` / `raise_on_auth_error` on `OWNEventSession`.
- **Firmware Oracle & Documentation Conformance**:
  - Firmware oracle conformance suite across emulated gateways (`#84`, `#117`, `#126`).
  - Unified documentation synchronization sentinel (`scripts/sync_documentation.py`) verifying WHO catalog, gateway profile tables, and coverage badges (`#101`, `#105`, `#108`).

### Changed
- **Packaging & Dependencies**:
  - Normalize version string to canonical PEP 440 (`2.0.0b11`).
  - Migrate package metadata to PEP 621 `[project]` and PEP 639 `license = "Apache-2.0"` in `pyproject.toml`.
  - Drop unused `pytz` and `python-dateutil` runtime dependencies in favor of Python 3.11+ standard library `datetime` and `zoneinfo` (with `tzdata` included in `[test]` on Windows).
- **Input Validation & Connection Reliability**:
  - Harden bounds and infeasible input validation across WHO subsystems and connection sessions (`#121`, `#125`, `#127`, `#128`).
  - Only retry idempotent status queries in `OWNCommandSession` after mid-send transport loss (`#131`).
  - `OWNCommandSession.send()` reconnects at most once, with a 2 s cooldown, instead of running the full backoff while holding the send lock; routine send logs move from `INFO` to `DEBUG` (`#132`). Callers that need the full 5-attempt retry, such as after closing an idle socket on a single-slot MH201, call `connect()` first (`#133`).
- **API**:
  - `set_datetime_to_now`, `set_date_to_today` and `set_time_to_now` accept a `datetime.tzinfo` as well as an IANA name; transport `send` accepts `str | OWNMessage`; `OWNd.connection` uses static re-exports (`#132`).
  - `OWNd.connection.gateway` no longer resolves `find_gateways` / `get_gateway` / `get_port` through the package at call time, so tests must patch `OWNd.connection.gateway.*` (`#133`).
  - WHO 13 builders raise `ValueError` for UTC offsets that are not whole hours (for example `Asia/Kolkata`), which the `0HH` / `1HH` field cannot carry, instead of truncating them (`#129`).
