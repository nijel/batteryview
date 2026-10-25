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

1. Save `info`, `stat`, then `data history` or `data event`.
2. The original uses the latest `Item Index + 1` as its count. Python does the
   same and falls back to a valid `stat` counter when that index is absent.
   Disagreements are logged; an indeterminate count is an error.
3. For offsets `0, 15, 30, ...`, try `datalist KIND dtls OFFSET`.
4. Explicit rejection switches to `datalist KIND OFFSET`, at the same offset.
5. After each page, save the response to a blank LF, including the final page.
6. In fallback mode, save `data KIND INDEX` for each record on the page.

The original's `RegoutHistoryData` changes `HistoryGetInfo.DtlsMode` on rejection;
`OnGetHistoryData` and `OnGetHistoryDataItem` implement both formats for both kinds.
The original always queues 15 individual reads on the last page, even beyond the
count. Python bounds those reads and verifies each returned index instead.

Detailed pages are checked for ordered record coverage. Some firmware includes a
sixteenth record overlapping the next page; that boundary overlap is accepted.
Other missing, repeated or unexpected indices fail collection and preserve partial
output. The private historical History capture has three missing records, so it
is now a negative completeness reference rather than proof of a complete export.
No response text is reconstructed or modified to repair it. Unknown columns and
firmware-specific fields remain intact in raw transcripts.

Full reports and SOC reset reject addressed selection before any operation.
The original uses explicit addressed identity/history-item commands in separate
UI paths; numbered login is a parameter/protection authorization helper, not a
verified redirection mechanism for bare report commands.

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
following prompts are retained. Ordinary report commands permit the specific
detailed-list fallback described above; other rejections remain failures.

The Python workflow additionally saves durable recovery information before
clearing EEPROM, validates the barcode before mutation, and checks identity
after restoration. It never retries `eepe`, `trst`, or `tbar` automatically. It
does not reselect the previous module address after reset, since a reset can
change it. Failure after a mutating write requires inspection
of the saved recovery state; there is no automatic resume command.

## Firmware evidence for SOC reset

For all registered commands, access modes and per-image handler addresses, see the
[firmware command reference](firmware-commands.md). The
[handler supplement](firmware-behavior.md#what-the-persistence-callbacks-actually-do)
resolves immediate statistics/extended-state saves and record-write behavior.

Static inspection of the user-supplied firmware archive now establishes the erase
scope for two specific images. Neither firmware was executed or flashed. The
archive also contains an updater and example update logs; none of those logs or
firmware payloads are included in this repository.

| Image | Bytes | SHA-256 |
| --- | ---: | --- |
| `US_E2_V2.5_Crc.bin` | 217088 | `897c3326ab8905df75a7297905112958a07c0a2cbb0592e0ecc274b886b0c82e` |
| `US_C_V3.1_Crc.bin` | 242688 | `5450e3bd884ae63549fc3b278ecccc0126227234f7148c7961542755cbad2d7d` |

Both are readable ARM Thumb images mapped at `0x08003800`. The inferred base is
supported by command-table string/function pointers and valid reset-vector code.
Addresses below are runtime addresses; subtract the base to obtain file offsets.
The E2 board tag at file offset `0x418` is `US2000C_NF4`; the other image's tag is
`US2000C`. These findings establish behavior in these images, not automatically
in every installed firmware revision.

### Erase and restart

The command table describes `eepe` as `EEPROM erase - eepe [chip]`. In E2 V2.5,
the handler at `0x08010410` accepts logical chip 0 or 1 and calls `0x080101ee`.
That routine zeroes a 16-byte buffer through `0x08017dcc`, then writes that buffer
128 times at offsets `i << 4`. Thus `eepe 0` attempts to overwrite **all 2048 bytes
of logical EEPROM chip 0 with zero**, rather than clearing a single SOC field.
Write statuses are combined for the command result. The driver at `0x0801004a`
checks the 2048-byte boundary and handles page writes/readiness waits.

C V3.1 has the same loop: handler `0x080103dc`, erase routine `0x08010142`, zero
helper `0x08017c50`, and EEPROM write routine `0x0800ffa2`. Erasing chip 0 does
not itself erase chip 1, external history flash, or executable firmware. This is
not a guarantee that restart will leave all other storage unchanged: startup
routines also initialize and update persistent data.

In E2 V2.5, `trst` at `0x0802b024` performs preparatory calls and ultimately invokes
`0x0801719c`, then `0x08016546`. The latter writes the AIRCR register at
`0xe000ed0c`, preserving priority grouping and adding `0x05fa0004`: the keyed
Cortex-M `SYSRESETREQ` operation. This is a processor/system reset, not merely
closing a console session. See [Arm's reset documentation](https://arm-software.github.io/CMSIS_5/Core/html/group__NVIC__gr.html).

### Confirmed E2 persistent fields

The following addresses are **EEPROM byte offsets**, not firmware addresses.
They are established by tracing both EEPROM reads/writes and the firmware's
labeled output. A cleared stored field may subsequently be recomputed or updated;
this table does not assert that every displayed value remains zero after restart.

| Chip | Offset | Size | Evidence / meaning |
| ---: | --- | ---: | --- |
| 0 | `0x021` | 16 | Barcode: `tbar` at `0x0802b080` writes it at `0x0802b130` and reads it back at `0x0802b13c`. This explains BatteryView's explicit barcode restoration. |
| 0 | `0x38f` | 124 | Saved statistics block: startup reads it into the per-module structure at `+0x88` through `0x08012654`–`0x0801265e`; `stat` at `0x08008a60` labels its fields. |
| 0 | `0x38f` / `0x391` | 2 each | Event/history item counts in that block. Clearing these affects record bookkeeping even though the erase handler does not erase the external log payloads. |
| 0 | `0x39f` | 2 | Saved `Pwr Percent`, read for `stat` at `0x08008c9e`. |
| 0 | `0x3a1` | 4 | Saved `Pwr Coulomb`, reconstructed from two halfwords at `0x08008caa`–`0x08008cae`. |
| 0 | `0x3df` | 2 | Cycle-count field, displayed as `CYCLE Times` at `0x08008c82`–`0x08008c90` after masking its high bit. |
| 0 | `0x3ef` | 4 | Discharge-capacity accumulator, labeled `Dsg Cap` at `0x08008cbe`–`0x08008cca`. |
| 1 | `0x021` | 8 | Configured nominal capacity, read by `totalcoul` at `0x08029f5e`–`0x08029f80`; its check byte is at `0x029`. Startup validates the supported capacity constants and falls back to a default if invalid. This is separate from chip-0 SOC/counter storage. |

The erased statistics block also contains charge/discharge and fault counters.
Chip 0 holds additional metadata/settings, so this procedure should be described
as clearing a persistence area used by SOC and diagnostics, not a narrowly
scoped percentage reset. There is a separate `setsoc` command in both command
tables; the bundled BatteryView reset script does not call it.

The evidence explains why the procedure can discard stale SOC/coulomb state and
why support wants reports beforehand. It does **not** yet establish the exact
post-reset SOC reconstruction algorithm, whether every parameter or calibration
value survives, whether log records can be recovered after their bookkeeping is
cleared, or why support requested the reset for a particular module. Those need
further firmware analysis and/or manufacturer confirmation.

## Monitoring

`OnGetpwrs` uses `getpwr` for a single module, or `getpwr N` for addressed reads,
plus `pwr` for the module table. Extended queries include `pwr N`, `pwrsys N`,
and system `pwrsys`; some are optional or disabled by configuration. Module
authorization for parameter/protection operations uses `login N debug`, while
identity and monitoring reads include their addresses explicitly.

The Python `pwr` parser accepts both tables and labeled summaries headed by
`Power N`. The latter identifies the connected module's reported address, not an
installation size. Labels include `Voltage`, `Current`, `Temperature`, `Coulomb`,
`Total Coulomb`, and status fields. Voltages, currents, temperatures, and capacities
are divided by 1000; percent SOC is unscaled. Status labels are normalized to the
existing state keys, while original fields, protection labels, and event masks
remain in `raw`. A labeled block requires a numeric address and recognizable
voltage; optional missing fields remain absent. Its event masks are not assumed
to share the hash-format error-code bit mapping.

Python's default auto mode acquires local `getpwr` first, then discovers modules
with `pwr`. Single mode uses the local reading and profile-enabled extensions;
parallel mode starts with the table and addressed detail reads. Explicit
`--module` reads use `info N`, `getpwr N` and profile-enabled `pwr N`/`pwrsys N`.
Profiles for UP2500 and 2500LFP2 use unaddressed `pwrsys` and disable the optional
`pwr` extension in single mode. System `pwrsys` is read once where enabled.
A single labeled address does not imply that preceding addresses exist. The snapshot merge keeps capacity from `pwr` if detailed reads omit it.
`Unknown command` replies are recognized as unsupported; optional `pwrsys` can
then be omitted without losing the other snapshot readings.

`RegoutConfig.xml` describes voltage/current/temperature scaling by 1000.
`getpwr` begins with eight hash-delimited fields: voltage, current, temperature,
capacity, basic state, voltage state, current state, temperature state. Cell
records contain voltage, temperature, voltage state, temperature state.
The configured trailing fields are error code and cycle count. Known error bits
are decoded using `Indicator.xml`, and unknown bits remain visible. The library
also preserves the full hash sequence, including other firmware trailers. Native
profiles share the eight scalar/four cell-field layout; US2K uses the last trailer
pair, while the other supported layouts use the first pair after the cell block.
Labeled replies normalize module states, SOC and error codes too. Extrema use
zero-based cell indices; system aggregates require values from every observed
module rather than silently treating missing values as zero.

Bundled native profiles are selected by `Device name`, with an explicit override
and a generic fallback for unknown models. They encode supported fields/scales,
extension enablement and addressing from the default and model-specific XML.
They do not execute XML or enable the original's disabled SOH queries.

Definitions cannot be mechanically reused: .NET variable-length lookbehinds
are incompatible with Python's standard regex engine, some XML declarations
misidentify their encoding, some type definitions are inconsistent, and
configuration limit expressions contain apparent typos. Python parsing uses
labels/headers and retains unrecognized fields rather than substituting zero.

## Command meanings from BatteryView's controls

This section adds **application intent**, alongside the firmware contracts in
[the parameter reference](firmware-parameters.md). Evidence is the managed code
and bundled configuration in `BatteryView_3.0.28_1`, not successful execution on
every supported model. Reviewed `BatteryView.exe` SHA-256:
`af69bbf5118856b5a72b07bd2d773a4565062ade3932c53cf9fc05205bcd45b6`.
Method RVAs below identify this assembly, not MCU addresses.

The relevant files under the application's `Configs/` directory are
`ParameterConfig.xml`, `Params/*_ParameterConfig.xml`, `CtrlConfig.xml`,
`Controls/*_CtrlConfig.xml`, `SetItem.xml`, `Controls/*_SetItem.xml`, and
`Indicator.xml` / `Indicators/*_Indicator.xml`. Labels describe intended use;
`CmdHeader` / `CmdBody` describe what the application constructs. Neither is
proof that the reviewed E2/C firmware implements that spelling. Original logs,
identities and telemetry were not used for this additional analysis.

### Parameter vocabulary and units

The labels consistently distinguish **protection trips** from **warning/alarm
thresholds**. A release value is a recovery threshold, not another trip level.
This makes the abbreviated selectors easier to understand:

| Selector family | Application description |
| --- | --- |
| `pov/povr`, `puv/puvr` | Module over-/under-voltage protection threshold and release. |
| `phv/phvr`, `plv/plvr` | Module high-/low-voltage alarm threshold and release. |
| `pslp` | Module sleep/shutdown voltage. |
| `bov/bovr`, `buv/buvr` | Cell over-/under-voltage protection threshold and release. |
| `bhv/bhvr`, `blv/blvr` | Cell high-/low-voltage alarm threshold and release. |
| `bslp` | Cell shutdown voltage. |
| `bot/botr`, `but/butr` | Battery over-/under-temperature protection and release in the US3000C/Forcel_C definitions. Their UI IDs retain older names `COT/COTR`, `CUT/CUTR`. |
| `bht/bhtr`, `blt/bltr` | Battery high-/low-temperature alarm and release in those definitions. UI IDs retain `CHT/CHTR`, `CLT/CLTR`. |
| Legacy `cot/cotr`, `dot/dotr`, `cht/chtr`, `dht/dhtr`, `clt/cltr`, `dlt/dltr`, `cut/cutr`, `dut/dutr` | Charge/discharge temperature protection or alarm families in older configuration files; **not aliases proven in E2/C**. |
| `eht/ehtr` | Environment high-temperature alarm and release. |
| `mot/motr` | Board over-temperature protection and release, according to the Forcel_C labels. This is board-level intent, not identification of a particular physical sensor. |
| `coc`, `doc` | Charge/discharge overcurrent protection threshold. |
| `coca/cocar`, `doca/docar` | Charge/discharge overcurrent alarm and alarm release; see the copied-selector bug below. |
| `ocd`, `ocr` | Overcurrent protection delay and recovery time, labelled milliseconds. |
| `COC2`, `DOC2`, `OC2D`, `OC2R` UI fields | Secondary charge/discharge overcurrent thresholds and secondary delay/recovery. These have empty command bodies and are marked **read-only** in the US3000C profile. |
| `SC`, `scd`, `scr` | Short-circuit current threshold, delay and recovery. `SC` is also read-only in that profile. |
| `uvtime` | Under-voltage shutdown time, labelled seconds. |
| `shuttime` | Idle shutdown time, labelled hours in the legacy UI. E2 instead reports `NO IDLE SHUT`; the UI does not establish an implemented timer. |

`BMUParamterItem.GetSetCmdString` (RVA `0x2a3f0`) multiplies numeric UI values by
configured `Accuracy` **when the numeric/HasLimit branch applies**. The reverse
parser `RegoutParamValue` (`0x2a81c`) divides by that factor, except for the
`RECINV` parameter type. Typical voltage, current and temperature factors are
1000, explaining V→mV, A→mA and °C→mC. For example, an invented UI value of
54.2 V with factor 1000 becomes integer `54200`, not a decimal-volts operand.
The default factor is 1. An `Accuracy` attribute on a `HasLimit="false"` row is
not sufficient to prove scaling: the legacy `shuttime` row has factor 2 but
bypasses this numeric-scaling branch. Use firmware units for implementation.

### Named actions and what they actually send

| UI action | Application command / meaning |
| --- | --- |
| Set System Time | `time` with a supplied value; the builder has a dedicated TIME branch. |
| Clear EEProm | `eepe 0`; intended to clear external EEPROM, not erase event/history flash. The firmware analysis establishes its exact overwrite behavior. |
| Write module barcode | `tbar` plus the supplied identity. No original identity is embedded in this documentation. |
| Clear AFuse Error | `ctrl afuse off`. The Chinese label explicitly refers to a **three-terminal fuse**. This establishes the application's intended fault-clear action, not physical repair of a fuse or proof of its circuitry. |
| Turn on/off aging log | `ctrl agelog on/off`; ageing/test recording control, separate from clearing stored records. |
| Manual charge / discharge | `ctrl cfet on/off` / `ctrl dfet on/off`; charge/discharge power-path control. |
| Manual buzzer / heater | `ctrl buzz on/off` / `ctrl heat on/off`; the heater label refers to a heating film. Availability depends on the board. |
| Default Parameters | `config default`; restore defaults, not show a default-value report. |
| LED Check | `tled`, followed by an operator question about the LED sequence. |
| Cell balance check | `tbld ffff` twice, followed by an operator question about the balancing LEDs. Two identical sends do **not** establish an on/off toggle. Both reviewed firmware tables allow only bare `tbld`; the extra mask is a compatibility mismatch. |

These descriptions come from `SetItem.xml`, the model-specific SetItem files and
`CtrlConfig.xml`. In E2, for example, `ctrl heat` reports OFF and its setters
have no implemented effect; the heating-film label does not override that
finding. `prot` entries separately enable/disable protections and alarms;
`ctrl` entries request manual controls. Disabling a protection entry is not the
same operation as clearing its recorded event or restoring its threshold.

### “Current sensor reset” is calibration, not the SOC-reset script

The default, UP2500 and US2KBPL action lists send `ctrl cfet off`, wait 2 s,
run **`soccal bdoffset`**, send `ctrl cfet on`, wait 3 s, then run
**`soccal current 10000`**. The explicit waits are empty-command script items;
they send no console command. The offset/current steps have Time values 60/30.
The US5000 SetItem variant replaces that sequence with **`currcal 10000`**,
Time 30. The 2500LFP2 file includes the older sequence under both ADC calibration
and current-sensor-reset labels.

The prompt describes an external constant-current calibration fixture. Its
54 V / 10.03 A text is bundled script text, **not a validated fixture requirement
for every listed model**; the sent reference remains 10000 mA. This is different
from the EEPROM-clear/restart/barcode-restoration [SOC-reset workflow](#soc-reset-button).
The C firmware's selector list does not recognize `bdoffset`; its traced forms
include `ccoffset`, `bdoffsetP1` and `bdoffsetP2`. Do not substitute between
these automatically. E2's actual `currcal` path is documented in the firmware
reference, including its failure to reject references other than 10000 before
mutation.

`SendEquipmentCommand` (RVA `0x32e04`) uses the configured Time multiplied by
1.5, truncated to an integer, as the send timeout. An empty command sleeps
Time × 1000 ms. Therefore Time is a UI workflow/timeout field, not necessarily a
required delay after every nonempty command or a firmware execution duration.
Pre-/post-prompts pause for an operator; visual checks are not autonomous
measurements.

### MOS-failure monitoring and nominal-capacity actions

`OnSetMosFail` (`0x2dc50`) is more specific than its name suggests:

1. Read **`bat`** and extract four-digit cell voltages from matched rows.
2. Reject a parsed cell **>= 4200 mV** or a parsed sum **>= 60000 mV**.
3. Send **`ctrl mostest on`** and require the success footer.
4. Query **`ctrl mostest`**, accepting a response containing **`ON`**.

This enables the [background fault checks](firmware-behavior.md#mostest-enables-active-background-fault-checks-e2);
it is not the one-shot `tmos` test or a generic fault-clear command. The app
creates an SOC regex but does not apply an SOC bound in this inspected check.
Its row regex does not verify the expected cell count: zero matched rows leave
a zero sum and can reach the enable branch. A future implementation should
require a complete, correctly identified cell table rather than copy that
acceptance bug. The UI voltage checks also do not establish the conditions
under which the firmware's background actions are safe on other boards.

`OnSetCoul` (`0x2da84`) sends **`totalcoul supplied_value`**, checks for `pass`,
then queries **`totalcoul`** and divides its reported mAh integer by 1000 for an
Ah display. This supports the nominal-capacity interpretation. It does not
make the command an arbitrary SOC adjustment: the firmware setter also changes
model/default configuration, as described in the firmware supplement.

### Parameter/protection command construction and acknowledgement

`Login` (`0x301c0`) translates zero-based UI device index `i` into
`login i+1 debug`, caches an `IsLogin` flag when the response contains `_debug`,
and skips the send for already-marked/offline devices. This is weaker than
verifying the final prompt after every exchange.

For per-item writes, `GetSetCmdString` constructs local
`config selector value` or addressed `config N selector value` for combined
commands, subject to `IsSupportUnit`. Control/protection items use the analogous
`ctrl` / `prot` headers. Their numeric device index is not an additional value
argument; the firmware frontend must support addressed routing for that command.
Set-all processing loops over online modules and logs in to each; it is not
proof of an atomic broadcast operation.

The collection-level builders `BMUParamItemCollection.GetCommand` (`0x2aac8`)
and `BMUContorlItemCollection.GetCommand` (`0x2b658`) select refresh/default/save
strings. A one-word query becomes `config N`, `ctrl N` or `prot N` for N > 1.
For multiword strings, however, both call `.Insert(...)` and **discard its
returned string**. They therefore return bare `config save`, `config default`
or `prot default` despite receiving another module address. Do not copy this
addressing bug or assume numbered login redirects otherwise bare commands.

`RefreshParam` (`0x30584`) logs in, reads each configured category and parses its
fields. `OnSaveConfig` (`0x30670`) and `OnDefaultConfig` (`0x3079c`) send the
category's configured action strings. `OnRefreshProtection` (`0x30d94`) queries
the control/protection categories; it does not itself modify their settings.
`BMUParamterItem.CheckSetResult` (`0x2a678`) merely searches for
`Command completed successfully`. The UI can update its cached value from the
requested value after that match, without reading back that individual setting.
This is application acknowledgement, not proof of persistence or effective
protection behavior. The firmware reference remains the authority for each
setter's actual return paths and storage effects.

### Fault labels are tied to their source field

`Indicator.xml` and the US3000C/US2KBPL indicator variants label the following
**`getpwr` ERRORCODE StatusKey indices**:

| Index | Mask | Vendor label, paraphrased |
| --- | --- | --- |
| 0 | `0x001` | Reversed input polarity. |
| 1 | `0x002` | Input overvoltage. |
| 2 | `0x004` | Hardware-version error. |
| 3 | `0x008` | Battery monitor IC error. |
| 4 | `0x010` | HIB error; acronym not expanded by the configuration. |
| 5 | `0x020` | Temperature-sensor error. |
| 6 | `0x040` | Voltage-sensor error. |
| 7 | `0x080` | I²C error. |
| 8 | `0x100` | Address-allocation error. |
| 9 | `0x200` | Internal communication error. |
| 10 | `0x400` | Charge MOS failure. |
| 11 | `0x800` | Discharge MOS failure. |

The UP2500 indicator file additionally names index 12 (`0x1000`) as fuse failure.
These are vendor UI meanings for that configured field/profile. They do not
establish that an event's `System Fault`, a `pwr` event mask, and every firmware's
`getpwr` trailer share the same bit layout. Preserve the source and raw value
before applying a label.

### Configuration defects and unsupported model commands

The XML is a description source, not a safe command generator:

- US3000C's `DOCA` / `DOCAR` entries use **`coca` / `cocar`** as command bodies,
  despite discharge-alarm labels. Those bodies address **charge** settings in
  the reviewed firmware. The legacy `DOTR` entry similarly uses `cotr`.
- Several limits contain malformed `ax(...)` expressions, copied voltage bounds
  on temperature entries, or self-referential limits. Firmware predicates take
  precedence over those UI limits.
- `Forcel_C` contains board-temperature entries such as `mht`, `mhtr`, `mlt`,
  `mltr`, `mut`, `mutr` without corresponding E2/C config selectors. The file's
  existence proves intended support for that family, not compatibility here.
- The 2500LFP2 SetItem file describes **`tclrpermflg`** as clearing permanent
  protection flags and **`ctrl canprt off`** as disabling an external-communication
  timeout. Neither spelling is established by the reviewed E2/C tables. Keep
  them as model-specific application evidence, not new aliases.
- Secondary-overcurrent UI fields being read-only do not remove the firmware's
  `oc2d` setter. They explain why the application does not exercise that setter;
  they do not resolve its downstream negative-delay behavior.

## Support collection wrapper

`collect` reuses the identity, History, Event, and snapshot operations in that
order, holding the session lock across the run. It uses the same History/Event
command selection and UTF-16 serialization as standalone exports, including
repeated `info`/`stat` requests. Normal disconnect
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

The first failed step ends collection. By default reads are not retried;
`read_retries=1` or `2` enables bounded recovery of explicit reads after a debug
prompt is verified. Pagination continuations and reset operations are never
retried. Failed report attempts and resynchronization replies remain in reports. Existing artifacts remain available, and read-response payloads
are not copied into manifest errors. The CLI prints an escaped, bounded response
tail from the failed exchange, including failures returned inside collection;
that diagnostic can contain private data. Successful raw traffic remains opt-in. Expected operational failures return an
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
