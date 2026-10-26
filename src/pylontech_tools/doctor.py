"""Conservative, deterministic health screening shared by online and offline doctor."""

from __future__ import annotations

from collections import Counter, defaultdict
from dataclasses import replace
from datetime import datetime
from pathlib import Path

from .doctor_inputs import BatteryEvidence, EvidenceReader, Observation
from .faults import SYSTEM_FIELDS, decode_faults, describe_faults, fault_severity
from .models import DoctorBattery, DoctorFinding, DoctorReport, ModuleReading
from .parsers import integer

FAULT_STATES = {"SysError", "OV", "UV", "Sleep", "COC2", "COC", "DOC2", "DOC", "SC", "OT", "UT"}
WARNING_STATES = {"High", "Low", "COCAlm", "DOCAlm"}
NORMAL_STATES = {"Normal", "Idle", "Charge", "Dischg", "ON", "OFF", ""}


def validate_threshold(imbalance_mv: int) -> None:
    if type(imbalance_mv) is not int or imbalance_mv <= 0:
        raise ValueError("Imbalance threshold must be a positive integer in mV")


def spread(observation: Observation) -> tuple[int | None, int | None, int | None]:
    cells = [c for c in observation.module.cells if c.voltage_v is not None and c.voltage_v > 0]
    if len(cells) >= 2:
        low = min(cells, key=lambda c: c.voltage_v)
        high = max(cells, key=lambda c: c.voltage_v)
        return round(high.voltage_v * 1000) - round(low.voltage_v * 1000), low.index, high.index
    low, high = observation.summary_min_v, observation.summary_max_v
    if low is not None and high is not None and 0 < low <= high:
        return round(high * 1000) - round(low * 1000), None, None
    return None, None, None


def _conflicts(a: Observation, b: Observation) -> bool:
    for name in ("voltage_v", "current_a", "soc_pct"):
        x, y = getattr(a.module, name), getattr(b.module, name)
        if x is not None and y is not None and x != y:
            return True
    if a.module.cells and b.module.cells:
        return [(c.index, c.voltage_v) for c in a.module.cells] != [
            (c.index, c.voltage_v) for c in b.module.cells
        ]
    av, _, _ = spread(a)
    bv, _, _ = spread(b)
    return av is not None and bv is not None and av != bv


def _deduplicate(bucket: BatteryEvidence) -> list[Observation]:
    result: dict[tuple, Observation] = {}
    conflicts = set()
    for obs in bucket.observations:
        if obs.live:
            key = (
                (obs.kind, datetime.fromisoformat(obs.acquired_at))
                if obs.acquired_at
                else (obs.source.split("#")[0], obs.kind, obs.module.address)
            )
        else:
            key = (
                (obs.kind, obs.index, obs.timestamp, obs.epoch) if obs.timestamp else (obs.source,)
            )
        if key in result:
            old = result[key]
            # getpwr/pwr complement each other; timestamped record disagreements do not.
            if (
                not obs.live or old.source.split("#")[0] != obs.source.split("#")[0]
            ) and _conflicts(old, obs):
                conflicts.add(key)
                bucket.limitations.append(
                    f"Conflicting duplicate observation: {old.source}, {obs.source}"
                )
                continue
            richer, other = (
                (obs, old) if len(obs.module.cells) > len(old.module.cells) else (old, obs)
            )
            if obs.live:
                updates = {
                    name: getattr(other.module, name)
                    for name in ("voltage_v", "current_a", "soc_pct", "temperature_c")
                    if getattr(richer.module, name) is None
                }
                richer = replace(richer, module=replace(richer.module, **updates))
            result[key] = replace(richer, masks={**other.masks, **richer.masks})
        else:
            result[key] = obs
    return [
        replace(
            obs,
            module=ModuleReading(address=obs.module.address),
            complete=False,
            masks={},
            summary_min_v=None,
            summary_max_v=None,
        )
        if key in conflicts
        else obs
        for key, obs in result.items()
    ]


def _clock_issues(observations: list[Observation]) -> bool:
    groups = defaultdict(list)
    for obs in observations:
        if obs.timestamp and obs.index is not None:
            groups[(obs.source.split("#")[0], obs.kind, obs.epoch)].append(obs)
    return any(
        any(b.timestamp < a.timestamp for a, b in zip(ordered, ordered[1:]))
        for group in groups.values()
        for ordered in [sorted(group, key=lambda obs: obs.index)]
    )


def _last(observations: list[Observation], clock_unreliable: bool) -> Observation | None:
    live = [obs for obs in observations if obs.live]
    if live:
        dated = [obs for obs in live if obs.acquired_at]
        if dated:
            return max(dated, key=lambda obs: datetime.fromisoformat(obs.acquired_at))
        return (
            max(live, key=lambda obs: len(obs.module.cells))
            if len({obs.source.split("#")[0] for obs in live}) == 1
            else None
        )
    dated = [obs for obs in observations if obs.timestamp]
    return max(dated, key=lambda obs: obs.timestamp) if dated and not clock_unreliable else None


def _eligible(obs: Observation, nominal_ah: float | None) -> bool:
    if not nominal_ah or not obs.complete or not obs.timestamp:
        return False
    m = obs.module
    low = min((c.voltage_v for c in m.cells if c.voltage_v is not None), default=obs.summary_min_v)
    return (
        m.soc_pct is not None
        and m.soc_pct >= 90
        and low is not None
        and low >= 3.40
        and m.states.get("Base.St") in {"Charge", "Idle"}
        and m.current_a is not None
        and abs(m.current_a) <= 0.05 * nominal_ah
    )


def _mask_value(value: str) -> int | None:
    try:
        token = value.split()[0]
        return int(token, 16 if token.lower().startswith("0x") else 10)
    except (ValueError, IndexError):
        return None


def _alarms(obs: Observation, model: str | None = None) -> list[tuple[str, str, str]]:
    alarms = []
    entries = [("module", obs.module.states)] + [
        (f"cell {c.index}", c.states) for c in obs.module.cells
    ]
    for source, states in entries:
        for field, state in states.items():
            for token in state.replace("|", " ").replace(",", " ").split():
                if token not in NORMAL_STATES:
                    severity = (
                        "error"
                        if token in FAULT_STATES
                        else "warning"
                        if token in WARNING_STATES
                        else "info"
                    )
                    alarms.append((f"{source}.{field}: {token}", severity, "bms_state"))
    for decoded in _decoded_faults(obs, model):
        if int(decoded["raw_mask"], 16):
            code = "indicator_fault" if decoded["source"] == "getpwr" else "fault_mask"
            severity = fault_severity(decoded)
            if (
                code == "indicator_fault"
                and severity == "warning"
                and not int(decoded["unknown_mask"], 16)
            ):
                severity = "error"
            alarms.append((describe_faults(decoded), severity, code))
    return alarms


def _decoded_faults(obs: Observation, model: str | None = None) -> list[dict]:
    values = []
    if obs.module.error_code is not None and obs.module.error_code >= 0:
        values.append(decode_faults(obs.module.error_code, "getpwr", model=model))
    for source, raw in obs.masks.items():
        value = _mask_value(raw)
        if value is not None and value >= 0:
            values.append(decode_faults(value, source, model=model))
    return values


def _statistics(bucket: BatteryEvidence) -> tuple[dict[str, str], str | None]:
    dated = [s for s in bucket.statistics if s[2]]
    if dated:
        fields, source, _ = max(dated, key=lambda s: datetime.fromisoformat(s[2]))
        return fields, source
    if not bucket.statistics:
        return {}, None
    # Undated files cannot establish an ordering; only retain agreed values.
    fields = dict(bucket.statistics[0][0])
    for other, _, _ in bucket.statistics[1:]:
        fields = {key: value for key, value in fields.items() if other.get(key) == value}
    if len(fields) < len(bucket.statistics[0][0]):
        bucket.limitations.append("Undated statistics disagree; differing values are omitted.")
    return fields, bucket.statistics[0][1]


def analyze_battery(bucket: BatteryEvidence, threshold: int) -> DoctorBattery:
    observations = _deduplicate(bucket)
    model = bucket.identity.name if bucket.identity else None
    clocks = sorted((c for c in bucket.clocks if c[2]), key=lambda c: datetime.fromisoformat(c[2]))
    bad_clock = _clock_issues(observations) or any(b[0] < a[0] for a, b in zip(clocks, clocks[1:]))
    if bucket.reset_seen:
        bucket.limitations.append(
            "Reset commands occur in the evidence; persistence is assessed within each source and reset epoch only."
        )
    if bad_clock:
        bucket.limitations.append(
            "Record timestamps move backwards as indices increase; persistence checks withheld."
        )
    if any(not obs.complete for obs in observations):
        bucket.limitations.append(
            "Some observations have incomplete or conflicting cell/record coverage."
        )
    latest = _last(observations, bad_clock)
    if latest is None:
        bucket.limitations.append("No unambiguous latest voltage observation is available.")
    elif not latest.live:
        bucket.limitations.append(
            "Historical evidence only; recorded faults are not necessarily active now."
        )
    findings = []
    metrics = {
        "source_count": len(bucket.sources),
        "sources": sorted(bucket.sources),
        "observation_count": len(observations),
        "historical_records": sum(not o.live for o in observations),
        "nominal_capacity_ah": bucket.nominal_ah,
    }
    stats, stat_source = _statistics(bucket)
    metrics.update(
        reported_soh_pct=integer(stats.get("SOH")), cycle_count=integer(stats.get("CYCLE Times"))
    )
    counters = {
        key: value
        for key, text in stats.items()
        if key.endswith("Times") and (value := integer(text)) is not None and value > 0
    }
    metrics["historical_counters"] = counters
    if counters:
        findings.append(
            DoctorFinding(
                "historical_counters",
                "info",
                "Nonzero historical counters are not proof of active faults.",
                [stat_source],
            )
        )
    if latest:
        m = latest.module
        delta, low_index, high_index = spread(latest)
        voltages = [c.voltage_v for c in m.cells if c.voltage_v is not None and c.voltage_v > 0]
        metrics.update(
            as_of="snapshot" if latest.live else "historical_record",
            source=latest.source,
            battery_timestamp=latest.timestamp,
            acquired_at=latest.acquired_at,
            voltage_v=m.voltage_v,
            current_a=m.current_a,
            soc_pct=m.soc_pct,
            temperature_c=m.temperature_c,
            cell_spread_mv=delta,
            min_cell_voltage_v=min(voltages) if voltages else latest.summary_min_v,
            max_cell_voltage_v=max(voltages) if voltages else latest.summary_max_v,
            lowest_cell_index=low_index,
            highest_cell_index=high_index,
            cycle_count=metrics["cycle_count"]
            if metrics["cycle_count"] is not None
            else m.cycle_count,
        )
        if delta is not None and delta >= threshold:
            findings.append(
                DoctorFinding(
                    "cell_voltage_spread",
                    "warning",
                    f"Observed cell spread {delta} mV meets the {threshold} mV screening threshold; interpret with SOC and load.",
                    [latest.source],
                )
            )
        for message, severity, code in _alarms(latest, model):
            prefix = "Latest snapshot" if latest.live else "Latest historical record"
            findings.append(
                DoctorFinding(
                    code,
                    severity,
                    f"{prefix}: {message}",
                    [latest.source],
                    details={"faults": _decoded_faults(latest, model)}
                    if code in {"fault_mask", "indicator_fault"}
                    else {},
                )
            )
    historical = Counter(
        message for o in observations if not o.live for message, _, _ in _alarms(o, model)
    )
    if historical:
        findings.append(
            DoctorFinding(
                "historical_faults",
                "info",
                "; ".join(
                    f"{name}: {count} recorded occurrence(s)"
                    for name, count in sorted(historical.items())
                ),
                [o.source for o in observations if not o.live and _alarms(o, model)],
            )
        )
    recorded = [o for o in observations if not o.live and o.complete]
    deltas = [(spread(o)[0], o) for o in recorded if spread(o)[0] is not None]
    if deltas:
        maximum, worst = max(deltas, key=lambda pair: pair[0])
        metrics["max_recorded_cell_spread_mv"] = maximum
        metrics["records_over_spread_threshold"] = sum(delta >= threshold for delta, _ in deltas)
        if maximum >= threshold:
            findings.append(
                DoctorFinding(
                    "historical_cell_voltage_spread",
                    "warning",
                    f"Historical cell spread reached {maximum} mV in {metrics['records_over_spread_threshold']} record(s); SOC and load affect interpretation. This does not prove a failed balancer.",
                    [worst.source],
                )
            )
    # Historical protection/alarm evidence remains important even if the current snapshot is quiet.
    for direction, tokens, labels in (
        ("high", {"High", "OV", "BHV", "BOV"}, ("Bat HV Times", "Bat OV Times")),
        ("low", {"Low", "UV", "BLV", "BUV"}, ("Bat LV Times", "Bat UV Times")),
    ):
        affected = [
            o
            for o in observations
            if not o.live and any(c.states.get("Volt.St") in tokens for c in o.module.cells)
        ]
        cells = sorted(
            {c.index for o in affected for c in o.module.cells if c.states.get("Volt.St") in tokens}
        )
        counts = {
            label: integer(stats.get(label))
            for label in labels
            if integer(stats.get(label)) and integer(stats.get(label)) > 0
        }
        if affected or counts:
            message = f"Recorded cell {direction}-voltage alarm/protection evidence"
            if cells:
                message += f" on zero-based cell(s) {', '.join(map(str, cells))}"
            message += f" ({len(affected)} observation(s)"
            if counts:
                message += "; BMS counters: " + ", ".join(f"{k}={v}" for k, v in counts.items())
            message += "). These are historical findings, not proof of a currently active alarm."
            findings.append(
                DoctorFinding(
                    f"historical_cell_{direction}_voltage",
                    "warning",
                    message,
                    [o.source for o in affected] + ([stat_source] if counts else []),
                )
            )
    system_faults = [
        o
        for o in observations
        if not o.live
        and (
            o.module.states.get("Base.St") == "SysError"
            or any(_mask_value(v) for k, v in o.masks.items() if k in SYSTEM_FIELDS)
        )
    ]
    if system_faults:
        counts = Counter()
        sources = defaultdict(set)
        for obs in system_faults:
            observed = defaultdict(set)
            for source, raw in obs.masks.items():
                value = _mask_value(raw)
                if source in SYSTEM_FIELDS and value is not None and value >= 0:
                    observed[value].add(source)
            for value, fields in observed.items():
                counts[value] += 1
                sources[value].update(fields)
        decoded_masks = []
        for value, count in sorted(counts.items()):
            decoded = decode_faults(value, "System Fault", model=model)
            decoded["source_fields"] = sorted(sources[value])
            decoded["observations"] = count
            decoded_masks.append(decoded)
        state_only = sum(
            obs.module.states.get("Base.St") == "SysError"
            and not any(
                _mask_value(raw) for field, raw in obs.masks.items() if field in SYSTEM_FIELDS
            )
            for obs in system_faults
        )
        explanations = list(
            dict.fromkeys(
                bit["explanation"]
                for decoded in decoded_masks
                for bit in decoded["decoded_bits"]
                if bit["explanation"] and bit["code"] == "internal_communication"
            )
        )
        needs_attention = any(
            obs.module.states.get("Base.St") == "SysError" for obs in system_faults
        ) or any(fault_severity(d) == "warning" for d in decoded_masks)
        label = "System error/fault" if needs_attention else "System operational flags"
        message = f"{label} recorded in {len(system_faults)} observation(s)."
        if decoded_masks:
            message += " " + "; ".join(describe_faults(d) for d in decoded_masks) + "."
        if state_only:
            message += f" {state_only} SysError observation(s) have no nonzero detailed fault code; investigate using the original record and communication diagnostics."
        if explanations:
            message += " " + " ".join(explanations)
        findings.append(
            DoctorFinding(
                "historical_system_fault",
                "warning" if needs_attention else "info",
                message,
                [o.source for o in system_faults],
                details={"faults": decoded_masks, "state_only_observations": state_only},
            )
        )
    # Repeated near-full readings are evidence of difficulty, not a hardware diagnosis.
    groups = defaultdict(list)
    for obs in observations:
        if _eligible(obs, bucket.nominal_ah) and spread(obs)[0] is not None:
            groups[(obs.epoch, obs.source.split("#")[0] if bucket.reset_seen else "")].append(obs)
    assessed = False
    if not bad_clock:
        for group in groups.values():
            # Event and History can describe the same instant. It is one observation,
            # not two independent opportunities to converge.
            unique = {}
            conflicting_times = set()
            for obs in group:
                if obs.timestamp in unique and _conflicts(unique[obs.timestamp], obs):
                    conflicting_times.add(obs.timestamp)
                elif obs.timestamp not in unique or len(obs.module.cells) > len(
                    unique[obs.timestamp].module.cells
                ):
                    unique[obs.timestamp] = obs
            group = sorted(
                (obs for stamp, obs in unique.items() if stamp not in conflicting_times),
                key=lambda obs: obs.timestamp,
            )
            if conflicting_times:
                bucket.limitations.append(
                    "Simultaneous inconsistent readings are excluded from balancing persistence checks."
                )
            # A later qualifying low-spread observation demonstrates convergence for this interval.
            abnormal = []
            for obs in group:
                if spread(obs)[0] >= threshold:
                    abnormal.append(obs)
                else:
                    abnormal.clear()
            if len(abnormal) >= 3:
                duration = (
                    datetime.fromisoformat(abnormal[-1].timestamp)
                    - datetime.fromisoformat(abnormal[0].timestamp)
                ).total_seconds()
                if duration >= 24 * 3600:
                    assessed = True
                    findings.append(
                        DoctorFinding(
                            "suspected_balancing_difficulty",
                            "warning",
                            "Repeated near-full, low-current readings remain imbalanced across at least 24 battery-reported hours; balancing difficulty is suspected, not proven.",
                            [o.source for o in abnormal],
                            "suspected",
                        )
                    )
    if not assessed:
        bucket.limitations.append(
            "Balancing difficulty is unproven: repeated qualifying near-full evidence is absent or shows convergence."
        )
    usable = latest is not None and latest.complete and spread(latest)[0] is not None
    severe = any(f.severity in {"warning", "error"} for f in findings)
    status = (
        "attention"
        if severe
        else "no_issues_detected"
        if usable
        and bucket.identity
        and bucket.identity.barcode
        and not any("Conflicting" in note for note in bucket.limitations)
        else "insufficient_data"
    )
    identity = (
        {
            "barcode": bucket.identity.barcode,
            "model": bucket.identity.name,
            "address": latest.module.address
            if latest and latest.module.address is not None
            else bucket.identity.address,
            "cell_count": bucket.identity.cell_count,
        }
        if bucket.identity
        else {"barcode": None, "model": None, "address": latest.module.address if latest else None}
    )
    return DoctorBattery(
        bucket.key, identity, status, metrics, findings, list(dict.fromkeys(bucket.limitations))
    )


def analyze_logs(path: str | Path, *, imbalance_mv: int = 100) -> DoctorReport:
    """Analyze a report, manifest, or directory; never open a serial connection."""
    validate_threshold(imbalance_mv)
    reader = EvidenceReader(path)
    buckets = reader.read()
    batteries = [
        analyze_battery(bucket, imbalance_mv)
        for bucket in sorted(buckets, key=lambda b: b.key)
        if bucket.observations or bucket.statistics or bucket.identity
    ]
    status = (
        "unusable"
        if not batteries
        else (
            "attention"
            if any(b.status == "attention" for b in batteries)
            else "insufficient_data"
            if reader.issues or any(b.status == "insufficient_data" for b in batteries)
            else "no_issues_detected"
        )
    )
    return DoctorReport(status, batteries, reader.issues, imbalance_mv)


def format_doctor(report: DoctorReport) -> str:
    """Render short per-battery summaries with bounded findings and limitations."""
    lines = [f"Battery doctor: {report.status.replace('_', ' ')}"]
    for battery in report.batteries:
        ident, m = battery.identity, battery.metrics
        lines.extend(
            [
                "",
                f"{ident.get('barcode') or battery.key} ({ident.get('model') or 'unknown model'}): {battery.status.replace('_', ' ')}",
            ]
        )
        values = [
            ("SOC", m.get("soc_pct"), "%"),
            ("SOH (reported)", m.get("reported_soh_pct"), "%"),
            ("voltage", m.get("voltage_v"), " V"),
            ("current", m.get("current_a"), " A"),
            ("cell spread", m.get("cell_spread_mv"), " mV"),
            ("recorded max", m.get("max_recorded_cell_spread_mv"), " mV"),
            ("cycles", m.get("cycle_count"), ""),
        ]
        lines.append(
            "  "
            + ", ".join(
                f"{label} {value:g}{unit}" for label, value, unit in values if value is not None
            )
            if any(v is not None for _, v, _ in values)
            else "  No usable measurements"
        )
        if m.get("cell_spread_mv") is not None:
            if m.get("min_cell_voltage_v") is not None and m.get("max_cell_voltage_v") is not None:
                lines.append(
                    f"  Cell voltage range {m['min_cell_voltage_v']:g}–{m['max_cell_voltage_v']:g} V"
                )
            if m.get("lowest_cell_index") is not None:
                lines.append(
                    f"  Lowest cell {m['lowest_cell_index']}; highest cell {m['highest_cell_index']} (zero-based)"
                )
            lines.append(
                f"  Evidence: {m.get('as_of', 'unknown')} {m.get('battery_timestamp') or m.get('acquired_at') or '(undated)'}"
            )
        for finding in sorted(
            battery.findings, key=lambda f: {"error": 0, "warning": 1, "info": 2}[f.severity]
        )[:5]:
            message = finding.message[:350]
            lines.append(f"  {finding.severity.upper()}: {message}")
        if len(battery.findings) > 5:
            lines.append(
                f"  {len(battery.findings) - 5} additional findings; use --format json for full evidence."
            )
        for limitation in battery.limitations[:3]:
            lines.append(f"  Note: {limitation}")
    if report.input_issues:
        lines.append(f"\nInput/acquisition issues: {len(report.input_issues)}")
        for issue in report.input_issues[:3]:
            lines.append(f"  {issue['source']}: {issue['message']}")
    if not report.batteries:
        lines.append("No usable battery evidence was found.")
    text = "\n".join(lines) + "\n"
    return "".join(
        c if c == "\n" or (ord(c) >= 32 and ord(c) != 127) else f"\\x{ord(c):02x}" for c in text
    )
