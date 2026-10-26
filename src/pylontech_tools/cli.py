"""Command-line access; vendor text reports are files, diagnostics are stderr."""

import argparse
import csv
import json
import logging
import sys
from dataclasses import asdict
from pathlib import Path
from typing import TextIO

from . import BatteryClient, CommandCancelled, PylontechError, Snapshot
from .diagnostics import configure_logging, failure_diagnostic
from .doctor import analyze_logs, format_doctor
from .profiles import PROFILES
from .transport import list_ports

logger = logging.getLogger(__name__)

CSV_FIELDS = [
    "timestamp",
    "type",
    "module",
    "cell",
    "voltage_v",
    "current_a",
    "temperature_c",
    "soc_pct",
    "capacity_ah",
    "recommended_charge_a",
    "recommended_discharge_a",
    "error_code",
    "cycle_count",
    "states",
    "min_cell_voltage_v",
    "max_cell_voltage_v",
    "min_cell_voltage_index",
    "max_cell_voltage_index",
    "min_cell_temperature_c",
    "max_cell_temperature_c",
    "min_cell_temperature_index",
    "max_cell_temperature_index",
]


def _positive(value: str) -> float:
    parsed = float(value)
    if not 0 < parsed < float("inf"):
        raise argparse.ArgumentTypeError("must be a finite positive number")
    return parsed


def _count(value: str) -> int:
    parsed = int(value)
    if parsed < 1:
        raise argparse.ArgumentTypeError("must be a positive integer")
    return parsed


def parser() -> argparse.ArgumentParser:
    diagnostics = argparse.ArgumentParser(add_help=False)
    diagnostics.add_argument(
        "--debug",
        action="store_true",
        default=argparse.SUPPRESS,
        help="log command metadata and connection diagnostics",
    )
    diagnostics.add_argument(
        "--trace-serial",
        action="store_true",
        default=argparse.SUPPRESS,
        help="include raw serial bytes (may contain private battery data); implies --debug",
    )
    diagnostics.add_argument(
        "--log-file",
        type=Path,
        default=argparse.SUPPRESS,
        help="write diagnostics to a new UTF-8 file instead of stderr; implies --debug",
    )
    root = argparse.ArgumentParser(
        prog="pylontech-console",
        description="Pylontech console reports and monitoring",
        parents=[diagnostics],
    )
    sub = root.add_subparsers(dest="command", required=True)
    ports = sub.add_parser("ports", help="list available serial ports", parents=[diagnostics])
    ports.add_argument("--format", choices=["json", "csv"], default="json")
    doctor = sub.add_parser(
        "doctor", help="screen battery health online or from saved logs", parents=[diagnostics]
    )
    doctor.add_argument(
        "source", nargs="?", type=Path, help="offline report, manifest, or collection directory"
    )
    doctor.add_argument("--port", help="serial port for online doctor (exclusive with source)")
    doctor.add_argument("--format", choices=["text", "json"], default="text")
    doctor.add_argument("--output", type=Path, help="new report file (default: stdout)")
    doctor.add_argument(
        "--imbalance-mv",
        type=_count,
        default=100,
        help="cell-spread screening threshold (default: 100 mV)",
    )
    doctor.add_argument(
        "--save-inputs", type=Path, help="save online evidence for offline analysis"
    )
    doctor.add_argument("--baud", type=_count, default=argparse.SUPPRESS)
    doctor.add_argument("--timeout", type=_positive, default=argparse.SUPPRESS)
    doctor.add_argument("--no-shift", action="store_true", default=argparse.SUPPRESS)
    doctor.add_argument("--read-retries", type=int, choices=range(3), default=argparse.SUPPRESS)
    doctor.add_argument("--profile", choices=sorted(PROFILES), default=argparse.SUPPRESS)
    for name, help_text in [
        ("info", "read device identity"),
        ("stat", "read counters, record counts, and state of health"),
        ("time", "read the battery clock without setting it"),
        ("log", "read the diagnostic log without clearing it"),
        ("config", "display configuration without changing it"),
        ("snapshot", "read module and cell measurements"),
        ("watch", "stream module and cell measurements"),
        ("history", "save a BatteryView-compatible History transcript"),
        ("event", "save a BatteryView-compatible Event transcript"),
        ("collect", "collect support files from the directly connected module"),
        ("reset-soc", "execute EEPROM clear, reset, and barcode restoration; save transcript"),
    ]:
        command = sub.add_parser(name, help=help_text, parents=[diagnostics])
        command.add_argument("--port", required=True, help="e.g. COM3 or /dev/ttyUSB0")
        command.add_argument(
            "--baud", type=_count, default=115200, help="console rate (default: 115200)"
        )
        command.add_argument(
            "--timeout", type=_positive, default=5, help="response timeout in seconds"
        )
        if name in {"info", "snapshot", "watch", "stat", "config"}:
            command.add_argument(
                "--module",
                type=int,
                choices=range(1, 17),
                metavar="1..16",
                help="select a chained module",
            )
        command.add_argument(
            "--no-shift", action="store_true", help="skip the 1200-baud console-mode switch"
        )
        if name == "collect":
            command.add_argument(
                "--output",
                type=Path,
                required=True,
                help="shared output directory; existing files are preserved",
            )
        elif name in {"history", "event", "reset-soc"}:
            command.add_argument(
                "--output", type=Path, help="new transcript path; never overwritten"
            )
        elif name in {"stat", "time", "log", "config"}:
            command.add_argument("--format", choices=["text", "json"], default="text")
            command.add_argument("--output", type=Path, help="new output file (default: stdout)")
            if name == "log":
                command.add_argument("--count", type=int, choices=range(1, 33), metavar="1..32")
        else:
            command.add_argument("--format", choices=["json", "csv"], default="json")
            command.add_argument("--output", type=Path, help="new output file (default: stdout)")
        command.add_argument(
            "--read-retries",
            type=int,
            choices=range(3),
            default=0,
            help="additional attempts for reads only (default: 0)",
        )
        if name in {"snapshot", "watch", "collect"}:
            command.add_argument(
                "--monitoring-mode", choices=["auto", "single", "parallel"], default="auto"
            )
            command.add_argument(
                "--profile", choices=sorted(PROFILES), help="override automatic model profile"
            )
        if name == "watch":
            command.add_argument("--interval", type=_positive, default=5)
            command.add_argument(
                "--count", type=_count, help="number of snapshots (default: unlimited)"
            )
    return root


def _progress(kind: str, current: int, total: int) -> None:
    print(f"{kind}: {current}/{total}", file=sys.stderr, flush=True)


def _write_snapshot(snapshot: Snapshot, output: TextIO, csv_writer: csv.DictWriter | None) -> None:
    if csv_writer is None:
        output.write(json.dumps(snapshot.to_dict(), ensure_ascii=False) + "\n")
    else:
        if snapshot.system is not None:
            csv_writer.writerow(
                {"timestamp": snapshot.timestamp, "type": "system", **asdict(snapshot.system)}
            )
        for module in snapshot.modules:
            row = {k: v for k, v in asdict(module).items() if k in CSV_FIELDS}
            row.update(
                timestamp=snapshot.timestamp,
                type="module",
                module=module.address,
                states=json.dumps(module.states, sort_keys=True),
            )
            csv_writer.writerow(row)
            for cell in module.cells:
                row = {k: v for k, v in asdict(cell).items() if k in CSV_FIELDS}
                row.update(
                    timestamp=snapshot.timestamp,
                    type="cell",
                    module=module.address,
                    cell=cell.index,
                    states=json.dumps(cell.states, sort_keys=True),
                )
                csv_writer.writerow(row)
    output.flush()


def main(argv: list[str] | None = None) -> int:
    root = parser()
    args = root.parse_args(argv)
    if args.command == "doctor":
        if bool(args.source) == bool(args.port):
            root.error("doctor requires exactly one input path or --port")
        if args.source and any(
            hasattr(args, key) for key in ("baud", "timeout", "no_shift", "read_retries", "profile")
        ):
            root.error("doctor connection options require --port")
        if args.source and args.save_inputs:
            root.error("--save-inputs requires online doctor")
    try:
        with configure_logging(
            debug=getattr(args, "debug", False),
            trace_serial=getattr(args, "trace_serial", False),
            log_file=getattr(args, "log_file", None),
        ):
            return _run(args)
    except OSError as exc:
        print(f"pylontech-console: Cannot configure diagnostic logging: {exc}", file=sys.stderr)
        return 2 if args.command == "doctor" else 1


def _run(args: argparse.Namespace) -> int:
    try:
        if args.command == "doctor":
            return _run_doctor(args)
        if args.command == "ports":
            ports = list_ports()
            if args.format == "json":
                print(json.dumps(ports, ensure_ascii=False))
            else:
                writer = csv.DictWriter(sys.stdout, ["port", "description", "serial_number"])
                writer.writeheader()
                writer.writerows(ports)
            return 0
        with BatteryClient(
            args.port,
            baudrate=args.baud,
            timeout=args.timeout,
            module=getattr(args, "module", None),
            shift=not args.no_shift,
            read_retries=args.read_retries,
            monitoring_mode=getattr(args, "monitoring_mode", "auto"),
            profile=getattr(args, "profile", None),
        ) as client:
            if args.command == "collect":
                result = client.collect(args.output, progress=_progress)
                print(json.dumps(asdict(result), default=str))
                if not result.complete:
                    print(f"Collection incomplete; see {result.manifest_path}", file=sys.stderr)
                    detail = failure_diagnostic(getattr(client, "last_failure", None))
                    if detail:
                        print(detail, file=sys.stderr)
                return 0 if result.complete else 1
            if args.command in {"history", "event", "reset-soc"}:
                method = {
                    "history": client.export_history,
                    "event": client.export_events,
                    "reset-soc": client.reset_soc,
                }[args.command]
                result = method(args.output, progress=_progress)
                print(json.dumps(asdict(result), default=str))
                return 0
            output = (
                args.output.open("x", encoding="utf-8", newline="") if args.output else sys.stdout
            )
            try:
                if args.command in {"stat", "time", "log", "config"}:
                    if args.command == "log":
                        result = client.diagnostic_log(args.count)
                    else:
                        result = getattr(
                            client,
                            {"stat": "statistics", "time": "read_clock", "config": "configuration"}[
                                args.command
                            ],
                        )()
                    output.write(
                        result.text
                        if args.format == "text"
                        else json.dumps(asdict(result), ensure_ascii=False) + "\n"
                    )
                    output.flush()
                elif args.command == "info":
                    identity = asdict(client.info())
                    if args.format == "json":
                        output.write(json.dumps(identity, ensure_ascii=False) + "\n")
                    else:
                        writer = csv.writer(output)
                        writer.writerow(["field", "value"])
                        writer.writerows(identity["fields"].items())
                else:
                    writer = csv.DictWriter(output, CSV_FIELDS) if args.format == "csv" else None
                    if writer:
                        writer.writeheader()
                    snapshots = (
                        client.watch(interval=args.interval, count=args.count)
                        if args.command == "watch"
                        else [client.snapshot()]
                    )
                    for snapshot in snapshots:
                        _write_snapshot(snapshot, output, writer)
            finally:
                if output is not sys.stdout:
                    output.close()
        return 0
    except (KeyboardInterrupt, CommandCancelled) as exc:
        logger.debug("Operation interrupted")
        print(
            "Doctor interrupted; saved inputs, if requested, have been retained."
            if args.command == "doctor"
            else "Interrupted; any partial report has been retained.",
            file=sys.stderr,
        )
        detail = failure_diagnostic(exc)
        if detail:
            print(detail, file=sys.stderr)
        return 130
    except (PylontechError, OSError, ValueError) as exc:
        logger.debug("Operation failed command=%s error=%s", args.command, type(exc).__name__)
        print(f"pylontech-console: {exc}", file=sys.stderr)
        detail = failure_diagnostic(exc)
        if detail:
            print(detail, file=sys.stderr)
        return 2 if args.command == "doctor" else 1


def _run_doctor(args: argparse.Namespace) -> int:
    # Analyze offline before creating a file that might lie inside the input directory.
    report = analyze_logs(args.source, imbalance_mv=args.imbalance_mv) if args.source else None
    output = args.output.open("x", encoding="utf-8", newline="") if args.output else sys.stdout
    try:
        if not args.source:
            with BatteryClient(
                args.port,
                baudrate=getattr(args, "baud", 115200),
                timeout=getattr(args, "timeout", 5),
                shift=not getattr(args, "no_shift", False),
                read_retries=getattr(args, "read_retries", 0),
                profile=getattr(args, "profile", None),
                monitoring_mode="single",
            ) as client:
                report = client.doctor(save_inputs=args.save_inputs, imbalance_mv=args.imbalance_mv)
        output.write(
            json.dumps(report.to_dict(), ensure_ascii=False) + "\n"
            if args.format == "json"
            else format_doctor(report)
        )
        output.flush()
        return report.exit_code
    finally:
        if output is not sys.stdout:
            output.close()


if __name__ == "__main__":
    raise SystemExit(main())
