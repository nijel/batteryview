"""Read-only doctor acquisition; saved evidence is also the offline input format."""

from __future__ import annotations

import tempfile
from dataclasses import asdict
from datetime import datetime, timezone
from pathlib import Path
from typing import TYPE_CHECKING
from uuid import uuid4

from .collection import _write_json, _write_manifest
from .doctor import analyze_logs, validate_threshold
from .errors import CommandCancelled, ProtocolError, PylontechError
from .models import DoctorReport

if TYPE_CHECKING:
    from .client import BatteryClient


def acquire_doctor(
    client: BatteryClient, *, save_inputs: str | Path | None = None, imbalance_mv: int = 100
) -> DoctorReport:
    validate_threshold(imbalance_mv)
    client._direct_only("Doctor")
    with client.session.lock:
        if save_inputs is None:
            with tempfile.TemporaryDirectory(prefix="pylontech-doctor-") as temporary:
                return _acquire(client, Path(temporary), imbalance_mv)
        directory = Path(save_inputs)
        directory.mkdir(parents=True, exist_ok=True)
        return _acquire(client, directory, imbalance_mv)


def _acquire(client: BatteryClient, directory: Path, threshold: int) -> DoctorReport:
    started = datetime.now(timezone.utc)
    run_id = f"{started:%Y%m%dT%H%M%SZ}_{uuid4().hex}"
    steps = [
        {"name": name, "status": "pending", "artifact": None, "records": None, "error": None}
        for name in (
            "identity",
            "snapshot",
            "statistics",
            "clock",
            "configuration",
            "diagnostic_log",
            "history",
            "event",
        )
    ]
    manifest = {
        "format_version": 1,
        "kind": "doctor",
        "run_id": run_id,
        "started_at": started.isoformat(),
        "finished_at": None,
        "status": "running",
        "complete": False,
        "device": None,
        "steps": steps,
    }
    manifest_path = directory / f"{run_id}_doctor_manifest.json"
    _write_manifest(manifest_path, manifest, create=True)
    old_mode = client.monitoring_mode
    client.monitoring_mode = "single"
    stopped = False
    artifact: Path | None = None
    try:
        for step in steps:
            if stopped:
                step["status"] = "skipped"
                continue
            name = step["name"]
            artifact = None
            step["status"] = "running"
            _write_manifest(manifest_path, manifest)
            suffix = ".txt.txt" if name in {"history", "event"} else ".json"
            artifact = directory / f"{run_id}_{name}{suffix}"
            try:
                if name in {"history", "event"}:
                    result = (client.export_history if name == "history" else client.export_events)(
                        artifact
                    )
                    step["records"] = result.records
                else:
                    method = {
                        "identity": client.info,
                        "snapshot": client.snapshot,
                        "statistics": client.statistics,
                        "clock": client.read_clock,
                        "configuration": client.configuration,
                        "diagnostic_log": client.diagnostic_log,
                    }[name]
                    result = method()
                    _write_json(
                        artifact,
                        result.to_console_dict()
                        if name in {"statistics", "clock", "configuration", "diagnostic_log"}
                        else asdict(result),
                    )
                    if name == "identity":
                        manifest["device"] = asdict(result)
                step.update(status="complete", artifact=artifact.name)
            except (PylontechError, ValueError) as exc:
                if isinstance(exc, CommandCancelled):
                    raise
                step.update(
                    status="failed", error={"type": type(exc).__name__, "message": str(exc)}
                )
                if artifact.is_file():
                    step["artifact"] = artifact.name
                elif isinstance(exc, ProtocolError) and exc.response:
                    partial = directory / f"{run_id}_{name}_partial.txt"
                    with partial.open("x", encoding="utf-8", newline="") as stream:
                        stream.write(exc.response)
                    step["artifact"] = partial.name
                session = client.session
                if not (session.synchronized and session.current_prompt == "pylon_debug>"):
                    try:
                        response = session.resynchronize(timeout=max(client.timeout, 15))
                        recovery = directory / f"{run_id}_{name}_resync.txt"
                        with recovery.open("x", encoding="utf-8", newline="") as stream:
                            stream.write(response.text)
                        step["recovery_artifact"] = recovery.name
                        stopped = response.prompt != "pylon_debug>"
                    except ProtocolError:
                        stopped = True
            _write_manifest(manifest_path, manifest)
        complete = all(step["status"] == "complete" for step in steps)
        manifest.update(
            status="complete" if complete else "failed",
            complete=complete,
            finished_at=datetime.now(timezone.utc).isoformat(),
        )
        _write_manifest(manifest_path, manifest)
    except (KeyboardInterrupt, CommandCancelled) as exc:
        active = next((step for step in steps if step["status"] == "running"), None)
        if active:
            active.update(
                status="interrupted",
                error={"type": type(exc).__name__, "message": "Acquisition interrupted"},
            )
            if artifact is not None and artifact.is_file():
                active["artifact"] = artifact.name
            elif isinstance(exc, ProtocolError) and exc.response:
                partial = directory / f"{run_id}_{active['name']}_partial.txt"
                with partial.open("x", encoding="utf-8", newline="") as stream:
                    stream.write(exc.response)
                active["artifact"] = partial.name
        for step in steps:
            if step["status"] == "pending":
                step["status"] = "skipped"
        manifest.update(
            status="interrupted", complete=False, finished_at=datetime.now(timezone.utc).isoformat()
        )
        _write_manifest(manifest_path, manifest)
        raise
    finally:
        client.monitoring_mode = old_mode
    return analyze_logs(manifest_path, imbalance_mv=threshold)
