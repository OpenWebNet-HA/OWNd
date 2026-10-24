# Changelog

All notable changes to `OWNd` are documented in this file.

## [Unreleased]

### Added
- **WHO 1 (`OWNLightingCommand`, `OWNLightingEvent`)**:
  - Automatic detection of legacy pre-`09W29` BTicino `F414` coarse-only dimmers via `DIMENSION 1` / `DIMENSION 4` transition speed `240` (`0xF0`, `DIMMER_SPEED_COARSE_ONLY`) with multi-gateway plant isolation (`gateway=` scoping on `OWNMessage.parse`, `OWNEvent.parse`, `OWNEventSession.get_next`, `is_coarse_dimmer_where`, `register_coarse_dimmer_where`, `clear_coarse_dimmer_wheres`, and `OWNLightingCommand.set_brightness`) (`#134`, `MyHOME#767`).
  - Canonical `libqtdevices` (`TS10_1_0_23`) coarse `WHAT 2..10` $\leftrightarrow$ fine `1..100%` conversion helpers (`COARSE_PRESET_TO_PERCENT`, `brightness_preset_to_percent`, `percent_to_brightness_preset`), `OWNLightingEvent.is_coarse_dimmer`, `OWNLightingEvent.brightness_preset_percent`, and `OWNLightingCommand.set_brightness(..., coarse=..., gateway=...)` (`#134`).
  - `WHAT 39` end of movement (`*1*39*WHERE##`) from WHO 1 motion detectors: `message_type` `motion_detected` with `motion` `False`, new `OWNLightingEvent.motion_end`, `is_sensor` `True`, `is_on` `None`. It was `unknown_state` `39` before (`MyHOME#777`).

### Fixed
- **WHO 4 Dimension 22 is never sent**: `OWNCommandSession.send` (and so `AsyncTcpTransport.send` and `send_to_gateway`) and `AsyncSerialTransport.send` refuse any WHO 4 Dimension 22 frame with `OWNProtocolError(reason="destructive_frame")` before writing: `*#4*ZONE*22##` crashes the gateway's thermoregulation daemon and reboots an F461 (own-firmware-oracle `tools/expected_divergences.yaml` crash frames, live F461 2.0.11). The detector `is_who4_dimension_22()` is public.

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
