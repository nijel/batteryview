"""Command-line access; vendor text reports are files, diagnostics are stderr."""

import argparse
import csv
import json
import sys
from dataclasses import asdict
from pathlib import Path
from typing import TextIO

from . import BatteryClient, BatteryViewError, CommandCancelled, Snapshot
from .transport import list_ports

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
    root = argparse.ArgumentParser(
        prog="batteryview",
        description="Pylontech console reports and monitoring",
    )
    sub = root.add_subparsers(dest="command", required=True)
    ports = sub.add_parser("ports", help="list available serial ports")
    ports.add_argument("--format", choices=["json", "csv"], default="json")
    for name, help_text in [
        ("info", "read device identity"),
        ("snapshot", "read module and cell measurements"),
        ("watch", "stream module and cell measurements"),
        ("history", "save a BatteryView-compatible History transcript"),
        ("event", "save a BatteryView-compatible Event transcript"),
        ("reset-soc", "execute EEPROM clear, reset, and barcode restoration; save transcript"),
    ]:
        command = sub.add_parser(name, help=help_text)
        command.add_argument("--port", required=True, help="e.g. COM3 or /dev/ttyUSB0")
        command.add_argument(
            "--baud", type=_count, default=115200, help="console rate (default: 115200)"
        )
        command.add_argument(
            "--timeout", type=_positive, default=5, help="response timeout in seconds"
        )
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
        if name in {"history", "event", "reset-soc"}:
            command.add_argument(
                "--output", type=Path, help="new transcript path; never overwritten"
            )
        else:
            command.add_argument("--format", choices=["json", "csv"], default="json")
            command.add_argument("--output", type=Path, help="new output file (default: stdout)")
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
    args = parser().parse_args(argv)
    try:
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
            module=args.module,
            shift=not args.no_shift,
        ) as client:
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
                if args.command == "info":
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
    except (KeyboardInterrupt, CommandCancelled):
        print("Interrupted; any partial report has been retained.", file=sys.stderr)
        return 130
    except (BatteryViewError, OSError, ValueError) as exc:
        print(f"batteryview: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
