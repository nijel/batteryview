"""Explicit passive command forms for BatteryClient; no arbitrary-command API."""

import re

from .errors import CommandTimeout, ConnectionError, ProtocolError
from .models import ConsoleReadResult
from .parsers import key_values, record_count, record_indices
from .profiles import monitoring_profile
from .read_models import (
    AccountingResult,
    CapacityResult,
    CheckResult,
    ClockResult,
    CommunicationResult,
    ConfigurationResult,
    MeasurementResult,
    RecordsResult,
    RegisterResult,
    StorageResult,
)
from .read_parsers import measurements, parse_result, records, storage

# Query branches only. Actions, no-op branches and bare-target mutations are absent.
CONFIG_QUERIES = frozenset(
    """
pov povr phv phvr plv plvr puv puvr pslp bov bovr bhv bhvr blv blvr buv buvr bslp
bot botr bht bhtr blt bltr but butr eot eotr eht ehtr elt eltr eut eutr mot motr
coc coca cocar doc doca docar sc ocd ocr oc2d oc2r scd scr clc bsv bv recinv uvtime
recuse idle shuttime sleep record hwsleep
""".split()
)
CONTROL_QUERIES = frozenset("cfet dfet buzz heat pwmc softstart agelog mostest".split())
KINDS = frozenset("event history pov puv plv bov buv inputov coc coca doc doca sc use".split())
FIELDS = frozenset({"id", "volt", "curr", "temp", "coul"})


def bounded(value: int, label: str, minimum: int, maximum: int) -> int:
    if type(value) is not int or not minimum <= value <= maximum:
        raise ValueError(f"{label} must be an integer between {minimum} and {maximum}")
    return value


def choice(value: str, label: str, choices: frozenset[str]) -> str:
    if type(value) is not str or value not in choices:
        raise ValueError(f"{label} must be one of: {', '.join(sorted(choices))}")
    return value


class ReadOnlyCommands:
    """Individual verified reads, inherited by the public BatteryClient."""

    def _passive(self, command, result_type, *, addressed=False):
        if addressed:
            name, *arguments = command.split()
            command = " ".join([name, *([str(self.module)] if self.module else []), *arguments])
        else:
            self._direct_only(command.split()[0] + " read")
        with self.session.lock:
            result = self._diagnostic_read(command)
            return self._parse(parse_result, result, command=command, cls=result_type)

    def command_help(self, name: str | None = None) -> CommunicationResult:
        """Read ``help [name]``. A name is one ASCII command token, never operands."""
        if name is not None and (
            type(name) is not str or not re.fullmatch(r"[a-z][a-z0-9]*", name, re.ASCII)
        ):
            raise ValueError("Help name must be one lowercase ASCII command name")
        return self._passive("help" if name is None else f"help {name}", CommunicationResult)

    def communication_frame(self, port: int) -> CommunicationResult:
        """Read ``ct port`` for port 0 or 1; does not start continuous tracing."""
        bounded(port, "Port", 0, 1)
        return self._passive(f"ct {port}", CommunicationResult)

    def configuration(self, selector: str | None = None) -> ConfigurationResult:
        """Read ``config [selector]`` using only documented passive selectors."""
        if selector is not None:
            choice(selector, "Configuration selector", CONFIG_QUERIES)
        return self._passive(
            "config" if selector is None else f"config {selector}",
            ConfigurationResult,
            addressed=True,
        )

    def control_status(self, target: str | None = None) -> ConfigurationResult:
        """Read ``ctrl [target]``; I2C/AFUSE and unimplemented selectors are excluded."""
        if target is not None:
            choice(target, "Control target", CONTROL_QUERIES)
        return self._passive(
            "ctrl" if target is None else f"ctrl {target}", ConfigurationResult, addressed=True
        )

    def power_summary(self) -> MeasurementResult:
        """Read ``pwr [module]``; retain present modules and original absent rows."""
        command = f"pwr {self.module}" if self.module else "pwr"
        with self.session.lock:
            result = self._diagnostic_read(command)
            return self._parse(measurements, result, command=command, address=self.module)

    def power_details(self) -> MeasurementResult:
        """Read ``getpwr [module]`` using the selected/native monitoring profile."""
        command = f"getpwr {self.module}" if self.module else "getpwr"
        with self.session.lock:
            if self.profile is None and self._identity is None:
                self.info()
            profile = (
                monitoring_profile(self.profile, explicit=True)
                if self.profile
                else monitoring_profile(self._identity.name)
            )
            result = self._diagnostic_read(command)
            return self._parse(
                measurements, result, command=command, address=self.module, profile=profile
            )

    def cell_readings(self, cell: int | None = None) -> MeasurementResult:
        """Read ``bat [module [cell]]``; cell indices are zero-based.

        Selecting a local cell first reads identity to obtain both its module
        address and cell count. The first bat operand is never a cell selector.
        """
        if cell is not None:
            bounded(cell, "Cell", 0, 65535)
        with self.session.lock:
            module = self.module
            if cell is not None:
                info = self.info()
                if info.cell_count is None or cell >= info.cell_count:
                    raise ValueError("Cell must be below the reported cell count")
                module = module or info.address
                bounded(module, "Reported module", 1, 16)
            command = (
                "bat" + (f" {module}" if module else "") + (f" {cell}" if cell is not None else "")
            )
            result = self._diagnostic_read(command)
            return self._parse(measurements, result, command=command, address=module)

    def system_status(self) -> MeasurementResult:
        """Read bare local ``pwrsys``; unsafe explicit-address forms are excluded."""
        self._direct_only("System status")
        with self.session.lock:
            result = self._diagnostic_read("pwrsys")
            return self._parse(measurements, result, command="pwrsys")

    def read_eeprom(self, chip: int, offset: int, size: int) -> StorageResult:
        """Read ``eepr`` bytes, chips 0/1, within the 2048-byte logical device."""
        bounded(chip, "Chip", 0, 1)
        bounded(offset, "Offset", 0, 0x800)
        bounded(size, "Size", 0, 0x800 - offset)
        return self._storage_read(f"eepr {chip} {offset:x} {size}", chip, offset, size)

    def read_flash(self, offset: int, size: int) -> StorageResult:
        """Read ``flar 0`` bytes; firmware checks its detected runtime capacity."""
        bounded(offset, "Offset", 0, 0xFFFFFFFF)
        bounded(size, "Size", 0, min(99999999, 0xFFFFFFFF - offset))
        return self._storage_read(f"flar 0 {offset:x} {size}", 0, offset, size)

    def _storage_read(self, command, chip, offset, size):
        self._direct_only("Storage read")
        with self.session.lock:
            result = self._diagnostic_read(command)
            return self._parse(
                storage, result, command=command, chip=chip, offset=offset, size=size
            )

    def monitor_configuration(self, ic_count: int) -> RegisterResult:
        """Read ``bmicrdcfg`` for 1–2 ICs; caller must match installed hardware.

        Three or more ICs overflow the inspected firmware's caller buffer.
        """
        bounded(ic_count, "IC count", 1, 2)
        return self._passive(f"bmicrdcfg {ic_count}", RegisterResult)

    def monitor_communication(self, ic_count: int) -> RegisterResult:
        """Read ``bmicrdcomm`` for the actual installed count, restricted to 1–2."""
        bounded(ic_count, "IC count", 1, 2)
        return self._passive(f"bmicrdcomm {ic_count}", RegisterResult)

    def ina_register(self, offset: int) -> RegisterResult:
        """Read ``inar offset`` (E2): hexadecimal register 00–7F, two-byte value."""
        bounded(offset, "Register offset", 0, 0x7F)
        return self._passive(f"inar {offset:x}", RegisterResult)

    def gauge_register(self, offset: int) -> RegisterResult:
        """Read ``socr offset`` (C): hexadecimal register 00–7F, one-byte value."""
        bounded(offset, "Register offset", 0, 0x7F)
        return self._passive(f"socr {offset:x}", RegisterResult)

    def _available_records(self, kind):
        if kind in {"event", "history"}:
            result = self.statistics()
            count = self._parse(record_count, result.text, command=result.command, kind=kind)
        else:
            result = self._diagnostic_read(
                "data " + (f"{self.module} " if self.module else "") + kind
            )
            indices = record_indices(result.text, detailed=True)
            if len(indices) == 1:
                count = indices[0] + 1
            elif re.search(r"\bno (?:data|records?)\b", result.text, re.I):
                count = 0
            else:
                raise ProtocolError(
                    "Cannot determine the selected record count", response=result.text
                )
        if not 0 <= count <= 65536:
            raise ProtocolError(
                "Record count exceeds the firmware index range", response=result.text
            )
        return count

    def read_record(self, kind: str = "event", index: int | None = None) -> RecordsResult:
        """Read ``data [module] kind [index]``; no index selects the latest item."""
        choice(kind, "Record kind", KINDS)
        if index is not None:
            bounded(index, "Record index", 0, 65535)
        with self.session.lock:
            if index is not None and index >= self._available_records(kind):
                raise ValueError("Record index must be below the available record count")
            command = (
                "data "
                + (f"{self.module} " if self.module else "")
                + kind
                + (f" {index}" if index is not None else "")
            )
            result = self._diagnostic_read(command)
            indices = record_indices(result.text, detailed=True)
            if index is not None and indices != [index]:
                raise ProtocolError(
                    "Record response has an unexpected or missing index",
                    response=result.text,
                    context=self._last_context,
                )
            return records(result, kind, indices)

    def list_records(
        self,
        kind: str,
        start: int = 0,
        *,
        detailed: bool = False,
        field: str | None = None,
        cell: int | None = None,
    ) -> RecordsResult:
        """Consume ``datalist`` through its final prompt, retaining every page.

        ``field`` is id/volt/curr/temp/coul and may select all cells or one
        zero-based ``cell``. Detailed and field modes cannot be combined.
        A failed paginated acquisition restarts in full after prompt recovery.
        """
        self._direct_only("Record list")
        choice(kind, "Record kind", KINDS)
        bounded(start, "Start", 0, 65535)
        if type(detailed) is not bool:
            raise ValueError("Detailed must be a boolean")
        if field is not None:
            choice(field, "Record field", FIELDS)
        if detailed and field is not None or cell is not None and field is None:
            raise ValueError("Cell requires field; detailed and field are mutually exclusive")
        if cell is not None:
            bounded(cell, "Cell", 0, 65535)
        with self.session.lock:
            if cell is not None:
                identity = self.info()
                if identity.cell_count is None or cell >= identity.cell_count:
                    raise ValueError("Cell must be below the reported cell count")
            count = self._available_records(kind)
            if start >= count:
                if start == 0 and count == 0:
                    return RecordsResult(command=f"datalist {kind} {start}", text="", kind=kind)
                raise ValueError("Start must be below the available record count")
            selection = (
                "dtls "
                if detailed
                else f"bat {str(cell) + ' ' if cell is not None else ''}{field} "
                if field is not None
                else ""
            )
            command = f"datalist {kind} {selection}{start}"
            text = self._record_pages(command)
            result = ConsoleReadResult(command, text, key_values(text))
            indices = record_indices(text)
            unique = list(dict.fromkeys(indices))
            if unique != list(range(start, count)):
                raise ProtocolError(
                    "Record list has missing, repeated or unexpected indices",
                    response=text,
                    context=self._last_context,
                )
            return records(result, kind, unique)

    def _record_pages(self, command):
        for attempt in range(self.read_retries + 1):
            pages = []
            seen = set()
            try:
                response = self._accept_read(
                    self.session.exchange(command, paginated=True), command
                )
                while True:
                    pages.append(response.text)
                    if response.boundary == "prompt":
                        return "".join(pages)
                    if response.boundary != "page" or response.text in seen:
                        raise ProtocolError(
                            "Record pagination made no progress", response="".join(pages)
                        )
                    seen.add(response.text)
                    response = self._accept_read(
                        self.session.exchange("", paginated=True, terminator=b"\r\n"), command
                    )
            except (CommandTimeout, ConnectionError) as exc:
                exc.response = "".join(pages) + exc.response
                if attempt == self.read_retries:
                    raise
                try:
                    sync = self.session.resynchronize(timeout=max(self.timeout, 15))
                except ProtocolError as recovery_error:
                    recovery_error.response = exc.response + recovery_error.response
                    raise
                if sync.prompt != "pylon_debug>":
                    raise ProtocolError(
                        "Read recovery did not confirm debug prompt",
                        response=exc.response + sync.text,
                    ) from exc
            except ProtocolError as exc:
                if exc.response != "".join(pages):
                    exc.response = "".join(pages) + exc.response
                raise
        raise AssertionError("unreachable")

    def check_charge_current(
        self, current_ma: int | None = None, *, tolerance_ma: int | None = None
    ) -> CheckResult:
        """Compare cached charge current with ``tchgc``; tolerance operand is E2-only."""
        return self._current_check("tchgc", current_ma, tolerance_ma)

    def check_discharge_current(
        self, magnitude_ma: int | None = None, *, tolerance_ma: int | None = None
    ) -> CheckResult:
        """Compare cached discharge current with ``tdisc``; supply a positive magnitude."""
        return self._current_check("tdisc", magnitude_ma, tolerance_ma)

    def _current_check(self, command, current, tolerance):
        if current is not None:
            bounded(current, "Current magnitude", 0, 99999999)
        if tolerance is not None:
            if current is None:
                raise ValueError("Tolerance requires a reference current")
            bounded(tolerance, "Tolerance", 50 if command == "tchgc" else 100, 500)
        suffix = (f" {current}" if current is not None else "") + (
            f" {tolerance}" if tolerance is not None else ""
        )
        return self._passive(command + suffix, CheckResult)

    def check_cell_voltage(self, spread_mv: int | None = None) -> CheckResult:
        """Compare cell-voltage spread using ``tvolt [spread-mV]``."""
        if spread_mv is not None:
            bounded(spread_mv, "Voltage spread", 0, 99999999)
        return self._passive(
            "tvolt" + (f" {spread_mv}" if spread_mv is not None else ""), CheckResult
        )

    def check_cell_temperature(self, spread_mc: int | None = None) -> CheckResult:
        """Compare cell-temperature spread using ``ttmp [spread-mC]``."""
        if spread_mc is not None:
            bounded(spread_mc, "Temperature spread", 0, 99999999)
        return self._passive(
            "ttmp" + (f" {spread_mc}" if spread_mc is not None else ""), CheckResult
        )

    def check_dip_switch(self, expected: int) -> CheckResult:
        """Compare the DIP switch with ``tdip expected`` (0–15)."""
        bounded(expected, "DIP switch", 0, 15)
        return self._passive(f"tdip {expected}", CheckResult)

    def check_input(self, condition: str) -> CheckResult:
        """Read ``tinput rv|dcov``; output-driving present/absent forms are excluded."""
        choice(condition, "Input condition", frozenset({"rv", "dcov"}))
        return self._passive(f"tinput {condition}", CheckResult)

    def check_ibc_inputs(self, expected: str) -> CheckResult:
        """Compare SLAVED/HOSTED/DCIN via passive ``tibcio nc|sc``."""
        choice(expected, "Expected inputs", frozenset({"nc", "sc"}))
        return self._passive(f"tibcio {expected}", CheckResult)

    def check_cbn_inputs(self, expected: str) -> CheckResult:
        """Compare SLAVED/HOSTED via passive ``tcbnio nc|sc``."""
        choice(expected, "Expected inputs", frozenset({"nc", "sc"}))
        return self._passive(f"tcbnio {expected}", CheckResult)

    def check_version(self, expected: int) -> CheckResult:
        """Compare hexadecimal software version with ``tver`` (C only)."""
        bounded(expected, "Version", 0, 0xFFFFFFFF)
        return self._passive(f"tver {expected:x}", CheckResult)

    def communication_info(self) -> CommunicationResult:
        """Read communication state with ``ci``."""
        return self._passive("ci", CommunicationResult, addressed=False)

    def unit_baud_rate(self) -> CommunicationResult:
        """Read the unit/RS485 rate using bare ``urates``; not the console baud rate."""
        return self._passive("urates", CommunicationResult, addressed=False)

    def inverter_protocol(self) -> CommunicationResult:
        """Read the inverter protocol with bare ``setprt``."""
        return self._passive("setprt", CommunicationResult, addressed=False)

    def lg_configuration(self) -> CommunicationResult:
        """Read customer/system CAN-ID state with bare ``lg``."""
        return self._passive("lg", CommunicationResult, addressed=False)

    def nominal_capacity(self) -> CapacityResult:
        """Read configured nominal capacity with bare ``totalcoul`` (mAh on wire)."""
        return self._passive("totalcoul", CapacityResult, addressed=False)

    def cycle_statistics(self) -> CapacityResult:
        """Read cycle count and real coulomb bookkeeping with bare ``tcycle``."""
        return self._passive("tcycle", CapacityResult, addressed=False)

    def empty_voltage(self) -> CapacityResult:
        """Read the cell-voltage SOC clamp threshold with bare ``emptyvolt``."""
        return self._passive("emptyvolt", CapacityResult, addressed=True)

    def low_soc_configuration(self) -> CapacityResult:
        """Read shutdown SOC and delay with bare ``setlowcfg``."""
        return self._passive("setlowcfg", CapacityResult, addressed=False)

    def protection_status(self) -> ConfigurationResult:
        """Read protection enable state with bare ``prot``."""
        return self._passive("prot", ConfigurationResult, addressed=True)

    def automatic_switch_status(self) -> ConfigurationResult:
        """Read the automatic-switch marker with bare ``autoswitch``."""
        return self._passive("autoswitch", ConfigurationResult, addressed=False)

    def blocking_soc(self) -> CapacityResult:
        """Read the block-current SOC setting with bare ``blocksoc`` (C only)."""
        return self._passive("blocksoc", CapacityResult, addressed=False)

    def lifetime_statistics(self) -> AccountingResult:
        """Read lifetime accounting with bare local ``euro``; no clear/address form."""
        return self._passive("euro", AccountingResult, addressed=False)

    def self_discharge_state(self) -> AccountingResult:
        """Read self-discharge estimation state with bare ``eurostub``."""
        return self._passive("eurostub", AccountingResult, addressed=False)

    def aging_voltage_history(self) -> AccountingResult:
        """Read stored aging-voltage extrema and samples with ``trdagevolt``."""
        return self._passive("trdagevolt", AccountingResult, addressed=False)

    def manufacturing_time(self) -> ClockResult:
        """Read the stored manufacturing/test timestamp with bare ``cmudtesttime``."""
        return self._passive("cmudtesttime", ClockResult, addressed=False)

    def soh_diagnostics(self) -> AccountingResult:
        """Read per-cell SOH diagnostic state with ``soh``; not a health percentage. E2 may reject it."""
        return self._passive("soh", AccountingResult, addressed=True)

    def ina_registers(self) -> RegisterResult:
        """Read the INA register report with ``inash`` (E2 only)."""
        return self._passive("inash", RegisterResult, addressed=False)

    def ina_calibration(self) -> ConfigurationResult:
        """Read coefficient/offset/mode with bare ``inacal`` (E2 only); no calibration action."""
        return self._passive("inacal", ConfigurationResult, addressed=False)

    def current_calibration(self) -> ConfigurationResult:
        """Read stored coefficient and offset with bare ``currcal`` (E2 only)."""
        return self._passive("currcal", ConfigurationResult, addressed=False)

    def gauge_registers(self) -> RegisterResult:
        """Read the gauge register report with ``socsh`` (C only)."""
        return self._passive("socsh", RegisterResult, addressed=False)

    def gauge_data(self) -> MeasurementResult:
        """Read gauge measurements with bare ``socd`` (C only); preserve printed scaling."""
        return self._passive("socd", MeasurementResult, addressed=False)

    def gauge_resistance_table(self) -> RegisterResult:
        """Read chemistry ID and resistance-table information with bare ``soct`` (C only)."""
        return self._passive("soct", RegisterResult, addressed=False)

    def gauge_configuration(self) -> ConfigurationResult:
        """Read the named gauge data-flash descriptor report with bare ``soccfg`` (C only)."""
        return self._passive("soccfg", ConfigurationResult, addressed=False)

    def check_environment_temperature(self) -> CheckResult:
        """Compare cached temperature sensors with ``tetmp``; no output controls."""
        return self._passive("tetmp", CheckResult, addressed=False)

    def check_pack_voltage(self) -> CheckResult:
        """Read the cached pack-voltage comparison with ``tpwr`` (C only)."""
        return self._passive("tpwr", CheckResult, addressed=False)

    def check_soh_events(self) -> CheckResult:
        """Read the SOH-event count comparison with ``tsoh`` (C only)."""
        return self._passive("tsoh", CheckResult, addressed=False)

    def check_system_faults(self) -> CheckResult:
        """Read cached system faults with ``tsto`` (C only); does not drive outputs."""
        return self._passive("tsto", CheckResult, addressed=False)

    def check_aging_voltage(self) -> CheckResult:
        """Compare the EEPROM aged minimum voltage with ``tagevolt`` (C only)."""
        return self._passive("tagevolt", CheckResult, addressed=False)
