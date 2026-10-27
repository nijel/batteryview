"""Conservative parsers for passive reads; unknown firmware output stays visible."""

import re
from datetime import datetime
from typing import TypeVar

from .errors import ProtocolError
from .models import CellReading, ConsoleReadResult, ModuleReading, SystemReading
from .parsers import (
    integer,
    key_values,
    number,
    parse_getpwr,
    parse_pwr,
    parse_table,
    recommended_currents,
)
from .read_models import (
    AccountingResult,
    CapacityResult,
    CheckResult,
    ClockResult,
    CommunicationResult,
    ConfigurationResult,
    MeasurementResult,
    ParsedReadResult,
    Quantity,
    Record,
    RecordsResult,
    RegisterResult,
    Scalar,
    StatisticsResult,
    StorageResult,
)

R = TypeVar("R", bound=ParsedReadResult)
UNITS = {"mV", "V", "mA", "A", "mC", "C", "°C", "mAH", "mAh", "AH", "Ah", "%", "s", "ms", "days"}
DATE = re.compile(r"(?<!\d)(\d{2}|\d{4})-(\d{2})-(\d{2})[ T](\d{2}):(\d{2}):(\d{2})(?!\d)")


def timestamp(text: str) -> datetime | None:
    """Read the console's 2000-based two-digit years; never assume a timezone."""
    match = DATE.search(text)
    if not match:
        return None
    year, month, day, hour, minute, second = map(int, match.groups())
    if len(match[1]) == 2:
        year += 2000
    try:
        return datetime(year, month, day, hour, minute, second)
    except ValueError:
        return None


def scalar(text: str) -> Scalar:
    value = text.strip()
    if re.fullmatch(r"[-+]?\d+", value):
        return int(value)
    if re.fullmatch(r"0[xX][0-9a-fA-F]+", value):
        return int(value, 16)
    if re.fullmatch(r"[-+]?\d+\.\d+", value):
        return float(value)
    return value


def common(result: ConsoleReadResult) -> dict:
    values = {}
    quantities = {}
    for label, value in result.fields.items():
        match = re.fullmatch(r"\s*([-+]?\d+(?:\.\d+)?)\s*([^\d\s]+)\s*", value)
        if match and match[2] in UNITS:
            parsed = scalar(match[1])
            values[label] = parsed
            quantities[label] = Quantity(parsed, match[2])
        else:
            values[label] = scalar(value)
    rows = [
        {label: scalar(value) for label, value in row.items()} for row in parse_table(result.text)
    ]
    lines = [
        line
        for line in result.text.splitlines()
        if line.strip()
        and line.strip()
        not in {
            result.command,
            "@",
            "$$",
            "Command completed successfully",
            "pylon_debug>",
            "pylon>",
        }
        and not re.fullmatch(r"[-\s]+", line)
        and not any(line.strip().startswith(label) and ":" in line for label in result.fields)
    ]
    return {
        "command": result.command,
        "text": result.text,
        "fields": result.fields,
        "values": values,
        "quantities": quantities,
        "masks": {
            label: int(match[1], 16)
            for label, value in result.fields.items()
            if (match := re.match(r"\s*(0[xX][0-9a-fA-F]+)\b", value))
        },
        "rows": rows,
        "unparsed_lines": lines,
    }


def parse_result(result: ConsoleReadResult, cls: type[R]) -> R:
    """Decode only known labels and layouts, preserving every original field."""
    data = common(result)
    values = data["values"]
    fields = result.fields
    command = result.command.split()[0]

    def numeric(*labels: str) -> int | float | None:
        for label in labels:
            value = values.get(label)
            if isinstance(value, (int, float)):
                return value
        return None

    def count(*labels: str) -> int | None:
        value = numeric(*labels)
        return value if type(value) is int else None

    if cls is StatisticsResult:
        data.update(
            counters={
                k: v
                for k, v in values.items()
                if type(v) is int and re.search(r"(?:Cnt|Count|Times|Items)\b", k, re.I)
            },
            cycle_count=count("CYCLE Times", "Cycle Times", "Cycle Count"),
            soh_pct=numeric("SOH"),
            soc_pct=numeric("Pwr Percent", "SOC"),
        )
    elif cls is ClockResult:
        data["timestamp"] = timestamp(result.text)
    elif cls is CapacityResult:
        capacity_labels = ("Total Coulomb", "TotalCoulomb", "Total Coul", "Capacity")
        capacity = numeric(*capacity_labels)
        if capacity is not None:
            unit = next(
                (
                    data["quantities"][key].unit
                    for key in capacity_labels
                    if key in data["quantities"]
                ),
                "mAh",
            )
            if unit in {"mAH", "mAh"}:
                data["nominal_capacity_ah"] = capacity / 1000
            elif unit in {"AH", "Ah"}:
                data["nominal_capacity_ah"] = capacity
        voltage_labels = ("Coul:0% Volt", "EmptyVolt", "Empty Voltage")
        voltage = numeric(*voltage_labels)
        voltage_unit = next(
            (data["quantities"][key].unit for key in voltage_labels if key in data["quantities"]),
            "mV",
        )
        if voltage is None and command == "emptyvolt":
            match = re.search(r"Coul:0% Volt\s*:\s*(\d+)", result.text)
            voltage = int(match[1]) if match else None
        voltage_v = None
        if voltage is not None and voltage_unit == "mV":
            voltage_v = voltage / 1000
        elif voltage is not None and voltage_unit == "V":
            voltage_v = voltage
        data.update(
            cycle_count=count("CYCLE Times", "Cycle Times", "Cycle Count", "Cycle"),
            empty_voltage_v=voltage_v,
            shutdown_soc_pct=numeric("ShutSoc"),
            shutdown_delay_s=count("ShutSocTime"),
            blocking_soc_pct=numeric("BlockSoc", "Block SOC"),
        )
    elif cls is ConfigurationResult:
        if command == "autoswitch":
            match = re.search(r"\b(ON|OFF)\b", result.text, re.I)
            data["enabled"] = match[1].upper() == "ON" if match else None
    elif cls is CommunicationResult:
        frame = fields.get("Frame")
        if frame and re.fullmatch(r"(?:[0-9a-fA-F]{2}\s*)+", frame):
            data["frame"] = bytes.fromhex(frame)
        if command == "urates":
            match = re.search(r"\b(9600|115200|500000)\b", result.text)
            data["baud_rate"] = int(match[1]) if match else None
        elif command == "setprt":
            match = re.search(r"\b(sma|lg)\b", "\n".join(fields.values()) or result.text, re.I)
            data["protocol"] = match[1].lower() if match else None
    elif cls is AccountingResult:
        data["timestamps"] = {k: t for k, v in fields.items() if (t := timestamp(v)) is not None}
    elif cls is CheckResult:
        outcomes = re.findall(r"\b(?:test\s+)?result\s*[:=]\s*(pass|fail)\b", result.text, re.I)
        data["passed"] = all(v.lower() == "pass" for v in outcomes) if outcomes else None
    elif cls is RegisterResult:
        registers = {}
        for line in result.text.splitlines():
            match = re.fullmatch(
                r"\s*(?:0x)?([0-9a-fA-F]{1,2})\s*[:=]\s*(?:0x)?([0-9a-fA-F]{1,4})\s*", line
            )
            if match:
                registers[int(match[1], 16)] = int(match[2], 16)
        if command in {"socr", "inar"} and not registers:
            match = re.search(r"(?:0x[0-9a-fA-F]+)\s*[:=]\s*(0x[0-9a-fA-F]+)", result.text)
            if match:
                registers[int(result.command.split()[1], 16)] = int(match[1], 16)
        data["registers"] = registers
    if cls is MeasurementResult and command == "socd":
        data["modules"] = [
            ModuleReading(
                voltage_v=number(fields.get("Voltage"), 1000),
                current_a=number(fields.get("Current"), 1000),
                soc_pct=number(fields.get("SOC")),
                capacity_ah=number(fields.get("Remaining Capacity"), 1000),
                raw=fields,
            )
        ]
    return cls(**data)


def cells(text: str) -> list[CellReading]:
    result = []
    for row in parse_table(text):
        index = integer(row.get("Battery"))
        if index is None:
            continue
        result.append(
            CellReading(
                index=index,
                voltage_v=number(row.get("Volt"), 1000),
                current_a=number(row.get("Curr"), 1000),
                temperature_c=number(row.get("Tempr"), 1000),
                soc_pct=number(row.get("Coulomb")),
                states={k: v for k, v in row.items() if ".St" in k},
                raw=row,
            )
        )
    return result


def measurements(result: ConsoleReadResult, *, address=None, profile=None) -> MeasurementResult:
    data = common(result)
    command = result.command.split()[0]
    if command == "pwr":
        data["modules"] = parse_pwr(result.text)
    elif command == "getpwr":
        data["modules"] = [parse_getpwr(result.text, address=address, profile=profile)]
    elif command == "bat":
        data["cells"] = cells(result.text)
        if not data["cells"]:
            raise ProtocolError("bat response has no recognizable cells", response=result.text)
    elif command == "pwrsys":
        # Keep known explicitly labeled recommendations without requiring a particular model.
        charge, discharge = recommended_currents(result.text, system=True)
        local_charge, local_discharge = recommended_currents(result.text)
        data["system"] = SystemReading(
            recommended_charge_a=charge if charge is not None else local_charge,
            recommended_discharge_a=discharge if discharge is not None else local_discharge,
        )
    return MeasurementResult(**data)


def storage(result: ConsoleReadResult, chip: int, offset: int, size: int) -> StorageResult:
    """Require a contiguous, complete dump; never fill missing bytes with zero."""
    output = bytearray()
    for line in result.text.splitlines():
        match = re.match(r"\s*(?:0x)?([0-9a-fA-F]+)\s*:\s*(.*)", line)
        if not match:
            continue
        address = int(match[1], 16)
        if address != offset + len(output):
            raise ProtocolError(
                "Storage dump has a missing or repeated address", response=result.text
            )
        # Eight bytes per row; ASCII columns are separated by pipes or wider spacing.
        payload = re.split(r"\s{2,}|\|", match[2].strip())[0]
        tokens = payload.split()
        if not tokens or any(not re.fullmatch(r"[0-9a-fA-F]{2}", v) for v in tokens):
            raise ProtocolError("Malformed storage dump row", response=result.text)
        output.extend(int(v, 16) for v in tokens)
    if len(output) != size:
        raise ProtocolError("Storage dump byte count differs from request", response=result.text)
    return StorageResult(**common(result), chip=chip, offset=offset, data=bytes(output))


def records(result: ConsoleReadResult, kind: str, indices: list[int]) -> RecordsResult:
    """Decode individual records and common list rows; retain unknown layouts."""
    output = []
    blocks = list(re.finditer(r"(?:^|[\r\n])\s*(?:Rec\s+)?Item Index\s*:\s*(\d+)", result.text))
    if blocks:
        for position, match in enumerate(blocks):
            end = blocks[position + 1].start() if position + 1 < len(blocks) else len(result.text)
            raw = result.text[match.start() : end]
            fields = key_values(raw)
            output.append(
                Record(
                    index=int(match[1]),
                    timestamp=timestamp(fields.get("Time", "")),
                    voltage_v=number(fields.get("Voltage"), 1000),
                    current_a=number(fields.get("Current"), 1000),
                    temperature_c=number(fields.get("Temperature"), 1000),
                    soc_pct=number(fields.get("Percent")),
                    cells=cells(raw),
                    fields=fields,
                    values=common(ConsoleReadResult(result.command, raw, fields))["values"],
                    raw=raw,
                )
            )
    else:
        for line in result.text.splitlines():
            match = re.match(r"^\s*(\d+)\s+(\d{2}-\d{2}-\d{2}\s+\d{2}:\d{2}:\d{2})\s+(.*)", line)
            if not match:
                continue
            tokens = match[3].split()
            # Field-selector output differs from summary/detail output; don't assign its
            # numbers to module voltage/current unless a module-list header is present.
            summary = bool(re.search(r"\bVo\(mV\)\s+Cu\(mA\)", result.text))
            output.append(
                Record(
                    index=int(match[1]),
                    timestamp=timestamp(match[2]),
                    voltage_v=number(tokens[0], 1000) if summary and len(tokens) > 0 else None,
                    current_a=number(tokens[1], 1000) if summary and len(tokens) > 1 else None,
                    temperature_c=number(tokens[2], 1000) if summary and len(tokens) > 2 else None,
                    values={f"column_{i}": scalar(v) for i, v in enumerate(tokens)},
                    raw=line,
                )
            )
    return RecordsResult(**common(result), kind=kind, records=output, indices=indices)
