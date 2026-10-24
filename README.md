# BatteryView for Python

A portable Pylontech console library and command-line tool. Its primary outputs
are the UTF-16 text transcripts produced by BatteryView's **History**, **Event**,
and **SOC reset** buttons. Monitoring supports JSON, JSON Lines, and CSV.

The protocol was recovered from BatteryView 3.0.28's compiled .NET code, bundled
XML definitions, and private reference console reports. The supplied reports can
be replayed in opt-in local tests. **Live hardware behavior and acceptance of newly
collected reports by Pylontech have not yet been verified.** Other firmware
variants need additional validation.

## Install

Requires Python 3.11 or newer on Windows, Linux, or macOS:

```sh
python -m pip install .
batteryview ports
```

Use the battery's console connection and the appropriate serial cable. The
default connection sequence sends BatteryView's mode-switch frame at 1200 baud,
then opens the console at 115200 baud, 8N1, without flow control. Use `--no-shift`
to connect to a console already in command mode, or `--baud` for another console
rate. Close other applications using the port before connecting.

## Pylontech reports

```sh
batteryview history --port /dev/ttyUSB0 --output history.txt.txt
batteryview event --port /dev/ttyUSB0 --output event.txt.txt
```

On Windows, use a port such as `--port COM3`. For a specific chained module, add
`--module 3`. This selects it with `login 3 debug` before starting collection.

Omit `--output` to derive a BatteryView-style filename from the barcode and local
time. History and Event filenames end in `.txt.txt`, matching the supplied files.
Existing files are never overwritten. Progress is written to stderr; stdout
contains a JSON result with the path, record count, and response count.

Reports retain console echoes, prompts, spacing, and device line endings. Each
response receives BatteryView's additional CRLF and the file has a single
UTF-16LE BOM. Connection setup traffic is excluded. No application metadata or
JSON is inserted into a vendor report. Failed collections retain partial files
and exit nonzero; a partial file is not a completed report.

### SOC reset

```sh
batteryview reset-soc --port /dev/ttyUSB0 --output reset.txt
```

This command **clears EEPROM, resets the battery, and restores its barcode**,
following the bundled BatteryView script. Invoke it only when you intend to
perform that operation. History, Event, and monitoring do not perform it.

Before EEPROM clearing, the client saves the original identity and barcode to
`reset.txt.recovery.json` and flushes the pre-reset transcript to disk. It aborts
before clearing if no usable barcode was captured. It then performs the reset,
reconnects, restores the barcode, and verifies the device identity. Address
changes are permitted after reset.

The recovery file records the last attempted step and completion status. If the
operation fails or is interrupted, retain both files and inspect the recovery
state before taking further action. Mutating commands are never automatically
retried, and there is no automatic restart/resume command. A timeout after a
write cannot establish whether the battery executed that command.

## Monitoring

```sh
batteryview info --port /dev/ttyUSB0
batteryview snapshot --port /dev/ttyUSB0
batteryview snapshot --port /dev/ttyUSB0 --format csv --output snapshot.csv
batteryview watch --port /dev/ttyUSB0 --interval 5 --count 10 --output readings.jsonl
```

JSON snapshots include timestamps, module/cell readings, alarms, unknown fields,
and raw responses. CSV has separate `module` and `cell` rows with explicit units.
Missing values are empty/null, not zero. Known alarms have `warning` or `error`
severity; unfamiliar state values are preserved with `unknown` severity.

Chained modules are discovered through `pwr`; detailed reads use `getpwr N`.
Monitoring parsers support the recovered hash-delimited `getpwr` format and
labelled responses with cell tables. These paths have synthetic tests but no
live-monitoring recording yet. Unsupported optional `pwrsys` queries do not
discard other readings; timeouts and malformed core responses stop collection.

## Python API

```python
from batteryview import BatteryClient

with BatteryClient("/dev/ttyUSB0", module=3) as battery:
    identity = battery.info()
    report = battery.export_history("history.txt.txt")
    snapshot = battery.snapshot()
    print(identity.name, report.records, snapshot.to_dict())
```

The client is synchronous and serializes operations on a shared console session.
`watch(interval=5, count=None)` yields snapshots. `reset_soc(path)` is the
separate mutating workflow. Exceptions derive from `BatteryViewError`;
`CommandTimeout`, `UnsupportedCommand`, and `ProtocolError` retain any partial
response. `ResetRecoveryError` exposes `recovery_path`.

## Development and validation

```sh
python -m pip install -e '.[test]'
python -m pytest -q
python -m ruff check .
python -m ruff format --check .
```

All distributed test data is synthetic: invented identities, timestamps, counts,
and measurements. Private files in `Logs/`, the vendor bundle, and editor recovery
files are ignored by Git. Package builds use an explicit source-file allowlist
that excludes private recordings and editor backups.

Local comparison with the three original recordings is opt-in:

```sh
python -m pytest -q --private-logs=Logs
```

These tests read the recordings at runtime and compare generated transcripts
byte-for-byte; they do not copy them into public fixtures. Their failures omit
private payloads. Without that option, the three private reference tests are
skipped. CI uses only synthetic data on Windows, macOS, and Linux with Python
3.11 and 3.14.

See [protocol notes](docs/protocol.md) for the recovered command sequences,
framing details, and remaining hardware acceptance checks.

GUI, TCP adapters, XLSX exports, parameter editing, firmware updating, and
arbitrary service scripts are outside this first implementation.
