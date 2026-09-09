"""OWNd mechanism for discovering gateways on local network"""

from __future__ import annotations

import asyncio
import email.parser
import socket
from contextlib import asynccontextmanager, suppress
from typing import Any
from urllib.parse import urlparse
from xml.parsers.expat import ExpatError

import aiohttp

# Use defusedxml instead of the stdlib XML parser: the XML processed here comes
# from network-discovered (and therefore untrusted) SSDP/SCPD endpoints, and the
# stdlib expat parser is vulnerable to entity-expansion / quadratic-blowup DoS.
from defusedxml.common import DefusedXmlException
from defusedxml.minidom import parseString

DEFAULT_PORT = 20000
# Bound discovery HTTP calls: a gateway that accepts the connection but never
# answers must not hang the discovery task indefinitely.
DISCOVERY_HTTP_TIMEOUT = aiohttp.ClientTimeout(total=10)
# USN prefixes identifying BTicino/Legrand OpenWebNet gateways in SSDP replies.
GATEWAY_USN_PREFIXES = (
    "uuid:pnp-webserver-",
    "uuid:pnp-scheduler-",
    "uuid:pnp-scheduler201-",
    "uuid:pnp-touchscreen-",
    "uuid:pnp-myhomeserver1-",
    "uuid:upnp-Basic gateway-",
    "uuid:upnp-IPscenariomodule-",
    "uuid:upnp-IPscenarioModule-",
)


def _node_text(xml, tag: str, default: str | None = None) -> str | None:
    """Text of the first <tag> element, or default if missing/empty.

    Guards against malformed or non-conforming XML (and HTML error pages):
    getElementsByTagName(...)[0] would otherwise raise IndexError.
    """
    nodes = xml.getElementsByTagName(tag)
    if not nodes or not nodes[0].childNodes:
        return default
    return nodes[0].childNodes[0].data


class SSDPMessage:
    """Simplified HTTP message to serve as a SSDP message."""

    def __init__(self, version="HTTP/1.1", headers=None):
        if headers is None:
            headers = []
        elif isinstance(headers, dict):
            headers = headers.items()

        self.version = version
        self.headers = list(headers)
        self.headers_dictionary: dict[str, str] = {}
        for header in self.headers:
            self.headers_dictionary.setdefault(header[0], header[1])

    @classmethod
    def parse(cls, msg):
        """
        Parse message a string into a :class:`SSDPMessage` instance.
        Args:
            msg (str): Message string.
        Returns:
            SSDPMessage: Message parsed from string.
        """
        raise NotImplementedError()

    @classmethod
    def parse_headers(cls, msg):
        """
        Parse HTTP headers.
        Args:
            msg (str): HTTP message.
        Returns:
            (List[Tuple[str, str]]): List of header tuples.
        """
        return list(email.parser.Parser().parsestr(msg).items())

    def __str__(self):
        """Return full HTTP message."""
        raise NotImplementedError()

    def __bytes__(self):
        """Return full HTTP message as bytes."""
        return self.__str__().encode().replace(b"\n", b"\r\n") + b"\r\n\r\n"


class SSDPResponse(SSDPMessage):
    """Simple Service Discovery Protocol (SSDP) response."""

    def __init__(self, status_code, reason, **kwargs):
        self.status_code = int(status_code)
        self.reason = reason
        super().__init__(**kwargs)

    @classmethod
    def parse(cls, msg):
        """Parse message string to response object."""
        lines = msg.splitlines()
        version, status_code, reason = lines[0].split()
        headers = cls.parse_headers("\r\n".join(lines[1:]))
        return cls(
            version=version, status_code=status_code, reason=reason, headers=headers
        )

    def __str__(self):
        """Return complete SSDP response."""
        lines = []
        lines.append(" ".join([self.version, str(self.status_code), self.reason]))
        for header in self.headers:
            lines.append(f"{header[0]}: {header[1]}")
        return "\n".join(lines)


class SSDPRequest(SSDPMessage):
    """Simple Service Discovery Protocol (SSDP) request."""

    def __init__(self, method, uri="*", version="HTTP/1.1", headers=None):
        self.method = method
        self.uri = uri
        super().__init__(version=version, headers=headers)

    @classmethod
    def parse(cls, msg):
        """Parse message string to request object."""
        lines = msg.splitlines()
        method, uri, version = lines[0].split()
        headers = cls.parse_headers("\r\n".join(lines[1:]))
        return cls(version=version, uri=uri, method=method, headers=headers)

    def __str__(self):
        """Return complete SSDP request."""
        lines = []
        lines.append(" ".join([self.method, self.uri, self.version]))
        for header in self.headers:
            lines.append(f"{header[0]}: {header[1]}")
        return "\n".join(lines)


class SimpleServiceDiscoveryProtocol(asyncio.DatagramProtocol):
    """
    Simple Service Discovery Protocol (SSDP).
    SSDP is part of UPnP protocol stack. For more information see:
    https://en.wikipedia.org/wiki/Simple_Service_Discovery_Protocol
    """

    def __init__(self, recvq, excq):
        """
        @param recvq    - asyncio.Queue for new datagrams
        @param excq     - asyncio.Queue for exceptions
        """
        self._recvq = recvq
        self._excq = excq

        # Transports are connected at the time a connection is made.
        self._transport = None

    def connection_made(self, transport):
        self._transport = transport

    def datagram_received(self, data, addr):
        # Anything on the network may answer an M-SEARCH: treat every datagram
        # as untrusted and never raise from this callback (an exception here
        # is only swallowed and logged by the event loop as an error).
        try:
            data = data.decode()
        except UnicodeDecodeError:
            return

        if not data.startswith("HTTP/"):
            return

        try:
            response = SSDPResponse.parse(data)
        except (ValueError, IndexError):
            # Malformed status line or headers: not a usable SSDP response.
            return

        headers = response.headers_dictionary
        usn = headers.get("USN", "")
        location = headers.get("LOCATION")
        ssdp_st = headers.get("ST")

        if location is None or ssdp_st is None:
            return

        if usn.startswith(GATEWAY_USN_PREFIXES):
            self._recvq.put_nowait(
                {
                    "address": addr[0],
                    "ssdp_location": location,
                    "ssdp_st": ssdp_st,
                }
            )

    def error_received(self, exc):
        self._excq.put_nowait(exc)

    def connection_lost(self, exc):
        if exc is not None:
            self._excq.put_nowait(exc)

        if self._transport is not None:
            self._transport.close()
            self._transport = None


@asynccontextmanager
async def _client_session(session: aiohttp.ClientSession | None):
    """Yield the caller-provided aiohttp session, or a short-lived one.

    Passing in Home Assistant's shared session avoids spinning up (and tearing
    down) a fresh connector on every discovery call.
    """
    if session is not None:
        yield session
    else:
        async with aiohttp.ClientSession() as owned_session:
            yield owned_session


def _get_soap_body(namespace: str, action: str) -> str:
    return f"""
        <?xml version="1.0"?>

        <soap:Envelope
        xmlns:soap="http://schemas.xmlsoap.org/soap/envelope/"
        soap:encodingStyle="http://schemas.xmlsoap.org/soap/encoding">

        <soap:Body>
        <m:{action} xmlns:m="{namespace}">
        </m:{action}>
        </soap:Body>

        </soap:Envelope>
    """


async def get_port(
    scpd_location: str, session: aiohttp.ClientSession | None = None
) -> int:

    host = urlparse(scpd_location).netloc
    scheme = urlparse(scpd_location).scheme
    try:
        async with _client_session(session) as http_session:
            service_ns = "urn:schemas-bticino-it:service:openserver:1"
            service_action = "getopenserverPort"
            service_control = "upnp/pwdControl"
            soap_body = _get_soap_body(service_ns, service_action)
            soap_action = f"{service_ns}#{service_action}"
            headers = {
                "SOAPAction": f'"{soap_action}"',
                "Host": f"{host}",
                "Content-Type": "text/xml",
                "Content-Length": str(len(soap_body)),
            }

            ctrl_url = f"{scheme}://{host}/{service_control}"
            resp = await http_session.post(
                ctrl_url,
                data=soap_body,
                headers=headers,
                timeout=DISCOVERY_HTTP_TIMEOUT,
            )
            resp.raise_for_status()
            soap_response = parseString(await resp.text()).documentElement

        port = _node_text(soap_response, "Port")
        return int(port) if port is not None else DEFAULT_PORT
    except (
        aiohttp.ClientError,
        DefusedXmlException,
        ExpatError,
        IndexError,
        ValueError,
        TimeoutError,
    ):
        # Unreachable gateway, HTTP error page, malformed/missing XML, timeout:
        # fall back to the default port instead of crashing discovery.
        return DEFAULT_PORT


async def _get_scpd_details(
    scpd_location: str, session: aiohttp.ClientSession | None = None
) -> dict:

    discovery_info: dict[str, Any] = {}

    async with _client_session(session) as http_session:
        scpd_response = await http_session.get(
            scpd_location, timeout=DISCOVERY_HTTP_TIMEOUT
        )
        scpd_response.raise_for_status()
        scpd_xml = parseString(await scpd_response.text()).documentElement

        for field in (
            "deviceType",
            "friendlyName",
            "manufacturer",
            "manufacturerURL",
            "modelName",
            "modelNumber",
            # "presentationURL",  ## bticino did not populate this field
            "serialNumber",
            "UDN",
        ):
            discovery_info[field] = _node_text(scpd_xml, field)

        discovery_info["port"] = await get_port(scpd_location, session=http_session)

    return discovery_info


async def find_gateways(session: aiohttp.ClientSession | None = None) -> list[dict]:

    return_list = []

    # Start the asyncio loop.
    loop = asyncio.get_running_loop()
    recvq: asyncio.Queue[dict[str, Any]] = asyncio.Queue()
    excq: asyncio.Queue[Exception] = asyncio.Queue()

    search_request = bytes(
        SSDPRequest(
            "M-SEARCH",
            headers={
                "MX": "2",
                "ST": "upnp:rootdevice",
                "MAN": '"ssdp:discover"',
                "HOST": "239.255.255.250:1900",
                "Content-Length": "0",
            },
        )
    )

    (
        transport,
        protocol,  # pylint: disable=unused-variable
    ) = await loop.create_datagram_endpoint(
        lambda: SimpleServiceDiscoveryProtocol(recvq, excq), family=socket.AF_INET
    )
    transport.sendto(search_request, ("239.255.255.250", 1900))
    try:
        await asyncio.sleep(2)
    finally:
        transport.close()

    while not recvq.empty():
        discovery_info = await recvq.get()
        # SCPD details are best-effort: a gateway that fails here is still
        # returned with the bare SSDP info.
        with suppress(
            aiohttp.ClientError,
            DefusedXmlException,
            ExpatError,
            IndexError,
            ValueError,
            TimeoutError,
            asyncio.TimeoutError,
        ):
            discovery_info.update(
                await _get_scpd_details(
                    discovery_info["ssdp_location"], session=session
                )
            )

        return_list.append(discovery_info)

    return return_list


async def get_gateway(
    address: str, session: aiohttp.ClientSession | None = None
) -> dict | None:
    _local_gateways = await find_gateways(session=session)
    for _gateway in _local_gateways:
        if _gateway["address"] == address:
            return _gateway
    return None


if __name__ == "__main__":
    local_gateways = asyncio.run(find_gateways())

    for gateway in local_gateways:
        print(f"Address: {gateway['address']}")
        print(f"Port: {gateway['port']}")
        print(f"Manufacturer: {gateway['manufacturer']}")
        print(f"Model: {gateway['modelName']}")
        print(f"Firmware: {gateway['modelNumber']}")
        print(f"Serial: {gateway['serialNumber']}")
        print()
