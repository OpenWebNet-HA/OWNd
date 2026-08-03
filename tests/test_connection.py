"""Regression tests for OWNEventSession.get_next()'s forced-reconnect guard.

Some failures inside get_next() (parse errors, generic exceptions) don't
reconnect the socket by themselves. If the underlying reader ever wedges
without raising a cancellable timeout, that used to mean spinning forever on
the same broken stream (the 4h20m hang seen in the field). These tests check
that after MAX_CONSECUTIVE_SOFT_FAILURES in a row, connect() is forced -
without needing a real socket, using a fake reader/gateway.

No pytest-asyncio here: the repo's dev environment doesn't have it, so async
calls are driven with plain asyncio.run() inside sync test_* functions.
"""

import asyncio
import logging
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from OWNd.connection import OWNEventSession

logging.getLogger("test_ownd").addHandler(logging.NullHandler())


class FakeGateway:
    log_id = "[fake gateway - 0.0.0.0]"


class FailingReader:
    """readuntil() always raises the given exception."""

    def __init__(self, exc):
        self._exc = exc

    async def readuntil(self, separator):
        raise self._exc


def _make_session():
    session = OWNEventSession(gateway=FakeGateway(), logger=logging.getLogger("test_ownd"))
    session._stream_reader = FailingReader(RuntimeError("simulated crash"))
    return session


def test_forces_reconnect_after_max_consecutive_soft_failures():
    session = _make_session()
    connect_calls = 0

    async def fake_connect():
        nonlocal connect_calls
        connect_calls += 1

    session.connect = fake_connect

    async def main():
        for _ in range(OWNEventSession.MAX_CONSECUTIVE_SOFT_FAILURES - 1):
            result = await session.get_next()
            assert result is None
        assert connect_calls == 0

        result = await session.get_next()
        assert result is None
        assert connect_calls == 1
        assert session._consecutive_soft_failures == 0

    asyncio.run(main())


def test_soft_failure_counter_resets_on_success():
    session = _make_session()
    connect_calls = 0

    async def fake_connect():
        nonlocal connect_calls
        connect_calls += 1

    session.connect = fake_connect

    async def main():
        await session.get_next()
        await session.get_next()
        assert session._consecutive_soft_failures == 2

        class OkReader:
            async def readuntil(self, separator):
                return b"*#13**0*10*30*45##"

        session._stream_reader = OkReader()
        message = await session.get_next()
        assert message is not None
        assert session._consecutive_soft_failures == 0

        session._stream_reader = FailingReader(RuntimeError("simulated crash"))
        await session.get_next()
        await session.get_next()
        assert connect_calls == 0
        assert session._consecutive_soft_failures == 2

    asyncio.run(main())


if __name__ == "__main__":
    test_forces_reconnect_after_max_consecutive_soft_failures()
    test_soft_failure_counter_resets_on_success()
    print("OK")
