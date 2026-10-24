"""Parsers use labels and column headers, rather than .NET variable lookbehinds."""

import logging
import re
from dataclasses import replace

from .errors import ProtocolError
from .models import Alarm, CellReading, DeviceInfo, ModuleReading
from .profiles import MonitoringProfile

logger = logging.getLogger(__name__)

PWR_STATUS_LABELS = {
    "Base State": "Base.St",
    "Volt. State": "Volt.St",
    "Curr. State": "Curr.St",
    "Tempr. State": "Temp.St",
    "Temp. State": "Temp.St",
    "Basic Status": "Base.St",
    "Volt Status": "Volt.St",
    "Current Status": "Curr.St",
    "Tmpr. Status": "Temp.St",
    "Coul. Status": "Coul.St",
    "Soh. Status": "Soh.St",
    "Heater Status": "H.St",
}

ERROR_BITS = [
    "Input RV",
    "Input DCOV",
    "Hardware Version Err",
    "BMIC ERR",
    "HIB ERR",
    "Tempr Sensor ERR",
    "Volt Sensor ERR",
    "I2C ERR",
    "Addr Allocation ERR",
    "InternalComm ERR",
    "Chg MOS Fail",
    "DSG MOS Fail",
]


def key_values(text: str) -> dict[str, str]:
    values = {}
    for line in text.splitlines():
        match = re.fullmatch(r"\s*([\w .()/-]+?)\s*:\s*(.*?)\s*", line)
        if match:
            values[match[1].strip()] = match[2]
    return values


def number(value: str | None, scale: float = 1) -> float | None:
    if value is None:
        return None
    match = re.fullmatch(r"\s*(-?\d+(?:\.\d+)?)\s*(?:%|mV|mA|mC|mAH|mAh)?\s*", value)
    return float(match[1]) / scale if match else None


def integer(value: str | None) -> int | None:
    numeric = number(value)
    return int(numeric) if numeric is not None and numeric.is_integer() else None


def parse_info(text: str) -> DeviceInfo:
    fields = key_values(text)
    if not fields.get("Device name"):
        raise ProtocolError("info response has no device name", response=text)
    return DeviceInfo(
        address=integer(fields.get("Device address")),
        name=fields.get("Device name"),
        barcode=fields.get("Barcode") or None,
        cell_count=integer(fields.get("Cell Number")),
        fields=fields,
    )


def record_count(stat: str, kind: str) -> int:
    label = "HisData Items" if kind == "history" else "Data Items"
    count = integer(key_values(stat).get(label))
    if count is None or count < 0:
        raise ProtocolError(f"stat response has no valid {label!r} count", response=stat)
    return count


def parse_table(text: str) -> list[dict[str, str]]:
    """Parse pwr and cell tables, preserving firmware-specific columns by name."""
    header: list[str] | None = None
    rows = []
    for line in text.splitlines():
        line = line.strip()
        if re.match(r"^(?:Power|No|Battery)\s+Volt", line):
            for old, new in [
                ("Base State", "Base.St"),
                ("Volt. State", "Volt.St"),
                ("Curr. State", "Curr.St"),
                ("Temp. State", "Temp.St"),
            ]:
                line = line.replace(old, new)
            header = line.split()
            continue
        if header and re.match(r"^\d+\s", line):
            tokens = line.split()
            # The Time column includes both date and clock time on some firmware.
            if "Time" in header:
                index = header.index("Time")
                if len(tokens) > index + 1 and re.fullmatch(r"\d+-\d+-\d+", tokens[index]):
                    tokens[index : index + 2] = [" ".join(tokens[index : index + 2])]
            row = dict(zip(header, tokens))
            for i, token in enumerate(tokens[len(header) :]):
                row[f"extra_{i}"] = token
            rows.append(row)
    return rows


def _states(row: dict[str, str]) -> dict[str, str]:
    return {key: val for key, val in row.items() if key.endswith(".St") or key.endswith(".State")}


def _alarms(states: dict[str, str], source: str, cell: int | None = None) -> list[Alarm]:
    warnings = {"High", "Low", "COCAlm", "DOCAlm"}
    faults = {"OV", "UV", "Sleep", "COC2", "COC", "DOC2", "DOC", "SC", "OT", "UT"}
    result = []
    for field, value in states.items():
        for code in re.split(r"[ ,|/]+", value):
            if code not in {"Normal", "Idle", "Charge", "Dischg", "ON", "OFF", ""}:
                severity = (
                    "warning" if code in warnings else "error" if code in faults else "unknown"
                )
                result.append(Alarm(f"{source}.{field}", code, severity, cell))
    return result


def module_from_row(row: dict[str, str]) -> ModuleReading:
    states = _states(row)
    return ModuleReading(
        address=integer(row.get("Power", row.get("No"))),
        voltage_v=number(row.get("Volt"), 1000),
        current_a=number(row.get("Curr"), 1000),
        temperature_c=number(row.get("Tempr"), 1000),
        soc_pct=number(row.get("Coulomb")),
        min_cell_voltage_v=number(row.get("Vlow", row.get("Vlowest")), 1000),
        max_cell_voltage_v=number(row.get("Vhigh", row.get("Vhighest")), 1000),
        min_cell_temperature_c=number(row.get("Tlow"), 1000),
        max_cell_temperature_c=number(row.get("Thigh"), 1000),
        states=states,
        alarms=_alarms(states, "module"),
        raw=row,
    )


def parse_pwr(text: str) -> list[ModuleReading]:
    rows = parse_table(text)
    if rows:
        logger.debug("Parsed pwr format=table module_count=%d", len(rows))
        modules = [module_from_row(row) for row in rows]
        if any(m.address is None or m.voltage_v is None for m in modules):
            raise ProtocolError("pwr table has no recognizable address or voltage", response=text)
        return modules

    # A directly connected module may report a labeled summary rather than a
    # rack table. 'Power N' identifies that module, not the number of modules.
    lines = text.splitlines()
    headers = []
    for index, line in enumerate(lines):
        match = re.fullmatch(r"\s*Power\s+([0-9]+)\s*", line)
        if match:
            headers.append((index, match[1]))
    if not headers:
        raise ProtocolError(
            "pwr response has no recognizable module table or labeled summary", response=text
        )
    modules = []
    for block, (start, address) in enumerate(headers):
        end = headers[block + 1][0] if block + 1 < len(headers) else len(lines)
        fields = key_values("\n".join(lines[start + 1 : end]))
        voltage = number(fields.get("Voltage"), 1000)
        if voltage is None:
            raise ProtocolError("Labeled pwr summary has no recognizable voltage", response=text)
        states = {key: fields[label] for label, key in PWR_STATUS_LABELS.items() if label in fields}
        modules.append(
            ModuleReading(
                address=int(address),
                voltage_v=voltage,
                current_a=number(fields.get("Current"), 1000),
                temperature_c=number(fields.get("Temperature"), 1000),
                soc_pct=number(fields.get("Coulomb")),
                capacity_ah=number(fields.get("Total Coulomb"), 1000),
                states=states,
                alarms=_alarms(states, "module"),
                raw={**fields, "Power": address},
            )
        )
    logger.debug("Parsed pwr format=labeled module_count=%d", len(modules))
    return modules


def parse_getpwr(
    text: str, *, address: int | None = None, profile: MonitoringProfile | None = None
) -> ModuleReading:
    # RegoutConfig.xml: first 8 '#' fields are module values, followed by cells
    # with four fields each. Use complete cell lines to avoid interpreting trailers.
    cells = []
    trailer_start = None
    line_end = 0
    for line in text.splitlines(keepends=True):
        line_end += len(line)
        match = re.fullmatch(
            r"\s*(-?\d+)#\s+(-?\d+)#\s+([A-Za-z][\w ]*)#\s+([A-Za-z][\w ]*)#\s*", line
        )
        if match:
            trailer_start = line_end
            states = {"Volt.St": match[3], "Temp.St": match[4].strip()}
            cells.append(
                CellReading(
                    index=len(cells),
                    voltage_v=int(match[1]) / 1000,
                    temperature_c=int(match[2]) / 1000,
                    states=states,
                    raw={"Volt": match[1], "Tempr": match[2], **states},
                )
            )
    tokens = re.findall(r"(-?\d+|[A-Za-z][\w -]*)\s*#", text)
    if len(tokens) >= 8 and all(number(t) is not None for t in tokens[:4]):
        states = dict(zip(["Base.St", "Volt.St", "Curr.St", "Temp.St"], tokens[4:8]))
        raw = dict(zip(["Volt", "Curr", "Tempr", "Capacity"], tokens[:4]))
        # Retain the complete hash sequence, including unknown firmware trailers.
        raw.update({f"hash_{i}": token for i, token in enumerate(tokens)})
        module = ModuleReading(
            address=address,
            voltage_v=number(tokens[0], 1000),
            current_a=number(tokens[1], 1000),
            temperature_c=number(tokens[2], 1000),
            capacity_ah=number(tokens[3], 1000),
            states=states,
            raw=raw,
        )
    else:
        fields = key_values(text)
        module = ModuleReading(
            address=address,
            voltage_v=number(fields.get("Voltage"), 1000),
            current_a=number(fields.get("Current"), 1000),
            temperature_c=number(fields.get("Temperature"), 1000),
            capacity_ah=number(fields.get("Total Coulomb"), 1000),
            soc_pct=number(fields.get("Percent", fields.get("Coulomb"))),
            states={
                key: fields[label] for label, key in PWR_STATUS_LABELS.items() if label in fields
            },
            error_code=_code(fields.get("System Fault", fields.get("Error Code"))),
            cycle_count=integer(fields.get("Cycle Count")),
            raw=fields,
        )
        for row in parse_table(text):
            states = _states(row)
            index = integer(row.get("Battery"))
            if index is not None:
                cells.append(
                    CellReading(
                        index=index,
                        voltage_v=number(row.get("Volt"), 1000),
                        current_a=number(row.get("Curr"), 1000),
                        temperature_c=number(row.get("Tempr"), 1000),
                        soc_pct=number(row.get("Coulomb")),
                        states=states,
                        raw=row,
                    )
                )
    if module.voltage_v is None and not cells:
        raise ProtocolError("getpwr response has no recognizable readings", response=text)
    alarms = _alarms(module.states, "module")
    # After the contiguous cell block the configured parser reads error code,
    # then cycle count. Do not infer either if that trailer is absent.
    if trailer_start is not None:
        trailer = re.findall(r"(-?\d+)\s*#", text[trailer_start:])
        if profile and profile.trailer_from_end:
            trailer = trailer[-2:]
        error_code = integer(trailer[0]) if trailer else None
        cycles = integer(trailer[1]) if len(trailer) > 1 else None
        module = replace(module, error_code=error_code, cycle_count=cycles)
    if module.error_code is not None and module.error_code >= 0:
        for bit in range(module.error_code.bit_length()):
            if module.error_code & (1 << bit):
                code = ERROR_BITS[bit] if bit < len(ERROR_BITS) else f"Unknown error bit {bit}"
                alarms.append(
                    Alarm(
                        "module.error_code", code, "error" if bit < len(ERROR_BITS) else "unknown"
                    )
                )
    for cell in cells:
        alarms.extend(_alarms(cell.states, "cell", cell.index))
    extrema = {}
    for field, suffix in (("voltage_v", "voltage"), ("temperature_c", "temperature")):
        available = [c for c in cells if getattr(c, field) is not None]
        for prefix, select in (("min", min), ("max", max)):
            if available:
                cell = select(available, key=lambda c: getattr(c, field))
                extrema[f"{prefix}_cell_{field}"] = getattr(cell, field)
                extrema[f"{prefix}_cell_{suffix}_index"] = cell.index
    return replace(module, cells=cells, alarms=alarms, **extrema)


def recommended_currents(text: str, *, system: bool = False) -> tuple[float | None, float | None]:
    fields = {k.lower(): v for k, v in key_values(text).items()}
    if system:
        fields = {
            k.removeprefix("system "): v for k, v in fields.items() if k.startswith("system ")
        }
    charge = fields.get("recommend chg current", fields.get("advise charge current"))
    discharge = fields.get("recommend dsg current", fields.get("advise discharge current"))
    return number(charge, 1000), number(discharge, 1000)


def record_indices(text: str, *, detailed: bool = False) -> list[int]:
    """Read indices without treating cell rows or command echoes as records."""
    labeled = [
        int(m) for m in re.findall(r"(?:^|[\r\n])\s*(?:Rec\s+)?Item Index\s*:\s*(\d+)", text)
    ]
    if detailed or labeled:
        return labeled
    return [int(m) for m in re.findall(r"(?:^|[\r\n])\s*(\d+)\s+\d+-\d+-\d+\s+\d+:\d+:\d+", text)]


def _code(value: str | None) -> int | None:
    if value is None:
        return None
    match = re.match(r"\s*(0[xX][0-9a-fA-F]+|\d+)\b", value)
    return int(match[1], 16 if match[1].lower().startswith("0x") else 10) if match else None


def parse_recommended_currents(
    text: str, *, system: bool = False
) -> tuple[float | None, float | None]:
    values = recommended_currents(text)
    system_values = recommended_currents(text, system=True)
    if all(value is None for value in (*values, *system_values)):
        raise ProtocolError(
            "pwrsys response has no recognizable recommended currents", response=text
        )
    return system_values if system else values
