"""Errors carry partial responses so failed collections remain useful."""


class BatteryViewError(Exception):
    """Base class for user-facing errors."""


class ProtocolError(BatteryViewError):
    """The device returned an unexpected or malformed response."""

    def __init__(self, message: str, *, response: str = ""):
        super().__init__(message)
        self.response = response


class ConnectionError(ProtocolError):
    """Cannot open or use the console transport."""


class CommandTimeout(ProtocolError):
    """A command did not reach a recognized response boundary."""


class CommandCancelled(ProtocolError):
    """Collection was interrupted; any received text is retained."""


class UnsupportedCommand(ProtocolError):
    """The console rejected a command."""


class ResetRecoveryError(BatteryViewError):
    """A reset was interrupted; consult the saved recovery state before continuing."""

    def __init__(self, message: str, *, recovery_path: str):
        super().__init__(message)
        self.recovery_path = recovery_path
