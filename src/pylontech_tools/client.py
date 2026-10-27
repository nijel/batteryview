"""Monitoring and vendor report workflows, sharing one console session."""

import json
import logging
import math
import os
import re
import time
from collections.abc import Callable, Iterator
from dataclasses import asdict, fields, replace
from datetime import datetime, timezone
from pathlib import Path

from .collection import collect
from .diagnostic_reads import read_diagnostics
from .diagnostics import command_label
from .errors import (
    CommandTimeout,
    ConnectionError,
    ProtocolError,
    PylontechError,
    ResetRecoveryError,
    UnsupportedCommand,
)
from .models import (
    CollectionResult,
    ConsoleReadResult,
    DeviceInfo,
    DiagnosticsReport,
    DoctorReport,
    ModuleReading,
    ReportResult,
    Snapshot,
    SystemReading,
)
from .parsers import (
    key_values,
    parse_getpwr,
    parse_info,
    parse_pwr,
    parse_recommended_currents,
    record_count,
    record_indices,
)
from .profiles import monitoring_profile
from .protocol import ConsoleSession, Response
from .read_models import ClockResult, ParsedReadResult, StatisticsResult
from .reads import ReadOnlyCommands
from .transcript import TranscriptWriter, report_filename
from .transport import SerialTransport

Progress = Callable[[str, int, int], None]
logger = logging.getLogger(__name__)


class BatteryClient(ReadOnlyCommands):
    def __init__(
        self,
        port: str | None = None,
        *,
        baudrate: int = 115200,
        timeout: float = 5,
        module: int | None = None,
        shift: bool = True,
        session: ConsoleSession | None = None,
        monitoring_mode: str = "auto",
        profile: str | None = None,
        read_retries: int = 0,
    ):
        if module is not None and (type(module) is not int or not 1 <= module <= 16):
            raise ValueError("Module must be between 1 and 16")
        if not math.isfinite(timeout) or timeout <= 0 or baudrate <= 0:
            raise ValueError("Timeout must be finite and positive; baud rate must be positive")
        if session is None and not port:
            raise ValueError("A serial port or session is required")
        if monitoring_mode not in {"auto", "single", "parallel"}:
            raise ValueError("Monitoring mode must be auto, single or parallel")
        if type(read_retries) is not int or read_retries not in range(3):
            raise ValueError("Read retries must be 0, 1 or 2")
        self.monitoring_mode = monitoring_mode
        if profile is not None:
            monitoring_profile(profile, explicit=True)
        self.profile = profile
        self.read_retries = read_retries
        self.last_failure: BaseException | None = None
        self._last_context: dict = {}
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
        except BaseException:
            try:
                session.close()
            except (PylontechError, OSError) as exc:
                logger.debug("Setup cleanup failed error=%s", type(exc).__name__)
            raise
        self._session = session
        return self

    def close(self) -> None:
        if self._session is not None:
            try:
                self._session.disconnect()
            finally:
                if not self._injected:
                    self._session = None

    def __enter__(self) -> "BatteryClient":
        return self.connect()

    def __exit__(self, *args: object) -> None:
        self.close()

    def info(self) -> DeviceInfo:
        with self.session.lock:
            command = f"info {self.module}" if self.module else "info"
            self._identity = self._parse(parse_info, self._read(command).text, command=command)
            return self._identity

    def _diagnostic_read(self, command: str) -> ConsoleReadResult:
        with self.session.lock:
            response = self._read(command)
            # A bare date/time contains colons but is not a labeled field.
            fields = {
                label: value
                for label, value in key_values(response.text).items()
                if any(character.isalpha() for character in label)
            }
            return ConsoleReadResult(command, response.text, fields)

    def statistics(self) -> StatisticsResult:
        """Read counters, record counts, SOH, and SOC without clearing them."""
        return self._passive("stat", StatisticsResult, addressed=True)

    def read_clock(self) -> ClockResult:
        """Read the directly connected battery's RTC without setting it."""
        self._direct_only("Clock read")
        return self._passive("time", ClockResult)

    def diagnostic_log(self, count: int | None = None) -> ParsedReadResult:
        """Read the local diagnostic ring, newest first; count must be 1–32.

        Omit count to let the firmware select the available entries. The response
        is preserved without interpreting log entries or assuming their validity.
        """
        self._direct_only("Diagnostic log")
        if count is not None and (type(count) is not int or not 1 <= count <= 32):
            raise ValueError("Log count must be an integer between 1 and 32")
        return self._passive("log" if count is None else f"log {count}", ParsedReadResult)

    def diagnostics(self) -> DiagnosticsReport:
        """Gather local read-only diagnostics, skipping unsupported commands.

        Other read failures stop acquisition and return an incomplete report;
        last_failure retains the exception. Cancellation propagates normally.
        """
        return read_diagnostics(self)

    def doctor(
        self, *, save_inputs: str | Path | None = None, imbalance_mv: int = 100
    ) -> DoctorReport:
        """Screen the connected battery using read-only live and historical evidence.

        Optionally retain inputs for offline analysis; no state-changing diagnostic
        tests or maintenance operations are run. Requires a direct connection.
        """
        from .doctor_acquisition import acquire_doctor

        return acquire_doctor(self, save_inputs=save_inputs, imbalance_mv=imbalance_mv)

    def collect(self, output: str | Path, *, progress: Progress | None = None) -> CollectionResult:
        """Collect the directly connected module, stopping at the first failure.

        Reuse an output directory across physical module connections; every run
        has its own manifest and JSON artifacts. Earlier files are never replaced.
        """
        return collect(self, output, progress=progress)

    def _output_path(self, output: str | Path | None, kind: str) -> Path:
        if output is not None:
            return Path(output)
        identity = self._identity or self.info()
        return Path(report_filename(identity.barcode, kind))

    def _parse(self, parser, text: str, *, command: str, **kwargs):
        try:
            return parser(text, **kwargs)
        except ProtocolError as exc:
            exc.context = {**self._last_context, "command": command_label(command)}
            raise

    def _read(self, command: str, *, writer: TranscriptWriter | None = None, **kwargs) -> Response:
        """Retry only explicit read commands, after a verified prompt."""
        for attempt in range(self.read_retries + 1):
            try:
                response = self.session.exchange(command, **kwargs)
            except ProtocolError as exc:
                if writer is not None and exc.response:
                    writer.append(exc.response)
                if (
                    not isinstance(exc, (CommandTimeout, ConnectionError))
                    or attempt == self.read_retries
                ):
                    raise
                logger.debug("Retrying read command=%s attempt=%d", command, attempt + 1)
                try:
                    sync = self.session.resynchronize(timeout=max(self.timeout, 15))
                except ProtocolError as sync_error:
                    if writer is not None and sync_error.response:
                        writer.append(sync_error.response)
                    raise
                if writer is not None:
                    writer.append(sync.text)
                if sync.prompt != "pylon_debug>":
                    raise ProtocolError(
                        "Read recovery did not confirm debug prompt", response=sync.text
                    )
            else:
                if writer is not None:
                    writer.append(response.text)
                return self._accept_read(response, command)
        raise AssertionError("unreachable")

    def _accept_read(self, response: Response, command: str) -> Response:
        """Share context and corrupt-record handling with paginated reads."""
        self._last_context = response.context or {
            "command": command_label(command),
            "boundary": response.boundary,
        }
        if command.split()[0] in {"data", "datalist"} and re.search(
            r"(?:^|[\r\n])[ \t]*Error![ \t]*(?=[\r\n]|$)", response.text
        ):
            raise ProtocolError(
                "Firmware reported a corrupt record; report incomplete",
                response=response.text,
                context=self._last_context,
            )
        return response

    def _direct_only(self, operation: str) -> None:
        if self.module is not None:
            raise ValueError(f"{operation} requires a direct module connection; omit --module")

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
        self._direct_only(kind)
        with self.session.lock:
            path = self._output_path(output, kind)
            with TranscriptWriter(path) as writer:
                identity = self._read("info", writer=writer)
                # A malformed identity must not prevent an otherwise useful raw report.
                try:
                    self._identity = parse_info(identity.text)
                except ProtocolError:
                    pass
                stat = self._read("stat", writer=writer)
                latest = self._read(f"data {kind}", writer=writer)
                indices = record_indices(latest.text, detailed=True)
                try:
                    stat_count = record_count(stat.text, kind)
                except ProtocolError:
                    stat_count = None
                if len(indices) > 1:
                    raise ProtocolError(
                        "Latest response has multiple record indices",
                        response=latest.text,
                        context=latest.context or {"command": f"data {kind}"},
                    )
                if indices:
                    count = indices[0] + 1
                    if stat_count is not None and stat_count != count:
                        logger.debug(
                            "Report count disagreement kind=%s stat=%d latest=%d",
                            kind,
                            stat_count,
                            count,
                        )
                elif stat_count is not None:
                    count = stat_count
                else:
                    raise ProtocolError(
                        "Cannot establish report record count",
                        response=latest.text,
                        context=latest.context or {"command": f"data {kind}"},
                    )
                verified = set()
                detailed = True
                for offset in range(0, count, 15):
                    if detailed:
                        try:
                            page = self._read(
                                f"datalist {kind} dtls {offset}",
                                writer=writer,
                                paginated=True,
                            )
                        except UnsupportedCommand:
                            # The vendor switches modes on an explicit rejection,
                            # retrying the same block as a plain summary page.
                            detailed = False
                            logger.debug(
                                "Report format fallback kind=%s offset=%d: dtls unsupported; "
                                "using summary pages and individual records",
                                kind,
                                offset,
                            )
                    if not detailed:
                        page = self._read(
                            f"datalist {kind} {offset}", writer=writer, paginated=True
                        )
                    # BatteryView sends LF after *every* block, including the last.
                    # On the supplied firmware LF exits pagination; CR+LF continues it.
                    finish = self._record(writer, "", paginated=True)
                    if finish.boundary != "prompt":
                        raise ProtocolError(
                            "Firmware did not exit detailed pagination after LF; report incomplete",
                            response=finish.text,
                            context=finish.context or {"command": "<enter>"},
                        )
                    if detailed:
                        received = record_indices(page.text)
                        expected = list(range(offset, min(offset + 15, count)))
                        # Some firmware includes the first row of the next page.
                        overlap = expected + [offset + 15] if offset + 15 < count else expected
                        if received not in (expected, overlap):
                            raise ProtocolError(
                                "Detailed page has missing, repeated or unexpected records; "
                                "report incomplete",
                                response=page.text,
                                context=page.context
                                or {"command": f"datalist {kind} dtls {offset}"},
                            )
                        verified.update(received)
                        if progress:
                            progress(kind, len(verified), count)
                    if not detailed:
                        for index in range(offset, min(offset + 15, count)):
                            detail = self._read(
                                f"data {kind} {index}",
                                writer=writer,
                                timeout=max(self.timeout, 10),
                            )
                            received = record_indices(detail.text, detailed=True)
                            if received != [index]:
                                raise ProtocolError(
                                    f"Unexpected or missing record index for data {kind} {index}; "
                                    "report incomplete",
                                    response=detail.text,
                                    context=detail.context or {"command": f"data {kind} {index}"},
                                )
                            verified.add(index)
                            if progress:
                                progress(kind, len(verified), count)
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
        self._direct_only("SOC reset")
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
            unsupported = set()

            def read(command: str, *, optional: bool = False) -> str | None:
                if command in unsupported:
                    return None
                if command in raw:
                    return raw[command]
                try:
                    text = self._read(command).text
                except UnsupportedCommand as exc:
                    if not optional:
                        raise
                    raw[command] = exc.response
                    unsupported.add(command)
                    return None
                raw[command] = text
                return text

            if self._identity is None and self.profile is None:
                try:
                    self.info()
                except UnsupportedCommand:
                    logger.debug("Identity unavailable; using generic monitoring profile")
            profile = monitoring_profile(
                self.profile or (self._identity.name if self._identity else None),
                explicit=self.profile is not None,
            )
            logger.debug(
                "Snapshot mode=%s profile=%s selected_module=%s",
                self.monitoring_mode,
                profile.name,
                self.module,
            )
            local = None
            summaries = []
            if self.module is not None or self.monitoring_mode != "parallel":
                command = f"getpwr {self.module}" if self.module else "getpwr"
                local = self._parse(
                    parse_getpwr,
                    read(command),
                    command=command,
                    address=self.module,
                    profile=profile,
                )
            if self.module is not None:
                if profile.pwr_extension:
                    text = read(f"pwr {self.module}", optional=True)
                    if text is not None:
                        summaries = self._parse(
                            parse_pwr, text, command=f"pwr {self.module}" if self.module else "pwr"
                        )
                        if len(summaries) != 1 or summaries[0].address != self.module:
                            raise ProtocolError(
                                "Addressed pwr returned another module", response=text
                            )
                summaries = summaries or [ModuleReading(address=self.module)]
            elif self.monitoring_mode == "parallel":
                summaries = self._parse(parse_pwr, read("pwr"), command="pwr")
            elif self.monitoring_mode == "auto" or profile.pwr_extension:
                text = read("pwr", optional=True)
                if text is not None:
                    summaries = self._parse(
                        parse_pwr, text, command=f"pwr {self.module}" if self.module else "pwr"
                    )
                if self.monitoring_mode == "single" and len(summaries) > 1:
                    address = self._identity.address if self._identity else None
                    summaries = [m for m in summaries if m.address == address]
                    if not summaries:
                        raise ProtocolError(
                            "Cannot identify local module in pwr table", response=text
                        )
            if not summaries:
                summaries = [
                    ModuleReading(address=self._identity.address if self._identity else None)
                ]
            addresses = [m.address for m in summaries]
            if len(set(addresses)) != len(addresses) or (len(summaries) > 1 and None in addresses):
                raise ProtocolError(
                    "pwr returned ambiguous module addresses", response=raw.get("pwr", "")
                )
            detailed = []
            for summary in summaries:
                addressed = (
                    self.module is not None
                    or len(summaries) > 1
                    or self.monitoring_mode == "parallel"
                )
                if addressed and self.module is None:
                    command = f"getpwr {summary.address}"
                    detail = self._parse(
                        parse_getpwr,
                        read(command),
                        command=command,
                        address=summary.address,
                        profile=profile,
                    )
                else:
                    detail = replace(local, address=summary.address)
                # Detail readings take precedence, while summary-only extensions survive.
                updates = {
                    f.name: getattr(detail, f.name)
                    for f in fields(ModuleReading)
                    if f.name not in {"raw", "states", "alarms"}
                    and getattr(detail, f.name) is not None
                }
                states = {**summary.states, **detail.states}
                module = replace(
                    summary,
                    **updates,
                    states=states,
                    raw={**summary.raw, **detail.raw},
                    alarms=list(
                        {
                            (a.source, a.code, a.cell): a
                            for a in summary.alarms + detail.alarms
                            if not (
                                a.source.startswith("module.")
                                and a.source[7:] in detail.states
                                and a not in detail.alarms
                            )
                        }.values()
                    ),
                )
                if (
                    addressed
                    and profile.addressed_pwrsys
                    and (type(module.address) is not int or not 1 <= module.address <= 16)
                ):
                    raise ProtocolError(
                        "Cannot query pwrsys with an invalid module address",
                        response=raw.get("pwr", ""),
                    )
                command = (
                    f"pwrsys {module.address}"
                    if addressed and profile.addressed_pwrsys
                    else "pwrsys"
                )
                text = read(command, optional=True)
                if text is not None:
                    charge, discharge = self._parse(
                        parse_recommended_currents, text, command=command
                    )
                    module = replace(
                        module, recommended_charge_a=charge, recommended_discharge_a=discharge
                    )
                detailed.append(module)
            charge = discharge = None
            if profile.system_pwrsys:
                text = read("pwrsys", optional=True)
                if text is not None:
                    charge, discharge = self._parse(
                        parse_recommended_currents, text, command="pwrsys", system=True
                    )
            currents = [m.current_a for m in detailed]
            voltages = [m.voltage_v for m in detailed]
            system = SystemReading(
                current_a=sum(currents) if all(v is not None for v in currents) else None,
                voltage_v=sum(voltages) / len(voltages)
                if all(v is not None for v in voltages)
                else None,
                recommended_charge_a=charge,
                recommended_discharge_a=discharge,
            )
            return Snapshot(datetime.now(timezone.utc).isoformat(), detailed, raw, system)

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
