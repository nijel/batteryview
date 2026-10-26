"""Read local diagnostic evidence without serial I/O or filename-based identities."""

from __future__ import annotations

import json
import math
import os
import re
from dataclasses import dataclass, field, replace
from datetime import datetime
from pathlib import Path
from typing import Any

from .errors import ProtocolError
from .models import CellReading, DeviceInfo, ModuleReading
from .parsers import integer, key_values, number, parse_getpwr, parse_info
from .profiles import monitoring_profile

MAX_INPUT_BYTES = 64 * 1024 * 1024
COMMAND = re.compile(
    r"^(?:pylon(?:_debug)?>)?[ \t]*"
    r"((?:info|stat|getpwr|pwr|pwrsys|config)(?:[ \t]+\d+)?|"
    r"time|log(?:[ \t]+\d+)?|(?:data|datalist)[ \t]+(?:history|event|misc)"
    r"(?:[ \t]+(?:dtls|\d+))*|eepe(?:[ \t]+\d+)?|trst|tbar[ \t]+\S+)"
    r"[ \t]*$",
    re.M,
)
INDEX = re.compile(r"^[ \t]*(?:Rec[ \t]+)?Item Index[ \t]*:[ \t]*(\d+)", re.M)
STAMP = re.compile(r"\b(\d{2}|\d{4})-(\d{2})-(\d{2})[ T](\d{2}):(\d{2}):(\d{2})\b")


def reject_json_constant(value: str) -> None:
    raise ValueError("Nonfinite JSON number")


def battery_time(text: str | None) -> str | None:
    """Battery two-digit years are 2000–2099; no timezone is inferred."""
    match = STAMP.search(text or "")
    if not match:
        return None
    parts = [int(value) for value in match.groups()]
    if parts[0] < 100:
        parts[0] += 2000
    try:
        return datetime(*parts).isoformat()
    except ValueError:
        return None


def host_time(value: object) -> str | None:
    if not isinstance(value, str):
        return None
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
        return parsed.isoformat() if parsed.tzinfo is not None else None
    except ValueError:
        return None


@dataclass
class Observation:
    module: ModuleReading
    source: str
    kind: str
    timestamp: str | None = None
    acquired_at: str | None = None
    index: int | None = None
    epoch: str = "normal"
    complete: bool = True
    masks: dict[str, str] = field(default_factory=dict)
    summary_min_v: float | None = None
    summary_max_v: float | None = None
    live: bool = False


@dataclass
class BatteryEvidence:
    key: str
    identity: DeviceInfo | None = None
    observations: list[Observation] = field(default_factory=list)
    clocks: list[tuple[str, str, str | None]] = field(default_factory=list)
    reset_seen: bool = False
    statistics: list[tuple[dict[str, str], str, str | None]] = field(default_factory=list)
    sources: set[str] = field(default_factory=set)
    limitations: list[str] = field(default_factory=list)

    @property
    def nominal_ah(self) -> float | None:
        specification = self.identity.fields.get("Specification", "") if self.identity else ""
        match = re.search(r"(?:^|[/\s])([0-9]+(?:\.[0-9]+)?)\s*AH\b", specification, re.I)
        return float(match[1]) if match and float(match[1]) > 0 else None


class EvidenceReader:
    def __init__(self, path: str | Path):
        self.path = Path(path)
        if self.path.is_symlink():
            raise ValueError("Doctor inputs must not be symbolic links")
        if not self.path.exists():
            raise ValueError("Doctor input does not exist")
        self.root = (self.path if self.path.is_dir() else self.path.parent).resolve()
        self.batteries: dict[str, BatteryEvidence] = {}
        self.issues: list[dict[str, str]] = []
        self.contexts: dict[Path, list[dict]] = {}
        self.loaded: dict[Path, Any] = {}
        self.visited: set[Path] = set()
        self.profile: str | None = None

    def source(self, path: Path) -> str:
        return path.relative_to(self.root).as_posix()

    def issue(self, source: str, code: str, message: str) -> None:
        self.issues.append({"source": source, "code": code, "message": message})

    def bucket(self, identity: DeviceInfo | None, source: str, suffix: str = "") -> BatteryEvidence:
        key = (
            f"barcode:{identity.barcode}"
            if identity and identity.barcode
            else f"unidentified:{source}{suffix}"
        )
        if key not in self.batteries:
            self.batteries[key] = BatteryEvidence(key, identity)
        bucket = self.batteries[key]
        if identity:
            if bucket.identity and bucket.identity.name != identity.name:
                self.issue(
                    source, "identity_conflict", "Conflicting model names for the same barcode"
                )
                bucket.limitations.append(
                    "Conflicting model names; model-specific conclusions withheld."
                )
            elif bucket.identity is None or len(identity.fields) > len(bucket.identity.fields):
                bucket.identity = identity
        bucket.sources.add(source.split("#")[0])
        if not identity or not identity.barcode:
            if (
                "No verified barcode; this input is isolated from other batteries."
                not in bucket.limitations
            ):
                bucket.limitations.append(
                    "No verified barcode; this input is isolated from other batteries."
                )
        return bucket

    def read(self) -> list[BatteryEvidence]:
        if self.path.is_dir():
            paths = []
            for directory, dirs, names in os.walk(self.root, followlinks=False):
                dirs[:] = sorted(
                    d
                    for d in dirs
                    if not d.startswith(".") and not (Path(directory) / d).is_symlink()
                )
                paths.extend(
                    Path(directory) / n
                    for n in sorted(names)
                    if not n.startswith(".")
                    and Path(n).suffix.lower() in {".json", ".txt"}
                    and not (Path(directory) / n).is_symlink()
                )
        else:
            paths = [self.path.resolve()]
        # Manifests associate files before any observations are parsed.
        for path in paths:
            if path.suffix.lower() == ".json":
                value = self.load_json(path)
                if self.is_manifest(value):
                    self.manifest(path, value)
        for path in sorted(set(paths) | set(self.contexts)):
            if path not in self.visited:
                self.read_file(path, explicit=not self.path.is_dir())
        for item in self.batteries.values():
            valid = []
            for obs in item.observations:
                numeric = [
                    getattr(obs.module, name)
                    for name in ("voltage_v", "current_a", "temperature_c", "soc_pct")
                ]
                numeric += [c.voltage_v for c in obs.module.cells] + [
                    c.temperature_c for c in obs.module.cells
                ]
                numeric += [obs.summary_min_v, obs.summary_max_v]
                if any(value is not None and not math.isfinite(value) for value in numeric):
                    self.issue(obs.source, "invalid_measurement", "Nonfinite measurement omitted")
                else:
                    valid.append(obs)
            item.observations = valid
        return list(self.batteries.values())

    @staticmethod
    def is_manifest(value: Any) -> bool:
        return isinstance(value, dict) and "steps" in value and "format_version" in value

    def load_json(self, path: Path) -> Any:
        if path not in self.loaded:
            try:
                if path.stat().st_size > MAX_INPUT_BYTES:
                    raise ValueError("Input exceeds 64 MiB limit")
                self.loaded[path] = json.loads(
                    path.read_text(encoding="utf-8-sig"),
                    parse_constant=reject_json_constant,
                )
            except (OSError, ValueError, UnicodeError, RecursionError):
                self.loaded[path] = None
        return self.loaded[path]

    def manifest(self, path: Path, value: dict) -> None:
        self.visited.add(path)
        source = self.source(path)
        if (
            type(value.get("format_version")) is not int
            or value.get("format_version") != 1
            or not isinstance(value.get("steps"), list)
        ):
            self.issue(source, "invalid_manifest", "Unsupported or malformed collection manifest")
            return
        device = self.identity(value.get("device"))
        acquired = host_time(value.get("started_at"))
        bucket = self.bucket(device, source)
        if value.get("complete") is not True:
            bucket.limitations.append(f"Incomplete collection: {source}")
            self.issue(source, "incomplete_collection", "Collection did not complete")
        inferred = None
        conflicting_identity = False
        for step in value["steps"]:
            if not isinstance(step, dict):
                self.issue(source, "invalid_manifest", "Invalid manifest step")
                continue
            artifact = step.get("artifact")
            if not artifact:
                if step.get("status") != "complete":
                    self.issue(
                        source,
                        "unavailable_read",
                        f"Read unavailable: {step.get('name', 'unknown')}",
                    )
                continue
            if not isinstance(artifact, str):
                self.issue(source, "unsafe_artifact", "Artifact path is not a string")
                continue
            raw = path.parent / artifact
            try:
                resolved = raw.resolve()
                relative = raw.absolute().relative_to(self.root)
                if (
                    Path(artifact).is_absolute()
                    or ".." in relative.parts
                    or not resolved.is_relative_to(self.root)
                ):
                    raise ValueError
                if any(
                    (self.root.joinpath(*relative.parts[:i])).is_symlink()
                    for i in range(1, len(relative.parts) + 1)
                ):
                    raise ValueError
            except (ValueError, OSError, RuntimeError):
                self.issue(
                    source,
                    "unsafe_artifact",
                    "Artifact reference escapes input directory or uses a symbolic link",
                )
                continue
            if step.get("name") == "identity":
                candidate = self.identity(self.load_json(resolved))
                if candidate and candidate.barcode:
                    if device and device.barcode and device.barcode != candidate.barcode:
                        conflicting_identity = True
                    elif not device or not device.barcode:
                        inferred = candidate
            context = {
                "identity": device,
                "acquired_at": acquired,
                "step": step.get("name"),
                "complete": step.get("status") == "complete",
                "manifest": source,
            }
            self.contexts.setdefault(resolved, []).append(context)

        if inferred:
            old_bucket = bucket
            device = inferred
            bucket = self.bucket(device, source)
            bucket.limitations.extend(old_bucket.limitations)
            if (
                old_bucket.key != bucket.key
                and old_bucket.sources == {source}
                and not old_bucket.observations
                and not old_bucket.statistics
            ):
                self.batteries.pop(old_bucket.key, None)
        if conflicting_identity:
            self.issue(
                source,
                "identity_conflict",
                "Manifest and its identity artifact disagree; observations remain isolated",
            )
        for contexts in self.contexts.values():
            for context in contexts:
                if context["manifest"] == source:
                    context["identity"] = device
                    if conflicting_identity:
                        context["isolate"] = True

    @staticmethod
    def identity(value: Any) -> DeviceInfo | None:
        if not isinstance(value, dict) or not isinstance(value.get("name"), str):
            return None
        barcode = value.get("barcode")
        fields = value.get("fields", {})
        address, count = value.get("address"), value.get("cell_count")
        return DeviceInfo(
            address if type(address) is int else None,
            value["name"],
            barcode if isinstance(barcode, str) and barcode else None,
            count if type(count) is int and count > 0 else None,
            {str(k): str(v) for k, v in fields.items()} if isinstance(fields, dict) else {},
        )

    def read_file(self, path: Path, *, explicit: bool) -> None:
        source = self.source(path)
        contexts = self.contexts.get(path, [])
        identities = {
            c["identity"].barcode for c in contexts if c["identity"] and c["identity"].barcode
        }
        if len(identities) > 1:
            self.issue(
                source,
                "identity_conflict",
                "Several batteries claim this artifact; association withheld",
            )
            context = {"isolate": True}
        else:
            context = dict(contexts[0]) if contexts else {}
        try:
            if path.stat().st_size > MAX_INPUT_BYTES:
                raise ValueError("Input exceeds 64 MiB limit")
            if path.suffix.lower() == ".json":
                value = self.load_json(path)
                if value is None:
                    if (
                        not explicit
                        and not contexts
                        and not any(
                            tag in path.stem
                            for tag in (
                                "_manifest",
                                "_info",
                                "_snapshot",
                                "_statistics",
                                "_clock",
                                "_configuration",
                                "_diagnostic_log",
                            )
                        )
                    ):
                        return
                    raise ValueError("Malformed or undecodable JSON")
                if self.is_manifest(value):
                    self.manifest(path, value)
                elif not self.json_input(value, source, context) and (explicit or contexts):
                    raise ValueError(
                        "Unsupported JSON input; expected identity, snapshot, or console read"
                    )
            elif path.suffix.lower() == ".txt":
                data = path.read_bytes()
                encoding = "utf-16" if data.startswith((b"\xff\xfe", b"\xfe\xff")) else "utf-8-sig"
                text = data.decode(encoding)
                if not self.text_input(text, source, context) and (explicit or contexts):
                    raise ValueError("No recognizable battery evidence in text input")
            elif explicit:
                raise ValueError("Unsupported doctor input format")
        except (OSError, ValueError, UnicodeError, TypeError, KeyError, OverflowError) as exc:
            self.issue(source, "input_error", str(exc))

    def json_input(self, value: Any, source: str, context: dict) -> bool:
        if not isinstance(value, dict):
            return False
        identity = self.identity(value)
        if identity:
            if (
                context.get("identity")
                and identity.barcode
                and identity.barcode != context["identity"].barcode
            ):
                self.issue(source, "identity_conflict", "Embedded identity disagrees with manifest")
            self.bucket(None if context.get("isolate") else identity, source)
            return True
        if isinstance(value.get("modules"), list):
            acquired = host_time(value.get("timestamp")) or context.get("acquired_at")
            for i, item in enumerate(value["modules"]):
                if not isinstance(item, dict):
                    raise ValueError("Invalid snapshot module")
                module = self.json_module(item)
                identity = None if context.get("isolate") else context.get("identity")
                if len(value["modules"]) > 1 and (
                    not identity or identity.address != module.address
                ):
                    if identity:
                        local = self.bucket(identity, source)
                        local.limitations.append(
                            "Auxiliary rack entries without verified barcodes are not attributed to other batteries."
                        )
                        continue
                    identity = None
                bucket = self.bucket(identity, source, f":module-{i}")
                complete = self.cell_coverage(module, identity)
                masks = self.masks(module.raw)
                # Only hash-format error codes have the verified indicator bit mapping.
                if "System Fault" in module.raw:
                    module = replace(
                        module,
                        error_code=None,
                        alarms=[a for a in module.alarms if a.source != "module.error_code"],
                    )
                bucket.observations.append(
                    Observation(
                        module,
                        f"{source}#module-{i}",
                        "snapshot",
                        acquired_at=acquired,
                        complete=complete,
                        masks=masks,
                        summary_min_v=module.min_cell_voltage_v,
                        summary_max_v=module.max_cell_voltage_v,
                        live=True,
                    )
                )
            return True
        if isinstance(value.get("command"), str) and isinstance(value.get("text"), str):
            if not COMMAND.fullmatch(value["command"]):
                raise ValueError("Unsupported diagnostic command in JSON input")
            return self.text_input(value["text"], source, context, command=value["command"])
        return False

    @staticmethod
    def json_module(item: dict) -> ModuleReading:
        def numeric(value):
            if value is None:
                return None
            if type(value) not in {int, float} or not math.isfinite(value):
                raise ValueError("Invalid/nonfinite numeric snapshot measurement")
            return value

        names = (
            "voltage_v",
            "current_a",
            "temperature_c",
            "soc_pct",
            "capacity_ah",
            "min_cell_voltage_v",
            "max_cell_voltage_v",
            "min_cell_temperature_c",
            "max_cell_temperature_c",
        )
        values = {name: numeric(item.get(name)) for name in names}
        address = item.get("address")
        if address is not None and (type(address) is not int or not 1 <= address <= 16):
            raise ValueError("Invalid snapshot module address")
        cells = []
        for cell in item.get("cells", []):
            if (
                not isinstance(cell, dict)
                or type(cell.get("index")) is not int
                or cell["index"] < 0
            ):
                raise ValueError("Invalid snapshot cell index")
            cells.append(
                CellReading(
                    cell["index"],
                    **{n: numeric(cell.get(n)) for n in names[:4]},
                    states=string_map(cell.get("states", {})),
                    raw=string_map(cell.get("raw", {})),
                )
            )
        error, cycles = item.get("error_code"), item.get("cycle_count")
        for value in (error, cycles):
            if value is not None and (type(value) is not int or value < 0):
                raise ValueError("Invalid snapshot counter or error code")
        return ModuleReading(
            address=address,
            **values,
            cells=cells,
            states=string_map(item.get("states", {})),
            raw=string_map(item.get("raw", {})),
            error_code=error,
            cycle_count=cycles,
        )

    @staticmethod
    def cell_coverage(module: ModuleReading, identity: DeviceInfo | None) -> bool:
        indices = [cell.index for cell in module.cells]
        expected = identity.cell_count if identity else None
        return (
            bool(indices)
            and (expected is None or len(indices) == expected)
            and indices == list(range(len(indices)))
            and all(c.voltage_v is not None and c.voltage_v > 0 for c in module.cells)
        )

    @staticmethod
    def masks(fields: dict[str, str]) -> dict[str, str]:
        return {
            k: v
            for k, v in fields.items()
            if k in {"System Fault", "Power Events", "Bat Events", "SysErrCode", "ErrCode"}
        }

    def text_input(
        self, text: str, source: str, context: dict, *, command: str | None = None
    ) -> bool:
        text = text.replace("\r\n", "\n").replace("\r", "\n")
        frames = list(COMMAND.finditer(text)) if command is None else []
        parts = (
            [
                (
                    m[1],
                    text[m.end() : frames[i + 1].start() if i + 1 < len(frames) else len(text)],
                    m.start(),
                )
                for i, m in enumerate(frames)
            ]
            if frames
            else [(command or "unknown", text, 0)]
        )
        embedded = []
        for cmd, body, _ in parts:
            if cmd.startswith("info") or (cmd == "unknown" and "Device name" in body):
                try:
                    embedded.append(parse_info(body))
                except ProtocolError:
                    pass
        embedded_codes = {d.barcode for d in embedded if d.barcode}
        context_identity = context.get("identity")
        conflicts = (
            context.get("isolate", False)
            or len(embedded_codes) > 1
            or bool(
                context_identity
                and context_identity.barcode
                and embedded_codes
                and embedded_codes != {context_identity.barcode}
            )
        )
        if conflicts:
            self.issue(
                source,
                "identity_conflict",
                "Conflicting embedded battery identities; segments remain isolated",
            )
        identity = context_identity or (embedded[0] if embedded else None)
        if conflicts:
            identity = None
        acquired = context.get("acquired_at")
        epoch = "normal"
        recognized = False
        segment = 0
        reset_seen = False
        seen_records: dict[str, set[int]] = {}
        counters: dict[str, int] = {}
        for cmd, body, position in parts:
            ref = f"{source}#line-{text.count(chr(10), 0, position) + 1}"
            if cmd.split()[0] in {"eepe", "trst"}:
                epoch = ref
                reset_seen = True
                continue
            if cmd.startswith("info"):
                segment += 1
                try:
                    current = parse_info(body)
                    if not conflicts:
                        identity = current if current.barcode else identity or current
                except ProtocolError:
                    pass
                recognized = True
            bucket = self.bucket(
                None if conflicts else identity, source, f":segment-{segment}" if conflicts else ""
            )
            bucket.reset_seen |= reset_seen
            fields = key_values(body)
            if cmd.startswith("stat") or "HisData Items" in fields or "Data Items" in fields:
                bucket.statistics.append((fields, ref, acquired))
                for kind, label in (("history", "HisData Items"), ("event", "Data Items")):
                    count = integer(fields.get(label))
                    if count is not None and count >= 0:
                        counters[kind] = count
                recognized = True
            if cmd.startswith(("getpwr", "pwr")) and not cmd.startswith("pwrsys"):
                try:
                    model = parse_getpwr(
                        body,
                        address=identity.address if identity else None,
                        profile=monitoring_profile(
                            self.profile or (identity.name if identity else None)
                        ),
                    )
                    if "System Fault" in model.raw:
                        model = replace(
                            model,
                            error_code=None,
                            alarms=[a for a in model.alarms if a.source != "module.error_code"],
                        )
                    bucket.observations.append(
                        Observation(
                            model,
                            ref,
                            "snapshot",
                            acquired_at=acquired,
                            epoch=epoch,
                            complete=self.cell_coverage(model, identity),
                            masks=self.masks(fields),
                            live=True,
                        )
                    )
                    recognized = True
                except ProtocolError:
                    self.issue(ref, "unparseable_read", "Power response has no usable measurements")
            matches = list(INDEX.finditer(body))
            kind = "event" if "event" in cmd else "history" if "history" in cmd else "record"
            for i, match in enumerate(matches):
                block = body[
                    match.end() : matches[i + 1].start() if i + 1 < len(matches) else len(body)
                ]
                record_fields = key_values(block)
                try:
                    model = parse_getpwr(block)
                except ProtocolError:
                    self.issue(
                        ref, "incomplete_record", "Record lacks recognizable voltage/cell readings"
                    )
                    continue
                model = replace(
                    model,
                    error_code=None,
                    alarms=[a for a in model.alarms if a.source != "module.error_code"],
                )
                stamp = battery_time(record_fields.get("Time"))
                complete = (
                    self.cell_coverage(model, identity) and bool(stamp) and "Error!" not in block
                )
                bucket.observations.append(
                    Observation(
                        model,
                        f"{ref}:record-{match[1]}",
                        kind,
                        stamp,
                        acquired,
                        int(match[1]),
                        epoch,
                        complete,
                        self.masks(record_fields),
                    )
                )
                if not complete:
                    self.issue(
                        ref,
                        "incomplete_record",
                        "Detailed record is incomplete or has an invalid timestamp",
                    )
                seen_records.setdefault(kind, set()).add(int(match[1]))
                recognized = True
            # Summary and expanded-list records share timestamped scalar rows.
            for row_number, line in enumerate(body.splitlines()):
                match = re.match(
                    r"^\s*(\d+)\s+((?:\d{2}|\d{4})-\d{2}-\d{2})\s+(\d{2}:\d{2}:\d{2})\s+(.*)", line
                )
                if not match:
                    continue
                values = match[4].split()
                if len(values) < 3:
                    self.issue(ref, "incomplete_record", "Truncated summary record")
                    continue
                voltage, current, temperature = (number(v, 1000) for v in values[:3])
                low = number(values[5], 1000) if len(values) >= 7 else None
                high = number(values[6], 1000) if len(values) >= 7 else None
                pct = next((number(v) for v in values[7:] if v.endswith("%")), None)
                states = {"Base.St": values[7]} if len(values) > 7 else {}
                cells = expanded_cells(values, identity.cell_count if identity else None)
                if len(values) >= 12 and (values[11].endswith("%") or cells):
                    states.update(dict(zip(("Volt.St", "Curr.St", "Temp.St"), values[8:11])))
                model = ModuleReading(
                    voltage_v=voltage,
                    current_a=current,
                    temperature_c=temperature,
                    soc_pct=pct,
                    states=states,
                    cells=cells,
                )
                summary_masks = (
                    [v for v in values[12:] if re.fullmatch(r"0[xX][0-9a-fA-F]+", v)]
                    if not cells
                    else []
                )
                masks = {"SysErrCode": summary_masks[-1]} if summary_masks else {}
                if cells and re.fullmatch(r"0[xX][0-9a-fA-F]+", values[11]):
                    masks["ErrCode"] = values[11]
                stamp = battery_time(f"{match[2]} {match[3]}")
                complete = (
                    all(v is not None for v in (voltage, low, high))
                    and bool(stamp)
                    and low > 0
                    and high >= low
                )
                if "dtls" in cmd and len(values) > 15 and not cells:
                    complete = False
                if not complete:
                    self.issue(
                        ref,
                        "incomplete_record",
                        "List row is incomplete or has an invalid timestamp",
                    )
                bucket.observations.append(
                    Observation(
                        model,
                        f"{ref}:row-{row_number + 1}",
                        kind,
                        stamp,
                        acquired,
                        int(match[1]),
                        epoch,
                        complete,
                        masks,
                        low,
                        high,
                    )
                )
                seen_records.setdefault(kind, set()).add(int(match[1]))
                recognized = True
            if "Error!" in body:
                self.issue(ref, "corrupt_record", "Firmware reported a corrupt record")
            if cmd == "time":
                clock = battery_time(body)
                if clock:
                    bucket.clocks.append((clock, ref, acquired))
            if cmd in {"time", "config"} or cmd.startswith("log"):
                recognized = True
            if ("Invalid command" in body or "Unknown command" in body) and cmd != "unknown":
                self.issue(ref, "unsupported_read", f"Device rejected {cmd.split()[0]} read")
        if reset_seen:
            for item in self.batteries.values():
                if source in item.sources:
                    item.reset_seen = True
        if frames and not re.search(r"pylon(?:_debug)?>\s*$", text):
            self.issue(source, "truncated_exchange", "Text ends without a complete console prompt")
        for kind, indices in seen_records.items():
            expected = counters.get(kind)
            if expected is not None and (
                len(indices) != expected
                or min(indices, default=0) != 0
                or max(indices, default=-1) != expected - 1
            ):
                self.issue(
                    source,
                    "incomplete_coverage",
                    f"{kind} record coverage differs from its reported count",
                )
        if not context.get("complete", True):
            self.issue(
                source, "partial_artifact", "Artifact comes from an unfinished collection step"
            )
        return recognized or bool(embedded)


def string_map(value: object) -> dict[str, str]:
    if not isinstance(value, dict) or any(not isinstance(v, str) for v in value.values()):
        raise ValueError("Expected string-valued state/raw fields")
    return {str(k): v for k, v in value.items()}


def expanded_cells(values: list[str], expected: int | None) -> list[CellReading]:
    """Detailed rows have 15 scalar tokens, then six tokens per cell.

    The scalar prefix includes the recorded ErrCode; it has a different layout
    from the hash monitoring trailer. Cells are index/voltage/temperature/voltage-state/
    temperature-state/SOC. Consecutive zero- or one-based IDs are normalized to
    zero-based indices, retaining the device's original cell ID in raw fields.
    """
    if len(values) <= 15 or (len(values) - 15) % 6:
        return []
    count = (len(values) - 15) // 6
    if expected is not None and count != expected:
        return []
    cells = []
    base = integer(values[15])
    if base not in {0, 1}:
        return []
    for index in range(count):
        chunk = values[15 + index * 6 : 21 + index * 6]
        voltage, temperature, soc = number(chunk[1], 1000), number(chunk[2], 1000), number(chunk[5])
        if (
            chunk[0] != str(index + base)
            or voltage is None
            or not 0 < voltage < 10
            or temperature is None
            or soc is None
            or not chunk[5].endswith("%")
            or not all(re.fullmatch(r"[A-Za-z][\w.-]*", token) for token in chunk[3:5])
        ):
            return []
        cells.append(
            CellReading(
                index,
                voltage_v=voltage,
                current_a=number(values[1], 1000),
                temperature_c=temperature,
                soc_pct=soc,
                states={"Volt.St": chunk[3], "Temp.St": chunk[4]},
                raw={"reported_cell_id": chunk[0]},
            )
        )
    return cells
