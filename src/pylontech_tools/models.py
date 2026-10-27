"""Public results. Raw console values remain available alongside normalized readings."""

from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any


@dataclass(frozen=True)
class DeviceInfo:
    """Device identity and firmware fields returned by the console."""

    address: int | None = None
    name: str | None = None
    barcode: str | None = None
    cell_count: int | None = None
    fields: dict[str, str] = field(default_factory=dict)


@dataclass(frozen=True)
class Alarm:
    """An alarm code and its source, severity, and optional cell index."""

    source: str
    code: str
    severity: str
    cell: int | None = None


@dataclass(frozen=True)
class CellReading:
    """Normalized measurements and states for one cell."""

    index: int
    voltage_v: float | None = None
    current_a: float | None = None
    temperature_c: float | None = None
    soc_pct: float | None = None
    states: dict[str, str] = field(default_factory=dict)
    raw: dict[str, str] = field(default_factory=dict)


@dataclass(frozen=True)
class ModuleReading:
    """Normalized module measurements, cell readings, and alarms."""

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
    """Measurements and current recommendations for the battery system."""

    current_a: float | None = None
    voltage_v: float | None = None
    recommended_charge_a: float | None = None
    recommended_discharge_a: float | None = None


@dataclass(frozen=True)
class Snapshot:
    """A timestamped set of module readings and raw console responses."""

    timestamp: str
    modules: list[ModuleReading]
    raw_responses: dict[str, str] = field(default_factory=dict)
    system: SystemReading | None = None

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True)
class ReportResult:
    """An exported transcript, its record count, and recovery information."""

    path: Path
    kind: str
    records: int | None
    responses: int
    complete: bool = True
    recovery_path: Path | None = None


@dataclass(frozen=True)
class CollectionResult:
    """Support collection paths and whether all collection steps completed."""

    directory: Path
    manifest_path: Path
    complete: bool


@dataclass(frozen=True)
class ConsoleReadResult:
    """A diagnostic read with its complete response and unscaled labeled fields."""

    command: str
    text: str
    fields: dict[str, str] = field(default_factory=dict)


@dataclass(frozen=True)
class DiagnosticReadResult:
    """One combined diagnostic read: complete, unavailable, or failed."""

    command: str
    status: str
    text: str = ""
    fields: dict[str, str] = field(default_factory=dict)
    error: dict[str, str] | None = None
    context: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class DiagnosticsReport:
    """Ordered read-only diagnostic evidence; unavailable reads are optional."""

    timestamp: str
    complete: bool
    reads: list[DiagnosticReadResult]


@dataclass(frozen=True)
class DoctorFinding:
    """A screening finding supported by named input observations."""

    code: str
    severity: str
    message: str
    evidence: list[str] = field(default_factory=list)
    certainty: str = "observed"
    details: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class DoctorBattery:
    """Health screening of one identified battery or isolated unidentified input."""

    key: str
    identity: dict[str, Any]
    status: str
    metrics: dict[str, Any]
    findings: list[DoctorFinding]
    limitations: list[str]


@dataclass(frozen=True)
class DoctorReport:
    """Versioned doctor output; findings do not certify physical battery health."""

    status: str
    batteries: list[DoctorBattery]
    input_issues: list[dict[str, str]] = field(default_factory=list)
    imbalance_mv: int = 100
    schema_version: int = 1
    rules_version: int = 2

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    @property
    def exit_code(self) -> int:
        if self.status == "unusable":
            return 2
        return 0 if self.status == "no_issues_detected" else 1
