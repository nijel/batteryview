"""Typed passive console results, retaining unmodified firmware evidence."""

from dataclasses import dataclass, field
from datetime import datetime

from .models import CellReading, ConsoleReadResult, ModuleReading, SystemReading

Scalar = int | float | str


@dataclass(frozen=True)
class Quantity:
    """A number and its firmware-reported unit, without inferred scaling."""

    value: int | float
    unit: str


@dataclass(frozen=True)
class ParsedReadResult(ConsoleReadResult):
    """Typed labeled values and table rows alongside the original reply.

    Unknown strings remain strings. Quantities retain the printed unit. Lines
    without a recognized label/table remain in ``unparsed_lines`` and ``text``.
    """

    values: dict[str, Scalar] = field(default_factory=dict)
    quantities: dict[str, Quantity] = field(default_factory=dict)
    masks: dict[str, int] = field(default_factory=dict)
    rows: list[dict[str, Scalar]] = field(default_factory=list)
    unparsed_lines: list[str] = field(default_factory=list)


@dataclass(frozen=True)
class CommunicationResult(ParsedReadResult):
    """Communication settings, help, or one buffered frame."""

    baud_rate: int | None = None
    protocol: str | None = None
    frame: bytes | None = None


@dataclass(frozen=True)
class MeasurementResult(ParsedReadResult):
    """Normalized readings; absent measurements are not replaced with zero."""

    modules: list[ModuleReading] = field(default_factory=list)
    cells: list[CellReading] = field(default_factory=list)
    system: SystemReading | None = None


@dataclass(frozen=True)
class StatisticsResult(ParsedReadResult):
    """Reported counters and percentages, without interpreting them as diagnoses."""

    counters: dict[str, int] = field(default_factory=dict)
    cycle_count: int | None = None
    soh_pct: float | None = None
    soc_pct: float | None = None


@dataclass(frozen=True)
class ClockResult(ParsedReadResult):
    """Battery-local time without an assumed timezone; raw text remains available."""

    timestamp: datetime | None = None


@dataclass(frozen=True)
class ConfigurationResult(ParsedReadResult):
    """Query results, preserving enum spellings and quantities with printed units."""

    enabled: bool | None = None


@dataclass(frozen=True)
class CapacityResult(ParsedReadResult):
    """Capacity bookkeeping and small settings in explicitly named units."""

    nominal_capacity_ah: float | None = None
    cycle_count: int | None = None
    empty_voltage_v: float | None = None
    shutdown_soc_pct: float | None = None
    shutdown_delay_s: int | None = None
    blocking_soc_pct: float | None = None


@dataclass(frozen=True)
class AccountingResult(ParsedReadResult):
    """Lifetime, self-discharge, per-cell SOH state, and aging evidence.

    These values do not share a universal health-percentage or counter mapping.
    Only explicit units are decoded; unfamiliar fields and rows remain available.
    """

    timestamps: dict[str, datetime] = field(default_factory=dict)


@dataclass(frozen=True)
class StorageResult(ParsedReadResult):
    """A complete byte dump at a logical storage offset, not an MCU address."""

    chip: int = 0
    offset: int = 0
    data: bytes = b""


@dataclass(frozen=True)
class RegisterResult(ParsedReadResult):
    """Register report with hexadecimal addresses and integer values."""

    registers: dict[int, int] = field(default_factory=dict)


@dataclass(frozen=True)
class Record:
    """One recorded observation; timestamps have no inferred timezone."""

    index: int
    timestamp: datetime | None = None
    voltage_v: float | None = None
    current_a: float | None = None
    temperature_c: float | None = None
    soc_pct: float | None = None
    cells: list[CellReading] = field(default_factory=list)
    fields: dict[str, str] = field(default_factory=dict)
    values: dict[str, Scalar] = field(default_factory=dict)
    raw: str = ""


@dataclass(frozen=True)
class RecordsResult(ParsedReadResult):
    """Individual/default record or fully consumed list, retaining every page."""

    kind: str = "event"
    records: list[Record] = field(default_factory=list)
    indices: list[int] = field(default_factory=list)


@dataclass(frozen=True)
class CheckResult(ParsedReadResult):
    """A passive firmware comparison; console completion does not imply a pass."""

    passed: bool | None = None
