""" This module handles TCP connections to the OpenWebNet gateway """

import asyncio
import socket as _socket
import hmac
import hashlib
import string
import random
import logging
from typing import Union
from urllib.parse import urlparse

from .discovery import find_gateways, get_gateway, get_port
from .message import OWNMessage, OWNSignaling


class OWNGateway:
    def __init__(self, discovery_info: dict):
        # Attributes potentially provided by user
        self.address = (
            discovery_info["address"] if "address" in discovery_info else None
        )
        self._password = (
            discovery_info["password"] if "password" in discovery_info else None
        )
        # Attributes retrieved from SSDP discovery
        self.ssdp_location = (
            discovery_info["ssdp_location"]
            if "ssdp_location" in discovery_info
            else None
        )
        self.ssdp_st = (
            discovery_info["ssdp_st"] if "ssdp_st" in discovery_info else None
        )
        # Attributes retrieved from UPnP device description
        self.device_type = (
            discovery_info["deviceType"] if "deviceType" in discovery_info else None
        )
        self.friendly_name = (
            discovery_info["friendlyName"] if "friendlyName" in discovery_info else None
        )
        self.manufacturer = (
            discovery_info["manufacturer"]
            if "manufacturer" in discovery_info
            else "BTicino S.p.A."
        )
        self.manufacturer_url = (
            discovery_info["manufacturerURL"]
            if "manufacturerURL" in discovery_info
            else None
        )
        self.model_name = (
            discovery_info["modelName"]
            if "modelName" in discovery_info
            else "Unknown model"
        )
        self.model_number = (
            discovery_info["modelNumber"] if "modelNumber" in discovery_info else None
        )
        # self.presentationURL = (
        #     discovery_info["presentationURL"]
        #     if "presentationURL" in discovery_info
        #     else None
        # )
        self.serial_number = (
            discovery_info["serialNumber"] if "serialNumber" in discovery_info else None
        )
        self.udn = discovery_info["UDN"] if "UDN" in discovery_info else None
        # Attributes retrieved from SOAP service control
        self.port = discovery_info["port"] if "port" in discovery_info else None

        self._log_id = f"[{self.model_name} gateway - {self.host}]"

    @property
    def unique_id(self) -> str:
        return self.serial_number

    @unique_id.setter
    def unique_id(self, unique_id: str) -> None:
        self.serial_number = unique_id

    @property
    def host(self) -> str:
        return self.address

    @host.setter
    def host(self, host: str) -> None:
        self.address = host

    @property
    def firmware(self) -> str:
        return self.model_number

    @firmware.setter
    def firmware(self, firmware: str) -> None:
        self.model_number = firmware

    @property
    def serial(self) -> str:
        return self.serial_number

    @serial.setter
    def serial(self, serial: str) -> None:
        self.serial_number = serial

    @property
    def password(self) -> str:
        return self._password

    @password.setter
    def password(self, password: str) -> None:
        self._password = password

    @property
    def log_id(self) -> str:
        return self._log_id

    @log_id.setter
    def log_id(self, id: str) -> None:
        self._log_id = id

    @classmethod
    async def get_first_available_gateway(cls, password: str = None):
        local_gateways = await find_gateways()
        local_gateways[0]["password"] = password
        return cls(local_gateways[0])

    @classmethod
    async def find_from_address(cls, address: str):
        if address is not None:
            return cls(await get_gateway(address))
        else:
            return await cls.get_first_available_gateway()

    @classmethod
    async def build_from_discovery_info(cls, discovery_info: dict):
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
                    password=discovery_info["password"]
                    if "password" in discovery_info
                    else None
                )

        return cls(discovery_info)


class OWNSession:
    """Connection to OpenWebNet gateway"""

    SEPARATOR = "##".encode()

    def __init__(
        self,
        gateway: OWNGateway = None,
        connection_type: str = "test",
        logger: logging.Logger = None,
    ):
        """Initialize the class
        Arguments:
        gateway: OpenWebNet gateway instance
        connection_type: used when logging to identify this session
        logger: instance of logging
        """

        self._gateway = gateway
        self._type = connection_type.lower()
        self._logger = logger

        # annotations for stream reader/writer:
        self._stream_reader: asyncio.StreamReader
        self._stream_writer: asyncio.StreamWriter
        # init them to None:
        self._stream_reader = None
        self._stream_writer = None

    @property
    def gateway(self) -> OWNGateway:
        return self._gateway

    @gateway.setter
    def gateway(self, gateway: OWNGateway) -> None:
        self._gateway = gateway

    # password is a property inside OWNGateway... right?
    #@property
    #def password(self) -> str:
    #    return str(self._password)
    #@password.setter
    #def password(self, password: str) -> None:
    #    self._password = password

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
        retry_count = 0
        retry_timer = 1

        while True:
            try:
                if retry_count > 2:
                    self._logger.error(
                        "%s Test session connection still refused after 3 attempts.",
                        self._gateway.log_id,
                    )
                    return None
                (
                    self._stream_reader,
                    self._stream_writer,
                ) = await asyncio.open_connection(
                    self._gateway.address, self._gateway.port
                )
                break
            except ConnectionRefusedError:
                self._logger.warning(
                    "%s Test session connection refused, retrying in %ss.",
                    self._gateway.log_id,
                    retry_timer,
                )
                await asyncio.sleep(retry_timer)
                retry_count += 1
                retry_timer *= 2

        try:
            result = await self._negotiate()
            await self.close()
        except ConnectionResetError:
            error = True
            error_message = "password_retry"
            self._logger.error(
                "%s Negotiation reset while opening %s session. Wait 60 seconds before retrying.",
                self._gateway.log_id,
                self._type,
            )

            return {"Success": not error, "Message": error_message}

        return result

    async def connect(self):
        self._logger.debug("%s Opening %s session.", self._gateway.log_id, self._type)

        retry_count = 0
        retry_timer = 1

        while True:
            try:
                if retry_count > 4:
                    self._logger.error(
                        "%s %s session connection still refused after 5 attempts.",
                        self._gateway.log_id,
                        self._type.capitalize(),
                    )
                    return None
                (
                    self._stream_reader,
                    self._stream_writer,
                ) = await asyncio.open_connection(
                    self._gateway.address, self._gateway.port
                )
                # Enable TCP keepalive on the underlying socket to sustain long connections
                try:
                    sock = self._stream_writer.get_extra_info("socket")
                    if sock is not None:
                        sock.setsockopt(_socket.SOL_SOCKET, _socket.SO_KEEPALIVE, 1)
                        # Linux-specific tuning: faster detection of dead peers
                        try:
                            sock.setsockopt(_socket.IPPROTO_TCP, _socket.TCP_KEEPIDLE, 60)
                            sock.setsockopt(_socket.IPPROTO_TCP, _socket.TCP_KEEPINTVL, 30)
                            sock.setsockopt(_socket.IPPROTO_TCP, _socket.TCP_KEEPCNT, 4)
                        except Exception:
                            # If platform doesn't support these options, ignore
                            pass
                except Exception:
                    # If keepalive setup fails, proceed without it
                    pass
                return await self._negotiate()
            except (ConnectionRefusedError, asyncio.IncompleteReadError):
                self._logger.warning(
                    "%s %s session connection refused, retrying in %ss.",
                    self._gateway.log_id,
                    self._type.capitalize(),
                    retry_timer,
                )
                await asyncio.sleep(retry_timer)
                retry_count += 1
                retry_timer = retry_count * 2
            except ConnectionResetError:
                self._logger.warning(
                    "%s %s session connection reset, retrying in 60s.",
                    self._gateway.log_id,
                    self._type.capitalize(),
                )
                await asyncio.sleep(60)
                retry_count += 1
            except asyncio.CancelledError:
                # Propagate cancellation cleanly
                raise

    async def close(self) -> None:
        """Closes the connection to the OpenWebNet gateway"""

        # this method may be invoked on an empty instance of OWNSession, so be robust against Nones:
        if self._stream_writer is not None:
            self._stream_writer.close()
            await self._stream_writer.wait_closed()
        if self._gateway is not None:
            self._logger.debug(
                "%s %s session closed.", self._gateway.log_id, self._type.capitalize()
            )

    async def _negotiate(self) -> dict:
        type_id = 0 if self._type == "command" else 1
        error = False
        error_message = None

        self._logger.debug(
            "%s Negotiating %s session.", self._gateway.log_id, self._type
        )

        self._stream_writer.write(f"*99*{type_id}##".encode())
        await self._stream_writer.drain()

        raw_response = await self._stream_reader.readuntil(OWNSession.SEPARATOR)
        resulting_message = OWNSignaling(raw_response.decode())
        # self._logger.debug("%s Reply: `%s`", self._gateway.log_id, resulting_message)

        if resulting_message.is_nack():
            self._logger.error(
                "%s Error while opening %s session.", self._gateway.log_id, self._type
            )
            error = True
            error_message = "connection_refused"

        raw_response = await self._stream_reader.readuntil(OWNSession.SEPARATOR)
        resulting_message = OWNSignaling(raw_response.decode())
        if resulting_message.is_nack():
            error = True
            error_message = "negotiation_refused"
            self._logger.debug(
                "%s Reply: `%s`", self._gateway.log_id, resulting_message
            )
            self._logger.error(
                "%s Error while opening %s session.", self._gateway.log_id, self._type
            )
        elif resulting_message.is_sha():
            self._logger.debug(
                "%s Received SHA challenge: `%s`",
                self._gateway.log_id,
                resulting_message,
            )
            if self._gateway.password is None:
                error = True
                error_message = "password_required"
                self._logger.warning(
                    "%s Connection requires a password but none was provided.",
                    self._gateway.log_id,
                )
                self._stream_writer.write("*#*0##".encode())
                await self._stream_writer.drain()
            else:
                method = "sha"
                if resulting_message.is_sha_1():
                    # self._logger.debug("%s Detected SHA-1 method.", self._gateway.log_id)
                    method = "sha1"
                elif resulting_message.is_sha_256():
                    # self._logger.debug("%s Detected SHA-256 method.", self._gateway.log_id)
                    method = "sha256"
                self._logger.debug(
                    "%s Accepting %s challenge, initiating handshake.",
                    self._gateway.log_id,
                    method,
                )
                self._stream_writer.write("*#*1##".encode())
                await self._stream_writer.drain()
                raw_response = await self._stream_reader.readuntil(OWNSession.SEPARATOR)
                resulting_message = OWNSignaling(raw_response.decode())
                if resulting_message.is_nonce():
                    server_random_string_ra = resulting_message.nonce
                    # self._logger.debug("%s Received Ra.", self._gateway.log_id)
                    key = "".join(random.choices(string.digits, k=56))
                    client_random_string_rb = self._hex_string_to_int_string(
                        hmac.new(key=key.encode(), digestmod=method).hexdigest()
                    )
                    # self._logger.debug("%s Generated Rb.", self._gateway.log_id)
                    hashed_password = f"*#{client_random_string_rb}*{self._encode_hmac_password(method=method, password=self._gateway.password, nonce_a=server_random_string_ra, nonce_b=client_random_string_rb)}##"  # pylint: disable=line-too-long
                    self._logger.debug(
                        "%s Sending %s session password.",
                        self._gateway.log_id,
                        self._type,
                    )
                    self._stream_writer.write(hashed_password.encode())
                    await self._stream_writer.drain()
                    try:
                        raw_response = await asyncio.wait_for(
                            self._stream_reader.readuntil(OWNSession.SEPARATOR),
                            timeout=5,
                        )
                        resulting_message = OWNSignaling(raw_response.decode())
                        if resulting_message.is_nack():
                            error = True
                            error_message = "password_error"
                            self._logger.error(
                                "%s Password error while opening %s session.",
                                self._gateway.log_id,
                                self._type,
                            )
                        elif resulting_message.is_nonce():
                            # self._logger.debug(
                            #     "%s Received HMAC response.", self._gateway.log_id
                            # )
                            hmac_response = resulting_message.nonce
                            if hmac_response == self._decode_hmac_response(
                                method=method,
                                password=self._gateway.password,
                                nonce_a=server_random_string_ra,
                                nonce_b=client_random_string_rb,
                            ):
                                # self._logger.debug(
                                #     "%s Server identity confirmed.", self._gateway.log_id
                                # )
                                self._stream_writer.write("*#*1##".encode())
                                await self._stream_writer.drain()
                                self._logger.debug(
                                    "%s Session established successfully.", self._gateway.log_id
                                )
                            else:
                                self._logger.error(
                                    "%s Server identity could not be confirmed.",
                                    self._gateway.log_id,
                                )
                                self._stream_writer.write("*#*0##".encode())
                                await self._stream_writer.drain()
                                error = True
                                error_message = "negociation_error"
                                self._logger.error(
                                    "%s Error while opening %s session: HMAC authentication failed.",
                                    self._gateway.log_id,
                                    self._type,
                                )
                    except asyncio.IncompleteReadError:
                        error = True
                        error_message = "password_error"
                        self._logger.error(
                            "%s Password error while opening %s session.",
                            self._gateway.log_id,
                            self._type,
                        )
                    except asyncio.TimeoutError:
                        error = True
                        error_message = "password_error"
                        self._logger.error(
                            "%s Password timeout error while opening %s session.",
                            self._gateway.log_id,
                            self._type,
                        )
        elif resulting_message.is_nonce():
            self._logger.debug(
                "%s Received nonce: `%s`", self._gateway.log_id, resulting_message
            )
            if self._gateway.password is not None:
                hashed_password = f"*#{self._get_own_password(self._gateway.password, resulting_message.nonce)}##"  # pylint: disable=line-too-long
                self._logger.debug(
                    "%s Sending %s session password.", self._gateway.log_id, self._type
                )
                self._stream_writer.write(hashed_password.encode())
                await self._stream_writer.drain()
                raw_response = await self._stream_reader.readuntil(OWNSession.SEPARATOR)
                resulting_message = OWNSignaling(raw_response.decode())
                # self._logger.debug("%s Reply: `%s`", self._gateway.log_id, resulting_message)
                if resulting_message.is_nack():
                    error = True
                    error_message = "password_error"
                    self._logger.error(
                        "%s Password error while opening %s session.",
                        self._gateway.log_id,
                        self._type,
                    )
                elif resulting_message.is_ack():
                    self._logger.debug(
                        "%s %s session established successfully.",
                        self._gateway.log_id,
                        self._type.capitalize(),
                    )
            else:
                error = True
                error_message = "password_error"
                self._logger.error(
                    "%s Connection requires a password but none was provided for %s session.",
                    self._gateway.log_id,
                    self._type,
                )
        elif resulting_message.is_ack():
            # self._logger.debug("%s Reply: `%s`", self._gateway.log_id, resulting_message)
            self._logger.debug(
                "%s %s session established successfully.",
                self._gateway.log_id,
                self._type.capitalize(),
            )
        else:
            error = True
            error_message = "negotiation_failed"
            self._logger.debug(
                "%s Unexpected message during negotiation: %s",
                self._gateway.log_id,
                resulting_message,
            )

        return {"Success": not error, "Message": error_message}

    def _get_own_password(self, password, nonce, test=False):
        start = True
        num1 = 0
        num2 = 0
        password = int(password)
        if test:
            print("password: %08x" % (password))
        for character in nonce:
            if character != "0":
                if start:
                    num2 = password
                start = False
            if test:
                print("c: %s num1: %08x num2: %08x" % (character, num1, num2))
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
            if test:
                print("     num1: %08x num2: %08x" % (num1, num2))
            num2 = num1
        return num1

    def _encode_hmac_password(
        self, method: str, password: str, nonce_a: str, nonce_b: str
    ):
        if method == "sha1":
            message = (
                self._int_string_to_hex_string(nonce_a)
                + self._int_string_to_hex_string(nonce_b)
                + "736F70653E"
                + "636F70653E"
                + hashlib.sha1(password.encode()).hexdigest()
            )
            return self._hex_string_to_int_string(
                hashlib.sha1(message.encode()).hexdigest()
            )
        elif method == "sha256":
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
        else:
            return None

    def _decode_hmac_response(
        self, method: str, password: str, nonce_a: str, nonce_b: str
    ):
        if method == "sha1":
            message = (
                self._int_string_to_hex_string(nonce_a)
                + self._int_string_to_hex_string(nonce_b)
                + hashlib.sha1(password.encode()).hexdigest()
            )
            return self._hex_string_to_int_string(
                hashlib.sha1(message.encode()).hexdigest()
            )
        elif method == "sha256":
            message = (
                self._int_string_to_hex_string(nonce_a)
                + self._int_string_to_hex_string(nonce_b)
                + hashlib.sha256(password.encode()).hexdigest()
            )
            return self._hex_string_to_int_string(
                hashlib.sha256(message.encode()).hexdigest()
            )
        else:
            return None

    def _int_string_to_hex_string(self, int_string: str) -> str:
        hex_string = ""
        for i in range(0, len(int_string), 2):
            hex_string += f"{int(int_string[i:i+2]):x}"
        return hex_string

    def _hex_string_to_int_string(self, hex_string: str) -> str:
        int_string = ""
        for i in range(0, len(hex_string), 1):
            int_string += f"{int(hex_string[i:i+1], 16):0>2d}"
        return int_string


class OWNEventSession(OWNSession):
    # A parse/attribute/generic failure alone doesn't reconnect the socket
    # (see except branches below). If the underlying reader wedges without
    # ever raising a cancellable timeout, we'd otherwise spin on the same
    # broken stream forever. After this many *consecutive* non-reconnecting
    # failures, force a fresh connection rather than keep trusting the reader.
    MAX_CONSECUTIVE_SOFT_FAILURES = 3

    def __init__(self, gateway: OWNGateway = None, logger: logging.Logger = None):
        super().__init__(gateway=gateway, connection_type="event", logger=logger)
        self._consecutive_soft_failures = 0

    @classmethod
    async def connect_to_gateway(cls, gateway: OWNGateway):
        connection = cls(gateway)
        await connection.connect()

    async def _force_reconnect_after_soft_failures(self) -> None:
        self._consecutive_soft_failures += 1
        if self._consecutive_soft_failures >= self.MAX_CONSECUTIVE_SOFT_FAILURES:
            self._logger.warning(
                "%s %d consecutive event session failures, forcing reconnect...",
                self._gateway.log_id,
                self._consecutive_soft_failures,
            )
            self._consecutive_soft_failures = 0
            await self.connect()

    async def get_next(self) -> Union[OWNMessage, str, None]:
        """Acts as an entry point to read messages on the event bus.
        It will read one frame and return it as an OWNMessage object"""
        try:
            # Use a timeout to detect stalled connections and trigger reconnection
            data = await asyncio.wait_for(
                self._stream_reader.readuntil(OWNSession.SEPARATOR), timeout=120
            )
            _decoded_data = data.decode()
            _message = OWNMessage.parse(_decoded_data)
            self._consecutive_soft_failures = 0
            return _message if _message else _decoded_data
        except asyncio.IncompleteReadError:
            self._logger.warning(
                "%s Connection interrupted, reconnecting...", self._gateway.log_id
            )
            self._consecutive_soft_failures = 0
            await self.connect()
            return None
        except asyncio.TimeoutError:
            self._logger.warning(
                "%s Event session idle timeout, reconnecting...", self._gateway.log_id
            )
            self._consecutive_soft_failures = 0
            await self.connect()
            return None
        except AttributeError:
            self._logger.exception(
                "%s Received data could not be parsed into a message:",
                self._gateway.log_id,
            )
            await self._force_reconnect_after_soft_failures()
            return None
        except ConnectionError:
            self._logger.exception("%s Connection error:", self._gateway.log_id)
            await self._force_reconnect_after_soft_failures()
            return None
        except Exception:  # pylint: disable=broad-except
            self._logger.exception("%s Event session crashed.", self._gateway.log_id)
            await self._force_reconnect_after_soft_failures()
            return None


class OWNCommandSession(OWNSession):
    def __init__(self, gateway: OWNGateway = None, logger: logging.Logger = None):
        super().__init__(gateway=gateway, connection_type="command", logger=logger)

    @classmethod
    async def send_to_gateway(cls, message: str, gateway: OWNGateway):
        connection = cls(gateway)
        await connection.connect()
        await connection.send(message)

    @classmethod
    async def connect_to_gateway(cls, gateway: OWNGateway):
        connection = cls(gateway)
        await connection.connect()

    async def send(self, message, is_status_request: bool = False, attempt: int = 1):
        """Send the attached message on an existing 'command' connection,
        actively reconnecting it if it had been reset."""

        try:
            # Guard against None writer/reader (disconnected)
            if self._stream_writer is None or self._stream_reader is None:
                await self.connect()

            self._stream_writer.write(str(message).encode())
            await self._stream_writer.drain()
            raw_response = await asyncio.wait_for(
                self._stream_reader.readuntil(OWNSession.SEPARATOR), timeout=10
            )
            resulting_message = OWNMessage.parse(raw_response.decode())

            while not isinstance(resulting_message, OWNSignaling):
                self._logger.debug(
                    "%s Message `%s` received response `%s`.",
                    self._gateway.log_id,
                    message,
                    resulting_message,
                )
                raw_response = await asyncio.wait_for(
                    self._stream_reader.readuntil(OWNSession.SEPARATOR), timeout=10
                )
                resulting_message = OWNMessage.parse(raw_response.decode())

            if resulting_message.is_nack():
                if attempt <= 2:
                    self._logger.error(
                        "%s Could not send message `%s`. Retrying (%d)...", self._gateway.log_id, message,
                        attempt
                    )
                    return await self.send(message, is_status_request, attempt + 1)
                else:
                    self._logger.error(
                        "%s Could not send message `%s`. No more retries.", self._gateway.log_id, message
                    )
            elif resulting_message.is_ack():
                log_message = "%s Message `%s` was successfully sent."
                if not is_status_request:
                    self._logger.info(log_message, self._gateway.log_id, message)
                else:
                    self._logger.debug(log_message, self._gateway.log_id, message)
                    
        except (ConnectionResetError, asyncio.IncompleteReadError, asyncio.TimeoutError):
            self._logger.debug(
                "%s Command session connection reset, retrying...", self._gateway.log_id
            )
            await self.connect()
            await self.send(message=message, is_status_request=is_status_request)
        except Exception:  # pylint: disable=broad-except
            self._logger.exception("%s Command session crashed.", self._gateway.log_id)
            return None
