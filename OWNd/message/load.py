"""WHO 3: Load control (load shedding) events and commands.

Evidence, in order of weight:

- Firmware: ``bt_energia`` v2.0.2 (2003-05-08) ARM binary and
  ``own-firmware-oracle`` suite ``energy-ts10`` (vendored in
  ``tests/golden/firmware_oracle.json``; see
  https://github.com/OpenWebNet-HA/own-firmware-oracle/blob/main/oracle/cases/energy-ts10.cases#L69-L86
  and
  https://github.com/OpenWebNet-HA/own-firmware-oracle/blob/main/findings/MyHomeServer1/energy-ts10.md#35-who-3-load-management--f421).
  Across all seven ``bt_energia`` gateways (F453AV 030014, F454 020051,
  F459 020105, H4684 020054, MH200 020102, MH200N 010108, and MH202 010024),
  which agree on every WHO 3 input in the oracle fixture, only ``*3*2*#N##``
  (force) is accepted as a command: it is ACKed and put on the bus as
  ``$04B70N1300`` (with the priority in the telegram), and six of them (all
  except F454) also echo ``*3*2*#N##`` on the event session. ``*3*0*``,
  ``*3*1*`` and ``*3*3*`` are NACKed with nothing on the bus, for a priority
  and for the general WHERE 0 alike; ``*#3*0##`` is also NACKed with nothing on
  the bus (``bt_energia`` at ``0x00b91c``/``0x00b998`` only accepts ``*#3##``
  and ``*#3*##`` for general status). ``*#3*#N##`` (``$03AA001614``) and
  ``*#3*10*D##`` (D 0-4, ``$03AA0016xx``) still put their register-read
  telegrams on the bus, but in the oracle fixture they get a NACK (``*#*0##``)
  on the command session — the opposite of the specification's "ACK if command
  is sent to Bus" (``WHO_3.pdf`` p. 6; in ``bt_energia``, ``0x00b140`` waits up
  to 4.0 s in ``select()`` for an F421 reply on the bus before sending ACK at
  ``0x00b030``, and sends NACK at ``0x009cf8`` when no F421 answers), so a
  client will see the NACK when no F421 responds.
  In ``bt_energia``, ``0x00b140`` (jump table ``0x00b3e0``) polls the F421
  central unit registers and ``0x00a63c`` decodes the ``$031900<REG>`` +
  ``$031A00<HH>`` replies via ``htod`` into unsigned integers formatted with
  ``%d``:
  - Dimension 1 (Voltage, V): register ``0x13`` (1 byte, 8-bit int ``0..255``,
    ``0x00b674`` / ``0x00af2c`` -> ``*#3*10*1*%d##``)
  - Dimension 2 (Current, A): register ``0x12`` (1 byte, 8-bit int ``0..255``,
    ``0x00b6f4`` / ``0x00ae7c`` -> ``*#3*10*2*%d##``)
  - Dimension 3 (Power, W): registers ``0x10..0x11`` (2 bytes, 16-bit int
    ``0..65535``, ``0x00b774`` / ``0x00ad88`` -> ``*#3*10*3*%d##``)
  - Dimension 4 (Energy): registers ``0x06..0x09`` (4 bytes, 32-bit int,
    ``0x00b830`` / ``0x00ac34`` -> ``*#3*10*4*%d##``)
  - Dimension 0 (All measurements): polls all 8 registers ``13, 12, 10..11,
    06..09`` (``0x00b3f4``) and joins them as ``*#3*10*0*%s*%s*%s*%s##``
    (``0x00aa24``) in ``T*C*P*E`` (Voltage, Current, Power, Energy) order.
- Specification: WHO 3 Load Control v1.0.0 (2006-08-30,
  ``OpenWebNet_Community_6_powermanagement_v1_0_0_EN.doc``, archived at
  https://archive.openwebnet-ha.org/sha256/4f/68/4f685a6ee3b16e6a7994a338186687bcea1dabba74dc5d24d22a07becb24dea1.pdf,
  pp. 4, 6-7), as summarised by the OpenWebNet Encyclopedia
  (https://github.com/OpenWebNet-HA/OpenWebNet-Encyclopedia/blob/main/functional/who-3-load-management/README.md#measurement-dimension-values).
  WHAT 0 load disabled, 1 enabled, 2 forced, 3 forcing removed; WHERE 0
  general, 10 control unit, #1-#8 priority; DIMENSION 0-4 at WHERE 10 are
  All dimensions (``T*C*P*E``), Voltage (``T``, Volt), Current (``C``, Ampere),
  Power (``P``, Watt), and Energy (``E``, unit unspecified in the spec).
"""

from __future__ import annotations

import re

from .base import OWNCommand, OWNEvent, register_command_parser, register_event_parser

LOAD_STATE_DISABLED = 0
LOAD_STATE_ENABLED = 1
LOAD_STATE_FORCED = 2
LOAD_STATE_FORCING_REMOVED = 3

LOAD_CONTROL_UNIT = "10"
LOAD_PRIORITIES = range(1, 9)
LOAD_MEASUREMENT_DIMENSIONS = range(0, 5)

LOAD_DIMENSION_ALL = 0
LOAD_DIMENSION_VOLTAGE = 1
LOAD_DIMENSION_CURRENT = 2
LOAD_DIMENSION_POWER = 3
LOAD_DIMENSION_ENERGY = 4

_STATE_TEXT = {
    LOAD_STATE_DISABLED: "disabled",
    LOAD_STATE_ENABLED: "enabled",
    LOAD_STATE_FORCED: "forced",
    LOAD_STATE_FORCING_REMOVED: "no longer forced",
}

# Dimension mappings verified against WHO_3.pdf v1.0.0 (pp. 4, 6-7) and
# central unit register polling/decoding in bt_energia v2.0.2 (0x00b140 / 0x00a63c):
# - Dimension 0: All measurements (T*C*P*E) -> 8 registers $03AA001613, 12, 10..11, 06..09
# - Dimension 1: Voltage (T, V) -> 1 register $03AA001613 (8-bit int)
# - Dimension 2: Current (C, A) -> 1 register $03AA001612 (8-bit int)
# - Dimension 3: Power (P, W) -> 2 registers $03AA001610..$03AA001611 (16-bit int)
# - Dimension 4: Energy (E) -> 4 registers $03AA001606..$03AA001609 (32-bit int)
_DIMENSION_NAMES = {
    LOAD_DIMENSION_ALL: "all measurements",
    LOAD_DIMENSION_VOLTAGE: "voltage",
    LOAD_DIMENSION_CURRENT: "current",
    LOAD_DIMENSION_POWER: "power",
    LOAD_DIMENSION_ENERGY: "energy",
}

_PRIORITY_WHERE = re.compile(r"^#([1-8])$")


def _safe_int(value: str | None) -> int | None:
    if value is None:
        return None
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def _priority_of(where: str | None) -> int | None:
    """Priority 1-8 for a ``#N`` WHERE; the leading ``#`` is part of the address."""
    match = _PRIORITY_WHERE.match(where or "")
    return int(match.group(1)) if match else None


def _priority_where(priority: int) -> str:
    if priority not in LOAD_PRIORITIES:
        raise ValueError("Load priority must be between 1 and 8")
    return f"#{priority}"


class OWNLoadEvent(OWNEvent):
    """A load priority state or a control-unit measurement reply."""

    def __init__(self, data: str) -> None:
        super().__init__(data)

        self._priority = _priority_of(self._where)
        self._state: int | None = None
        self._measurement_values: list[str] = []
        self._voltage: int | None = None
        self._current: int | None = None
        self._power: int | None = None
        self._energy: int | None = None

        if self._priority is not None:
            _target = f"Load priority {self._priority} is"
        elif self._where == "0":
            _target = "All load priorities are"
        else:
            _target = f"Load {self._where} is"

        if self._message_type == "STATUS" and self._what in _STATE_TEXT:
            self._state = self._what
            self._human_readable_log = f"{_target} {_STATE_TEXT[self._what]}."
        elif (
            self._message_type == "DIMENSION_REQUEST_REPLY"
            and self._where == LOAD_CONTROL_UNIT
            and self._dimension is not None
        ):
            self._measurement_values = list(self._dimension_value)
            if self._dimension == LOAD_DIMENSION_VOLTAGE and self._dimension_value:
                self._voltage = _safe_int(self._dimension_value[0])
                self._human_readable_log = (
                    f"Load control unit voltage: {self._voltage} V."
                )
            elif self._dimension == LOAD_DIMENSION_CURRENT and self._dimension_value:
                self._current = _safe_int(self._dimension_value[0])
                self._human_readable_log = (
                    f"Load control unit current: {self._current} A."
                )
            elif self._dimension == LOAD_DIMENSION_POWER and self._dimension_value:
                self._power = _safe_int(self._dimension_value[0])
                self._human_readable_log = (
                    f"Load control unit power: {self._power} W."
                )
            elif self._dimension == LOAD_DIMENSION_ENERGY and self._dimension_value:
                self._energy = _safe_int(self._dimension_value[0])
                self._human_readable_log = (
                    f"Load control unit energy: {self._energy}."
                )
            elif self._dimension == LOAD_DIMENSION_ALL and self._dimension_value:
                self._voltage = _safe_int(self._dimension_value[0])
                if len(self._dimension_value) >= 2:
                    self._current = _safe_int(self._dimension_value[1])
                if len(self._dimension_value) >= 3:
                    self._power = _safe_int(self._dimension_value[2])
                if len(self._dimension_value) >= 4:
                    self._energy = _safe_int(self._dimension_value[3])
                self._human_readable_log = (
                    f"Load control unit all measurements: "
                    f"voltage={self._voltage} V, current={self._current} A, "
                    f"power={self._power} W, energy={self._energy}."
                )
            else:
                _name = _DIMENSION_NAMES.get(self._dimension)
                _label = f" ({_name})" if _name else ""
                self._human_readable_log = (
                    f"Load control unit dimension {self._dimension}{_label}: "
                    f"raw values {self._measurement_values}."
                )

    @property
    def priority(self) -> int | None:
        """Load priority 1-8 from a ``#N`` WHERE, None for any other target."""
        return self._priority

    @property
    def state(self) -> int | None:
        """WHAT 0-3 of a state frame (see ``LOAD_STATE_*``), None otherwise."""
        return self._state

    @property
    def is_forced(self) -> bool | None:
        """Whether the load is forced, None when the frame carries no state."""
        return None if self._state is None else self._state == LOAD_STATE_FORCED

    @property
    def is_control_unit(self) -> bool:
        return self._where == LOAD_CONTROL_UNIT

    @property
    def measurement_values(self) -> list[str]:
        """Raw values of a control-unit measurement reply, unscaled and unitless."""
        return self._measurement_values

    @property
    def voltage(self) -> int | None:
        """Measured voltage in V (dimension 1, or index 0 of dimension 0), None if not reported."""
        return self._voltage

    @property
    def current(self) -> int | None:
        """Measured current in A (dimension 2, or index 1 of dimension 0), None if not reported."""
        return self._current

    @property
    def power(self) -> int | None:
        """Measured power in W (dimension 3, or index 2 of dimension 0), None if not reported."""
        return self._power

    @property
    def energy(self) -> int | None:
        """Measured energy counter (dimension 4, or index 3 of dimension 0), None if not reported."""
        return self._energy


class OWNLoadCommand(OWNCommand):
    """WHO 3 commands and requests.

    Only frames that the firmware oracle shows reaching the bus get a builder:
    ``*3*2*#N##`` (ACKed, emits ``$04B70N1300``), ``*#3*#N##`` and
    ``*#3*10*D##`` (both put their ``$03AA0016xx`` register reads on the bus,
    though in the oracle fixture the command session replies NACK when no F421
    answers within the 4 s bus timeout, opposite to ``WHO_3.pdf`` p. 6 "ACK if
    command is sent to Bus"). WHAT 0, 1 and 3, the general WHERE 0 and the
    general status request ``*#3*0##`` are refused by the gateways with no bus
    output, so there is no builder for them.
    """

    def __init__(self, data: str) -> None:
        super().__init__(data)
        _priority = _priority_of(self._where)
        if self._message_type == "STATUS" and self._what == LOAD_STATE_FORCED:
            if _priority is not None:
                self._human_readable_log = f"Forcing load priority {_priority}."
        elif self._message_type == "STATUS_REQUEST" and _priority is not None:
            self._human_readable_log = f"Requesting load priority {_priority} status."
        elif (
            self._message_type == "DIMENSION_REQUEST"
            and self._where == LOAD_CONTROL_UNIT
            and self._dimension is not None
        ):
            self._human_readable_log = (
                f"Requesting load control unit dimension {self._dimension}."
            )

    @classmethod
    def force(cls, priority: int) -> OWNLoadCommand:
        """Force the load on ``priority`` 1-8 (``*3*2*#N##``)."""
        return cls(f"*3*{LOAD_STATE_FORCED}*{_priority_where(priority)}##")

    @classmethod
    def status(cls, priority: int) -> OWNLoadCommand:
        """Request the state of load ``priority`` 1-8 (``*#3*#N##``)."""
        return cls(f"*#3*{_priority_where(priority)}##")

    @classmethod
    def request_measurement(cls, dimension: int = 0) -> OWNLoadCommand:
        """Request control-unit measurement ``dimension`` 0-4 (``*#3*10*D##``)."""
        if dimension not in LOAD_MEASUREMENT_DIMENSIONS:
            raise ValueError("Load measurement dimension must be between 0 and 4")
        return cls(f"*#3*{LOAD_CONTROL_UNIT}*{dimension}##")


register_event_parser(3, OWNLoadEvent)
register_command_parser(3, OWNLoadCommand)
