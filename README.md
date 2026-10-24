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

Connection setup recognizes a console that is already at `pylon_debug>` and
skips redundant login. Otherwise it sends `login debug` once and verifies the
final prompt. A rejected login is accepted only when that prompt independently
confirms debug mode; a base prompt or timeout still fails the connection.

On normal client/context-manager exit, the client follows BatteryView's disconnect
sequence: send `cmdquit` with LF, wait up to five seconds for received text
containing `cmdquit` (possibly its echo), then close the serial port. No subsequent
prompt is required. Timeouts and serial errors during disconnect are diagnostic
only: the port is still closed, and an earlier operation error is preserved.
Some firmware rejects `cmdquit`; diagnostics report that rejection explicitly
even when its echo matches. An echo alone does not confirm that console mode ended.
The disconnect response is excluded from report files. Repeated `close()` calls
do not send additional commands. Failed connection setup releases the port
immediately without attempting a console command.

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

`pwr` can return a module table or a labeled summary headed `Power N`. The header
reports the connected module's address, not the number of installed modules.
Labeled summaries support voltage, signed current, temperature, SOC, capacity,
and status fields; unknown fields remain available in `raw`.

For a single returned module without `--module`, detailed reads use bare `getpwr`
and `pwrsys` on the connected console, even when its reported address is greater
than one. Multiple returned modules or explicit `--module N` selection use
addressed queries. Monitoring supports hash-delimited `getpwr` responses and
labeled responses with cell tables. Capacity from `pwr` is retained if the
detailed response omits it. Full snapshots still require hardware verification.

Unsupported optional `pwrsys` queries, including firmware replies beginning with
`Unknown command`, do not discard other readings. Timeouts and malformed core
responses stop collection.

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

`BatteryClient.close()` performs the same disconnect as context-manager exit.
There are no background polling tasks or queued report writes to drain: operations
share a session lock, and report responses are flushed before their methods return.

## Diagnostic logging

```sh
batteryview snapshot --port /dev/ttyUSB0 --debug
batteryview --debug snapshot --port /dev/ttyUSB0 --log-file debug.log
batteryview snapshot --port /dev/ttyUSB0 --trace-serial --log-file serial-trace.log
```

`--debug` logs connection stages, baud changes, command names, recognized prompts,
timing, byte counts, and failure types. It excludes response contents and redacts
identity-bearing arguments such as barcodes. `--trace-serial` additionally logs
escaped raw sent/received bytes, making CR and LF visible. **Raw traces may contain
private battery identities and telemetry.** Keep them local and review them before
sharing; do not copy them into public test fixtures.

Both `--trace-serial` and `--log-file` imply debug logging. Options work before or
after the subcommand. Diagnostics go to stderr unless `--log-file` selects a new
UTF-8 file; existing log files are never overwritten. JSON/CSV on stdout and vendor
transcript files remain separate from diagnostic output. Error messages and
report progress still go to stderr when diagnostics are directed to a file.

Library callers configure standard Python logging themselves. For metadata:

```python
import logging

logging.basicConfig(level=logging.DEBUG)
```

Raw I/O uses the separate `batteryview.serial` logger at level 5 (`TRACE`), below
`DEBUG`. Enable it explicitly with
`logging.getLogger("batteryview.serial").setLevel(5)` and a handler that accepts
that level. The library installs no output handlers or root-logger configuration.

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
