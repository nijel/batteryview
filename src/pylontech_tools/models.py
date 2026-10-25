"""Public results. Raw console values remain available alongside normalized readings."""

from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any


@dataclass(frozen=True)
class DeviceInfo:
    address: int | None = None
    name: str | None = None
    barcode: str | None = None
    cell_count: int | None = None
    fields: dict[str, str] = field(default_factory=dict)


@dataclass(frozen=True)
class Alarm:
    source: str
    code: str
    severity: str
    cell: int | None = None


@dataclass(frozen=True)
class CellReading:
    index: int
    voltage_v: float | None = None
    current_a: float | None = None
    temperature_c: float | None = None
    soc_pct: float | None = None
    states: dict[str, str] = field(default_factory=dict)
    raw: dict[str, str] = field(default_factory=dict)


@dataclass(frozen=True)
class ModuleReading:
    address: int | None = None
    voltage_v: float | None = None
    current_a: float | None = None
    temperature_c: float | None = None
    soc_pct: float | None = None
    capacity_ah: float | None = None
    recommended_charge_a: float | None = None
    recommended_discharge_a: float | None = None
    error_code: int | None = None
    cycle_count: int | None = None
    states: dict[str, str] = field(default_factory=dict)
    cells: list[CellReading] = field(default_factory=list)
    alarms: list[Alarm] = field(default_factory=list)
    raw: dict[str, str] = field(default_factory=dict)
    min_cell_voltage_v: float | None = None
    max_cell_voltage_v: float | None = None
    min_cell_voltage_index: int | None = None
    max_cell_voltage_index: int | None = None
    min_cell_temperature_c: float | None = None
    max_cell_temperature_c: float | None = None
    min_cell_temperature_index: int | None = None
    max_cell_temperature_index: int | None = None


@dataclass(frozen=True)
class SystemReading:
    current_a: float | None = None
    voltage_v: float | None = None
    recommended_charge_a: float | None = None
    recommended_discharge_a: float | None = None


@dataclass(frozen=True)
class Snapshot:
    timestamp: str
    modules: list[ModuleReading]
    raw_responses: dict[str, str] = field(default_factory=dict)
    system: SystemReading | None = None

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True)
class ReportResult:
    path: Path
    kind: str
    records: int | None
    responses: int
    complete: bool = True
    recovery_path: Path | None = None


@dataclass(frozen=True)
class CollectionResult:
    directory: Path
    manifest_path: Path
    complete: bool
