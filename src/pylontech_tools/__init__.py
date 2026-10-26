"""Portable Pylontech console library."""

import logging

from .client import BatteryClient
from .doctor import analyze_logs
from .errors import (
    CommandCancelled,
    CommandTimeout,
    ConnectionError,
    DeviceBusyError,
    DeviceNotPresentError,
    ProtocolError,
    PylontechError,
    ResetRecoveryError,
    UnsupportedCommand,
)
from .models import (
    Alarm,
    CellReading,
    CollectionResult,
    ConsoleReadResult,
    DeviceInfo,
    DoctorBattery,
    DoctorFinding,
    DoctorReport,
    ModuleReading,
    ReportResult,
    Snapshot,
    SystemReading,
)

logging.getLogger(__name__).addHandler(logging.NullHandler())

__all__ = [
    "Alarm",
    "analyze_logs",
    "DoctorBattery",
    "DoctorFinding",
    "DoctorReport",
    "BatteryClient",
    "PylontechError",
    "CellReading",
    "CollectionResult",
    "CommandTimeout",
    "CommandCancelled",
    "ConnectionError",
    "DeviceBusyError",
    "DeviceNotPresentError",
    "ConsoleReadResult",
    "DeviceInfo",
    "ModuleReading",
    "ProtocolError",
    "ReportResult",
    "ResetRecoveryError",
    "Snapshot",
    "SystemReading",
    "UnsupportedCommand",
]
