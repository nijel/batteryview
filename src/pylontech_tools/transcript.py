"""The vendor report is console response text, not a table regenerated from data."""

import codecs
import os
import re
from datetime import datetime
from pathlib import Path


def filename_serial(barcode: str | None) -> str:
    """Make a barcode safe for a filename without treating it as verified identity."""
    return re.sub(r"[^a-zA-Z0-9_+-]", "_", barcode or "UnknownSN")


def report_filename(barcode: str | None, kind: str, *, now: datetime | None = None) -> str:
    if kind not in {"history", "event", "resetsoc"}:
        raise ValueError(f"Unknown report kind: {kind}")
    serial = filename_serial(barcode)
    timestamp = (now or datetime.now()).strftime("%Y%m%d%H%M%S")
    middle = "resetsoc " if kind == "resetsoc" and barcode else kind
    return f"{serial}_{middle}_{timestamp}.txt"


class TranscriptWriter:
    """Exclusive creation prevents accidental mixing of two report sessions."""

    def __init__(self, path: str | Path):
        self.path = Path(path)
        self._file = self.path.open("xb")
        self._file.write(codecs.BOM_UTF16_LE)
        self._file.flush()
        self.responses = 0

    def append(self, text: str) -> None:
        self._file.write((text + "\r\n").encode("utf-16-le"))
        self._file.flush()
        self.responses += 1

    def sync(self) -> None:
        self._file.flush()
        os.fsync(self._file.fileno())

    def close(self) -> None:
        self._file.close()

    def __enter__(self) -> "TranscriptWriter":
        return self

    def __exit__(self, *args: object) -> None:
        self.close()
