"""WHO 13: Gateway management events, clock commands, and timezone helpers."""

from __future__ import annotations

import datetime as _dt
import re
from zoneinfo import ZoneInfo

from .base import OWNCommand, OWNEvent, register_command_parser, register_event_parser


def _validate_gateway_clock_values(
    dimension: int | None, values: list[str]
) -> None:
    """Reject truncated gateway clock frames before indexing their values."""
    if dimension is None:
        return
    required = {0: 3, 1: 4, 22: 8}.get(dimension)
    if required is not None and len(values) < required:
        raise ValueError(
            f"Gateway dimension {dimension} requires {required} values"
        )


def _is_ascii_digits(value: str) -> bool:
    """Only ASCII digits are a wire value: ``str.isdigit`` also accepts fullwidth,
    superscript and circled digits, which ``int`` converts (or rejects) but which
    are not on the bus (Encyclopedia ``protocol/frame-syntax.md``)."""
    return bool(value) and value.isascii() and value.isdigit()


def _gateway_timezone(values: list[str]) -> str:
    """Decode an optional OWN timezone, preserving unspecified local time."""
    value = values[3] if len(values) > 3 else ""
    if not value or value == "999":
        return ""
    # re.ASCII: a fullwidth "0０１" matched \d and reached fromisoformat.
    if re.fullmatch(r"[01]\d{2}", value, re.ASCII) is None:
        raise ValueError(f"Invalid gateway timezone: {value!r}")
    sign = "+" if value[0] == "0" else "-"
    return f"{sign}{value[1:]}:00"


# WHO 13 Dimension 15: Functional gateway model/device type (*#13**15*<TYPE>##).
# Grounded in published BTicino protocol tables, physical plant captures,
# and firmware reverse engineering (bt_device dispatch table at VA 0x02003194,
# selector r4 == 0). The published table (Encyclopedia
# who-13-integration-gateway/dimensions.md "DIMENSION 15 - Device type") has
# 2, 4, 6, 7, 11 and 13 and says it is not exhaustive; the other codes come
# from firmware reverse engineering and plant captures. A code that is not in
# this table stays an unknown code (``device_type`` reads ``Unknown (N)``,
# ``device_type_code`` keeps ``N``), and a non-unique code (``200``) is not a
# product identity: ``device_type`` lists the gateways known to share it and
# WHO 1013 Dimension 1 tells them apart (capabilities.md
# "Product identification").
WHO13_DEVICE_TYPES: dict[str, str] = {
    "2": "MHServer",
    "4": "MH200",
    "6": "F452",
    "7": "F452V",
    "11": "MHServer2",
    "12": "F453AV",
    "13": "H4684",
    "15": "F427",
    "16": "F453",
    "17": "INTERF2FIP",
    "18": "LGRF452",
    "19": "LGRMH200",
    "20": "LGRH4684",
    "23": "H4684",
    "27": "L4686SDK",
    "44": "MH200N",
    "51": "F454",
    # Code 200 is shared across modern gateways (F454, MyHomeServer1,
    # MH202, F461, H4890; plus emulated F450/F459/F460 in trace-corpus.tsv)
    # and MH201 (fw 3.3.6, 3.6.27; MyHOME #370, #466 and plant fixtures;
    # catalogued on 030644 outside the Linux QEMU fleet). WHO 1013
    # dimension 1 tells them apart (the MH201 on 3.6.27 answers only
    # *#1013**1##, model 10, and NACKs *#1013*0*1##).
    "200": (
        "F454 / MyHomeServer1 / MH202 / F461 / H4890 / F450 / F459 / F460 / MH201"
    ),
}

# WHO 1013 Dimension 1: Diagnostic object model (*#1013**1*<MODEL>*<N_CONF>*<BRAND>*<LINE>##).
# Grounded in firmware reverse engineering (bt_device dispatch table at VA 0x02003194,
# selector r4 != 0), canonical MHCatalogue.db AS_ITEM_SYSTEM.modobj cross-referencing,
# and corroborated live gateway captures (OpenWebNet-Encyclopedia / guides/identify-openwebnet-gateway.md).
WHO1013_DEVICE_TYPES: dict[str, str] = {
    "2": "MHServer",
    "4": "MH200",
    "5": "MH202",
    "6": "F452",
    "7": "F452V",
    "8": "F455",
    "10": "MH201",
    "11": "MHServer2",
    "12": "F453AV",
    "19": "H4684",
    "22": "F453",
    "23": "INTERF2FIP",
    "24": "LGRF452",
    "25": "LGRMH200",
    "26": "LGRH4684",
    "29": "H4684",
    "30": "H4890",
    "35": "BMNE500",
    "38": "573992",
    "42": "F453",
    "44": "MH200N",
    "51": "F454",
    "54": "MH4892",
    "55": "MH4892C",
    "65": "F459",
    "67": "MyHomeServer1",
    "105": "F458",
    "134": "F461",
}

# OpenZigBee product device types reported in WHO 13 Dimension 66.
# Reimplemented from openwebnet4j OpenDeviceType (EPL-2.0) and Encyclopedia
# Machine KB claims ownkb:claim:c001851, c001954.
ZIGBEE_DEVICE_TYPES: dict[int, str] = {
    2: "Scenario Control",
    256: "On/Off Switch",
    257: "Dimmer Control",
    258: "Dimmer Switch",
    259: "Switch Motion Detector",
    260: "Daylight Sensor",
    261: "SCS On/Off Switch",
    262: "SCS Dimmer Control",
    263: "SCS Dimmer Switch",
    264: "Waterproof 1-Gang Switch",
    265: "Automatic Dimmer Switch",
    266: "Toggle Control",
    267: "SCS Toggle Control",
    268: "Motion Detector",
    269: "Switch Motion Detector II",
    270: "Motion Detector II",
    271: "Auxiliary Motion Control",
    272: "SCS Auxiliary Toggle Control",
    273: "Multifunction Scenario Control",
    274: "On/Off Control",
    275: "Auxiliary On/Off 1-Gang Switch",
    512: "Shutter Control",
    513: "Shutter Switch",
    514: "SCS Shutter Control",
    515: "SCS Shutter Switch",
    1024: "SCS 1-System 1-4 Gateway",
    1025: "SCS 2-System 1-4 Gateway",
    1029: "Network Repeater",
    1030: "OpenWebNet Interface",
    1536: "Video Switcher",
}

_WHO13_BOOT_MODE_REGEX = re.compile(
    r"^\s*\*\s*\+?0*13\s*\*\s*\+?0*12(?=[*#\s]|\Z)",
    re.ASCII,
)


def is_who13_boot_mode_frame(frame: object) -> bool:
    """True if ``frame`` (or any ``##``-delimited frame in it) requests WHO 13 WHAT 12 boot mode.

    ``*13*12*##`` drops the OpenZigBee USB interface out of OpenWebNet into an
    STX/ETX bootloader protocol (Encyclopedia
    ``who-13-integration-gateway/zigbee-network-management.md``).
    """
    if isinstance(frame, (bytes, bytearray, memoryview)):
        raw = bytes(frame).decode("latin-1")
    else:
        raw = str(frame)
    return any(_WHO13_BOOT_MODE_REGEX.search(chunk) for chunk in raw.split("##"))


_ZIGBEE_COMMAND_LOGS: dict[int, str] = {
    12: "Requesting ZigBee interface boot mode.",
    22: "Resetting ZigBee interface.",
    30: "Creating ZigBee network.",
    31: "Closing ZigBee network.",
    32: "Opening ZigBee network.",
    33: "Joining ZigBee network.",
    34: "Leaving ZigBee network.",
    60: "Checking ZigBee gateway readiness (keep connect).",
    61: "Identifying ZigBee product.",
    65: "Scanning ZigBee network.",
    66: "Enabling ZigBee OpenWebNet supervisor mode.",
    67: "Disabling ZigBee OpenWebNet supervisor mode.",
}

_ZIGBEE_EVENT_LOGS: dict[int, str] = {
    12: "ZigBee interface entered boot mode.",
    22: "ZigBee interface reset.",
    30: "ZigBee network created.",
    31: "ZigBee network closed.",
    32: "ZigBee network opened.",
    33: "ZigBee interface joined network.",
    34: "ZigBee interface left network.",
    60: "ZigBee gateway readiness (keep connect).",
    61: "Identifying ZigBee product.",
    65: "ZigBee network scan.",
    66: "Enabling ZigBee OpenWebNet supervisor mode.",
    67: "Disabling ZigBee OpenWebNet supervisor mode.",
}

_ZIGBEE_ADDRESSED_EVENT_LOGS: dict[int, str] = {
    31: "ZigBee network closed by {target}.",
    32: "ZigBee network opened by {target}.",
    33: "ZigBee product {target} joined network.",
    34: "ZigBee product {target} left network.",
    61: "Identifying ZigBee product {target}.",
    66: "ZigBee supervisor indication from {target}.",
    67: "ZigBee supervisor remove indication from {target}.",
}


class OWNGatewayEvent(OWNEvent):
    def __init__(self, data: str) -> None:
        super().__init__(data)

        self._year = None
        self._month = None
        self._day = None
        self._hour = None
        self._minute = None
        self._second = None
        self._timezone = None
        self._raw_timezone = None

        self._time = None
        self._date = None
        self._datetime = None

        self._ip_address = None
        self._netmask = None
        self._mac_address = None
        self._ieee_address: str | None = None

        self._device_type = None
        self._firmware_version = None
        self._firmware_version_tuple: tuple[int, int, int] | None = None

        self._uptime = None

        self._kernel_version = None
        self._distribution_version = None
        self._model_name: str | None = None
        self._zigbee_product_index: int | None = None
        self._zigbee_device_type_code: int | None = None
        self._zigbee_device_type: str | None = None
        self._is_zigbee_product_unreachable: bool = False
        self._network_product_count: int | None = None

        _validate_gateway_clock_values(self._dimension, self._dimension_value)

        if self._dimension == 0:
            self._hour = self._dimension_value[0]
            self._minute = self._dimension_value[1]
            self._second = self._dimension_value[2]
            self._raw_timezone = (
                self._dimension_value[3]
                if len(self._dimension_value) > 3 and self._dimension_value[3]
                else None
            )
            if not all(_is_ascii_digits(v) for v in (self._hour, self._minute, self._second)):
                raise ValueError(f"Invalid gateway time: {self._dimension_value!r}")
            self._timezone = _gateway_timezone(self._dimension_value)
            self._time = _dt.time.fromisoformat(
                f"{self._hour}:{self._minute}:{self._second}{self._timezone}"
            )
            self._human_readable_log = (
                f"Gateway's internal time is: {self._time}."
            )

        elif self._dimension == 1:
            self._year = self._dimension_value[3]
            self._month = self._dimension_value[2]
            self._day = self._dimension_value[1]
            if not all(_is_ascii_digits(v) for v in (self._year, self._month, self._day)):
                raise ValueError(f"Invalid gateway date: {self._dimension_value!r}")
            self._date = _dt.date(
                year=int(self._year), month=int(self._month), day=int(self._day)
            )
            self._human_readable_log = (
                f"Gateway's internal date is: {self._date}."
            )
        elif self._dimension == 10 and len(self._dimension_value) >= 4:
            self._ip_address = f"{self._dimension_value[0]}.{self._dimension_value[1]}.{self._dimension_value[2]}.{self._dimension_value[3]}"  # pylint: disable=line-too-long
            self._human_readable_log = f"Gateway's IP address is: {self._ip_address}."

        elif self._dimension == 11 and len(self._dimension_value) >= 4:
            self._netmask = f"{self._dimension_value[0]}.{self._dimension_value[1]}.{self._dimension_value[2]}.{self._dimension_value[3]}"  # pylint: disable=line-too-long
            self._human_readable_log = f"Gateway's netmask is: {self._netmask}."

        elif (
            self._dimension == 12
            and len(self._dimension_value) == 6
            and all(_is_ascii_digits(v) for v in self._dimension_value)
        ):
            # Six ASCII-digit fields: int() cannot raise here;
            # an empty or non-ASCII field leaves the frame untyped.
            self._mac_address = ":".join(
                f"{int(v):02x}" for v in self._dimension_value
            )
            self._human_readable_log = f"Gateway's MAC address is: {self._mac_address}."

        elif (
            self._dimension == 12
            and len(self._dimension_value) == 8
            and all(
                _is_ascii_digits(v) and 0 <= int(v) <= 255
                for v in self._dimension_value
            )
        ):
            # Eight ASCII-digit octets (0..255): ZigBee IEEE EUI-64 identity
            # (ownkb:claim:c001873, openwebnet4j GatewayMgmt).
            self._ieee_address = ":".join(
                f"{int(v):02x}" for v in self._dimension_value
            )
            self._human_readable_log = (
                f"Gateway's IEEE address is: {self._ieee_address}."
            )

        elif self._dimension == 15 and self._dimension_value and _is_ascii_digits(self._dimension_value[0]):
            code = self._dimension_value[0]
            self._device_type = WHO13_DEVICE_TYPES.get(code, f"Unknown ({code})")
            self._human_readable_log = f"Gateway device type is: {self._device_type}."

        elif self._dimension == 16 and len(self._dimension_value) >= 3:
            self._firmware_version = f"{self._dimension_value[0]}.{self._dimension_value[1]}.{self._dimension_value[2]}"  # pylint: disable=line-too-long
            if all(_is_ascii_digits(v) for v in self._dimension_value[:3]):
                self._firmware_version_tuple = (
                    int(self._dimension_value[0]),
                    int(self._dimension_value[1]),
                    int(self._dimension_value[2]),
                )
            self._human_readable_log = (
                f"Gateway's firmware version is: {self._firmware_version}."
            )

        elif (
            self._dimension == 19
            and len(self._dimension_value) >= 4
            and all(_is_ascii_digits(v) for v in self._dimension_value[:4])
        ):
            # Four ASCII-digit fields: int() cannot raise, but timedelta does
            # on an absurd magnitude (tests/test_message_exhaustive.py).
            try:
                self._uptime = _dt.timedelta(
                    days=int(self._dimension_value[0]),
                    hours=int(self._dimension_value[1]),
                    minutes=int(self._dimension_value[2]),
                    seconds=int(self._dimension_value[3]),
                )
                self._human_readable_log = f"Gateway's uptime is: {self._uptime}."
            except (OverflowError, ValueError):
                pass

        elif self._dimension == 22:
            self._hour = self._dimension_value[0]
            self._minute = self._dimension_value[1]
            self._second = self._dimension_value[2]
            self._raw_timezone = (
                self._dimension_value[3]
                if len(self._dimension_value) > 3 and self._dimension_value[3]
                else None
            )
            self._timezone = _gateway_timezone(self._dimension_value)
            self._day = self._dimension_value[5]
            self._month = self._dimension_value[6]
            self._year = self._dimension_value[7]
            if not all(
                _is_ascii_digits(v)
                for v in (self._hour, self._minute, self._second, self._day, self._month, self._year)
            ):
                raise ValueError(f"Invalid gateway datetime: {self._dimension_value!r}")
            self._datetime = _dt.datetime.fromisoformat(
                f"{self._year}-{self._month}-{self._day}T{self._hour}:{self._minute}:{self._second}{self._timezone}"  # pylint: disable=line-too-long
            )
            self._date = self._datetime.date()
            self._time = (
                self._datetime.timetz()
                if self._datetime.tzinfo is not None
                else self._datetime.time()
            )
            self._human_readable_log = (
                f"Gateway's internal datetime is: {self._datetime}."
            )
        elif self._dimension == 23 and len(self._dimension_value) >= 3:
            self._kernel_version = f"{self._dimension_value[0]}.{self._dimension_value[1]}.{self._dimension_value[2]}"  # pylint: disable=line-too-long
            self._human_readable_log = (
                f"Gateway's kernel version is: {self._kernel_version}."
            )

        elif self._dimension == 24 and len(self._dimension_value) >= 3:
            self._distribution_version = f"{self._dimension_value[0]}.{self._dimension_value[1]}.{self._dimension_value[2]}"  # pylint: disable=line-too-long
            self._human_readable_log = (
                f"Gateway's distribution version is: {self._distribution_version}."
            )

        elif (
            self._dimension == 27
            and len(self._dimension_value) == 1
            and "#" in self._dimension_value[0]
        ):
            # Model name as one '#'-separated value of ASCII codes:
            # *#13**27*70#52#54#49## is "F461" (live F461 2.0.11, 2026-10-23),
            # *#13**27*77#121#...#49## is "MyHomeServer1" (live 3.87.13,
            # 2026-10-24; MyHOME#799). Only that shape is decoded: the general
            # '*'-separated form (*#13**27*70*52*54*49##) and a single code
            # without '#' are not a model name. The frame pattern
            # (``_HASH_VALUE_REPLIES``, ASCII digits only) admits the shape;
            # every code must name a printable ASCII character, else
            # model_name stays None.
            codes = self._dimension_value[0].split("#")
            if all(32 <= int(c) < 127 for c in codes):
                self._model_name = "".join(chr(int(c)) for c in codes)
                self._human_readable_log = (
                    f"Gateway's model name is: {self._model_name}."
                )

        elif (
            self._dimension == 66
            and self._dimension_value
            and all(_is_ascii_digits(v) for v in self._dimension_value)
        ):
            dev_code: int | None = None
            if len(self._dimension_value) >= 2:
                self._zigbee_product_index = int(self._dimension_value[0])
                dev_code = int(self._dimension_value[-1])
            elif self._dimension_param and len(self._dimension_value) == 1:
                if _is_ascii_digits(self._dimension_param[0]):
                    self._zigbee_product_index = int(self._dimension_param[0])
                dev_code = int(self._dimension_value[0])
            elif (
                not self._where
                and not self._dimension_param
                and self._dimension_value == ["0"]
            ):
                dev_code = 0
            elif (
                len(self._dimension_value) == 1
                and not self._dimension_param
                and self._where_param == ["9"]
                and isinstance(self._where, str)
                and len(self._where) >= 3
                and _is_ascii_digits(self._where)
                and self._where.endswith("00")
            ):
                # Live Legrand 3578 fw 1.2.3 offline reply:
                # *#13*<ADDR>00#9*66*<INDEX>## (+ *#*0## NACK).
                self._zigbee_product_index = int(self._dimension_value[0])
                self._is_zigbee_product_unreachable = True
                self._human_readable_log = (
                    f"ZigBee product {self._where[:-2]} at index "
                    f"{self._zigbee_product_index} is unreachable (dimension 66)."
                )
            else:
                dev_code = int(self._dimension_value[0])

            if dev_code is not None:
                self._zigbee_device_type_code = dev_code
                if dev_code == 0:
                    self._is_zigbee_product_unreachable = True
                    self._human_readable_log = (
                        "ZigBee product is unreachable (dimension 66)."
                    )
                else:
                    self._zigbee_device_type = ZIGBEE_DEVICE_TYPES.get(
                        dev_code, f"Unknown ({dev_code})"
                    )
                    self._human_readable_log = (
                        f"ZigBee product {self._where} type is: {self._zigbee_device_type} ({dev_code})."
                    )

        elif (
            self._dimension == 67
            and self._dimension_value
            and _is_ascii_digits(self._dimension_value[0])
        ):
            self._network_product_count = int(self._dimension_value[0])
            self._human_readable_log = (
                f"Gateway product database count is: {self._network_product_count}."
            )

        elif self._dimension is None and self._what is not None:
            target = self.zigbee_where or self._where
            if target and self._what in _ZIGBEE_ADDRESSED_EVENT_LOGS:
                self._human_readable_log = _ZIGBEE_ADDRESSED_EVENT_LOGS[
                    self._what
                ].format(target=target)
            elif self._what in _ZIGBEE_EVENT_LOGS:
                self._human_readable_log = _ZIGBEE_EVENT_LOGS[self._what]

    @property
    def time(self) -> _dt.time | None:
        """Return the decoded gateway internal time."""
        return self._time

    @property
    def date(self) -> _dt.date | None:
        """Return the decoded gateway internal date."""
        return self._date

    @property
    def datetime(self) -> _dt.datetime | None:
        """Return the decoded gateway internal datetime."""
        return self._datetime

    @property
    def timezone(self) -> str | None:
        """Return the decoded timezone offset string (e.g. '+02:00', '-05:00', or '')."""
        return self._timezone

    @property
    def raw_timezone(self) -> str | None:
        """Return the raw timezone string as reported by the gateway."""
        return self._raw_timezone

    @property
    def is_timezone_unconfigured(self) -> bool:
        """Return True if the gateway reported an unconfigured timezone (sentinel 999)."""
        return self._raw_timezone == "999"

    @property
    def uptime(self) -> _dt.timedelta | None:
        """Return the gateway uptime duration."""
        return self._uptime

    @property
    def ip_address(self) -> str | None:
        """Return the decoded gateway IP address."""
        return self._ip_address

    @property
    def netmask(self) -> str | None:
        """Return the decoded gateway netmask."""
        return self._netmask

    @property
    def mac_address(self) -> str | None:
        """Return the decoded gateway MAC address (6 octets)."""
        return self._mac_address

    @property
    def ieee_address(self) -> str | None:
        """Return the decoded ZigBee gateway IEEE EUI-64 address (8 octets)."""
        return self._ieee_address

    @property
    def firmware_version(self) -> str | None:
        """Return the decoded gateway firmware version string."""
        return self._firmware_version

    @property
    def firmware_version_tuple(self) -> tuple[int, int, int] | None:
        """Return the decoded gateway firmware version as ``(major, minor, build)``."""
        return self._firmware_version_tuple

    @property
    def device_type(self) -> str | None:
        """Return the decoded gateway device type string.

        ``Unknown (N)`` for a Dimension 15 code outside ``WHO13_DEVICE_TYPES``
        (the published table is not exhaustive and an unlisted code stays an
        unknown code); the non-unique ``200`` reads as the slash-separated list
        of the gateways known to share it, not as one product: identify them
        through WHO 1013 Dimension 1 (``OWNGatewayDiagnosticEvent``).
        ``device_type_code`` keeps the raw code either way.
        """
        return self._device_type

    @property
    def device_type_code(self) -> str | None:
        """Return the raw WHO 13 dimension 15 code (``"200"`` on an F454, F461, ...)."""
        if self._dimension == 15 and self._dimension_value:
            return str(self._dimension_value[0])
        return None

    @property
    def kernel_version(self) -> str | None:
        """Return the decoded gateway kernel version string."""
        return self._kernel_version

    @property
    def distribution_version(self) -> str | None:
        """Return the decoded gateway distribution version string."""
        return self._distribution_version

    @property
    def model_name(self) -> str | None:
        """Return the gateway model name of a Dimension 27 reply (e.g. ``"F461"``)."""
        return self._model_name

    @property
    def zigbee_product_index(self) -> int | None:
        """Return the 0-based product index from a WHO 13 Dimension 66 reply."""
        return self._zigbee_product_index

    @property
    def zigbee_device_type_code(self) -> int | None:
        """Return the raw ``DEV_ID`` integer from a WHO 13 Dimension 66 reply."""
        return self._zigbee_device_type_code

    @property
    def zigbee_device_type(self) -> str | None:
        """Return the ZigBee device type label from ``ZIGBEE_DEVICE_TYPES``."""
        return self._zigbee_device_type

    @property
    def is_zigbee_product_unreachable(self) -> bool:
        """Return True when Dimension 66 reported an unreachable ZigBee product."""
        return self._is_zigbee_product_unreachable

    @property
    def network_product_count(self) -> int | None:
        """Return the stored ZigBee product count from a Dimension 67 reply."""
        return self._network_product_count

    @property
    def is_zigbee_network_close(self) -> bool:
        """Return True when WHO 13 WHAT 31 closed the ZigBee network."""
        return self._dimension is None and self._what == 31

    @property
    def is_zigbee_network_open(self) -> bool:
        """Return True when WHO 13 WHAT 32 opened the ZigBee network."""
        return self._dimension is None and self._what == 32

    @property
    def is_zigbee_join(self) -> bool:
        """Return True when WHO 13 WHAT 33 reported a ZigBee join indication."""
        return self._dimension is None and self._what == 33

    @property
    def is_zigbee_leave(self) -> bool:
        """Return True when WHO 13 WHAT 34 reported a ZigBee leave indication."""
        return self._dimension is None and self._what == 34


class OWNGatewayCommand(OWNCommand):
    def __init__(self, data: str) -> None:
        super().__init__(data)

        self._year = None
        self._month = None
        self._day = None
        self._hour = None
        self._minute = None
        self._second = None
        self._timezone = None
        self._raw_timezone = None

        self._time = None
        self._date = None
        self._datetime = None

        # Dimension requests carry no values and are valid as-is.
        if self.is_request:
            return

        if self._what in _ZIGBEE_COMMAND_LOGS:
            target = self.zigbee_where or self._where
            if target and self._what == 34:
                self._human_readable_log = (
                    f"Requesting ZigBee product {target} to leave network."
                )
            elif target and self._what == 61:
                self._human_readable_log = f"Identifying ZigBee product {target}."
            else:
                self._human_readable_log = _ZIGBEE_COMMAND_LOGS[self._what]
            return

        _validate_gateway_clock_values(self._dimension, self._dimension_value)

        if self._dimension == 0:
            self._hour = self._dimension_value[0]
            self._minute = self._dimension_value[1]
            self._second = self._dimension_value[2]
            self._raw_timezone = (
                self._dimension_value[3]
                if len(self._dimension_value) > 3 and self._dimension_value[3]
                else None
            )
            if not all(_is_ascii_digits(v) for v in (self._hour, self._minute, self._second)):
                raise ValueError(f"Invalid gateway time: {self._dimension_value!r}")
            self._timezone = _gateway_timezone(self._dimension_value)
            self._time = _dt.time.fromisoformat(
                f"{self._hour}:{self._minute}:{self._second}{self._timezone}"
            )
            self._human_readable_log = (
                f"Gateway broadcasting internal time: {self._time}."
            )

        elif self._dimension == 1:
            self._year = self._dimension_value[3]
            self._month = self._dimension_value[2]
            self._day = self._dimension_value[1]
            if not all(_is_ascii_digits(v) for v in (self._year, self._month, self._day)):
                raise ValueError(f"Invalid gateway date: {self._dimension_value!r}")
            self._date = _dt.date(
                year=int(self._year), month=int(self._month), day=int(self._day)
            )
            self._human_readable_log = (
                f"Gateway broadcasting internal date: {self._date}."
            )

        elif self._dimension == 22:
            self._hour = self._dimension_value[0]
            self._minute = self._dimension_value[1]
            self._second = self._dimension_value[2]
            self._raw_timezone = (
                self._dimension_value[3]
                if len(self._dimension_value) > 3 and self._dimension_value[3]
                else None
            )
            self._timezone = _gateway_timezone(self._dimension_value)
            self._day = self._dimension_value[5]
            self._month = self._dimension_value[6]
            self._year = self._dimension_value[7]
            if not all(
                _is_ascii_digits(v)
                for v in (self._hour, self._minute, self._second, self._day, self._month, self._year)
            ):
                raise ValueError(f"Invalid gateway datetime: {self._dimension_value!r}")
            self._datetime = _dt.datetime.fromisoformat(
                f"{self._year}-{self._month}-{self._day}T{self._hour}:{self._minute}:{self._second}{self._timezone}"  # pylint: disable=line-too-long
            )
            self._date = self._datetime.date()
            self._time = (
                self._datetime.timetz()
                if self._datetime.tzinfo is not None
                else self._datetime.time()
            )
            self._human_readable_log = (
                f"Gateway broadcasting internal datetime: {self._datetime}."
            )

    @property
    def time(self) -> _dt.time | None:
        """Return the decoded gateway internal time."""
        return self._time

    @property
    def date(self) -> _dt.date | None:
        """Return the decoded gateway internal date."""
        return self._date

    @property
    def datetime(self) -> _dt.datetime | None:
        """Return the decoded gateway internal datetime."""
        return self._datetime

    @property
    def timezone(self) -> str | None:
        """Return the decoded timezone offset string (e.g. '+02:00', '-05:00', or '')."""
        return self._timezone

    @property
    def raw_timezone(self) -> str | None:
        """Return the raw timezone string as reported by the gateway."""
        return self._raw_timezone

    @property
    def is_timezone_unconfigured(self) -> bool:
        """Return True if the gateway reported an unconfigured timezone (sentinel 999)."""
        return self._raw_timezone == "999"

    @property
    def is_clock_query(self) -> bool:
        """True if this message is a gateway clock/date/datetime query (Dimensions 0, 1, 22)."""
        return self.is_dimension_request and self._dimension in (0, 1, 22)

    @staticmethod
    def _resolve_tzinfo(time_zone: _dt.tzinfo | str) -> _dt.tzinfo:
        if isinstance(time_zone, _dt.tzinfo):
            return time_zone
        if isinstance(time_zone, str):
            return ZoneInfo(time_zone)
        raise ValueError(
            "time_zone must be a datetime.tzinfo instance or IANA timezone string"
        )

    @classmethod
    def _normalize_datetime(
        cls, dt: _dt.datetime, time_zone: _dt.tzinfo | str | None = None
    ) -> _dt.datetime:
        if not isinstance(dt, _dt.datetime):
            raise ValueError("dt must be a datetime.datetime instance")
        is_naive = dt.tzinfo is None or dt.tzinfo.utcoffset(dt) is None
        if time_zone is not None:
            tz = cls._resolve_tzinfo(time_zone)
            target = dt.replace(tzinfo=tz) if is_naive else dt.astimezone(tz)
        else:
            target = dt
        if target.tzinfo is None or target.tzinfo.utcoffset(target) is None:
            raise ValueError("Naive datetime/time requires an explicit time_zone")
        if not 2000 <= target.year <= 2099:
            raise ValueError("year must be between 2000 and 2099")
        return target

    @classmethod
    def _normalize_date(
        cls, d: _dt.date | _dt.datetime, time_zone: _dt.tzinfo | str | None = None
    ) -> _dt.date:
        if not isinstance(d, _dt.date):
            raise ValueError("d must be a datetime.date or datetime.datetime instance")
        if isinstance(d, _dt.datetime):
            return cls._normalize_datetime(d, time_zone=time_zone).date()
        if time_zone is not None:
            cls._resolve_tzinfo(time_zone)
        if not 2000 <= d.year <= 2099:
            raise ValueError("year must be between 2000 and 2099")
        return d

    @classmethod
    def _normalize_time(
        cls, t: _dt.time | _dt.datetime, time_zone: _dt.tzinfo | str | None = None
    ) -> tuple[_dt.datetime, str]:
        if not isinstance(t, (_dt.time, _dt.datetime)):
            raise ValueError("t must be a datetime.time or datetime.datetime instance")
        dt_val = (
            t
            if isinstance(t, _dt.datetime)
            else _dt.datetime.combine(_dt.datetime.now(_dt.timezone.utc).date(), t)
        )
        target = cls._normalize_datetime(dt_val, time_zone=time_zone)
        return target, cls._encode_tz_offset(target)

    @staticmethod
    def _encode_tz_offset(dt: _dt.datetime) -> str:
        z = dt.strftime("%z")
        # The TZ field (0HH / 1HH) carries whole hours only.
        if z[3:] != "00":
            raise ValueError(
                f"UTC offset {z[:3]}:{z[3:5]} is not a whole number of hours"
            )
        return f"0{z[1:3]}" if z[0] == "+" else f"1{z[1:3]}"

    @classmethod
    def set_datetime(
        cls, dt: _dt.datetime, time_zone: _dt.tzinfo | str | None = None
    ) -> OWNGatewayCommand:
        """Build a WHO 13 Dimension 22 datetime write frame (*#13**#22*H*M*S*TZ*0W*D*M*Y##)."""
        target = cls._normalize_datetime(dt, time_zone=time_zone)
        tz_offset = cls._encode_tz_offset(target)
        message = cls(
            f"*#13**#22*{target.strftime('%H*%M*%S')}*{tz_offset}*0{target.strftime('%w*%d*%m*%Y')}##"
        )
        message._human_readable_log = f"Setting gateway time to: {message._datetime}."
        return message

    @classmethod
    def set_date(
        cls, d: _dt.date | _dt.datetime, time_zone: _dt.tzinfo | str | None = None
    ) -> OWNGatewayCommand:
        """Build a WHO 13 Dimension 1 date write frame (*#13**#1*0W*D*M*Y##)."""
        target = cls._normalize_date(d, time_zone=time_zone)
        message = cls(f"*#13**#1*0{target.strftime('%w*%d*%m*%Y')}##")
        message._human_readable_log = f"Setting gateway date to: {message._date}."
        return message

    @classmethod
    def set_time(
        cls, t: _dt.time | _dt.datetime, time_zone: _dt.tzinfo | str | None = None
    ) -> OWNGatewayCommand:
        """Build a WHO 13 Dimension 0 time write frame (*#13**#0*H*M*S*TZ##)."""
        target, tz_offset = cls._normalize_time(t, time_zone=time_zone)
        message = cls(f"*#13**#0*{target.strftime('%H*%M*%S')}*{tz_offset}##")
        message._human_readable_log = f"Setting gateway time to: {message._time}."
        return message

    @classmethod
    def report_datetime(
        cls, dt: _dt.datetime, time_zone: _dt.tzinfo | str | None = None
    ) -> OWNGatewayCommand:
        """Build a WHO 13 Dimension 22 datetime reply frame (*#13**22*H*M*S*TZ*0W*D*M*Y##)."""
        target = cls._normalize_datetime(dt, time_zone=time_zone)
        tz_offset = cls._encode_tz_offset(target)
        message = cls(
            f"*#13**22*{target.strftime('%H*%M*%S')}*{tz_offset}*0{target.strftime('%w*%d*%m*%Y')}##"
        )
        return message

    @classmethod
    def report_date(
        cls, d: _dt.date | _dt.datetime, time_zone: _dt.tzinfo | str | None = None
    ) -> OWNGatewayCommand:
        """Build a WHO 13 Dimension 1 date reply frame (*#13**1*0W*D*M*Y##)."""
        target = cls._normalize_date(d, time_zone=time_zone)
        return cls(f"*#13**1*0{target.strftime('%w*%d*%m*%Y')}##")

    @classmethod
    def report_time(
        cls, t: _dt.time | _dt.datetime, time_zone: _dt.tzinfo | str | None = None
    ) -> OWNGatewayCommand:
        """Build a WHO 13 Dimension 0 time reply frame (*#13**0*H*M*S*TZ##)."""
        target, tz_offset = cls._normalize_time(t, time_zone=time_zone)
        return cls(f"*#13**0*{target.strftime('%H*%M*%S')}*{tz_offset}##")

    @classmethod
    def set_datetime_to_now(
        cls, time_zone: _dt.tzinfo | str
    ) -> OWNGatewayCommand:
        timezone = cls._resolve_tzinfo(time_zone)
        now = _dt.datetime.now(timezone)
        return cls.set_datetime(now)

    @classmethod
    def set_date_to_today(
        cls, time_zone: _dt.tzinfo | str
    ) -> OWNGatewayCommand:
        timezone = cls._resolve_tzinfo(time_zone)
        now = _dt.datetime.now(timezone)
        return cls.set_date(now)

    @classmethod
    def set_time_to_now(
        cls, time_zone: _dt.tzinfo | str
    ) -> OWNGatewayCommand:
        timezone = cls._resolve_tzinfo(time_zone)
        now = _dt.datetime.now(timezone)
        return cls.set_time(now)

    @classmethod
    def request_time(cls) -> OWNGatewayCommand:
        """Request the gateway internal time (Dimension 0)."""
        return cls("*#13**0##")

    @classmethod
    def request_date(cls) -> OWNGatewayCommand:
        """Request the gateway internal date (Dimension 1)."""
        return cls("*#13**1##")

    @classmethod
    def request_ip_address(cls) -> OWNGatewayCommand:
        """Request the gateway IP address (Dimension 10).

        own-firmware-oracle ``who13-identification``: answered by 8 of the 13
        emulated gateways and ACKed silently by F453, F453AV and MH200N, but
        H4684 020054 and MH200 020102 NACK it and crash their worker process.
        """
        return cls("*#13**10##")

    @classmethod
    def request_netmask(cls) -> OWNGatewayCommand:
        """Request the gateway netmask (Dimension 11).

        own-firmware-oracle ``who13-identification``: answered by 8 of the 13
        emulated gateways and ACKed silently by F453, F453AV and MH200N, but
        H4684 020054 and MH200 020102 NACK it and crash their worker process.
        """
        return cls("*#13**11##")

    @classmethod
    def request_mac_address(cls) -> OWNGatewayCommand:
        """Request the gateway MAC address (Dimension 12).

        own-firmware-oracle ``who13-identification``: answered by 8 of the 13
        emulated gateways and ACKed silently by F453, F453AV and MH200N, but
        H4684 020054 and MH200 020102 NACK it and crash their worker process.
        """
        return cls("*#13**12##")

    @classmethod
    def request_device_type(cls) -> OWNGatewayCommand:
        """Request the gateway device model type (Dimension 15)."""
        return cls("*#13**15##")

    @classmethod
    def request_firmware_version(cls) -> OWNGatewayCommand:
        """Request the gateway firmware version (Dimension 16)."""
        return cls("*#13**16##")

    @classmethod
    def request_uptime(cls) -> OWNGatewayCommand:
        """Request the gateway uptime (Dimension 19)."""
        return cls("*#13**19##")

    @classmethod
    def request_datetime(cls) -> OWNGatewayCommand:
        """Request the gateway internal datetime (Dimension 22)."""
        return cls("*#13**22##")

    @classmethod
    def request_kernel_version(cls) -> OWNGatewayCommand:
        """Request the gateway kernel version (Dimension 23)."""
        return cls("*#13**23##")

    @classmethod
    def request_distribution_version(cls) -> OWNGatewayCommand:
        """Request the gateway distribution version (Dimension 24)."""
        return cls("*#13**24##")

    @classmethod
    def keep_connect(cls) -> OWNGatewayCommand:
        """Build ZigBee readiness check ``*13*60*##`` (openwebnet4j GatewayMgmt.requestKeepConnect)."""
        return cls("*13*60*##")

    @classmethod
    def scan_network(cls) -> OWNGatewayCommand:
        """Build ZigBee network scan ``*13*65*##`` (openwebnet4j GatewayMgmt.requestScanNetwork)."""
        return cls("*13*65*##")

    @classmethod
    def enable_supervisor(cls) -> OWNGatewayCommand:
        """Build ZigBee supervisor enable ``*13*66*##`` (openwebnet4j GatewayMgmt.requestSupervisor, ownkb:claim:c001823)."""
        return cls("*13*66*##")

    @classmethod
    def disable_supervisor(cls) -> OWNGatewayCommand:
        """Build ZigBee supervisor remove ``*13*67*##``."""
        return cls("*13*67*##")

    @classmethod
    def request_product_count(cls) -> OWNGatewayCommand:
        """Request ZigBee stored product count ``*#13**67##`` (ownkb:claim:c000691)."""
        return cls("*#13**67##")

    @classmethod
    def get_product_info(cls, index: int) -> OWNGatewayCommand:
        """Request ZigBee product info ``*#13**66*<index>##``.

        Uses ``*`` before ``index`` instead of ``#`` to accommodate the USB stick
        firmware parser quirk documented in openwebnet4j GatewayMgmt.requestProductInfo.
        """
        if isinstance(index, bool) or not isinstance(index, int) or index < 0:
            raise ValueError("index must be a non-negative integer")
        msg = cls(f"*#13**66*{index}##")
        msg._human_readable_log = f"Requesting ZigBee product info at index {index}."
        return msg


register_event_parser(13, OWNGatewayEvent)
register_command_parser(13, OWNGatewayCommand)


class OWNGatewayDiagnosticEvent(OWNEvent):
    """WHO 1013: Gateway diagnostic events (dimension 1: object model)."""

    def __init__(self, data: str) -> None:
        super().__init__(data)

        self._device_type: str | None = None
        self._object_model: str | None = None
        self._n_conf: str | None = None
        self._brand: str | None = None
        self._line: str | None = None

        if self._dimension == 1 and self._dimension_value:
            self._object_model = self._dimension_value[0]
            if len(self._dimension_value) >= 2:
                self._n_conf = self._dimension_value[1]
            if len(self._dimension_value) >= 3:
                self._brand = self._dimension_value[2]
            if len(self._dimension_value) >= 4:
                self._line = self._dimension_value[3]

            self._device_type = WHO1013_DEVICE_TYPES.get(
                self._object_model, f"Unknown ({self._object_model})"
            )
            self._human_readable_log = (
                f"Gateway diagnostic object model is: {self._device_type} ({self._object_model})."
            )

    @property
    def device_type(self) -> str | None:
        """Return the decoded gateway device type string."""
        return self._device_type

    @property
    def object_model(self) -> str | None:
        """Return the raw diagnostic object model code."""
        return self._object_model

    @property
    def n_conf(self) -> str | None:
        """Return the diagnostic N_CONF field."""
        return self._n_conf

    @property
    def brand(self) -> str | None:
        """Return the diagnostic BRAND field."""
        return self._brand

    @property
    def line(self) -> str | None:
        """Return the diagnostic LINE field."""
        return self._line


class OWNGatewayDiagnosticCommand(OWNCommand):
    """WHO 1013: Gateway diagnostic requests and commands."""

    @classmethod
    def request_diagnostic_object_model(
        cls, where: str = ""
    ) -> OWNGatewayDiagnosticCommand:
        """Request the gateway diagnostic object model code (Dimension 1)."""
        return cls(f"*#1013*{where}*1##")


register_event_parser(1013, OWNGatewayDiagnosticEvent)
register_command_parser(1013, OWNGatewayDiagnosticCommand)

