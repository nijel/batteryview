"""BatteryView's text-console framing, independent of OS and serial read boundaries."""

import logging
import math
import re
import threading
import time
from dataclasses import dataclass, field
from typing import Literal

from .diagnostics import SERIAL_TRACE, command_label, serial_logger
from .errors import (
    CommandCancelled,
    CommandTimeout,
    ConnectionError,
    DeviceBusyError,
    DeviceNotPresentError,
    ProtocolError,
    PylontechError,
    UnsupportedCommand,
)
from .transport import Transport

logger = logging.getLogger(__name__)

SHIFT_SEQUENCE = bytes.fromhex("7E 32 30 30 31 34 36 38 32 43 30 30 34 38 35 32 30 46 43 43 33 0D")
CONTINUATION = "Press [Enter] to be continued,other key to exit"
PROMPT = re.compile(r"(?:^|[\r\n@])pylon(?:_debug)?>(?=$|[\r\n])")
INVALID = re.compile(
    r"Invalid command or fail to excute\.?|Invalid command|(?:^|[\r\n])[ \t]*Unknown command\b",
    re.I,
)
Boundary = Literal["prompt", "page", "disconnect"]


@dataclass(frozen=True)
class Response:
    text: str
    boundary: Boundary
    context: dict = field(default_factory=dict)

    @property
    def unsupported(self) -> bool:
        return bool(INVALID.search(self.text))

    @property
    def prompt(self) -> str | None:
        """Final recognized console prompt, never an earlier or echoed substring."""
        matches = list(PROMPT.finditer(self.text))
        return matches[-1][0].lstrip("\r\n@") if matches else None


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
        self.current_prompt: str | None = None
        self._closed = False

    def connect(
        self, *, baudrate: int = 115200, shift: bool = True, enter_debug: bool = True
    ) -> None:
        with self.lock:
            if self._closed:
                raise ConnectionError("Console session is closed")
            logger.debug(
                "Connecting console baud=%d shift=%s enter_debug=%s", baudrate, shift, enter_debug
            )
            if shift:
                logger.debug("Switching to console mode at baud=1200")
                self.transport.baudrate = 1200
                self._write(SHIFT_SEQUENCE)
                time.sleep(0.5)
            self.transport.baudrate = baudrate
            time.sleep(0.5)
            response = self.resynchronize(timeout=max(self.timeout, 15))
            if enter_debug:
                if response.prompt == "pylon_debug>":
                    logger.debug("Console already in debug mode; skipping login debug")
                else:
                    logger.debug("Entering debug mode from prompt=%s", response.prompt)
                    response = self.exchange("login debug", allow_unsupported=True)
                    if response.prompt != "pylon_debug>":
                        if response.unsupported:
                            raise UnsupportedCommand(
                                "Unsupported command: 'login debug'; console remains outside debug mode",
                                response=response.text,
                            )
                        raise ProtocolError(
                            "Console did not enter debug mode", response=response.text
                        )
                    if response.unsupported:
                        logger.debug("Login rejected but final prompt confirms debug mode")
            logger.debug("Console connection ready prompt=%s", self.current_prompt)

    def _write(self, data: bytes) -> None:
        serial_logger.log(SERIAL_TRACE, "TX %r", data)
        if self.transport.write(data) != len(data):
            raise ConnectionError("Incomplete serial write; command outcome is unknown")

    def resynchronize(self, *, timeout: float | None = None) -> Response:
        """Request a prompt without repeating the previous command."""
        with self.lock:
            logger.debug("Resynchronizing console")
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
            if self._closed:
                raise ConnectionError("Console session is closed")
            label = command_label(command)
            if self._needs_resync and command:
                logger.debug("Command blocked command=%s; resynchronization required", label)
                raise ProtocolError(
                    "Console state is unknown; call resynchronize() before sending another command"
                )
            previous_prompt = self.current_prompt
            self.synchronized = False
            self.current_prompt = None
            self._needs_resync = True
            started = time.monotonic()
            data = command.encode("ascii") + terminator
            logger.debug(
                "Command start command=%s tx_bytes=%d terminator=%r timeout=%.3fs paginated=%s",
                label,
                len(data),
                terminator,
                wait,
                paginated,
            )
            try:
                self._write(data)
                response = self._receive(command, paginated=paginated, timeout=wait)
            except BaseException as exc:
                if isinstance(exc, OSError):
                    exc = ConnectionError(str(exc))
                if isinstance(exc, ProtocolError):
                    exc.context = {
                        "command": label,
                        "terminator": terminator,
                        "elapsed_s": round(time.monotonic() - started, 3),
                        "timeout_s": wait,
                        "boundary": None,
                        "previous_prompt": previous_prompt,
                    }
                logger.debug(
                    "Command failed command=%s error=%s elapsed=%.3fs partial_bytes=%d",
                    label,
                    type(exc).__name__,
                    time.monotonic() - started,
                    len(getattr(exc, "response", "")),
                )
                raise exc
            response.context.update(
                command=label,
                terminator=terminator,
                elapsed_s=round(time.monotonic() - started, 3),
                timeout_s=wait,
                boundary=response.boundary,
            )
            self.synchronized = response.boundary == "prompt"
            self.current_prompt = response.prompt if self.synchronized else None
            self._needs_resync = False
            logger.debug(
                "Command complete command=%s boundary=%s prompt=%s rx_bytes=%d elapsed=%.3fs unsupported=%s",
                label,
                response.boundary,
                response.prompt,
                len(response.text),
                time.monotonic() - started,
                response.unsupported,
            )
            # Firmware can report a target failure alongside a success footer.
            for pattern, error_type, message in (
                (r"Target device is Busy", DeviceBusyError, "Target device is busy"),
                (
                    r"(?:Target device|Device [0-9]+) is not present",
                    DeviceNotPresentError,
                    "Target device is not present",
                ),
            ):
                if re.search(
                    r"(?:^|[\r\n])[ \t]*" + pattern + r"[.!]?[ \t]*(?=[\r\n]|$)",
                    response.text,
                    re.I,
                ):
                    logger.debug("Target failure command=%s error=%s", label, error_type.__name__)
                    raise error_type(message, response=response.text, context=response.context)
            if response.unsupported and not allow_unsupported:
                raise UnsupportedCommand(
                    f"Unsupported command: {label!r}",
                    response=response.text,
                    context={
                        "command": label,
                        "terminator": terminator,
                        "elapsed_s": round(time.monotonic() - started, 3),
                        "timeout_s": wait,
                        "boundary": response.boundary,
                    },
                )
            return response

    def _receive(
        self, command: str, *, paginated: bool, timeout: float, disconnect: bool = False
    ) -> Response:
        data = bytearray()
        try:
            return self._read_frame(
                command, paginated=paginated, timeout=timeout, data=data, disconnect=disconnect
            )
        except KeyboardInterrupt as exc:
            raise CommandCancelled(
                f"Interrupted while waiting for {command_label(command)!r}",
                response=data.decode("ascii", errors="replace"),
            ) from exc

    def _read_frame(
        self,
        command: str,
        *,
        paginated: bool,
        timeout: float,
        data: bytearray,
        disconnect: bool = False,
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
                    f"Timeout waiting for {command_label(command)!r}; command was not retried",
                    response=data.decode("ascii", errors="replace"),
                )
            try:
                chunk = self.transport.read()
            except (ConnectionError, OSError) as exc:
                raise ConnectionError(
                    str(exc), response=data.decode("ascii", errors="replace")
                ) from exc
            if not chunk:
                continue
            serial_logger.log(SERIAL_TRACE, "RX %r", chunk)
            data.extend(chunk)
            if len(data) > self.max_response_bytes:
                raise ProtocolError(
                    f"Response to {command_label(command)!r} exceeded {self.max_response_bytes} bytes",
                    response=data.decode("ascii", errors="replace"),
                )
            text = data.decode("ascii", errors="replace")
            # The last terminator wins if an entire page and its prompt arrive together.
            prompts = list(PROMPT.finditer(text))
            page_at = text.rfind(CONTINUATION) if paginated else -1
            boundary = None
            quiet_deadline = None
            if disconnect:
                # Original ResponsePattern.Disconnect matches just 'cmdquit',
                # potentially its echo; a subsequent console prompt is not required.
                if "cmdquit" in text:
                    boundary = "disconnect"
            elif prompts and prompts[-1].start() > page_at:
                boundary = "prompt"
            elif page_at >= 0:
                boundary = "page"
            if boundary is not None:
                quiet_deadline = time.monotonic() + self.settle_time

    def disconnect(self) -> None:
        """Best-effort vendor disconnect: cmdquit + up to 5 seconds, then close.

        This bypasses the resynchronization guard, like the original disconnect
        overload, without retrying the last operation. No response enters reports.
        Cleanup failures are diagnostic only, so an earlier error stays intact.
        """
        with self.lock:
            if self._closed:
                return
            started = time.monotonic()
            logger.debug("Disconnecting console command=cmdquit timeout=5.000s")
            self.synchronized = False
            self.current_prompt = None
            self._needs_resync = True
            try:
                self._write(b"cmdquit\n")
                response = self._receive("cmdquit", paginated=False, timeout=5, disconnect=True)
                if response.unsupported:
                    logger.debug(
                        "Disconnect command=cmdquit rejected by firmware; closing port anyway rx_bytes=%d elapsed=%.3fs",
                        len(response.text),
                        time.monotonic() - started,
                    )
                else:
                    logger.debug(
                        "Disconnect response matched cmdquit rx_bytes=%d elapsed=%.3fs",
                        len(response.text),
                        time.monotonic() - started,
                    )
            except (PylontechError, OSError) as exc:
                logger.debug(
                    "Disconnect failed error=%s elapsed=%.3fs; closing port anyway",
                    type(exc).__name__,
                    time.monotonic() - started,
                )
            finally:
                try:
                    self.close()
                except (PylontechError, OSError) as exc:
                    logger.debug("Port close failed error=%s", type(exc).__name__)

    def close(self) -> None:
        """Release the transport immediately, including failed connection setup."""
        with self.lock:
            if not self._closed:
                self._closed = True
                self.synchronized = False
                self.current_prompt = None
                logger.debug("Closing console session")
                self.transport.close()
