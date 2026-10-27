"""A fixed set of verified bare read forms, with no user-supplied operands."""

from datetime import datetime, timezone
from typing import TYPE_CHECKING

from .errors import CommandCancelled, PylontechError, UnsupportedCommand
from .models import DiagnosticReadResult, DiagnosticsReport

if TYPE_CHECKING:
    from .client import BatteryClient

COMMANDS = (
    "stat",
    "time",
    "log",
    "config",
    "totalcoul",
    "tcycle",
    "emptyvolt",
    "setlowcfg",
    "ctrl",
    "prot",
    "euro",
    "trdagevolt",
    "soh",
)


def read_diagnostics(client: "BatteryClient") -> DiagnosticsReport:
    """Keep completed evidence and stop on failures other than unsupported reads."""
    client._direct_only("Combined diagnostics")
    with client.session.lock:
        client.last_failure = None
        timestamp = datetime.now(timezone.utc).isoformat()
        reads = []
        for command in COMMANDS:
            try:
                result = client._diagnostic_read(command)
            except (KeyboardInterrupt, CommandCancelled):
                raise
            except (PylontechError, OSError, ValueError) as exc:
                optional = isinstance(exc, UnsupportedCommand)
                reads.append(
                    DiagnosticReadResult(
                        command,
                        "unavailable" if optional else "failed",
                        text=getattr(exc, "response", ""),
                        error={"type": type(exc).__name__, "message": str(exc)},
                        context=getattr(exc, "context", {}),
                    )
                )
                if not optional:
                    client.last_failure = exc
                    return DiagnosticsReport(timestamp, False, reads)
            else:
                reads.append(DiagnosticReadResult(command, "complete", result.text, result.fields))
        return DiagnosticsReport(timestamp, any(r.status == "complete" for r in reads), reads)


def format_diagnostics(report: DiagnosticsReport) -> str:
    """Separate command responses without truncating their original contents."""
    parts = [
        f"Battery diagnostics: {'complete' if report.complete else 'incomplete'}\n"
        f"Acquired: {report.timestamp}\n"
    ]
    for read in report.reads:
        parts.append(f"\n[{read.command}]\n")
        if read.status == "unavailable":
            parts.append("Unavailable: command not supported by this firmware.\n")
            continue
        if read.status == "failed":
            parts.append(f"Failed: {read.error['message']}\n")
        parts.append(read.text)
        if read.text and not read.text.endswith("\n"):
            parts.append("\n")
    return "".join(parts)
