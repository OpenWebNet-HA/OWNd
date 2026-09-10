# OWNd

[![PyPI version](https://img.shields.io/pypi/v/OWNd.svg?color=blue)](https://pypi.org/project/OWNd/)
[![Python versions](https://img.shields.io/pypi/pyversions/OWNd.svg)](https://pypi.org/project/OWNd/)
[![CI](https://github.com/OpenWebNet-HA/OWNd/actions/workflows/ci.yml/badge.svg)](https://github.com/OpenWebNet-HA/OWNd/actions/workflows/ci.yml)
[![License: LGPL-3.0](https://img.shields.io/badge/License-LGPL--3.0-blue.svg)](https://www.gnu.org/licenses/lgpl-3.0)
[![Ruff](https://img.shields.io/endpoint?url=https://raw.githubusercontent.com/astral-sh/ruff/main/assets/badge/v2.json)](https://github.com/astral-sh/ruff)
[![Coverage](coverage.svg)](coverage.svg)

**OWNd** is an asynchronous Python library and daemon for the Legrand / BTicino **OpenWebNet** home automation protocol.

It powers the [Home Assistant MyHOME integration](https://github.com/OpenWebNet-HA/MyHOME) and serves as a standalone Python client for discovering, monitoring, and controlling OpenWebNet bus devices over TCP/IP gateways and serial USB interfaces.

---

## Key Features

- **Hardened Dual-Session Architecture**: Decouples real-time bus event monitoring (`OWNEventSession`) from command and query execution (`OWNCommandSession`), preventing command bursts from interrupting event monitoring.
- **Serial & USB Dongle Support**: Built-in single-channel serial transport (`AsyncSerialTransport`) for the Legrand 3578 USB/ZigBee interface with in-band event and command-reply demultiplexing.
- **Connection Resilience**:
  - Fail-closed SHA-1 and HMAC-SHA2 gateway authentication with constant-time signature verification.
  - OS-level TCP keepalive (`SO_KEEPALIVE`) with aggressive probing (30s idle / 10s interval / 3 count) to detect silent network drops (power loss, cable unplugged) in ~60s.
  - Periodic application-level keepalives and passive watchdogs.
  - Non-blocking bounded timeouts on handshakes and commands to prevent event loop stalls.
  - Multi-frame response collection for large bus status sweeps (up to 256 frames).
- **Declarative Hardware Profiles**: Tailored queue pacing, session concurrency, and subsystem limits for known Legrand/BTicino hardware (F454, F455, MH200N, MH201, MH202, MyHomeServer1, and conservative generic fallbacks).
- **Modern Python**: Designed for Python **3.11+**, tested continuously against Python 3.11, 3.12, 3.13, and 3.14.

---

## Installation

Install the latest stable release from PyPI:

```bash
pip install OWNd
```

To test preview releases or beta builds:

```bash
pip install --pre OWNd
```

### Optional Extras

- **Serial / USB support** (required for Legrand 3578 USB dongles):
  ```bash
  pip install "OWNd[serial]"
  ```
- **Development & test suite**:
  ```bash
  pip install "OWNd[test]"
  ```

---

## Supported Subsystems (WHO Catalog)

OWNd parses OpenWebNet frames and dispatches typed commands and events across the full MyHOME spectrum:

| WHO | Subsystem | Description & Capabilities | Event / Command Classes |
|:---:|:---|:---|:---|
| **1** | Lighting | On/off switching, dimming level (0–100%), status queries | `OWNLightingCommand`, `OWNLightingEvent` |
| **2** | Automation | Shutters, blinds, motorized curtains, tilt angles, short & full replies | `OWNAutomationCommand`, `OWNAutomationEvent` |
| **3** | Load Control | Load shedding status, circuit priority management | `OWNCommand`, `OWNEvent` |
| **4** | Thermoregulation / Climate | Multi-zone temperature readouts, target adjustments, HVAC modes (Heat/Cool/Auto/Off), local offsets, fan coil speeds, valve states | `OWNHeatingCommand`, `OWNHeatingEvent` |
| **5** | Burglar Alarm | Zone status, system arming / disarming states | `OWNAlarmCommand`, `OWNAlarmEvent` |
| **13** | Gateway Diagnostics & Clock | Gateway date/time synchronization, timezone offsets, firmware metadata | `OWNGatewayCommand`, `OWNGatewayEvent` |
| **15** | CEN Scenarios | Scenario control, pushbutton push/release/extended press events | `OWNCENEvent`, `OWNScenarioEvent` |
| **16** / **22** | Sound Diffusion | Multi-source selection, zone activation, volume adjustment, F441 matrix | `OWNSoundCommand`, `OWNSoundEvent`, `OWNAVCommand` |
| **17** | Scenario Programmer | MH200N / MH202 scenario activation and state monitoring | `OWNSceneEvent` |
| **18** | Energy Management | Active power (W), hourly/daily/monthly consumption (kWh), Stop & Go breaker diagnostics | `OWNEnergyCommand`, `OWNEnergyEvent` |
| **25** | CEN+ & Dry Contacts | 32-button keypads, rotary knob encoders (CW/CCW), dry contacts, PIR sensors | `OWNCENPlusEvent`, `OWNDryContactCommand`, `OWNDryContactEvent` |

---

## Hardware Gateway Profiles

Gateways have varying processing limitations, socket budgets, and pacing requirements. OWNd uses declarative profiles to protect your hardware:

| Gateway Model | Concurrency | Queue Delay | Keepalive | Features |
|:---|:---:|:---:|:---:|:---|
| **MyHomeServer1** | 4 sessions (2 default) | 20 ms | Profile | HMAC-SHA2, Native transitions, Extended frames |
| **F454 / F455** | 4 sessions | 50 ms | 90 s | HMAC-SHA2, Native transitions, Extended frames |
| **MH202** | 2 sessions | 100 ms | Profile | HMAC-SHA2, Extended frames |
| **MH201** | 1 session | 100 ms | Profile | Extended frames, Clock diagnostics |
| **MH200N** | 1 session | 150 ms | 90 s | Safe pacing, Legacy password auth |
| **Generic Gateway** | 1 session | 50 ms | Profile | Conservative fallback |

Profiles can be resolved automatically using `get_gateway_profile(model_name)`:

```python
from OWNd.profiles import get_gateway_profile

profile = get_gateway_profile("F454")
print(f"Max concurrent sessions: {profile.max_command_sessions}")
print(f"Command queue delay: {profile.command_queue_delay}s")
```

---

## Quick Start

### 1. High-Level TCP Transport (Dual-Session)

```python
import asyncio
from OWNd.connection import OWNGateway
from OWNd.transport.tcp import AsyncTcpTransport
from OWNd.message import OWNMessage

async def main():
    # Configure gateway credentials
    gateway = OWNGateway({
        "address": "192.168.1.50",
        "port": 20000,
        "password": "12345",
    })

    transport = AsyncTcpTransport(gateway)

    # Register an event listener for bus notifications
    def on_event(msg: OWNMessage | str):
        if isinstance(msg, OWNMessage) and msg.is_event:
            print(f"Bus Event: {msg.human_readable_log}")

    transport.register_listener(on_event)

    # Connect both event and command channels
    if await transport.connect():
        print("Connected to OpenWebNet gateway!")

        # Send a command: Turn ON light at address 12 (*1*1*12##)
        response = await transport.send("*1*1*12##")
        print(f"Command response: {response}")

        # Keep listening for events
        await asyncio.sleep(10)
        await transport.disconnect()

if __name__ == "__main__":
    asyncio.run(main())
```

### 2. Direct Session Management

For fine-grained control, `OWNEventSession` and `OWNCommandSession` can be operated independently:

```python
import asyncio
from OWNd.connection import OWNGateway, OWNEventSession, OWNCommandSession

async def main():
    gateway = OWNGateway({"address": "192.168.1.50", "port": 20000, "password": "12345"})

    # Event listening session
    event_session = OWNEventSession(gateway=gateway)
    await event_session.connect()

    # Command session
    command_session = OWNCommandSession(gateway=gateway)
    await command_session.connect()

    # Query status of zone 1 climate: *#4*1*0##
    status = await command_session.send("*#4*1*0##", is_status_request=True)
    print(f"Status response: {status}")

    await event_session.close()
    await command_session.close()

asyncio.run(main())
```

### 3. Serial / USB Dongle (Legrand 3578)

```python
import asyncio
from OWNd.transport.serial import AsyncSerialTransport

async def main():
    transport = AsyncSerialTransport(port="/dev/ttyUSB0")
    transport.register_listener(lambda msg: print(f"Serial Inbound: {msg}"))

    await transport.connect()
    # Send OpenWebNet frame over serial
    await transport.send("*1*1*12##")

    await asyncio.sleep(5)
    await transport.disconnect()

asyncio.run(main())
```

---

## Command Line Interface (CLI)

OWNd includes a built-in CLI for discovering gateways and inspecting live bus events:

### Auto-Discovery (SSDP)

Scan the local network for OpenWebNet gateways and listen for events:

```bash
python -m OWNd
```

### Direct Connection

Connect to a known gateway IP address:

```bash
python -m OWNd --address 192.168.1.50 --port 20000 --password 12345 --verbose 2
```

Available options:
- `-a`, `--address`: IP address of the gateway
- `-p`, `--port`: Gateway TCP port (default: `20000`)
- `-P`, `--password`: Numeric OPEN password or HMAC secret (default: `12345`)
- `-m`, `--mac`: MAC address (used as unique identifier when skipping SSDP)
- `-v`, `--verbose`: Verbosity level (`0` = WARNING, `1` = INFO, `2` = DEBUG)

---

## Development

Clone the repository and install development dependencies:

```bash
git clone https://github.com/OpenWebNet-HA/OWNd.git
cd OWNd
pip install -e ".[test,serial]" ruff mypy types-python-dateutil types-pytz
```

### Running Tests

Execute the test suite across all subsystems:

```bash
python -m pytest -q
```

### Static Analysis & Linting

Verify type safety and coding standards:

```bash
ruff check OWNd tests setup.py
mypy OWNd
```

---

## License

This project is licensed under the **GNU Lesser General Public License v3.0 (LGPL-3.0-only)**. See the [LICENSE](LICENSE) file for details.


## 📊 Code Coverage & Quality Assurance

OWNd maintains an automated unit test suite with strict line coverage tracking across all core modules:

<!-- START_COVERAGE_TABLE -->

| Component / Module | Coverage | Notes |
|---|:---:|---|
| [`OWNd/__init__.py`](OWNd/__init__.py) | **100%** | Package initialization and version metadata |
| [`OWNd/transport/__init__.py`](OWNd/transport/__init__.py) | **100%** | Transport subpackage exports |
| [`OWNd/transport/base.py`](OWNd/transport/base.py) | **100%** | Abstract transport layer and event listener notification contracts |
| [`OWNd/profiles.py`](OWNd/profiles.py) | **96%** | Declarative hardware gateway models (F454, MH200N, MH201, MH202, MyHomeServer1) |
| [`OWNd/discovery.py`](OWNd/discovery.py) | **96%** | SSDP multicast and UPnP XML gateway discovery and descriptor parsing |
| [`OWNd/transport/tcp.py`](OWNd/transport/tcp.py) | **96%** | Dual-session TCP transport linking event and command channels |
| [`OWNd/transport/serial.py`](OWNd/transport/serial.py) | **93%** | Async Serial/USB transport for Legrand 3578 interface with in-band demux |
| [`OWNd/connection.py`](OWNd/connection.py) | **92%** | Hardened dual-session TCP engine, SHA-1/HMAC auth, keepalives & bounded read loops |
| [`OWNd/message.py`](OWNd/message.py) | 86% | OpenWebNet frame parsers, encoders, and WHO dimension decoders |

<!-- END_COVERAGE_TABLE -->
