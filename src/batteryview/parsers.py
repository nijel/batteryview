"""Parsers use labels and column headers, rather than .NET variable lookbehinds."""

import re
from dataclasses import replace

from .errors import ProtocolError
from .models import Alarm, CellReading, DeviceInfo, ModuleReading

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
        states=states,
        alarms=_alarms(states, "module"),
        raw=row,
    )


def parse_pwr(text: str) -> list[ModuleReading]:
    rows = parse_table(text)
    if not rows:
        raise ProtocolError("pwr response has no recognizable module table", response=text)
    return [module_from_row(row) for row in rows]


def parse_getpwr(text: str, *, address: int | None = None) -> ModuleReading:
    # RegoutConfig.xml: first 8 '#' fields are module values, followed by cells
    # with four fields each. Use complete cell lines to avoid interpreting trailers.
    cells = []
    trailer_start = None
    line_end = 0
    for line in text.splitlines(keepends=True):
        line_end += len(line)
        match = re.fullmatch(r"\s*(-?\d+)#\s+(-?\d+)#\s+(\w+)#\s+([\w ]+)#\s*", line)
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
        error_code = integer(trailer[0]) if trailer else None
        cycles = integer(trailer[1]) if len(trailer) > 1 else None
        module = replace(module, error_code=error_code, cycle_count=cycles)
        if error_code is not None and error_code >= 0:
            for bit in range(error_code.bit_length()):
                if error_code & (1 << bit):
                    code = ERROR_BITS[bit] if bit < len(ERROR_BITS) else f"Unknown error bit {bit}"
                    alarms.append(
                        Alarm(
                            "module.error_code",
                            code,
                            "error" if bit < len(ERROR_BITS) else "unknown",
                        )
                    )
    for cell in cells:
        alarms.extend(_alarms(cell.states, "cell", cell.index))
    return replace(module, cells=cells, alarms=alarms)


def recommended_currents(text: str) -> tuple[float | None, float | None]:
    fields = {k.lower(): v for k, v in key_values(text).items()}
    charge = fields.get("recommend chg current", fields.get("advise charge current"))
    discharge = fields.get("recommend dsg current", fields.get("advise discharge current"))
    return number(charge, 1000), number(discharge, 1000)
