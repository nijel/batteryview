"""BatteryView's text-console framing, independent of OS and serial read boundaries."""

import math
import re
import threading
import time
from dataclasses import dataclass
from typing import Literal

from .errors import (
    CommandCancelled,
    CommandTimeout,
    ConnectionError,
    ProtocolError,
    UnsupportedCommand,
)
from .transport import Transport

SHIFT_SEQUENCE = bytes.fromhex("7E 32 30 30 31 34 36 38 32 43 30 30 34 38 35 32 30 46 43 43 33 0D")
CONTINUATION = "Press [Enter] to be continued,other key to exit"
PROMPT = re.compile(r"(?:^|[\r\n@])pylon(?:_debug)?>(?=$|[\r\n])")
INVALID = re.compile(r"Invalid command or fail to excute\.?|Invalid command", re.I)
Boundary = Literal["prompt", "page"]


@dataclass(frozen=True)
class Response:
    text: str
    boundary: Boundary

    @property
    def unsupported(self) -> bool:
        return bool(INVALID.search(self.text))


class ConsoleSession:
    """One outstanding command per session; mutating commands are never retried.

    Regular commands use LF (.NET SerialPort.WriteLine's default), while script
    commands and pagination use CR or CR+LF exactly as BatteryView's overloads do.
    A short quiet interval collects trailing CR/LF received after a split prompt.
    """

    def __init__(
        self,
        transport: Transport,
        *,
        timeout: float = 5,
        settle_time: float = 0.05,
        max_response_bytes: int = 16 * 1024 * 1024,
    ):
        if (
            not math.isfinite(timeout)
            or timeout <= 0
            or not math.isfinite(settle_time)
            or settle_time < 0
            or max_response_bytes <= 0
        ):
            raise ValueError("Timeout and response limit must be positive; settle time nonnegative")
        self.transport = transport
        self.timeout = timeout
        self.settle_time = settle_time
        self.max_response_bytes = max_response_bytes
        self.lock = threading.RLock()
        self.synchronized = False
        self._needs_resync = False

    def connect(
        self, *, baudrate: int = 115200, shift: bool = True, enter_debug: bool = True
    ) -> None:
        with self.lock:
            if shift:
                self.transport.baudrate = 1200
                self._write(SHIFT_SEQUENCE)
                time.sleep(0.5)
            self.transport.baudrate = baudrate
            time.sleep(0.5)
            self.resynchronize(timeout=max(self.timeout, 15))
            if enter_debug:
                response = self.exchange("login debug")
                if "pylon_debug>" not in response.text:
                    raise ProtocolError("Console did not enter debug mode", response=response.text)

    def _write(self, data: bytes) -> None:
        if self.transport.write(data) != len(data):
            raise ConnectionError("Incomplete serial write; command outcome is unknown")

    def resynchronize(self, *, timeout: float | None = None) -> Response:
        """Request a prompt without repeating the previous command."""
        with self.lock:
            return self.exchange("", timeout=timeout)

    def exchange(
        self,
        command: str,
        *,
        paginated: bool = False,
        timeout: float | None = None,
        terminator: bytes = b"\n",
        allow_unsupported: bool = False,
    ) -> Response:
        if "\r" in command or "\n" in command:
            raise ValueError("A command must contain a single console line")
        wait = self.timeout if timeout is None else timeout
        if not math.isfinite(wait) or wait <= 0:
            raise ValueError("Timeout must be positive")
        with self.lock:
            if self._needs_resync and command:
                raise ProtocolError(
                    "Console state is unknown; call resynchronize() before sending another command"
                )
            self.synchronized = False
            self._needs_resync = True
            self._write(command.encode("ascii") + terminator)
            response = self._receive(command, paginated=paginated, timeout=wait)
            self.synchronized = response.boundary == "prompt"
            self._needs_resync = False
            if response.unsupported and not allow_unsupported:
                raise UnsupportedCommand(
                    f"Unsupported command: {command!r}", response=response.text
                )
            return response

    def _receive(self, command: str, *, paginated: bool, timeout: float) -> Response:
        data = bytearray()
        try:
            return self._read_frame(command, paginated=paginated, timeout=timeout, data=data)
        except KeyboardInterrupt as exc:
            raise CommandCancelled(
                f"Interrupted while waiting for {command!r}",
                response=data.decode("ascii", errors="replace"),
            ) from exc

    def _read_frame(
        self, command: str, *, paginated: bool, timeout: float, data: bytearray
    ) -> Response:
        deadline = time.monotonic() + timeout
        boundary: Boundary | None = None
        quiet_deadline: float | None = None
        while True:
            now = time.monotonic()
            if boundary is not None and quiet_deadline is not None and now >= quiet_deadline:
                return Response(data.decode("ascii", errors="replace"), boundary)
            if now >= deadline:
                if boundary is not None:
                    return Response(data.decode("ascii", errors="replace"), boundary)
                raise CommandTimeout(
                    f"Timeout waiting for {command!r}; command was not retried",
                    response=data.decode("ascii", errors="replace"),
                )
            try:
                chunk = self.transport.read()
            except ConnectionError as exc:
                raise ConnectionError(
                    str(exc), response=data.decode("ascii", errors="replace")
                ) from exc
            if not chunk:
                continue
            data.extend(chunk)
            if len(data) > self.max_response_bytes:
                raise ProtocolError(
                    f"Response to {command!r} exceeded {self.max_response_bytes} bytes",
                    response=data.decode("ascii", errors="replace"),
                )
            text = data.decode("ascii", errors="replace")
            # The last terminator wins if an entire page and its prompt arrive together.
            prompts = list(PROMPT.finditer(text))
            page_at = text.rfind(CONTINUATION) if paginated else -1
            boundary = None
            quiet_deadline = None
            if prompts and prompts[-1].start() > page_at:
                boundary = "prompt"
            elif page_at >= 0:
                boundary = "page"
            if boundary is not None:
                quiet_deadline = time.monotonic() + self.settle_time

    def close(self) -> None:
        self.transport.close()
