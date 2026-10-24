# Recovered BatteryView 3.0.28 behavior

## Evidence and limits

The application is an unobfuscated .NET Framework 4.5.2 WinForms assembly. The
PDB lists source paths but does not supply those source files. Inspection used
managed metadata and IL, specifically `PylonSerialPort`, `MsgBackgroundWorker`,
`HistoryGetInfo`, `DataStorage`, and the History-window button handlers. The
Python package does not execute or depend on the vendor assembly or its DLLs.

The private reference recordings cover History, Event, and SOC reset workflows.
Device identities, firmware inventories, timestamps, counters, and raw telemetry
remain in the local recordings, not in distributed fixtures. The recordings
contain some truncated device text. Raw export must preserve such text rather
than reconstruct it from parsed fields. Tests do not infer that truncation is
desirable or intentionally reproduce missing serial bytes.

The following is confirmed by IL and/or the supplied files. Actual adapter
timing, mode switching, and reset execution require hardware validation.

## Connection and framing

`ConnConfig.xml` enables console-mode switching at 1200 baud using these bytes:

```text
7E 32 30 30 31 34 36 38 32 43 30 30 34 38 35 32 30 46 43 43 33 0D
```

`ShifttoConsole` waits 500 ms after sending the frame, restores the selected
console baud rate, waits another 500 ms, then sends an empty command to find a
`pylon` prompt. The UI defaults to 115200 baud. Serial settings include 8 data
bits and one stop bit. Vendor initialization sends `login debug`, then `info`.
The Python client skips that login when synchronization already ends at
`pylon_debug>`, since redundant login can be rejected. From the base prompt it
sends login once and checks the last complete prompt, accepting a rejected
login only if the final prompt confirms debug mode. The reset script's explicit
post-reconnection login remains part of its saved transcript.

Regular response patterns recognize `pylon>` and `$$` followed by a
`pylon_debug>` prompt. History mode additionally recognizes:

```text
Press [Enter] to be continued,other key to exit
```

The Python framer recognizes both prompt variants and buffers fragmented reads.
It collects trailing bytes until a short quiet interval after a terminator,
preserving CR/LF even when a serial read splits the prompt from its terminator.
As in the original console, only one command may be outstanding.

Regular `SerialPort.WriteLine` calls send LF. The script overload with its final
boolean enabled uses `Write(command)` followed by a single CR. Pagination sends
the string CR through `WriteLine`, producing CR+LF. These are different console
actions and must not be normalized to the host OS's default newline.

After a timeout, the session requires explicit prompt resynchronization before
another nonempty command. It does not automatically repeat a command whose
outcome is unknown.

## Disconnect button

Both the menu and toolbar Disconnect buttons queue a message handled by
`MsgBackgroundWorker.OnDisconnectBatMangeSystems`. It disables scan scheduling,
waits up to ten seconds for pending scan rows to be saved when its queue is
nonempty, clears pending messages, and stops application logging.

With `IsNeedCmdQuit="true"` (the bundled connection setting), it then invokes
`Send("cmdquit", ResponsePattern.Disconnect, 5)`. That overload sends LF through
`SerialPort.WriteLine` and waits up to five seconds. The disconnect regex is just
`cmdquit`, so an echo suffices; it does not verify a new prompt or operating mode.
The port is closed/disposed in a finally block even after a command error or
timeout. The separate shutdown operation sends `shut` twice; disconnect sends no
shutdown, reset, or EEPROM command.

Some firmware responds with `Unknown command` when sent `cmdquit`. The Python
client classifies that response as a rejection and logs it explicitly, while
retaining the original echo-based wait and unconditional port cleanup. A received
echo therefore does not establish that console mode actually ended.

The Python client performs this command and wait on `BatteryClient.close()` and
context-manager exit, using a separate disconnect boundary that does not require
a prompt. It sends `cmdquit` once even if the previous command left framing
unsynchronized, without repeating the previous command or adding synchronization
traffic. Disconnect/port-close errors are logged without masking an earlier
failure, and repeated closes are idempotent. Failed connection setup uses the
low-level `ConsoleSession.close()` to release the port immediately.

Python operations already share a synchronous session lock, and report writes are
flushed before their methods return. There is no background scan queue requiring
an additional ten-second drain wait. Disconnect responses are not vendor report
content; they are visible in explicitly enabled serial tracing.

## Report writer

`DataStorage.SaveLogDataToTxt` opens a new or appended file and constructs a
`StreamWriter` with `Encoding.Unicode`, then calls `WriteLine(response)`.
On Windows this yields:

- One UTF-16LE BOM at the beginning of the file.
- The response text exactly as accumulated from the console.
- An additional CRLF after each saved response.

The Python writer emits those bytes explicitly on every platform, flushes after
each response, and exclusively creates output files to prevent accidental
mixing of sessions. It does not prepend commands: command echoes come from the
console itself. Recovery metadata is a separate UTF-8 JSON file.

The History/Event button handlers append `.txt` to the selected filename,
explaining `.txt.txt` in the supplied reports. The reset button embeds a space
in `_resetsoc _`; both quirks are retained in generated default filenames.

## History and Event buttons

1. Save `info`.
2. Save `stat`, reading `HisData Items` for History or `Data Items` for Event.
3. Save `data history` or `data event`.
4. For offsets `0, 15, 30, ...` below the count, save
   `datalist history dtls OFFSET` or `datalist event dtls OFFSET`.
5. After each detailed block, save an empty command's response, sending LF.
   On the supplied firmware this exits the pagination prompt. The final block
   also gets this empty command, even when it already returned to the prompt.

The count is needed only to schedule blocks, not to render their data. Unknown
columns and firmware-specific fields therefore remain intact in reports.
Missing/invalid counts fail collection instead of pretending the report is empty.

## SOC reset button

The user-defined-data button loads `Script.xml` and names its output `resetsoc`.
`OnGetUserData` executes the following sequence:

1. `stat` (CR).
2. `datalist event 0` (LF), then CR+LF continuation until the console prompt.
3. `datalist misc 0` with the same continuation behavior.
4. `datalist history 0` with the same continuation behavior.
5. `info` (CR); capture its barcode for a subsequent command.
6. `setlowcfg` (CR).
7. `eepe 0` (CR).
8. `trst` (CR), waiting for `pylon>`.
9. The `login` script pseudo-command runs console switching/reconnection. On
   success it contributes no text to the report.
10. `login debug` (CR).
11. `tbar ORIGINAL_BARCODE` (CR).
12. `info` (CR).
13. `setlowcfg` (CR).

`RetrieveHistoryData` sends at least one CR+LF after each initial datalist reply,
including empty and unsupported replies. The provided firmware rejects event
and miscellaneous datalist commands in this script; those responses and their
following prompts are retained. Ordinary report commands treat rejected
commands as failures.

The Python workflow additionally saves durable recovery information before
clearing EEPROM, validates the barcode before mutation, and checks identity
after restoration. It never retries `eepe`, `trst`, or `tbar` automatically. It
does not reselect the previous module address after reset, since a reset can
change it. Failure after a mutating write requires inspection
of the saved recovery state; there is no automatic resume command.

## Monitoring

`OnGetpwrs` uses `getpwr` for a single module, or `getpwr N` for addressed reads,
plus `pwr` for the module table. Extended queries include `pwr N`, `pwrsys N`,
and system `pwrsys`; some are optional or disabled by configuration. Module
login uses `login N debug` with one-based module numbering.

The Python `pwr` parser accepts both tables and labeled summaries headed by
`Power N`. The latter identifies the connected module's reported address, not an
installation size. Labels include `Voltage`, `Current`, `Temperature`, `Coulomb`,
`Total Coulomb`, and status fields. Voltages, currents, temperatures, and capacities
are divided by 1000; percent SOC is unscaled. Status labels are normalized to the
existing state keys, while original fields, protection labels, and event masks
remain in `raw`. A labeled block requires a numeric address and recognizable
voltage; optional missing fields remain absent. Its event masks are not assumed
to share the hash-format error-code bit mapping.

A single returned module uses bare `getpwr` and `pwrsys` unless an explicit
`--module` was selected, independently of that module's reported address. No
preceding addresses are enumerated. Multiple returned modules retain addressed
queries. The snapshot merge keeps capacity from `pwr` if detailed reads omit it.
`Unknown command` replies are recognized as unsupported; optional `pwrsys` can
then be omitted without losing the other snapshot readings.

`RegoutConfig.xml` describes voltage/current/temperature scaling by 1000.
`getpwr` begins with eight hash-delimited fields: voltage, current, temperature,
capacity, basic state, voltage state, current state, temperature state. Cell
records contain voltage, temperature, voltage state, temperature state.
The configured trailing fields are error code and cycle count. Known error bits
are decoded using `Indicator.xml`, and unknown bits remain visible. The library
also preserves the full hash sequence, including other firmware trailers.

Definitions cannot be mechanically reused: .NET variable-length lookbehinds
are incompatible with Python's standard regex engine, some XML declarations
misidentify their encoding, some type definitions are inconsistent, and
configuration limit expressions contain apparent typos. Python parsing uses
labels/headers and retains unrecognized fields rather than substituting zero.

## Support collection wrapper

`collect` reuses the identity, History, Event, and snapshot operations in that
order, holding the session lock across the run. History/Event command sequences
and UTF-16 transcript serialization are unchanged, including their repeated
`info`/`stat` requests. No new battery commands are introduced. Normal disconnect
runs afterward and remains outside report content.

The wrapper supports repeated physical connections to different modules with one
shared flat output directory. Complete support exports routed to a remote module
have not been verified. Consequently, `collect` rejects addressed module selection;
the existing monitoring and standalone command interfaces remain available.

Each invocation reserves its own manifest using a UTC timestamp and UUID-based
run ID. JSON artifacts share that run ID, while transcripts keep their existing
barcode/timestamp filenames. Exclusive artifact creation prevents replacement of
earlier files, and manifest references never claim a colliding report from an
earlier run as this run's partial output.

Manifest format version 1 records the application version, run ID, start/end times,
overall status/completeness, device identity, and ordered step records. Step records
contain a name, status, relative artifact filename, reported record count where
available, and failure type/message. Status transitions are `pending` → `running`
→ `complete`, `failed`, or `interrupted`; later steps become `skipped` after a
failure or interruption. Updates replace the run's manifest atomically.

The first failed step ends collection without additional collection commands or
automatic retries. Existing artifacts remain available, and read-response payloads
are not copied into manifest errors. Expected operational failures return an
incomplete collection result; interruption is re-raised after finalization. Fatal
manifest I/O failures are raised and can leave the last valid manifest indicating
an unfinished run. Serial packet traces are only produced when explicitly enabled.

## Acceptance still requiring hardware

- Confirm 1200-to-115200 switching, serial adapter behavior, and debug login.
- Compare a newly collected History and a nonempty Event report with BatteryView
  on the same firmware; compare structure and captured device data, allowing
  counters/timestamps to change between runs.
- Validate module selection with a chain and live `pwr`/`getpwr` readings.
- Exercise the explicitly requested reset on an appropriate device, check barcode
  restoration and changed address, and retain both recovery state and transcript.
- Have Pylontech confirm that newly generated reports meet its requirements.

Replay equality proves serialization and command sequencing for recorded
responses; it cannot prove physical operation or vendor acceptance.
