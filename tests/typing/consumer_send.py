"""What a typed consumer of OWNd is allowed to write - checked by mypy, not run.

OWNd ships ``py.typed``, so its annotations are the contract MyHOME and
every other consumer type-check against. This module is the consumer's
side of that contract for the command session: each function below is a
call MyHOME really makes, and ``mypy --strict`` over this file (see the
``quality`` job in CI, and ``tests/test_typing_consumer.py``) fails the
build if a signature change would reject it.

Keep it to public API and to calls that must keep working; a private
name here would pin an implementation detail.
"""
from __future__ import annotations

from OWNd.connection import OWNCommandSession, OWNGateway
from OWNd.message import OWNCommand, OWNLightingCommand, OWNMessage


async def send_raw_frame(session: OWNCommandSession) -> None:
    """A frame typed by the user, e.g. the ``myhome.send_message`` service."""
    await session.send("*1*1*11##")


async def send_built_command(session: OWNCommandSession) -> None:
    """A command from a builder - the common case in an integration."""
    await session.send(OWNLightingCommand.switch_on("11"))
    await session.send(OWNLightingCommand.status("11"), is_status_request=True)


async def send_parsed_command(session: OWNCommandSession, frame: str) -> None:
    """A frame parsed first, so the caller can inspect it before sending."""
    command = OWNCommand.parse(frame)
    if command is not None:
        await session.send(command)


async def send_parsed_message(session: OWNCommandSession, frame: str) -> None:
    """Any parsed message, not only a command - ``OWNMessage.parse`` is the base parser."""
    message = OWNMessage.parse(frame)
    if message is not None:
        await session.send(message)


async def one_shot(gateway: OWNGateway) -> None:
    """The connect-send-close helper accepts the same two forms."""
    await OWNCommandSession.send_to_gateway("*1*0*11##", gateway)
    await OWNCommandSession.send_to_gateway(OWNLightingCommand.switch_off("11"), gateway)
