"""This module handles TCP connections to the OpenWebNet gateway"""

from __future__ import annotations

import asyncio
import contextlib
import hashlib
import hmac
import logging
import secrets
import socket
import string
from collections.abc import Callable
from urllib.parse import urlparse

from .discovery import find_gateways, get_gateway, get_port
from .message import OWNMessage, OWNSignaling
from .profiles import GatewayProfile, get_gateway_profile

# The gateway is expected to answer promptly during session negotiation and
# when acknowledging a command. These reads are bounded so a stalled or
# misbehaving gateway can never block the asyncio event loop indefinitely.
# NOTE: the *event* listener read (`OWNEventSession.get_next`) is intentionally
# NOT bounded: long periods of silence on the bus are normal and must not
# trigger spurious reconnections.
NEGOTIATION_TIMEOUT = 10
# The complete handshake may span several frames, but must still have one
# absolute deadline and a hard frame budget.
NEGOTIATION_TOTAL_TIMEOUT = 30
NEGOTIATION_MAX_FRAMES = 5
COMMAND_TIMEOUT = 10
# Status sweeps can legitimately return one frame per configured device.  Keep
# a hard budget, but leave enough headroom for large installations (the V2
# regression suite covers a 100-frame lighting sweep).
COMMAND_RESPONSE_MAX_FRAMES = 256
# Bound the TCP connect itself, so a black-holed host (SYN accepted, never
# completed) cannot hang the event loop for the OS-default TCP timeout.
CONNECT_TIMEOUT = 10
MAX_CONNECT_ATTEMPTS = 5
# Active keepalive: a harmless "gateway time" request that the MH201 answers.
# Sent periodically on the COMMAND session; a failure forces a reconnect.
KEEPALIVE_FRAME = "*#13**0##"
KEEPALIVE_INTERVAL = 900  # 15 minutes
EVENT_KEEPALIVE_FRAME = b"*#*1##"
# Passive watchdog on the EVENT session: if no frame arrives for this long the
# connection is presumed dead and re-established. Must be set ABOVE the gateway's
# own session lifetime (observed ~58 min on MH201) so it never false-positives
# during normal operation; it only catches a truly silent death (power loss,
# cable pulled) when no clean FIN/RST is received.
EVENT_INACTIVITY_TIMEOUT = 3900  # 65 minutes
# OS-level TCP keepalive for the EVENT session socket. The kernel sends empty
# probes on the *existing* connection (no new sessions, no gateway-side app
# load) and surfaces a dead link as a socket error, which the read loop turns
# into a reconnect. This actively detects a silent death (power loss, cable
# pulled, blackholed route) in ~TCP_KEEPALIVE_IDLE + TCP_KEEPALIVE_CNT *
# TCP_KEEPALIVE_INTVL seconds, instead of waiting for the passive watchdog.
TCP_KEEPALIVE_IDLE = 30  # start probing after 30s of silence
TCP_KEEPALIVE_INTVL = 10  # probe every 10s
TCP_KEEPALIVE_CNT = 3  # declare dead after 3 missed probes (~60s total)
# Negotiation failures that will never succeed on a retry: don't loop on them.
_FATAL_NEGOTIATION_ERRORS = frozenset(
    {"password_required", "password_error", "negotiation_error"}
)
# Pause before the next reconnection cycle when connect() returned without an
# open stream (gave up after MAX_CONNECT_ATTEMPTS, or hit a fatal negotiation
# error). Without this pause the event read loop would spin at full speed,
# hammering the gateway with connection attempts (observed ~100/s on an MH201
# whose session slots were exhausted after an outage: the flood prevented it
# from ever expiring its stale sessions and recovering on its own).
RECONNECT_PAUSE = 10
# Longer pause when the failure was fatal (e.g. a genuinely wrong password):
# retrying fast cannot help, and every attempt costs the gateway a session.
RECONNECT_PAUSE_FATAL = 60


def _first_scalar(value, default=None):
    """Return a scalar from legacy tuple/list discovery values."""
    while isinstance(value, (list, tuple)):
        if not value:
            return default
        value = value[0]
    return default if value is None else value


class OWNGateway:
    def __init__(self, discovery_info: dict):
        # Attributes potentially provided by user
        self.address = discovery_info.get("address")
        pw = discovery_info.get("password")
        self._password = str(pw) if pw not in (None, "") else None
        # Attributes retrieved from SSDP discovery
        self.ssdp_location = discovery_info.get("ssdp_location")
        self.ssdp_st = discovery_info.get("ssdp_st")
        # Attributes retrieved from UPnP device description
        self.device_type = discovery_info.get("deviceType")
        self.friendly_name = discovery_info.get("friendlyName")
        self.manufacturer = _first_scalar(
            discovery_info.get("manufacturer"), "BTicino S.p.A."
        )
        self.manufacturer_url = discovery_info.get("manufacturerURL")
        self.model_name = discovery_info.get("modelName", "Unknown model")
        self.model = self.model_name
        self.profile: GatewayProfile = get_gateway_profile(self.model_name)
        model_number = discovery_info.get("modelNumber")
        if isinstance(model_number, (list, tuple)):
            self.model_number = (
                ".".join(str(part) for part in model_number) if model_number else None
            )
        elif model_number is None:
            self.model_number = None
        else:
            self.model_number = str(model_number)
        # self.presentationURL = discovery_info.get("presentationURL")
        self.serial_number = discovery_info.get("serialNumber")
        self.udn = discovery_info.get("UDN")
        # Attributes retrieved from SOAP service control
        self.port = discovery_info.get("port") or self.profile.default_port

        self._log_id = f"[{self.model_name} gateway - {self.host}]"

    @property
    def unique_id(self) -> str | None:
        return self.serial_number

    @unique_id.setter
    def unique_id(self, unique_id: str) -> None:
        self.serial_number = unique_id

    @property
    def host(self) -> str | None:
        return self.address

    @host.setter
    def host(self, host: str) -> None:
        self.address = host

    @property
    def firmware(self) -> str | None:
        return self.model_number

    @firmware.setter
    def firmware(self, firmware: object) -> None:
        if isinstance(firmware, (list, tuple)):
            self.model_number = (
                ".".join(str(part) for part in firmware) if firmware else None
            )
        elif firmware is None:
            self.model_number = None
        else:
            self.model_number = str(firmware)

    @property
    def serial(self) -> str | None:
        return self.serial_number

    @serial.setter
    def serial(self, serial: str) -> None:
        self.serial_number = serial

    @property
    def password(self) -> str | None:
        return self._password

    @password.setter
    def password(self, password: str | None) -> None:
        self._password = str(password) if password not in (None, "") else None

    @property
    def log_id(self) -> str:
        return self._log_id

    @log_id.setter
    def log_id(self, value: str) -> None:
        self._log_id = value

    @classmethod
    async def get_first_available_gateway(cls, password: str | None = None):
        local_gateways = await find_gateways()
        if not local_gateways:
            return None
        local_gateways[0]["password"] = password
        return cls(local_gateways[0])

    @classmethod
    async def find_from_address(cls, address: str):
        if address is not None:
            gateway = await get_gateway(address)
            return cls(gateway) if gateway is not None else None
        return await cls.get_first_available_gateway()

    @classmethod
    async def build_from_discovery_info(cls, discovery_info: dict):
        # Work on our own copy: never mutate the caller's dict.
        discovery_info = dict(discovery_info)
        if (
            ("address" not in discovery_info or discovery_info["address"] is None)
            and "ssdp_location" in discovery_info
            and discovery_info["ssdp_location"] is not None
        ):
            discovery_info["address"] = urlparse(
                discovery_info["ssdp_location"]
            ).hostname

        if "port" in discovery_info and discovery_info["port"] is None:
            if (
                "ssdp_location" in discovery_info
                and discovery_info["ssdp_location"] is not None
            ):
                discovery_info["port"] = await get_port(discovery_info["ssdp_location"])
            elif "address" in discovery_info and discovery_info["address"] is not None:
                return await cls.find_from_address(discovery_info["address"])
            else:
                return await cls.get_first_available_gateway(
                    password=discovery_info.get("password")
                )

        return cls(discovery_info)


class OWNSession:
    """Connection to OpenWebNet gateway"""

    SEPARATOR = b"##"

    def __init__(
        self,
        gateway: OWNGateway | None = None,
        connection_type: str = "test",
        logger: logging.Logger | None = None,
        on_state_change: Callable[[bool], None] | None = None,
    ):
        """Initialize the class
        Arguments:
        gateway: OpenWebNet gateway instance
        connection_type: used when logging to identify this session
        logger: instance of logging
        on_state_change: optional callback invoked with True/False whenever the
            connection comes up / goes down. Lets a consumer (e.g. the Home
            Assistant integration) flip entity availability instantly instead of
            waiting for the next keepalive.
        """

        self._gateway = gateway
        self._type = connection_type.lower()
        # A session must always be able to log: fall back to the module
        # logger when the caller provides none (e.g. the classmethod helpers),
        # instead of crashing on `None.warning(...)` and masking the real error.
        self._logger = logger if logger is not None else logging.getLogger(__name__)
        self._on_state_change = on_state_change
        self._connected = False
        # Enable OS-level TCP keepalive on the socket (event session only).
        self._tcp_keepalive = False

        # Stream reader/writer, initialised on connect():
        self._stream_reader: asyncio.StreamReader | None = None
        self._stream_writer: asyncio.StreamWriter | None = None

    @property
    def is_connected(self) -> bool:
        """True once a session has been negotiated and not since lost."""
        return self._connected

    @property
    def _log_id(self) -> str:
        """Log prefix; safe also on a session created without a gateway."""
        # NB: must go through the *gateway*'s log_id — returning self._log_id
        # here would recurse into this very property.
        return self._gateway.log_id if self._gateway is not None else "[no gateway]"

    def _set_connected(self, value: bool) -> None:
        """Update connection state and notify the consumer on transitions only."""
        if value == self._connected:
            return
        self._connected = value
        if self._on_state_change is not None:
            try:
                self._on_state_change(value)
            except Exception:  # noqa: BLE001 - consumer callback must not break us
                if self._logger is not None:
                    self._logger.exception(
                        "%s on_state_change callback raised.", self._log_id
                    )

    def _apply_tcp_keepalive(self) -> None:
        """Enable OS-level TCP keepalive on the current socket (best-effort).

        Any failure (option unsupported, platform without the fine-grained
        Linux knobs, no socket) is logged and ignored: the connection keeps
        working exactly as before, so this can never break the link.
        """
        if not self._tcp_keepalive or self._stream_writer is None:
            return
        try:
            sock = self._stream_writer.get_extra_info("socket")
            if sock is None:
                return
            sock.setsockopt(socket.SOL_SOCKET, socket.SO_KEEPALIVE, 1)
            # Linux-specific fine tuning; absent on some platforms -> ignored.
            if hasattr(socket, "TCP_KEEPIDLE"):
                sock.setsockopt(
                    socket.IPPROTO_TCP, socket.TCP_KEEPIDLE, TCP_KEEPALIVE_IDLE
                )
            if hasattr(socket, "TCP_KEEPINTVL"):
                sock.setsockopt(
                    socket.IPPROTO_TCP, socket.TCP_KEEPINTVL, TCP_KEEPALIVE_INTVL
                )
            if hasattr(socket, "TCP_KEEPCNT"):
                sock.setsockopt(
                    socket.IPPROTO_TCP, socket.TCP_KEEPCNT, TCP_KEEPALIVE_CNT
                )
            self._logger.debug(
                "%s TCP keepalive enabled on event socket "
                "(idle=%ss, intvl=%ss, cnt=%s).",
                self._log_id,
                TCP_KEEPALIVE_IDLE,
                TCP_KEEPALIVE_INTVL,
                TCP_KEEPALIVE_CNT,
            )
        except OSError as err:
            self._logger.warning(
                "%s Could not enable TCP keepalive (%s); continuing without it.",
                self._log_id,
                err,
            )

    async def _read_frame(self, timeout: float | None = None) -> str:  # noqa: ASYNC109
        """Read one OWN frame (terminated by SEPARATOR) and return it decoded.

        When ``timeout`` is provided, an ``asyncio.TimeoutError`` is raised if the
        gateway stays silent for longer than that, so negotiation and command
        acknowledgements can never block the event loop indefinitely. The event
        listener passes ``None`` on purpose, as bus silence is expected there.
        """
        # Programming-error guard (and mypy narrowing): callers must have an
        # open connection before reading frames.
        assert self._stream_reader is not None
        reader = self._stream_reader.readuntil(OWNSession.SEPARATOR)
        if timeout is not None:
            raw_response = await asyncio.wait_for(reader, timeout=timeout)
        else:
            raw_response = await reader
        return raw_response.decode()

    @property
    def gateway(self) -> OWNGateway | None:
        return self._gateway

    @gateway.setter
    def gateway(self, gateway: OWNGateway) -> None:
        self._gateway = gateway

    @property
    def logger(self) -> logging.Logger:
        return self._logger

    @logger.setter
    def logger(self, logger: logging.Logger) -> None:
        self._logger = logger

    @property
    def connection_type(self) -> str:
        return self._type

    @connection_type.setter
    def connection_type(self, connection_type: str) -> None:
        self._type = connection_type.lower()

    @classmethod
    async def test_gateway(cls, gateway: OWNGateway) -> dict:
        connection = cls(gateway)
        return await connection.test_connection()

    async def test_connection(self) -> dict:
        assert self._gateway is not None
        retry_count = 0
        retry_timer = 1

        while True:
            try:
                if retry_count > 2:
                    self._logger.error(
                        "%s Test session connection still refused after 3 attempts.",
                        self._log_id,
                    )
                    return {"Success": False, "Message": "connection_error"}
                (
                    self._stream_reader,
                    self._stream_writer,
                ) = await asyncio.wait_for(
                    asyncio.open_connection(
                        self._gateway.address, self._gateway.port
                    ),
                    timeout=CONNECT_TIMEOUT,
                )
                break
            except (ConnectionRefusedError, TimeoutError, OSError) as error:
                self._logger.warning(
                    "%s Test session connection failed (%s), retrying in %ss.",
                    self._log_id,
                    error,
                    retry_timer,
                )
                await asyncio.sleep(retry_timer)
                retry_count += 1
                retry_timer *= 2

        try:
            try:
                return await self._negotiate()
            except ConnectionResetError:
                self._logger.error(
                    "%s Negotiation reset while opening %s session. Wait 60 seconds before retrying.",
                    self._log_id,
                    self._type,
                )
                return {"Success": False, "Message": "password_retry"}
            except (
                asyncio.IncompleteReadError,
                EOFError,
                TimeoutError,
                OSError,
            ) as error:
                # The gateway accepted the TCP connection but closed it (or timed
                # out) during negotiation: typical right after a reboot/power-cycle
                # when it is not ready yet. Report a clean transient failure instead
                # of letting the exception propagate and crash the caller's setup.
                self._logger.warning(
                    "%s Negotiation failed while opening %s session (%s).",
                    self._log_id,
                    self._type,
                    error,
                )
                return {"Success": False, "Message": "connection_error"}
        finally:
            # Test sessions are always temporary. Release the descriptor on
            # success, protocol rejection, transport failure and cancellation.
            with contextlib.suppress(Exception):
                await self.close()

    async def connect(self):
        assert self._gateway is not None
        self._logger.debug("%s Opening %s session.", self._log_id, self._type)

        retry_count = 0

        while True:
            try:
                # Bound the connect: open_connection has no timeout of its own.
                (
                    self._stream_reader,
                    self._stream_writer,
                ) = await asyncio.wait_for(
                    asyncio.open_connection(self._gateway.address, self._gateway.port),
                    timeout=CONNECT_TIMEOUT,
                )
                self._apply_tcp_keepalive()
                result = await self._negotiate()
                if result.get("Success"):
                    self._set_connected(True)
                    return result
                # Negotiation completed but was rejected.
                if result.get("Message") in _FATAL_NEGOTIATION_ERRORS:
                    self._logger.error(
                        "%s %s session negotiation failed (%s); giving up.",
                        self._log_id,
                        self._type.capitalize(),
                        result.get("Message"),
                    )
                    self._set_connected(False)
                    # The TCP connection survived the rejected negotiation:
                    # release it, it will not be used.
                    with contextlib.suppress(Exception):
                        await self.close()
                    return result
                reason = f"negotiation failed ({result.get('Message')})"
                wait = max(1, retry_count * 2)
            except ConnectionResetError:
                reason, wait = "connection reset", 60
            except (ConnectionRefusedError, asyncio.IncompleteReadError):
                reason, wait = "connection refused", max(1, retry_count * 2)
            except TimeoutError:
                reason, wait = (
                    f"connect timed out ({CONNECT_TIMEOUT}s)",
                    max(1, retry_count * 2),
                )
            except OSError as error:
                # Host unreachable, no route, DNS failure, etc.
                reason, wait = f"network error ({error})", max(1, retry_count * 2)

            retry_count += 1
            # A failed attempt can leave a half-open socket behind (e.g. TCP
            # connected but negotiation failed or was reset): release it before
            # retrying or giving up, so retries never accumulate leaked
            # descriptors.
            with contextlib.suppress(Exception):
                await self.close()
            if retry_count >= MAX_CONNECT_ATTEMPTS:
                self._logger.warning(
                    "%s %s session could not be established after %d attempts; "
                    "will retry.",
                    self._log_id,
                    self._type.capitalize(),
                    MAX_CONNECT_ATTEMPTS,
                )
                self._set_connected(False)
                return None
            self._logger.warning(
                "%s %s session: %s. Retrying in %ss (attempt %d/%d).",
                self._log_id,
                self._type.capitalize(),
                reason,
                wait,
                retry_count,
                MAX_CONNECT_ATTEMPTS,
            )
            await asyncio.sleep(wait)

    async def _reconnect(self) -> dict | None:
        """Tear down a (likely broken) connection and open a fresh one.

        Connection state is intentionally NOT flipped to False here: a routine
        reconnect (the gateway recycles the session ~hourly) recovers in well
        under a second and must not flap entity availability. State only goes
        False when connect() definitively gives up (see below).
        """
        # Closing a broken socket may itself fail; we don't care here.
        with contextlib.suppress(Exception):
            await self.close()
        return await self.connect()

    async def close(self) -> None:
        """Closes the connection to the OpenWebNet gateway."""

        # May be invoked on an empty instance, or on an already-broken socket:
        # be robust against Nones and against wait_closed() re-raising.
        if self._stream_writer is not None:
            self._stream_writer.close()
            # The peer may already be gone; we only need it marked closed.
            with contextlib.suppress(OSError, asyncio.IncompleteReadError):
                await self._stream_writer.wait_closed()
        self._stream_reader = None
        self._stream_writer = None
        if self._gateway is not None:
            self._logger.debug(
                "%s %s session closed.", self._log_id, self._type.capitalize()
            )

    async def _negotiate(self) -> dict:
        """Negotiate one session within an absolute deadline."""
        try:
            async with asyncio.timeout(NEGOTIATION_TOTAL_TIMEOUT):
                return await self._negotiate_exchange()
        except TimeoutError:
            self._logger.error(
                "%s Timed out negotiating %s session after %ss.",
                self._log_id,
                self._type,
                NEGOTIATION_TOTAL_TIMEOUT,
            )
            return {"Success": False, "Message": "negotiation_timeout"}

    async def _negotiate_exchange(self) -> dict:
        """Perform the bounded frame exchange for session negotiation."""
        # Programming-error guards (and mypy narrowing): negotiation is only
        # ever entered right after a successful open_connection() on a
        # session bound to a gateway.
        assert self._gateway is not None
        assert self._stream_reader is not None and self._stream_writer is not None

        if self._gateway.password is not None and not (
            isinstance(self._gateway.password, str)
            and self._gateway.password.isascii()
        ):
            self._logger.error(
                "%s Invalid OpenWebNet password: expected ASCII characters only.",
                self._log_id,
            )
            return {"Success": False, "Message": "password_error"}

        type_id = 0 if self._type == "command" else 1
        error = False
        error_message = None

        self._logger.debug(
            "%s Negotiating %s session.", self._log_id, self._type
        )

        frames_read = 0

        async def read_signaling() -> OWNSignaling:
            nonlocal frames_read
            if frames_read >= NEGOTIATION_MAX_FRAMES:
                raise TimeoutError(
                    f"negotiation exceeded {NEGOTIATION_MAX_FRAMES} frames"
                )
            frames_read += 1
            return OWNSignaling(await self._read_frame(NEGOTIATION_TIMEOUT))

        try:
            self._stream_writer.write(f"*99*{type_id}##".encode())
            await self._stream_writer.drain()

            resulting_message = await read_signaling()

            if resulting_message.is_nack() and self._type == "command":
                self._logger.debug(
                    "%s Standard command session refused; trying alternate session.",
                    self._log_id,
                )
                self._stream_writer.write(b"*99*9##")
                await self._stream_writer.drain()
                resulting_message = await read_signaling()

            if resulting_message.is_nack():
                self._logger.error(
                    "%s Error while opening %s session.",
                    self._log_id,
                    self._type,
                )
                return {"Success": False, "Message": "connection_refused"}

            resulting_message = await read_signaling()
            if resulting_message.is_nack():
                error = True
                error_message = "negotiation_refused"
                self._logger.debug(
                    "%s Reply: `%s`", self._log_id, resulting_message
                )
                self._logger.error(
                    "%s Error while opening %s session.",
                    self._log_id,
                    self._type,
                )
            elif resulting_message.is_sha():
                self._logger.debug(
                    "%s Received SHA challenge: `%s`",
                    self._log_id,
                    resulting_message,
                )
                if self._gateway.password is None:
                    error = True
                    error_message = "password_required"
                    self._logger.warning(
                        "%s Connection requires a password but none was provided.",
                        self._log_id,
                    )
                    self._stream_writer.write(b"*#*0##")
                    await self._stream_writer.drain()
                else:
                    method = "sha"
                    if resulting_message.is_sha_1():
                        method = "sha1"
                    elif resulting_message.is_sha_256():
                        method = "sha256"
                    self._logger.debug(
                        "%s Accepting %s challenge, initiating handshake.",
                        self._log_id,
                        method,
                    )
                    self._stream_writer.write(b"*#*1##")
                    await self._stream_writer.drain()
                    resulting_message = await read_signaling()
                    if resulting_message.is_nonce():
                        server_random_string_ra = resulting_message.nonce
                        # Rb must be unpredictable: use a CSPRNG (not `random`).
                        key = "".join(secrets.choice(string.digits) for _ in range(56))
                        client_random_string_rb = self._hex_string_to_int_string(
                            hmac.new(key=key.encode(), digestmod=method).hexdigest()
                        )
                        hashed_password = f"*#{client_random_string_rb}*{self._encode_hmac_password(method=method, password=self._gateway.password, nonce_a=server_random_string_ra, nonce_b=client_random_string_rb)}##"  # pylint: disable=line-too-long
                        self._logger.debug(
                            "%s Sending %s session password.",
                            self._log_id,
                            self._type,
                        )
                        self._stream_writer.write(hashed_password.encode())
                        await self._stream_writer.drain()
                        resulting_message = await read_signaling()
                        if resulting_message.is_nack():
                            error = True
                            error_message = "password_error"
                            self._logger.error(
                                "%s Password error while opening %s session.",
                                self._log_id,
                                self._type,
                            )
                        elif resulting_message.is_nonce():
                            hmac_response = resulting_message.nonce
                            expected_response = self._decode_hmac_response(
                                method=method,
                                password=self._gateway.password,
                                nonce_a=server_random_string_ra,
                                nonce_b=client_random_string_rb,
                            )
                            # Constant-time comparison: never leak through
                            # timing how much of the digest matched.
                            if expected_response is not None and hmac.compare_digest(
                                hmac_response, expected_response
                            ):
                                self._stream_writer.write(b"*#*1##")
                                await self._stream_writer.drain()
                                self._logger.debug(
                                    "%s Session established successfully.",
                                    self._log_id,
                                )
                            else:
                                self._logger.error(
                                    "%s Server identity could not be confirmed.",
                                    self._log_id,
                                )
                                self._stream_writer.write(b"*#*0##")
                                await self._stream_writer.drain()
                                error = True
                                error_message = "negotiation_error"
                                self._logger.error(
                                    "%s Error while opening %s session: HMAC authentication failed.",
                                    self._log_id,
                                    self._type,
                                )
                        else:
                            error = True
                            error_message = "negotiation_error"
                            self._logger.error(
                                "%s Unexpected response `%s` after sending the HMAC password; "
                                "closing %s session.",
                                self._log_id,
                                resulting_message,
                                self._type,
                            )
                    else:
                        error = True
                        error_message = "negotiation_error"
                        self._logger.error(
                            "%s Unexpected response `%s` after accepting the HMAC challenge; "
                            "closing %s session.",
                            self._log_id,
                            resulting_message,
                            self._type,
                        )
            elif resulting_message.is_nonce():
                self._logger.debug(
                    "%s Received nonce: `%s`", self._log_id, resulting_message
                )
                if self._gateway.password is not None:
                    if not self._gateway.password.isdecimal():
                        error = True
                        error_message = "password_error"
                        self._logger.error(
                            "%s Gateway requested legacy numeric authentication, but provided password is not decimal digits only.",
                            self._log_id,
                        )
                    else:
                        hashed_password = f"*#{self._get_own_password(self._gateway.password, resulting_message.nonce)}##"  # pylint: disable=line-too-long
                        self._logger.debug(
                            "%s Sending %s session password.",
                            self._log_id,
                            self._type,
                        )
                        self._stream_writer.write(hashed_password.encode())
                        await self._stream_writer.drain()
                        resulting_message = await read_signaling()
                        if resulting_message.is_nack():
                            error = True
                            error_message = "password_error"
                            self._logger.error(
                                "%s Password error while opening %s session.",
                                self._log_id,
                                self._type,
                            )
                        elif resulting_message.is_ack():
                            self._logger.debug(
                                "%s %s session established successfully.",
                                self._log_id,
                                self._type.capitalize(),
                            )
                        else:
                            error = True
                            error_message = "negotiation_error"
                            self._logger.error(
                                "%s Unexpected response `%s` after sending the legacy password; "
                                "closing %s session.",
                                self._log_id,
                                resulting_message,
                                self._type,
                            )
                else:
                    error = True
                    error_message = "password_error"
                    self._logger.error(
                        "%s Connection requires a password but none was provided for %s session.",
                        self._log_id,
                        self._type,
                    )
            elif resulting_message.is_ack():
                self._logger.debug(
                    "%s %s session established successfully.",
                    self._log_id,
                    self._type.capitalize(),
                )
            else:
                error = True
                error_message = "negotiation_failed"
                self._logger.debug(
                    "%s Unexpected message during negotiation: %s",
                    self._log_id,
                    resulting_message,
                )
        except TimeoutError:
            error = True
            error_message = "negotiation_timeout"
            self._logger.error(
                "%s Timed out negotiating %s session.",
                self._log_id,
                self._type,
            )
        except asyncio.IncompleteReadError:
            # The gateway closed the connection mid-negotiation. This is NOT
            # a password problem: it happens when the gateway is busy or out
            # of session slots (e.g. an MH201 still holding stale sessions
            # right after an outage). It must be treated as transient — never
            # as a fatal error — so connect() retries it with back-off.
            error = True
            error_message = "connection_closed"
            self._logger.warning(
                "%s Connection closed by the gateway while negotiating %s "
                "session (busy or out of session slots?); will retry.",
                self._log_id,
                self._type,
            )

        return {"Success": not error, "Message": error_message}

    def _get_own_password(self, password, nonce, test: bool = False):
        # Retained for compatibility with the previously vendored implementation.
        # Do not print password-derived intermediate values even in test mode.
        del test
        start = True
        num1 = 0
        num2 = 0
        password = int(password)
        for character in nonce:
            if character != "0":
                if start:
                    num2 = password
                start = False
            if character == "1":
                num1 = (num2 & 0xFFFFFF80) >> 7
                num2 = num2 << 25
            elif character == "2":
                num1 = (num2 & 0xFFFFFFF0) >> 4
                num2 = num2 << 28
            elif character == "3":
                num1 = (num2 & 0xFFFFFFF8) >> 3
                num2 = num2 << 29
            elif character == "4":
                num1 = num2 << 1
                num2 = num2 >> 31
            elif character == "5":
                num1 = num2 << 5
                num2 = num2 >> 27
            elif character == "6":
                num1 = num2 << 12
                num2 = num2 >> 20
            elif character == "7":
                num1 = (
                    num2 & 0x0000FF00
                    | ((num2 & 0x000000FF) << 24)
                    | ((num2 & 0x00FF0000) >> 16)
                )
                num2 = (num2 & 0xFF000000) >> 8
            elif character == "8":
                num1 = (num2 & 0x0000FFFF) << 16 | (num2 >> 24)
                num2 = (num2 & 0x00FF0000) >> 8
            elif character == "9":
                num1 = ~num2
            else:
                num1 = num2

            num1 &= 0xFFFFFFFF
            num2 &= 0xFFFFFFFF
            if character not in "09":
                num1 |= num2
            num2 = num1
        return num1

    def _encode_hmac_password(
        self, method: str, password: str, nonce_a: str, nonce_b: str
    ):
        # SHA-1 here is mandated by the OpenWebNet protocol: the gateway
        # selects the digest, the client cannot opt out. See nosec below.
        if method == "sha1":
            message = (
                self._int_string_to_hex_string(nonce_a)
                + self._int_string_to_hex_string(nonce_b)
                + "736F70653E"
                + "636F70653E"
                + hashlib.sha1(password.encode()).hexdigest()  # nosec B324
            )
            return self._hex_string_to_int_string(
                hashlib.sha1(message.encode()).hexdigest()  # nosec B324
            )
        if method == "sha256":
            message = (
                self._int_string_to_hex_string(nonce_a)
                + self._int_string_to_hex_string(nonce_b)
                + "736F70653E"
                + "636F70653E"
                + hashlib.sha256(password.encode()).hexdigest()
            )
            return self._hex_string_to_int_string(
                hashlib.sha256(message.encode()).hexdigest()
            )
        return None

    def _decode_hmac_response(
        self, method: str, password: str, nonce_a: str, nonce_b: str
    ):
        # SHA-1 here is mandated by the OpenWebNet protocol: the gateway
        # selects the digest, the client cannot opt out. See nosec below.
        if method == "sha1":
            message = (
                self._int_string_to_hex_string(nonce_a)
                + self._int_string_to_hex_string(nonce_b)
                + hashlib.sha1(password.encode()).hexdigest()  # nosec B324
            )
            return self._hex_string_to_int_string(
                hashlib.sha1(message.encode()).hexdigest()  # nosec B324
            )
        if method == "sha256":
            message = (
                self._int_string_to_hex_string(nonce_a)
                + self._int_string_to_hex_string(nonce_b)
                + hashlib.sha256(password.encode()).hexdigest()
            )
            return self._hex_string_to_int_string(
                hashlib.sha256(message.encode()).hexdigest()
            )
        return None

    def _int_string_to_hex_string(self, int_string: str) -> str:
        hex_string = ""
        for i in range(0, len(int_string), 2):
            hex_string += f"{int(int_string[i : i + 2]):x}"
        return hex_string

    def _hex_string_to_int_string(self, hex_string: str) -> str:
        int_string = ""
        for i in range(0, len(hex_string), 1):
            int_string += f"{int(hex_string[i : i + 1], 16):0>2d}"
        return int_string


class OWNEventSession(OWNSession):
    def __init__(
        self,
        gateway: OWNGateway | None = None,
        logger: logging.Logger | None = None,
        inactivity_timeout: float | None = EVENT_INACTIVITY_TIMEOUT,
        on_state_change: Callable[[bool], None] | None = None,
    ):
        super().__init__(
            gateway=gateway,
            connection_type="event",
            logger=logger,
            on_state_change=on_state_change,
        )
        # Passive watchdog: reconnect if no frame arrives for this long.
        # Set to None to disable (pure blocking read, never times out).
        self._inactivity_timeout = inactivity_timeout
        # The event session is the long-lived monitored connection: let the OS
        # actively probe it so a silent outage is detected in ~60s.
        self._tcp_keepalive = True
        self._keepalive_interval = (
            gateway.profile.event_keepalive_interval if gateway is not None else None
        )
        self._keepalive_task: asyncio.Task[None] | None = None

    async def connect(self):
        await self._stop_keepalive()
        result = await super().connect()
        if result is not None and result.get("Success"):
            self._start_keepalive()
        return result

    def _start_keepalive(self) -> None:
        if self._keepalive_interval is None:
            return
        self._keepalive_task = asyncio.create_task(self._keepalive_loop())

    async def _stop_keepalive(self) -> None:
        task = self._keepalive_task
        self._keepalive_task = None
        if task is None or task is asyncio.current_task():
            return
        task.cancel()
        with contextlib.suppress(asyncio.CancelledError):
            await task

    async def _keepalive_loop(self) -> None:
        assert self._keepalive_interval is not None
        try:
            while True:
                await asyncio.sleep(self._keepalive_interval)
                if self._stream_writer is None:
                    return
                self._stream_writer.write(EVENT_KEEPALIVE_FRAME)
                await self._stream_writer.drain()
                self._logger.debug("%s Event session keepalive sent.", self._log_id)
        except asyncio.CancelledError:
            raise
        except (ConnectionError, OSError) as error:
            self._logger.warning(
                "%s Event session keepalive failed (%s).", self._log_id, error
            )
            if self._stream_writer is not None:
                self._stream_writer.close()

    async def close(self) -> None:
        await self._stop_keepalive()
        await super().close()

    @classmethod
    async def connect_to_gateway(cls, gateway: OWNGateway):
        connection = cls(gateway)
        try:
            return await connection.connect()
        finally:
            with contextlib.suppress(Exception):
                await connection.close()

    async def get_next(self) -> OWNMessage | str | None:
        """Acts as an entry point to read messages on the event bus.
        It will read one frame and return it as an OWNMessage object.

        Bus silence is normal, so the read does not time out aggressively;
        however a *very* long silence (``inactivity_timeout``, set above the
        gateway's own session lifetime) is treated as a dead connection and
        triggers a reconnect — this catches a silent death (power loss, cable
        pulled) where no clean FIN/RST is ever received. On any loss of
        connectivity it transparently reconnects and returns None for that
        cycle; the caller simply calls it again.
        """
        if self._stream_reader is None:
            # No live connection (e.g. a previous reconnect attempt gave up).
            self._logger.warning(
                "%s Event session not connected, reconnecting...",
                self._log_id,
            )
            result = await self._reconnect()
            if self._stream_reader is None:
                # Still no stream: connect() gave up or failed fatally and
                # returned IMMEDIATELY (its internal back-off only covers the
                # transient retries). Pause here, otherwise the caller's read
                # loop would re-enter this branch instantly and flood the
                # gateway with connection attempts.
                pause = (
                    RECONNECT_PAUSE_FATAL
                    if result is not None
                    and result.get("Message") in _FATAL_NEGOTIATION_ERRORS
                    else RECONNECT_PAUSE
                )
                self._logger.warning(
                    "%s Reconnection failed; next attempt in %ss.",
                    self._log_id,
                    pause,
                )
                await asyncio.sleep(pause)
            return None
        try:
            read = self._stream_reader.readuntil(OWNSession.SEPARATOR)
            if self._inactivity_timeout is not None:
                data = await asyncio.wait_for(read, timeout=self._inactivity_timeout)
            else:
                data = await read
        except TimeoutError:
            self._logger.warning(
                "%s No bus traffic for %ss; assuming stale connection, reconnecting...",
                self._log_id,
                self._inactivity_timeout,
            )
            await self._reconnect()
            return None
        except (
            asyncio.IncompleteReadError,
            asyncio.LimitOverrunError,
            ConnectionError,
            OSError,
        ):
            # Covers EOF, RST (ConnectionResetError), aborted connections,
            # over-long frames and other socket errors: reconnect in all cases.
            self._logger.warning(
                "%s Event connection lost, reconnecting...", self._log_id
            )
            await self._reconnect()
            return None
        except Exception:  # pylint: disable=broad-except
            self._logger.exception(
                "%s Event session crashed, reconnecting...", self._log_id
            )
            await self._reconnect()
            return None

        # A frame was read successfully: from here on, any failure is a
        # *parsing* problem, not a connection problem. Never tear the session
        # down (and lose bus events) over a frame we could not make sense of.
        try:
            _decoded_data = data.decode()
            _message = OWNMessage.parse(_decoded_data)
            return _message if _message else _decoded_data
        except (UnicodeDecodeError, ValueError, IndexError, TypeError) as error:
            _decoded_data = data.decode(errors="replace")
            self._logger.warning(
                "%s Malformed event frame %r: %s",
                self._log_id,
                _decoded_data,
                error,
            )
            return _decoded_data


class OWNCommandSession(OWNSession):
    def __init__(
        self,
        gateway: OWNGateway | None = None,
        logger: logging.Logger | None = None,
        on_state_change: Callable[[bool], None] | None = None,
    ):
        super().__init__(
            gateway=gateway,
            connection_type="command",
            logger=logger,
            on_state_change=on_state_change,
        )
        # Serializes concurrent senders sharing this session (e.g. the
        # keepalive loop and a regular command): interleaved write/read pairs
        # on the same stream would steal each other's acknowledgements.
        self._send_lock = asyncio.Lock()

    @classmethod
    async def send_to_gateway(cls, message: str, gateway: OWNGateway):
        connection = cls(gateway)
        try:
            await connection.connect()
            return await connection.send(message)
        finally:
            with contextlib.suppress(Exception):
                await connection.close()

    @classmethod
    async def connect_to_gateway(cls, gateway: OWNGateway):
        connection = cls(gateway)
        try:
            return await connection.connect()
        finally:
            with contextlib.suppress(Exception):
                await connection.close()

    @classmethod
    async def probe_gateway(
        cls, gateway: OWNGateway, logger: logging.Logger | None = None
    ) -> bool:
        """Probe gateway responsiveness with a read-only model request."""
        connection = cls(gateway=gateway, logger=logger)
        try:
            result = await connection.connect()
            if result is None or not result.get("Success", False):
                return False
            response = await connection.send(
                "*#13**15##", is_status_request=True
            )
            return response is not None
        except Exception:  # noqa: BLE001 - watchdog probes must be fail-safe
            return False
        finally:
            with contextlib.suppress(Exception):
                await connection.close()

    async def keepalive(self) -> bool:
        """Send one harmless keepalive (gateway time request) on this command
        session. Returns True if the gateway acknowledged, False otherwise.

        ``send()`` already reconnects on a broken socket, so a False here means
        the gateway is genuinely unresponsive even after a reconnect attempt.
        """
        try:
            result = await self.send(KEEPALIVE_FRAME, is_status_request=True)
            return result is not None
        except Exception:  # pylint: disable=broad-except
            self._logger.exception("%s Keepalive failed.", self._log_id)
            return False

    async def run_keepalive(
        self, stop_event: asyncio.Event, interval: float = KEEPALIVE_INTERVAL
    ) -> None:
        """Background loop: ping the gateway every ``interval`` seconds until
        ``stop_event`` is set. Meant to be launched as an asyncio task."""
        self._logger.info(
            "%s Keepalive started (every %ss).", self._log_id, interval
        )
        while not stop_event.is_set():
            try:
                await asyncio.wait_for(stop_event.wait(), timeout=interval)
            except TimeoutError:
                ok = await self.keepalive()
                self._logger.debug(
                    "%s Keepalive %s.",
                    self._log_id,
                    "ok" if ok else "FAILED",
                )

    async def _read_command_response(
        self,
    ) -> tuple[OWNSignaling, list[OWNMessage | str]]:
        """Read a bounded command response through its final ACK or NACK.

        Status and dimension frames preceding the signaling terminator are
        returned to the caller instead of being discarded.
        """
        collected: list[OWNMessage | str] = []
        async with asyncio.timeout(COMMAND_TIMEOUT):
            for _ in range(COMMAND_RESPONSE_MAX_FRAMES):
                raw_response = await self._read_frame(COMMAND_TIMEOUT)
                try:
                    resulting_message = OWNMessage.parse(raw_response)
                except (ValueError, IndexError, TypeError) as error:
                    self._logger.warning(
                        "%s Malformed command response %r: %s",
                        self._log_id,
                        raw_response,
                        error,
                    )
                    resulting_message = None
                if isinstance(resulting_message, OWNSignaling):
                    if resulting_message.is_ack() or resulting_message.is_nack():
                        return resulting_message, collected
                    self._logger.debug(
                        "%s Ignoring non-terminal signaling response `%s`.",
                        self._log_id,
                        resulting_message,
                    )
                    continue
                collected.append(resulting_message or raw_response)
                self._logger.debug(
                    "%s Collected command response `%s`.",
                    self._log_id,
                    collected[-1],
                )
        raise TimeoutError(
            f"no signaling response within {COMMAND_RESPONSE_MAX_FRAMES} frames"
        )

    async def _read_signaling_response(self) -> OWNSignaling:
        """Read only the final signaling frame for backward compatibility."""
        signaling, _ = await self._read_command_response()
        return signaling

    async def send(
        self, message, is_status_request: bool = False
    ) -> list[OWNMessage | str] | bool | None:
        """Send the attached message on an existing 'command' connection,
        actively reconnecting it if it had been reset.

        Concurrency-safe: an internal lock serializes callers sharing this
        session (e.g. ``run_keepalive`` alongside regular commands), so the
        write/read-acknowledgement pairs can never interleave.

        Retries (both on NACK and on connection reset/timeout) are bounded and
        iterative, never recursive, so a flapping connection can neither grow
        the call stack nor loop forever.
        """
        async with self._send_lock:
            return await self._locked_send(message, is_status_request)

    async def _locked_send(
        self, message, is_status_request: bool = False
    ) -> list[OWNMessage | str] | bool | None:
        # One retry is enough for an immediate NACK or for a connection that
        # was already unavailable.  More importantly, never replay a command
        # after it was written: the gateway may have executed it even if its
        # acknowledgement was lost.  Status requests are idempotent and can be
        # retried safely after a transport reset.
        max_attempts = 2

        for attempt in range(1, max_attempts + 1):
            # After an outage the previous connect()/reconnect may have given up
            # and left the writer at None; rebuild the session here so commands
            # resume automatically when the gateway comes back, instead of
            # crashing forever on `NoneType.write`.
            if self._stream_reader is None or self._stream_writer is None:
                result = await self.connect()
                if (
                    result is None
                    or not result.get("Success", False)
                    or self._stream_reader is None
                    or self._stream_writer is None
                ):
                    await self.close()
                    self._logger.warning(
                        "%s Command session unavailable; message `%s` not sent.",
                        self._log_id,
                        message,
                    )
                    return None

            written = False
            try:
                self._stream_writer.write(str(message).encode())
                written = True
                await self._stream_writer.drain()

                resulting_message, collected = await self._read_command_response()

                if resulting_message.is_ack():
                    log_message = "%s Message `%s` was successfully sent."
                    if not is_status_request:
                        self._logger.info(log_message, self._log_id, message)
                    else:
                        self._logger.debug(log_message, self._log_id, message)
                    return collected or True

                if resulting_message.is_nack():
                    # A NACK after response data terminates that transaction;
                    # replaying it would duplicate the already returned sweep.
                    if collected or attempt == max_attempts:
                        if is_status_request:
                            self._logger.debug(
                                "%s Gateway rejected status request %s (NACK, %s response(s)). Subsystem or device may not be present.",
                                self._log_id,
                                message,
                                len(collected),
                            )
                        else:
                            self._logger.error(
                                "%s Could not send message `%s`. No more retries.",
                                self._log_id,
                                message,
                            )
                        return None
                    self._logger.error(
                        "%s Could not send message `%s`. Retrying (%d)...",
                        self._log_id,
                        message,
                        attempt,
                    )
                    continue

                self._logger.warning(
                    "%s Unexpected response `%s` to message `%s`.",
                    self._log_id,
                    resulting_message,
                    message,
                )
                return None

            except asyncio.CancelledError:
                await self.close()
                raise
            except TimeoutError:
                await self.close()
                self._logger.warning(
                    "%s Timed out awaiting the complete response for `%s`; "
                    "command session closed.",
                    self._log_id,
                    message,
                )
                return None
            except (
                ConnectionResetError,
                asyncio.IncompleteReadError,
                asyncio.LimitOverrunError,
                OSError,
            ) as error:
                await self.close()
                if attempt < max_attempts and (is_status_request or not written):
                    self._logger.debug(
                        "%s Command session connection lost (%s), retrying once...",
                        self._log_id,
                        error,
                    )
                    continue
                self._logger.warning(
                    "%s Connection lost before acknowledgement of `%s`; "
                    "message will not be replayed.",
                    self._log_id,
                    message,
                )
                return None
            except Exception:  # pylint: disable=broad-except
                await self.close()
                self._logger.exception(
                    "%s Command session crashed.", self._log_id
                )
                return None
