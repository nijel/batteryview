import threading
import time
from collections import deque

import pytest

from batteryview.protocol import ConsoleSession


def pytest_addoption(parser):
    parser.addoption(
        "--private-logs",
        type=str,
        default=None,
        help="opt in to replaying local private vendor recordings from this directory",
    )


class ReplayTransport:
    """Each expected write releases its recorded bytes, independent of chunk boundaries."""

    def __init__(self, exchanges=(), *, chunk_size=37):
        self.exchanges = deque(exchanges)
        self.pending = bytearray()
        self.writes = []
        self.baudrate = 115200
        self.closed = False
        self.chunk_size = chunk_size

    def write(self, data):
        self.writes.append(data)
        assert self.exchanges, f"Unexpected write: {data!r}"
        expected, response = self.exchanges.popleft()
        assert data == expected
        assert not self.pending, "Previous response was not fully consumed"
        self.pending.extend(response.encode("ascii"))
        return len(data)

    def read(self, size=65536):
        if not self.pending:
            time.sleep(0.001)
            return b""
        data = bytes(self.pending[: self.chunk_size])
        del self.pending[: self.chunk_size]
        return data

    def close(self):
        self.closed = True


@pytest.fixture
def replay():
    def factory(exchanges, *, chunk_size=37, timeout=0.1):
        transport = ReplayTransport(exchanges, chunk_size=chunk_size)
        session = ConsoleSession(transport, timeout=timeout, settle_time=0.002)
        return session, transport

    return factory


class ScriptedSession:
    """Workflow failure injection without serial timing."""

    def __init__(self, exchanges):
        self.exchanges = deque(exchanges)
        self.lock = threading.RLock()
        self.calls = []
        self.reconnects = []

    def exchange(self, command, **kwargs):
        self.calls.append((command, kwargs))
        expected, result = self.exchanges.popleft()
        assert command == expected
        if isinstance(result, BaseException):
            raise result
        return result

    def connect(self, **kwargs):
        self.reconnects.append(kwargs)

    def close(self):
        pass
