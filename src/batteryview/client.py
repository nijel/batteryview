"""Monitoring and vendor report workflows, sharing one console session."""

import json
import math
import os
import re
import time
from collections.abc import Callable, Iterator
from dataclasses import asdict, replace
from datetime import datetime, timezone
from pathlib import Path

from .errors import ProtocolError, ResetRecoveryError, UnsupportedCommand
from .models import DeviceInfo, ReportResult, Snapshot
from .parsers import parse_getpwr, parse_info, parse_pwr, recommended_currents, record_count
from .protocol import ConsoleSession, Response
from .transcript import TranscriptWriter, report_filename
from .transport import SerialTransport

Progress = Callable[[str, int, int], None]


class BatteryClient:
    def __init__(
        self,
        port: str | None = None,
        *,
        baudrate: int = 115200,
        timeout: float = 5,
        module: int | None = None,
        shift: bool = True,
        session: ConsoleSession | None = None,
    ):
        if module is not None and not 1 <= module <= 16:
            raise ValueError("Module must be between 1 and 16")
        if not math.isfinite(timeout) or timeout <= 0 or baudrate <= 0:
            raise ValueError("Timeout must be finite and positive; baud rate must be positive")
        if session is None and not port:
            raise ValueError("A serial port or session is required")
        self.port = port
        self.baudrate = baudrate
        self.timeout = timeout
        self.module = module
        self.shift = shift
        self._session = session
        self._injected = session is not None
        self._identity: DeviceInfo | None = None

    @property
    def session(self) -> ConsoleSession:
        if self._session is None:
            raise ProtocolError("Client is not connected; use a context manager or connect()")
        return self._session

    def connect(self) -> "BatteryClient":
        if self._session is not None:
            return self
        session = ConsoleSession(SerialTransport(self.port, self.baudrate), timeout=self.timeout)
        try:
            session.connect(baudrate=self.baudrate, shift=self.shift)
            self._select_module(session)
        except BaseException:
            session.close()
            raise
        self._session = session
        return self

    def _select_module(self, session: ConsoleSession) -> None:
        if self.module is not None:
            session.exchange(f"login {self.module} debug")

    def close(self) -> None:
        if self._session is not None:
            self._session.close()
            if not self._injected:
                self._session = None

    def __enter__(self) -> "BatteryClient":
        return self.connect()

    def __exit__(self, *args: object) -> None:
        self.close()

    def info(self) -> DeviceInfo:
        with self.session.lock:
            self._identity = parse_info(self.session.exchange("info").text)
            return self._identity

    def _output_path(self, output: str | Path | None, kind: str) -> Path:
        if output is not None:
            return Path(output)
        identity = self._identity or self.info()
        return Path(report_filename(identity.barcode, kind))

    def _record(
        self,
        writer: TranscriptWriter,
        command: str,
        **kwargs: object,
    ) -> Response:
        try:
            response = self.session.exchange(command, **kwargs)
        except ProtocolError as exc:
            if exc.response:
                writer.append(exc.response)
            raise
        writer.append(response.text)
        return response

    def export_history(
        self, output: str | Path | None = None, *, progress: Progress | None = None
    ) -> ReportResult:
        return self._export("history", output, progress=progress)

    def export_events(
        self, output: str | Path | None = None, *, progress: Progress | None = None
    ) -> ReportResult:
        return self._export("event", output, progress=progress)

    def _export(
        self, kind: str, output: str | Path | None, *, progress: Progress | None
    ) -> ReportResult:
        with self.session.lock:
            path = self._output_path(output, kind)
            with TranscriptWriter(path) as writer:
                identity = self._record(writer, "info")
                # A malformed identity must not prevent an otherwise useful raw report.
                try:
                    self._identity = parse_info(identity.text)
                except ProtocolError:
                    pass
                stat = self._record(writer, "stat")
                count = record_count(stat.text, kind)
                self._record(writer, f"data {kind}")
                for offset in range(0, count, 15):
                    response = self._record(
                        writer,
                        f"datalist {kind} dtls {offset}",
                        paginated=True,
                    )
                    # BatteryView sends LF after *every* block, including the last.
                    # On the supplied firmware LF exits pagination; CR+LF continues it.
                    finish = self._record(writer, "", paginated=True)
                    if finish.boundary != "prompt":
                        raise ProtocolError(
                            "Firmware did not exit detailed pagination after LF; report incomplete"
                        )
                    if response.boundary not in {"page", "prompt"}:
                        raise ProtocolError("Unexpected detailed report boundary")
                    if progress:
                        progress(kind, min(offset + 15, count), count)
                if progress and count == 0:
                    progress(kind, 0, 0)
                return ReportResult(path, kind, count, writer.responses)

    def _dump_script_history(self, writer: TranscriptWriter, kind: str) -> None:
        response = self._record(
            writer,
            f"datalist {kind} 0",
            paginated=True,
            timeout=max(self.timeout, 8),
            allow_unsupported=True,
        )
        # RetrieveHistoryData always sends one CR+LF, even for an empty/invalid command.
        # Its response can contain two console prompts; record them verbatim.
        pages = 0
        while True:
            response = self._record(
                writer,
                "",
                terminator=b"\r\n",
                paginated=True,
                timeout=max(self.timeout, 8),
                allow_unsupported=True,
            )
            pages += 1
            if response.boundary == "prompt":
                return
            if pages >= 100000:
                raise ProtocolError("Script pagination exceeded 100000 pages")

    @staticmethod
    def _save_recovery(path: Path, state: dict[str, object], *, create: bool = False) -> None:
        """Exclusive first write and atomic, durable updates before each mutating step."""
        data = (json.dumps(state, indent=2, ensure_ascii=False) + "\n").encode("utf-8")
        if create:
            with path.open("xb") as stream:
                stream.write(data)
                stream.flush()
                os.fsync(stream.fileno())
        else:
            temporary = path.with_name(path.name + ".tmp")
            with temporary.open("xb") as stream:
                stream.write(data)
                stream.flush()
                os.fsync(stream.fileno())
            os.replace(temporary, path)
        # Persist directory entries too, where the OS exposes directory fsync.
        # Windows has no O_DIRECTORY; file flushes above still apply there.
        if hasattr(os, "O_DIRECTORY"):
            directory = os.open(path.parent, os.O_RDONLY | os.O_DIRECTORY)
            try:
                os.fsync(directory)
            finally:
                os.close(directory)

    def reset_soc(
        self, output: str | Path | None = None, *, progress: Progress | None = None
    ) -> ReportResult:
        """Execute the shipped reset script once. No automatic destructive retries.

        The recovery JSON is deliberately outside the vendor transcript. An interrupted
        operation raises ResetRecoveryError with the path and last attempted step.
        """
        with self.session.lock:
            path = self._output_path(output, "resetsoc")
            recovery_path = path.with_name(path.name + ".recovery.json")
            state: dict[str, object] = {
                "version": 1,
                "report": str(path.resolve()),
                "port": self.port,
                "baudrate": self.baudrate,
                "module": self.module,
                "status": "collecting",
                "step": "pre-reset collection",
            }
            with TranscriptWriter(path) as writer:
                self._save_recovery(recovery_path, state, create=True)
                try:
                    self._record(writer, "stat", terminator=b"\r")
                    for kind in ("event", "misc", "history"):
                        self._dump_script_history(writer, kind)
                        if progress:
                            progress(
                                "collecting reset history",
                                ("event", "misc", "history").index(kind) + 1,
                                3,
                            )
                    before = parse_info(self._record(writer, "info", terminator=b"\r").text)
                    if not before.barcode or not re.fullmatch(r"[A-Za-z0-9_+-]+", before.barcode):
                        raise ProtocolError(
                            "Cannot reset: info contains no usable original barcode"
                        )
                    state.update(identity=asdict(before), barcode=before.barcode)
                    self._save_recovery(recovery_path, state)
                    self._record(writer, "setlowcfg", terminator=b"\r")
                    # Flush both artifacts before clearing EEPROM, including metadata needed
                    # to restore identity if the machine loses power mid-operation.
                    writer.sync()
                    for command in ("eepe 0", "trst"):
                        state.update(status="in_progress", step=command)
                        self._save_recovery(recovery_path, state)
                        result = self._record(writer, command, terminator=b"\r")
                        if (
                            command == "eepe 0"
                            and "Command completed successfully" not in result.text
                        ):
                            raise ProtocolError(
                                "EEPROM clearing did not report successful completion"
                            )
                        if command == "trst" and not re.search(r"(?:^|[\r\n@])pylon>", result.text):
                            raise ProtocolError("Reset did not return to the base console prompt")
                    state.update(step="reconnect")
                    self._save_recovery(recovery_path, state)
                    # Script's 'login' pseudo-command runs ShifttoConsole and produces
                    # no report text on success. Do not select the old address here.
                    self.session.connect(
                        baudrate=self.baudrate, shift=self.shift, enter_debug=False
                    )
                    state.update(step="restore barcode")
                    self._save_recovery(recovery_path, state)
                    # Script.xml sends login debug as a saved command after reconnect.
                    self._record(writer, "login debug", terminator=b"\r")
                    restored = self._record(writer, f"tbar {before.barcode}", terminator=b"\r")
                    if "Test result:pass" not in restored.text:
                        raise ProtocolError("Barcode restoration did not report Test result:pass")
                    after = parse_info(self._record(writer, "info", terminator=b"\r").text)
                    if after.barcode != before.barcode or after.name != before.name:
                        raise ProtocolError(
                            "Post-reset identity does not match the original device"
                        )
                    self._record(writer, "setlowcfg", terminator=b"\r")
                    writer.sync()
                    self._identity = after
                    state.update(status="complete", step="complete", identity_after=asdict(after))
                    self._save_recovery(recovery_path, state)
                    return ReportResult(
                        path, "resetsoc", None, writer.responses, recovery_path=recovery_path
                    )
                except BaseException as exc:
                    state.update(status="interrupted", error=str(exc))
                    try:
                        self._save_recovery(recovery_path, state)
                    except OSError:
                        pass  # Preserve the original failure; an earlier durable state remains.
                    if isinstance(exc, (KeyboardInterrupt, Exception)):
                        raise ResetRecoveryError(
                            f"SOC reset interrupted at {state['step']}: {exc}. "
                            f"Do not repeat the reset blindly; recovery state: {recovery_path}",
                            recovery_path=str(recovery_path),
                        ) from exc
                    raise

    def snapshot(self) -> Snapshot:
        with self.session.lock:
            raw: dict[str, str] = {}
            raw["pwr"] = self.session.exchange("pwr").text
            modules = parse_pwr(raw["pwr"])
            if self.module is not None:
                modules = [m for m in modules if m.address == self.module]
                if not modules:
                    raise ProtocolError(f"Module {self.module} is absent from pwr")
            detailed = []
            for module in modules:
                command = (
                    f"getpwr {module.address}" if len(modules) > 1 or self.module else "getpwr"
                )
                raw[command] = self.session.exchange(command).text
                detail = parse_getpwr(raw[command], address=module.address)
                # pwr supplies SOC and firmware extensions not present in getpwr.
                states = {**module.states, **detail.states}
                module = replace(
                    module,
                    cells=detail.cells,
                    capacity_ah=detail.capacity_ah,
                    states=states,
                    raw={**module.raw, **detail.raw},
                    alarms=list(
                        {
                            (a.source, a.code, a.cell): a for a in module.alarms + detail.alarms
                        }.values()
                    ),
                    voltage_v=detail.voltage_v
                    if detail.voltage_v is not None
                    else module.voltage_v,
                    current_a=detail.current_a
                    if detail.current_a is not None
                    else module.current_a,
                    temperature_c=detail.temperature_c
                    if detail.temperature_c is not None
                    else module.temperature_c,
                    error_code=detail.error_code,
                    cycle_count=detail.cycle_count,
                )
                command = (
                    f"pwrsys {module.address}" if len(modules) > 1 or self.module else "pwrsys"
                )
                try:
                    raw[command] = self.session.exchange(command).text
                except UnsupportedCommand as exc:
                    raw[command] = exc.response
                else:
                    charge, discharge = recommended_currents(raw[command])
                    module = replace(
                        module, recommended_charge_a=charge, recommended_discharge_a=discharge
                    )
                detailed.append(module)
            return Snapshot(datetime.now(timezone.utc).isoformat(), detailed, raw)

    def watch(self, *, interval: float = 5, count: int | None = None) -> Iterator[Snapshot]:
        if not math.isfinite(interval) or interval <= 0 or (count is not None and count < 1):
            raise ValueError("Interval and count must be positive")
        index = 0
        while count is None or index < count:
            start = time.monotonic()
            yield self.snapshot()
            index += 1
            if count is None or index < count:
                time.sleep(max(0, interval - (time.monotonic() - start)))
