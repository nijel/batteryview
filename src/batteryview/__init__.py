"""Portable Pylontech console library."""

import logging

from .client import BatteryClient
from .errors import (
    BatteryViewError,
    CommandCancelled,
    CommandTimeout,
    ConnectionError,
    ProtocolError,
    ResetRecoveryError,
    UnsupportedCommand,
)
from .models import Alarm, CellReading, DeviceInfo, ModuleReading, ReportResult, Snapshot

logging.getLogger(__name__).addHandler(logging.NullHandler())

__all__ = [
    "Alarm",
    "BatteryClient",
    "BatteryViewError",
    "CellReading",
    "CommandTimeout",
    "CommandCancelled",
    "ConnectionError",
    "DeviceInfo",
    "ModuleReading",
    "ProtocolError",
    "ReportResult",
    "ResetRecoveryError",
    "Snapshot",
    "UnsupportedCommand",
]
