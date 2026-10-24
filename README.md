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

RTS and DTR are explicitly inactive, matching BatteryView's .NET serial defaults.
Their states are set before the initial open and each baud-change reopen, and
included in debug diagnostics.
When the port is already open at the requested baud rate it stays open, so
`--no-shift` avoids a redundant close/reopen and the associated input-buffer reset.

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

On Windows, use a port such as `--port COM3`. Full History/Event reports and SOC
reset require a direct connection and reject `--module`. Addressed identity and
monitoring use explicit commands such as `info 3` and `getpwr 3`; numbered login
is not a substitute for addressing reads.

Omit `--output` to derive a BatteryView-style filename from the barcode and local
time. History and Event filenames end in `.txt.txt`, matching the supplied files.
Existing files are never overwritten. Progress is written to stderr; stdout
contains a JSON result with the path, record count, and response count.

Reports retain console echoes, prompts, spacing, and device line endings. Each
response receives BatteryView's additional CRLF and the file has a single
UTF-16LE BOM. Connection setup traffic is excluded. No application metadata or
JSON is inserted into a vendor report. Failed collections retain partial files
and exit nonzero; a partial file is not a completed report.

Reports first try `datalist KIND dtls OFFSET`. Firmware that explicitly rejects
that format uses plain summary pages followed by `data KIND INDEX` for each
record. The latest record's index determines the count, with `stat` as fallback.
Missing, repeated or unexpected records fail the export. A firmware-specific
sixteenth row overlapping the next page is accepted; reads never exceed the
expected count. Failed attempts remain in the transcript.

### Support collection for several modules

```sh
batteryview collect --port /dev/ttyUSB0 --output support/
```

This collects **identity → History → Event → snapshot** using one connection.
Connect the console cable to each module separately and repeat the same command
with the same output directory. Complete support exports through addressed
module selection are not verified, so `collect` does not accept `--module`.
The command performs no reset or configuration writes.

The directory is created if needed and may already contain earlier collections.
All artifacts are written directly into it:

- `<run-id>_info.json`: device identity and firmware fields.
- `<barcode>_history_<timestamp>.txt.txt`: BatteryView-compatible History transcript.
- `<barcode>_event_<timestamp>.txt.txt`: BatteryView-compatible Event transcript.
- `<run-id>_snapshot.json`: the ordinary JSON snapshot, including raw responses.
- `<run-id>_manifest.json`: status, identity, file references, and report counts for this run.

Each run ID combines its UTC start time with a random identifier. Earlier files
are never overwritten. Reports retain their existing filename convention and
use `UnknownSN` when no barcode is available. A report filename collision fails
that step rather than replacing a file from an earlier run.

Collection stops at the first failed step. Completed files and partial report
files remain, and subsequent steps are marked `skipped`. The per-run manifest is
updated atomically as work progresses; it records failure type and message
without embedding console response payloads. Cancellation records an interrupted
step and retains existing files. A filesystem failure writing the manifest is
reported as an error, and its last valid state may remain `running`.

Progress goes to stderr and stdout contains a JSON summary with `directory`,
`manifest_path`, and `complete`. Exit codes are `0` for complete collection, `1`
for failure, and `130` for interruption. Connection setup failures create no
collection artifacts. Normal disconnect cleanup still runs after collection.

Existing `--debug`, `--trace-serial`, and `--log-file` options also work with
`collect`; raw serial tracing remains opt-in. Collection files contain private
device information and telemetry. The example `support/` directory is ignored by
Git, and package source allowlists exclude generated collections.

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

For support collection, use a client with no addressed module selection:

```python
with BatteryClient("/dev/ttyUSB0") as battery:
    result = battery.collect("support")
    print(result.complete, result.manifest_path)
```

`collect(output, progress=None)` requires a connected client and returns a
`CollectionResult(directory, manifest_path, complete)`. Expected step failures
return an incomplete result. Cancellation is re-raised after updating the
manifest; output-directory and manifest-write errors are raised to the caller.

`BatteryClient.close()` performs the same disconnect as context-manager exit.
There are no background polling tasks or queued report writes to drain: operations
share a session lock, and report responses are flushed before their methods return.

## Monitoring modes and profiles

```sh
batteryview snapshot --port /dev/ttyUSB0 --monitoring-mode single
batteryview watch --port /dev/ttyUSB0 --monitoring-mode parallel
batteryview snapshot --port /dev/ttyUSB0 --module 3 --profile generic
```

`--monitoring-mode auto` is the default: read local `getpwr`, then discover modules
with `pwr`. Single mode uses the local reading and optional summary extensions;
parallel mode requires a module table and addressed detail reads. An explicit
`--module` always uses addressed reads and does not depend on a numbered login.
Unsupported optional extensions are retained as raw responses without discarding
valid primary readings; malformed replies and timeouts still fail.

The first monitoring call reads identity to select a bundled native profile.
`--profile` (or the library's `profile=`) overrides this selection and skips that
identity query. Profiles cover `generic`, `US3000C`, `UP2500`, `2500LFP2`, `US2K`,
and `Forcel_C`; unknown device names use `generic`. Profiles encode reviewed
monitoring layouts and extension enablement/addressing from the original XML,
including older trailer placement. They do not load executable scripts or
arbitrary XML regexes. Disabled `tsoh` queries remain disabled.

Snapshots include cell voltage/temperature extrema and their zero-based indices,
and a `system` summary with total current, average module voltage and available
system recommended currents. Aggregates describe only the modules in the
snapshot, including a single selected module. Missing inputs produce `null`;
unknown fields and alarm codes remain available. CSV adds extrema columns and a
`type=system` row before module/cell rows. Existing JSON keys remain available.
The library accepts `monitoring_mode=`, `profile=` and `read_retries=` on
`BatteryClient`; `SystemReading` is also public.

Operations fail immediately by default. `--read-retries 1` or `2` permits that many
additional attempts for explicit read commands, after resynchronizing to a debug
prompt. Reports retry pages from their explicit offset and retain failed responses.
Pagination continuations, explicit rejections, login, disconnect and all SOC-reset
commands are never retried. `collect` inherits this policy and stops if recovery
fails. There is no automatic reconnect loop.

## Diagnostic logging

```sh
batteryview snapshot --port /dev/ttyUSB0 --debug
batteryview --debug snapshot --port /dev/ttyUSB0 --log-file debug.log
batteryview snapshot --port /dev/ttyUSB0 --trace-serial --log-file serial-trace.log
```

On failure, stderr shows the failed command, available timing/framing context,
and the last 4096 bytes of its response, including timeout fragments. Control
characters are escaped, truncation is marked, and an empty reply is explicit.
This also applies to failures caught by `collect`; its manifest does not contain
response tails. **Failure output can contain private identifiers and telemetry.**
Successful traffic is not printed by default. Library protocol exceptions expose
`response` and `context`; collection clients expose `last_failure`.

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

These tests read recordings at runtime without copying them into public fixtures.
Complete references are compared byte-for-byte. The historical History capture
contains missing records: its replay now verifies rejection and byte-exact partial
output instead of accepting an incomplete report. Failures omit private payloads. Without that option, the three private reference tests are
skipped. CI uses only synthetic data on Windows, macOS, and Linux with Python
3.11 and 3.14.

See [protocol notes](docs/protocol.md) for the recovered command sequences,
framing details, and remaining hardware acceptance checks.

GUI, TCP adapters, XLSX exports, parameter editing, firmware updating, and
arbitrary service scripts are outside this first implementation.
