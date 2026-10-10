"""Base message, signaling, and protocol dispatcher classes."""

from __future__ import annotations

from collections.abc import Callable
import importlib
import re
import sys
from typing import Any

_EVENT_DISPATCH: dict[int, Callable[[str], OWNEvent]] = {}
_COMMAND_DISPATCH: dict[int, Callable[[str], OWNCommand]] = {}

_WHO_SUBMODULES: tuple[str, ...] = (
    "alarm",
    "automation",
    "cen",
    "door_entry",
    "energy",
    "gateway",
    "heating",
    "lighting",
    "scenario",
    "sound",
)


_SUBSYSTEMS_REGISTERED = False


def _ensure_all_subsystems_registered() -> None:
    """Ensure all WHO subsystem parser modules are imported and registered."""
    global _SUBSYSTEMS_REGISTERED  # pylint: disable=global-statement
    if _SUBSYSTEMS_REGISTERED:
        return
    for mod_name in _WHO_SUBMODULES:
        full_name = f"OWNd.message.{mod_name}"
        if full_name not in sys.modules:
            importlib.import_module(full_name)
    _SUBSYSTEMS_REGISTERED = True


def register_event_parser(who: int, parser: Callable[[str], OWNEvent]) -> None:
    """Register a specialized event parser for a WHO subsystem."""
    _EVENT_DISPATCH[who] = parser


def register_command_parser(who: int, parser: Callable[[str], OWNCommand]) -> None:
    """Register a specialized command parser for a WHO subsystem."""
    _COMMAND_DISPATCH[who] = parser



class OWNMessage:
    _ACK = re.compile(r"^\*#\*1##$")  #  *#*1##
    _NACK = re.compile(r"^\*#\*0##$")  #  *#*0##
    _COMMAND_SESSION = re.compile(r"^\*99\*0##$")  #  *99*0##
    _EVENT_SESSION = re.compile(r"^\*99\*1##$")  #  *99*1##
    _NONCE = re.compile(r"^\*#(\d{4,})##$")  #  *#123456789##
    _SHA = re.compile(r"^\*98\*(\d)##$")  #  *98*SHA##

    _STATUS = re.compile(
        r"^\*(?P<who>\d+)\*(?P<what>\d+)(?P<what_param>(?:#\d+)*)\*(?P<where>\*|#?\d+)(?P<where_param>(?:#\d+)*)##$"  # pylint: disable=line-too-long
    )  #  *WHO*WHAT*WHERE##
    # WHO 5 only: field units log system broadcasts with an empty WHERE
    # (*5*1*##) next to the documented star form (*5*1**##).
    _ALARM_EMPTY_WHERE = re.compile(
        r"^\*5\*(?P<what>\d+)(?P<what_param>(?:#\d+)*)\*##$"
    )  #  *5*WHAT*##
    # WHO 6: camera OFF published form has no WHERE field (*6*9##), but field
    # units may also emit a single trailing star delimiter (*6*9*##).
    # The double-star form (*6*9**##) has WHERE="*" and is matched by _STATUS.
    # Only WHAT 9 may omit WHERE; any other short WHO 6 frame is not valid.
    _DOOR_ENTRY_SHORT = re.compile(
        r"^\*6\*(?P<what>9)\*?##$"
    )  # *6*9##, *6*9*##
    _STATUS_REQUEST = re.compile(
        r"^\*#(?P<who>\d+)(?:\*(?P<where>#?\d+)(?P<where_param>(?:#\d+)*))?##$"
    )  #  *#WHO*WHERE## or *#WHO##
    _DIMENSION_WRITING = re.compile(
        r"^\*#(?P<who>\d+)\*(?P<where>#?\d+)?(?P<where_param>(?:#\d+)*)?\*#(?P<dimension>\d+)(?P<dimension_param>(?:#\d+)*)?(?P<dimension_value>(?:\*\d*)+)##$"  # pylint: disable=line-too-long
    )  #  *#WHO*WHERE*#DIMENSION*VAL1*VALn##
    _DIMENSION_REQUEST = re.compile(
        r"^\*#(?P<who>\d+)\*(?P<where>#?\d+)?(?P<where_param>(?:#\d+)*)?\*(?P<dimension>\d+)(?P<dimension_param>(?:#\d+)*)?##$"
    )  #  *#WHO*WHERE*DIMENSION##
    _DIMENSION_REQUEST_REPLY = re.compile(
        r"^\*#(?P<who>\d+)\*(?P<where>#?\d+)?(?P<where_param>(?:#\d+)*)?\*(?P<dimension>\d+)(?P<dimension_param>(?:#\d+)*)?(?P<dimension_value>(?:\*\d*)+)##$"  # pylint: disable=line-too-long
    )  #  *#WHO*WHERE*DIMENSION*VAL1*VALn##

    """ Base class for all OWN messages """

    def __init__(self, data: str) -> None:
        self._raw: str = data
        self._human_readable_log: str = self._raw
        self._family: str = ""
        self._message_type: str | None = None
        self._match: re.Match[str] | None = None
        self._is_valid_message: bool = False
        # Explicit attribute types: every branch below only overrides what the
        # frame actually carries; missing parts keep these defaults (empty
        # lists instead of None, so consumers can index/iterate safely).
        self._who: int | None = None
        self._what: int | None = None
        self._what_param: list[str] = []
        self._where: str | None = None
        self._where_param: list[str] = []
        self._dimension: int | None = None
        self._dimension_param: list[str] = []
        self._dimension_value: list[str] = []

        if match := self._STATUS.match(self._raw):
            self._is_valid_message = True
            self._match = match
            self._family = "EVENT"
            self._message_type = "STATUS"
            self._who = int(match.group("who"))
            self._what = int(match.group("what"))
            if self._what == 1000:
                self._family = "COMMAND_TRANSLATION"
            self._what_param = match.group("what_param").split("#")[1:]
            self._where = match.group("where")
            if self._who == 5 and self._where == "*":
                self._where = "0"  # the documented star form is the system address
            self._where_param = match.group("where_param").split("#")[1:]

        elif match := self._ALARM_EMPTY_WHERE.match(self._raw):
            self._is_valid_message = True
            self._match = match
            self._family = "EVENT"
            self._message_type = "STATUS"
            self._who = 5
            self._what = int(match.group("what"))
            self._what_param = match.group("what_param").split("#")[1:]
            # Kept empty on purpose: gateways without a panel answer the *#5*0##
            # poll with these (*5*9*##), a panel sends *5*9*0##. Consumers must
            # not turn this spelling into a device.
            self._where = ""

        elif match := self._DOOR_ENTRY_SHORT.match(self._raw):
            self._is_valid_message = True
            self._match = match
            self._family = "EVENT"
            self._message_type = "STATUS"
            self._who = 6
            self._what = int(match.group("what"))
            self._where = ""

        elif match := self._STATUS_REQUEST.match(self._raw):
            self._is_valid_message = True
            self._match = match
            self._family = "REQUEST"
            self._message_type = "STATUS_REQUEST"
            self._who = int(match.group("who"))
            self._where = match.group("where")
            self._where_param = (match.group("where_param") or "").split("#")[1:]

        elif match := self._DIMENSION_REQUEST.match(self._raw):
            self._is_valid_message = True
            self._match = match
            self._family = "REQUEST"
            self._message_type = "DIMENSION_REQUEST"
            self._who = int(match.group("who"))
            self._where = match.group("where") or ""
            self._where_param = (match.group("where_param") or "").split("#")[1:]
            self._dimension = int(match.group("dimension"))
            self._dimension_param = (match.group("dimension_param") or "").split("#")[1:]

        elif match := self._DIMENSION_REQUEST_REPLY.match(self._raw):
            self._is_valid_message = True
            self._match = match
            self._family = "EVENT"
            self._message_type = "DIMENSION_REQUEST_REPLY"
            self._who = int(match.group("who"))
            self._where = match.group("where") or ""
            self._where_param = (match.group("where_param") or "").split("#")[1:]
            self._dimension = int(match.group("dimension"))
            self._dimension_param = (match.group("dimension_param") or "").split("#")[1:]
            self._dimension_value = match.group("dimension_value").split("*")[1:]

        elif match := self._DIMENSION_WRITING.match(self._raw):
            self._is_valid_message = True
            self._match = match
            self._family = "COMMAND"
            self._message_type = "DIMENSION_WRITING"
            self._who = int(match.group("who"))
            self._where = match.group("where") or ""
            self._where_param = (match.group("where_param") or "").split("#")[1:]
            self._dimension = int(match.group("dimension"))
            self._dimension_param = (match.group("dimension_param") or "").split("#")[1:]
            self._dimension_value = match.group("dimension_value").split("*")[1:]

    @classmethod
    def parse(cls, data: str) -> OWNMessage | None:
        if (
            cls._ACK.match(data)
            or cls._NACK.match(data)
            or cls._COMMAND_SESSION.match(data)
            or cls._EVENT_SESSION.match(data)
            or cls._NONCE.match(data)
            or cls._SHA.match(data)
        ):
            return OWNSignaling(data)
        if (
            cls._STATUS.match(data)
            or cls._ALARM_EMPTY_WHERE.match(data)
            or cls._DOOR_ENTRY_SHORT.match(data)
            or cls._DIMENSION_REQUEST_REPLY.match(data)
        ):
            return OWNEvent.parse(data)
        if (
            cls._STATUS_REQUEST.match(data)
            or cls._DIMENSION_REQUEST.match(data)
            or cls._DIMENSION_WRITING.match(data)
        ):
            return OWNCommand.parse(data)
        return None

    @property
    def is_event(self) -> bool:
        return self._family == "EVENT"

    @property
    def is_command(self) -> bool:
        return self._family == "COMMAND"

    @property
    def is_request(self) -> bool:
        return self._family == "REQUEST"

    @property
    def is_translation(self) -> bool:
        return self._family == "COMMAND_TRANSLATION"

    @property
    def is_valid(self) -> bool:
        return self._is_valid_message

    @property
    def who(self) -> int | None:
        """The 'who' ID of the subject of this message"""
        return self._who

    @property
    def where(self) -> str | None:
        """The 'where' ID of the subject of this message"""
        return self._where  # [1:] if self._where.startswith('#') else self._where

    @property
    def interface(self) -> str | None:
        """The 'where' parameter corresponding to the bus interface of the subject of this message"""
        return (
            self._where_param[1]
            if self._who in [0, 1, 2, 14, 15]
            and len(self._where_param) > 1
            and self._where_param[0] == "4"
            else None
        )

    @property
    def dimension(self) -> int | None:
        """The 'dimension' ID of this message"""
        return self._dimension

    @property
    def entity(self) -> str:
        """The ID of the subject of this message"""
        return self.unique_id

    @property
    def unique_id(self) -> str:
        """The ID of the subject of this message"""
        if self.where is None:
            return str(self.who)
        return (
            f"{self.who}-{self.where}#4#{self.interface}"
            if self.interface is not None
            else f"{self.who}-{self.where}"
        )

    @property
    def event_content(self) -> dict[str, Any]:
        _event: dict[str, Any] = {
            "message": self._raw,
            "family": self._family.replace("_", " ").capitalize(),
            "type": (self._message_type or "").replace("_", " ").capitalize(),
            "who": self._who,
        }
        if self._where:
            _event.update({"where": self._where})
        if self.interface:
            _event.update({"interface": self.interface})
            if self._where_param and len(self._where_param) > 2:
                _event.update({"where parameters": self._where_param[2:]})
        elif self._where_param:
            _event.update({"where parameters": self._where_param})
        # Explicit None checks: 0 is meaningful (what=0 is OFF, dimension=0
        # is temperature) and must not be dropped from the event payload.
        if self._what is not None:
            _event.update({"what": self._what})
        if self._what_param:
            _event.update({"what parameters": self._what_param})
        if self._dimension is not None:
            _event.update({"dimension": self._dimension})
        if self._dimension_param:
            _event.update({"dimension parameters": self._dimension_param})
        if self._dimension_value:
            _event.update({"dimension values": self._dimension_value})

        return _event

    @property
    def human_readable_log(self) -> str:
        """A human readable log of the event"""
        return self._human_readable_log

    @property
    def _interface_log_text(self) -> str:
        return f" on interface {self.interface}" if self.interface is not None else ""

    @property
    def is_general(self) -> bool:
        if self.who == 1 or self.who == 2:
            return self._where == "0"
        return False

    @property
    def is_group(self) -> bool:
        if self.who == 1 or self.who == 2:
            return self._where is not None and self._where.startswith("#")
        return False

    @property
    def is_area(self) -> bool:
        if self.who == 1 or self.who == 2:
            try:
                return (
                    self._where == "00"
                    or self._where == "100"
                    or (
                        self._where is not None
                        and len(self._where) == 1
                        and int(self._where) > 0
                        and int(self._where) < 10
                    )
                )
            except (TypeError, ValueError):
                return False
        return False

    @property
    def group(self) -> int | None:
        if self.is_group and self._where is not None:
            return int(self._where[1:])
        return None

    @property
    def area(self) -> int | None:
        if self.is_area and self._where is not None:
            return 10 if self._where == "100" else int(self._where)
        return None

    def __repr__(self) -> str:
        return self._raw

    def __str__(self) -> str:
        return self._raw



class OWNEvent(OWNMessage):
    """
    This class is a subclass of messages.
    All messages received during an event session are events.
    Dividing this in a subclass provides better clarity
    """

    @classmethod
    def parse(cls, data: str) -> OWNEvent | None:
        _match = re.match(r"^\*#?(?P<who>\d+)(?:\*.+)?##$", data)

        if _match:
            _who = int(_match.group("who"))
            _ensure_all_subsystems_registered()
            parser = _EVENT_DISPATCH.get(_who)
            if parser is not None:
                return parser(data)
            return cls(data)

        return None


class OWNCommand(OWNMessage):
    """
    This class is a subclass of messages.
    All messages sent during a command session are commands.
    Dividing this in a subclass provides better clarity
    """

    @classmethod
    def parse(cls, data: str) -> OWNCommand | None:
        _match = re.match(r"^\*#?(?P<who>\d+)(?:\*.+)?##$", data)

        if _match:
            _who = int(_match.group("who"))
            _ensure_all_subsystems_registered()
            parser = _COMMAND_DISPATCH.get(_who)
            if parser is not None:
                return parser(data)
            if _who in (0, 3, 14, 22, 24) or _who > 1000:
                return cls(data)
            if _who in (7, 9):
                return (
                    OWNStatusRequest(data)
                    if cls._STATUS_REQUEST.match(data)
                    else cls(data)
                )

        return None


class OWNStatusRequest(OWNCommand):
    """A status request that may target a whole subsystem."""

    def __init__(self, data: str) -> None:
        super().__init__(data)
        if self._where:
            self._human_readable_log = (
                f"Requesting status for WHO={self._who} WHERE={self._where}."
            )
        else:
            self._human_readable_log = f"Requesting global status for WHO={self._who}."

    @classmethod
    def request(cls, who: int, where: str | None = None) -> OWNStatusRequest:
        return cls(f"*#{who}*{where}##" if where else f"*#{who}##")



class OWNSignaling(OWNMessage):
    """
    This class is a subclass of messages.
    It is dedicated to signaling messages such as ACK or Authentication negotiation
    """

    def __init__(self, data: str) -> None:  # pylint: disable=super-init-not-called
        self._raw = data
        self._family = ""
        self._match: re.Match[str] | None = None
        self._type = "UNKNOWN"
        self._human_readable_log = data
        self._who: int | None = None
        self._where: str | None = None
        self._is_valid_message = False

        if match := self._ACK.match(self._raw):
            self._is_valid_message = True
            self._match = match
            self._family = "SIGNALING"
            self._type = "ACK"
            self._human_readable_log = "ACK."
        elif match := self._NACK.match(self._raw):
            self._is_valid_message = True
            self._match = match
            self._family = "SIGNALING"
            self._type = "NACK"
            self._human_readable_log = "NACK."
        elif match := self._NONCE.match(self._raw):
            self._is_valid_message = True
            self._match = match
            self._family = "SIGNALING"
            self._type = "NONCE"
            self._human_readable_log = (
                f"Nonce challenge received: {self._match.group(1)}."
            )
        elif match := self._SHA.match(self._raw):
            self._is_valid_message = True
            self._match = match
            self._family = "SIGNALING"
            self._type = f"SHA{'-1' if self._match.group(1) == '1' else '-256'}"
            self._human_readable_log = f"SHA{'-1' if self._match.group(1) == '1' else '-256'} challenge received."  # pylint: disable=line-too-long
        elif match := self._COMMAND_SESSION.match(self._raw):
            self._is_valid_message = True
            self._match = match
            self._family = "SIGNALING"
            self._type = "COMMAND_SESSION"
            self._human_readable_log = "Command session requested."
        elif match := self._EVENT_SESSION.match(self._raw):
            self._is_valid_message = True
            self._match = match
            self._family = "SIGNALING"
            self._type = "EVENT_SESSION"
            self._human_readable_log = "Event session requested."

    @property
    def nonce(self) -> str | None:
        """Return the authentication nonce IF the message is a nonce message"""
        # NB: is_nonce is a method — referencing it without calling it was
        # always truthy, making this guard ineffective.
        if self.is_nonce() and self._match is not None:
            return self._match.group(1)
        return None

    @property
    def sha_version(self) -> str | None:
        """Return the authentication SHA version IF the message is a SHA challenge message"""
        if self.is_sha() and self._match is not None:
            return self._match.group(1)
        return None

    def is_ack(self) -> bool:
        return self._type == "ACK"

    def is_nack(self) -> bool:
        return self._type == "NACK"

    def is_nonce(self) -> bool:
        return self._type == "NONCE"

    def is_sha(self) -> bool:
        return self._type == "SHA-1" or self._type == "SHA-256"

    def is_sha_1(self) -> bool:
        return self._type == "SHA-1"

    def is_sha_256(self) -> bool:
        return self._type == "SHA-256"

