"""Errors carry partial responses so failed collections remain useful."""


class PylontechError(Exception):
    """Base class for user-facing errors."""


class ProtocolError(PylontechError):
    """The device returned an unexpected or malformed response."""

    def __init__(self, message: str, *, response: str = "", context: dict | None = None):
        super().__init__(message)
        self.response = response
        self.context = context or {}


class ConnectionError(ProtocolError):
    """Cannot open or use the console transport."""


class CommandTimeout(ProtocolError):
    """A command did not reach a recognized response boundary."""


class CommandCancelled(ProtocolError):
    """Collection was interrupted; any received text is retained."""


class UnsupportedCommand(ProtocolError):
    """The console rejected a command."""


class DeviceBusyError(ProtocolError):
    """The target module cannot currently handle the request."""


class DeviceNotPresentError(ProtocolError):
    """The requested module is not present."""


class ResetRecoveryError(PylontechError):
    """A reset was interrupted; consult the saved recovery state before continuing."""

    def __init__(self, message: str, *, recovery_path: str):
        super().__init__(message)
        self.recovery_path = recovery_path
