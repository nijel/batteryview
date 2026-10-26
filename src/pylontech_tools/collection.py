"""Fail-fast collection of a directly connected module into a shared directory."""

from __future__ import annotations

import json
import logging
import os
import tempfile
from dataclasses import asdict
from datetime import datetime, timezone
from importlib.metadata import PackageNotFoundError, version
from pathlib import Path
from typing import TYPE_CHECKING
from uuid import uuid4

from .errors import CommandCancelled, PylontechError
from .models import CollectionResult
from .transcript import filename_serial

if TYPE_CHECKING:
    from .client import BatteryClient, Progress

logger = logging.getLogger(__name__)


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _application_version() -> str:
    try:
        return version("pylontech-tools")
    except PackageNotFoundError:
        return "unknown"


def _write_json(path: Path, data: object) -> None:
    """Create one artifact exclusively; keep any partial write on failure."""
    payload = json.dumps(data, indent=2, ensure_ascii=False) + "\n"
    with path.open("x", encoding="utf-8", newline="\n") as stream:
        stream.write(payload)
        stream.flush()


def _write_manifest(path: Path, data: dict, *, create: bool = False) -> None:
    """Replace only this run's manifest atomically; never touch another run."""
    if create:
        _write_json(path, data)
        return
    temporary = None
    try:
        with tempfile.NamedTemporaryFile(
            mode="w",
            encoding="utf-8",
            newline="\n",
            dir=path.parent,
            prefix=f".{path.stem}_",
            suffix=".tmp",
            delete=False,
        ) as stream:
            temporary = Path(stream.name)
            json.dump(data, stream, indent=2, ensure_ascii=False)
            stream.write("\n")
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary, path)
    finally:
        if temporary is not None:
            temporary.unlink(missing_ok=True)


def _record_failure(path: Path, manifest: dict, index: int, exc: BaseException) -> bool:
    interrupted = isinstance(exc, (KeyboardInterrupt, CommandCancelled))
    step = manifest["steps"][index]
    step["status"] = "interrupted" if interrupted else "failed"
    step["error"] = {"type": type(exc).__name__, "message": str(exc)}
    for remaining in manifest["steps"][index + 1 :]:
        remaining["status"] = "skipped"
    manifest.update(
        status="interrupted" if interrupted else "failed", complete=False, finished_at=_now()
    )
    _write_manifest(path, manifest)
    logger.debug("Collection stopped step=%s error=%s", step["name"], type(exc).__name__)
    return interrupted


def _write_transition(path: Path, manifest: dict, index: int) -> None:
    try:
        _write_manifest(path, manifest)
    except (KeyboardInterrupt, CommandCancelled) as exc:
        _record_failure(path, manifest, index, exc)
        raise


def collect(
    client: BatteryClient, output: str | Path, *, progress: Progress | None
) -> CollectionResult:
    if client.module is not None:
        raise ValueError("collect requires a direct module connection; omit --module")
    # Access before creating files so an unconnected client does not leave a bundle.
    with client.session.lock:
        directory = Path(output)
        directory.mkdir(parents=True, exist_ok=True)
        started = datetime.now(timezone.utc)
        run_id = f"{started:%Y%m%dT%H%M%SZ}_{uuid4().hex}"
        steps = [
            {"name": name, "status": "pending", "artifact": None, "records": None, "error": None}
            for name in ("identity", "history", "event", "snapshot")
        ]
        manifest = {
            "format_version": 1,
            "application_version": _application_version(),
            "run_id": run_id,
            "started_at": started.isoformat(),
            "finished_at": None,
            "status": "running",
            "complete": False,
            "device": None,
            "steps": steps,
        }
        # Resolve the prefix once, before publishing any named artifacts. Retain
        # acquisition failures so they can be recorded in an UnknownSN manifest.
        identity = None
        identity_error = None
        try:
            logger.debug("Collection step start step=%s", "identity")
            if progress:
                progress("identity", 0, 1)
            identity = client.info()
        except (Exception, KeyboardInterrupt) as exc:
            identity_error = exc
        prefix = f"{filename_serial(identity.barcode if identity else None)}_{run_id}"
        manifest_path = directory / f"{prefix}_manifest.json"
        if identity is not None:
            manifest["device"] = asdict(identity)
        # Exclusive creation is outside the failure handler: a collision must
        # never lead to replacing a manifest belonging to a previous run.
        _write_manifest(manifest_path, manifest, create=True)
        for index, step in enumerate(steps):
            name = step["name"]
            step["status"] = "running"
            _write_transition(manifest_path, manifest, index)
            artifact = None
            try:
                if name != "identity":
                    logger.debug("Collection step start step=%s", name)
                if progress and name != "identity":
                    progress(name, 0, 1)
                if name == "identity":
                    if identity_error is not None:
                        raise identity_error
                    artifact = directory / f"{prefix}_info.json"
                    _write_json(artifact, asdict(identity))
                elif name in {"history", "event"}:
                    artifact = directory / f"{prefix}_{name}.txt"
                    export = client.export_history if name == "history" else client.export_events
                    report = export(artifact, progress=progress)
                    step["records"] = report.records
                else:
                    artifact = directory / f"{prefix}_snapshot.json"
                    _write_json(artifact, client.snapshot().to_dict())
                step["artifact"] = artifact.name
                if progress and name in {"identity", "snapshot"}:
                    progress(name, 1, 1)
            except (Exception, KeyboardInterrupt) as exc:
                # A collision belongs to an earlier run, never this step's partial output.
                if (
                    not isinstance(exc, FileExistsError)
                    and artifact is not None
                    and artifact.is_file()
                ):
                    step["artifact"] = artifact.name
                client.last_failure = exc
                interrupted = _record_failure(manifest_path, manifest, index, exc)
                if interrupted or not isinstance(exc, (PylontechError, OSError, ValueError)):
                    raise
                return CollectionResult(directory, manifest_path, False)
            step["status"] = "complete"
            logger.debug("Collection step complete step=%s", name)
            if index == len(steps) - 1:
                manifest.update(status="complete", complete=True, finished_at=_now())
            _write_transition(manifest_path, manifest, index)
        return CollectionResult(directory, manifest_path, True)
