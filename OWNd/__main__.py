""" OWNd entry point when running it directly from CLI
(as opposed to imported into another project)
"""
import argparse
import asyncio
import logging
from typing import Any

from .message import OWNMessage

from .connection import OWNEventSession, OWNGateway
from .exceptions import OWNConnectionError


async def main(arguments: dict[str, Any], connection: OWNEventSession) -> None:
    """Package entry point!"""

    address = (
        arguments["address"]
        if "address" in arguments and isinstance(arguments["address"], str)
        else None
    )
    port = (
        arguments["port"]
        if "port" in arguments and isinstance(arguments["port"], int)
        else None
    )
    password = (
        arguments["password"]
        if "password" in arguments and isinstance(arguments["password"], str)
        else None
    )
    serial_number = (
        arguments["serialNumber"]
        if "serialNumber" in arguments and isinstance(arguments["serialNumber"], str)
        else None
    )
    raw_logger = arguments.get("logger")
    logger = raw_logger if isinstance(raw_logger, logging.Logger) else logging.getLogger("OWNd")

    cli_info: dict[str, Any] = {
        "address": address,
        "port": port,
        "password": password,
        "serialNumber": serial_number,
    }

    logger.info("Starting discovery of a supported gateway via SSDP")
    gateway = await OWNGateway.build_from_discovery_info(cli_info)
    if gateway is None:
        # Without --port, build_from_discovery_info() probes the network
        # (SSDP, or the HTTP descriptor of --address) and returns None when
        # nothing answers. Connecting with no gateway would fail on an
        # assertion in the session, so decide here.
        if address is None:
            raise OWNConnectionError(
                "No OpenWebNet gateway discovered on the network",
                reason="discovery_failed",
            )
        gateway = OWNGateway(cli_info)  # port None -> the profile default, 20000
        logger.info(
            "No gateway description found at %s; connecting to it directly on port %s",
            address,
            gateway.port,
        )
    else:
        # The HTTP / SSDP probe builds the gateway from its description, which
        # carries no password; fill in what the command line gave and the
        # description did not (a description's own serial number stays).
        if password is not None and gateway.password is None:
            gateway.password = password
        if serial_number is not None and gateway.serial_number is None:
            gateway.serial_number = serial_number
    connection.gateway = gateway

    if logger is not None:
        connection.logger = logger

    try:
        logger.info("Starting connection to the discovered gateway")
        # The first connection has to succeed: an unreachable gateway or a
        # rejected password ends the command with that error, instead of
        # leaving it retrying forever. Once connected, get_next() still
        # reconnects by itself after a drop.
        await connection.connect(raise_on_error=True)

        logger.info("Now waiting for events from the gateway (e.g. a cover opening/closing)")
        while True:
            message = await connection.get_next()
            if message:
                logger.debug("Received: %s", message)
                if isinstance(message, OWNMessage) and message.is_event:
                    logger.info(message.human_readable_log)
    finally:
        await connection.close()


if __name__ == "__main__":

    parser = argparse.ArgumentParser()
    parser.add_argument(
        "-a", "--address", type=str, help="IP address of the OpenWebNet gateway"
    )
    parser.add_argument(
        "-p",
        "--port",
        type=int,
        help="TCP port to connectect the gateway, default is 20000",
    )
    parser.add_argument(
        "-P",
        "--password",
        type=str,
        help="Numeric password for the OpenWebNet connection, default is 12345",
    )
    parser.add_argument(
        "-m",
        "--mac",
        type=str,
        help="MAC address of the gateway (to be used as ID, if  not found via SSDP)",
    )
    parser.add_argument(
        "-v",
        "--verbose",
        type=int,
        help="Change output verbosity [0 = WARNING; 1 = INFO (default); 2 = DEBUG]",
    )
    args = parser.parse_args()

    # create logger with 'OWNd'
    _logger = logging.getLogger("OWNd")
    _logger.setLevel(logging.DEBUG)

    # create console handler which logs even debug messages
    log_stream_handler = logging.StreamHandler()

    if args.verbose == 2:
        log_stream_handler.setLevel(logging.DEBUG)
    elif args.verbose == 0:
        log_stream_handler.setLevel(logging.WARNING)
    else:
        log_stream_handler.setLevel(logging.INFO)

    # create formatter and add it to the handlers
    formatter = logging.Formatter(
        "%(asctime)s - %(name)s - %(levelname)s - %(message)s"
    )
    log_stream_handler.setFormatter(formatter)
    # add the handlers to the logger
    _logger.addHandler(log_stream_handler)

    event_session = OWNEventSession(gateway=None, logger=_logger)
    _arguments = {
        "address": args.address,
        "port": args.port,
        "password": args.password,
        "serialNumber": args.mac,
        "logger": _logger,
    }

    try:
        _logger.info("Starting OWNd.")
        asyncio.run(main(_arguments, event_session))
    except KeyboardInterrupt:
        _logger.info("Stopping OWNd.")
    finally:
        _logger.info("OWNd stopped.")
