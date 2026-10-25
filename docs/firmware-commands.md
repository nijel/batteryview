# Firmware console command reference

This reference covers **all registered text-console command names** in the two
reviewed firmware images: **96 names total**, with 81 in E2 V2.5 and 91 in C V3.1.
It is an implementation reference, not a claim that every command is available
on every Pylontech model or firmware revision. Binary inverter/bootloader
protocol opcodes and unregistered internal routines are outside this inventory.

The source is the firmware supplied in `Firmwareupdate-Pylontech-US2000_3000-V6_1.zip`.
No commands were sent to hardware to prepare this document. Firmware binaries,
updater executables and the archive's example logs are not included in the repository.

## Evidence and reproduction

The [machine-readable catalog](firmware-commands.json) preserves every local and
remote table entry: command name, exact firmware help, maximum token count,
required access mask, handler address and table-record offset, plus decoded
selector tables for config/prot/ctrl/datalist. The firmware
hashes distinguish these observations from guesses based on another revision.
The [parameter and effects reference](firmware-parameters.md) documents handler-derived
argument bases, ranges, defaults, storage effects and unresolved contracts.
The [handler/persistence supplement](firmware-behavior.md) adds full record-query
forms, callback storage layouts, calibration and hardware-test behavior, with
[reproducible decoded metadata](firmware-details.json).
[Reset analysis](protocol.md#firmware-evidence-for-soc-reset) provides the deeper
EEPROM and restart findings.

| Image | Board tag | SHA-256 | Local / remote records |
| --- | --- | --- | --- |
| US_E2_V2.5_Crc.bin | `US2000C_NF4` | `897c3326ab8905df75a7297905112958a07c0a2cbb0592e0ecc274b886b0c82e` | 79 / 12 |
| US_C_V3.1_Crc.bin | `US2000C` | `5450e3bd884ae63549fc3b278ecccc0126227234f7148c7961542755cbad2d7d` | 90 / 12 |

Both images use base address `0x08003800` and ARM Thumb handlers. Each command
record is seven little-endian 32-bit words (28 bytes):

```text
name pointer, maximum token count, Thumb handler pointer, help pointer,
reserved zero, reserved zero, required access mask
```

The mask is the **last** word, not the word before the name pointer. Table
walking stops at a null name pointer. Function addresses in the JSON clear the
Thumb low bit; subtract the image base for file offsets.

Regenerate the JSON with Python's standard library:

```sh
python scripts/extract_firmware_commands.py Firmwareupdate-Pylontech-US2000_3000-V6_1.zip > /tmp/firmware-commands.json
cmp docs/firmware-commands.json /tmp/firmware-commands.json
```

The extractor also accepts the individual `.bin` files, requires a reviewed
SHA-256, checks both table sentinels, and independently scans the complete image
for overlooked command records. It skips unrelated archive entries, including logs.

## Notation and dispatch rules

`L` means registered in the local table; `R` means registered in the remote table.
`—` means absent from that image's command tables. A local and a remote entry can
have different metadata, so the JSON retains both rather than collapsing them.

| Mode code | Required mask | Available in session modes |
| --- | --- | --- |
| U | `0x01` | User, config, equipment, debug |
| C | `0x03` | Config or debug |
| E | `0x05` | Equipment or debug |
| D | `0x0f` | Debug only |

E2 `help` at `0x08024d66` and local/remote lookup at `0x08024cbe`/`0x08024d12`
require `(session_mask & command_mask) == command_mask`. `login` at `0x08025578`
sets masks 3/5/15 for config/equipment/debug; `logout` returns to mask 1. The C
handlers have the corresponding mask checks. Access does not describe safety:
for example, `trst`, `shut` and `updata` are U commands.

The firmware's **maximum token count includes the command name**. It is not a
minimum-argument count: handlers decide whether no-argument calls read status or
fail. Do not infer valid arguments merely from that maximum. Firmware help
contains omissions and inconsistencies highlighted below. Syntax in the tables
is a compact guide; exact original help and limits are in the JSON. `<...>`
marks a value/choice and `[...]` an optional or incompletely specified argument.
Numeric base, value units, signedness, range and persistence are not globally
uniform and remain unverified unless a note explicitly establishes them.

`V` means a relevant part of the handler was inspected, with confirmed details
below; it does not mean all branches and arguments have been validated. `H`
means the description is based on the registered help and command name. Unknown
acronyms and undocumented argument meanings are left unresolved.

## Command inventory

### Session and communications

| Command / compact syntax | Purpose | E2 | C | Evidence |
| --- | --- | --- | --- | --- |
| `help [command]` | List accessible local/remote commands, or show help for one name. | L:U | L:U | V |
| `login <mode>` | Enter config, equipment or debug mode from user mode. | L/R:U | L/R:U | V |
| `logout` | Return to user mode. | L/R:U | L/R:U | V |
| `ci` | Show current communications information. | L:D | L:D | H |
| `ct <port>` | Dump a buffered protocol frame for decimal port 0 or 1. | L:D | L:D | V |
| `lg <cstm\|sys> <en\|dis>` | Control LG customer/system compatibility state. | L:D | L:D | V |
| `setprt <sma\|lg>` | Select the inverter communication protocol. | L:C | L:C | V |
| `urates <500000\|115200\|9600>` | Set the RS485 port rate; this is not the console baud setting. | L:C | L:C | V |

### Identity, measurements and status

| Command / compact syntax | Purpose | E2 | C | Evidence |
| --- | --- | --- | --- | --- |
| `info` | Show identity, firmware, barcode and module specification. | L/R:U | L/R:U | H |
| `bmicrdcfg <total-ic>` | Read battery-monitor IC configuration for the requested IC count. | L:D | L:D | V |
| `bmicrdcomm <total-ic>` | Read battery-monitor IC communication data for the requested IC count. | L:D | L:D | V |
| `bat [pwr] [index]` | Show battery/cell readings; exact selection defaults are handler-specific. | L:U | L:U | V |
| `pwr [index]` | Show module power summaries, including absent rack slots. | L:U | L:U | V |
| `getpwr [index]` | Show detailed module/cell readings in hash-delimited form; checks optional module selection. | L:U | L:U | V |
| `pwrsys [argument]` | Show system status or selected module charge/discharge recommendations. | L:E | L:E | V |
| `soh [addr]` | Show state of health; remote-only in E2, local and remote in C. | R:U | L/R:U | V |
| `tsoh` | Read-only SOH event-count test; C only. | — | L:E | V |
| `disp [selection...]` | Select background module/cell display; zero stops it. | L:U | L:U | V |
| `euro [arguments...]` | Euro metrics report, optional module selection, or mutating clear. | L:U | L:U | V |
| `eurostub [arguments...]` | Report, initialize or inject runtime Euro test slots. | L:U | L:U | V |

### Recorded data and counters

| Command / compact syntax | Purpose | E2 | C | Evidence |
| --- | --- | --- | --- | --- |
| `stat` | Show record counts, SOC/coulomb fields and operating/fault counters. | L/R:U | L/R:U | V |
| `statc` | Clear most runtime statistics, preserving selected counters; invokes a state callback. Not EEPROM erase. | L/R:C | L/R:C | V |
| `data <kind> [item]` | Show a recorded item; the no-item/default path is handler-dependent. | L/R:U | L/R:U | V |
| `datalist <kind> [selection...]` | List recorded data; handler also supports the unadvertised dtls form. | L:U | L:U | V |
| `datac [event\|history\|event_log\|use]` | Clear record metadata; explicit event/history also enters flash erasure, while bare form resets both counts. | L:C | L:C | V |
| `save [event\|history]` | Request a record; defaults to event. | L:D | L:D | V |
| `log [data]` | Show internal diagnostic log information. | L:U | L:U | V |
| `logc` | Clear internal log count/wrap bookkeeping; E2 writes chip-0 offset 0x387. | L:C | L:C | V |
| `logt <data>` | Generate test log data. | L:D | L:D | V |
| `tclear` | Clear record indices and runtime statistics; persist both state blocks. | L:E | L:E | V |
| `tcycle [cycle-times]` | Set/test the cycle-count value; do not treat as a read. | L:D | L:D | V |

### Configuration, protection and SOC

| Command / compact syntax | Purpose | E2 | C | Evidence |
| --- | --- | --- | --- | --- |
| `config [key] [values...]` | Read/change protection and scheduling parameters; includes save/default actions. | L/R:C | L/R:C | V |
| `prot [key] [en\|dis]` | Read/change protection enablement; includes default and smart-charge controls. | L/R:C | L/R:C | V |
| `ctrl [target] [value]` | Read/control FETs, outputs and test flags; handler supports more targets than help lists. | L/R:C | L/R:C | V |
| `couls [iah\|vah\|asic\|default]` | Select/report coulomb calculation mode; registered only in the remote table. | R:D | R:D | V |
| `autoswitch [1\|0]` | Read/control automatic-switching enablement. | L:D | L:D | V |
| `setlowcfg [save\|shutsoc\|sstime] [num]` | Read/set low-SOC shutdown settings; E2 save path reports unsupported. | L:D | L:D | V |
| `setsoc <0..100>` | Set per-cell runtime remaining charge/SOC; distinct from BatteryView SOC reset. | L:C | L:C | V |
| `emptyvolt [val]` | Read/set empty-voltage threshold; E2 accepts 500–3300 after u16 conversion. | L/R:C | L/R:C | V |
| `blocksoc [val]` | Read/set block-current SOC percentage; C accepts 1–100. | — | L:C | V |
| `totalcoul [val]` | Read/set configured nominal capacity; E2 accepts 50, 74 or 100 Ah and stores chip-1 data. | L:C | L:C | V |
| `time [yy MM dd hh mm ss]` | Read/set battery RTC; six date/time values when setting. | L:U | L:U | V |
| `cmudtesttime [year month day hour minute second]` | Read/write EEPROM manufacturing-test timestamp; separate from RTC. | L:U | L:U | V |

### EEPROM, external flash and memory

| Command / compact syntax | Purpose | E2 | C | Evidence |
| --- | --- | --- | --- | --- |
| `eepe <chip>` | Overwrite the selected logical EEPROM with zeros: 2048 bytes in both images. | L:D | L:D | V |
| `eepr <chip> <offset> <size>` | Read bytes: decimal chip/count, hexadecimal offset. | L:D | L:D | V |
| `eepw <chip> <offset> <value> [repeat]` | Repeat a byte; offset, value and optional repeat are hexadecimal. | L:D | L:D | V |
| `flae <chip>` | Erase selected external flash; not the same storage operation as eepe. | L:D | L:D | V |
| `flar <chip> <offset> <size>` | Read external flash. | L:D | L:D | V |
| `flaw <chip> <offset> <value>` | Write external flash. | L:D | L:D | V |
| `md <width> <address> <size>` | Dump MCU address-space contents, potentially including peripheral registers. | L:D | L:D | V |
| `mm <width> <address> <value>` | Write MCU address-space contents, potentially including peripheral registers. | L:D | L:D | V |

### Fuel-gauge registers and calibration

| Command / compact syntax | Purpose | E2 | C | Evidence |
| --- | --- | --- | --- | --- |
| `inar <offset>` | Read INA226 register; actual name differs from socr in its help. | L:D | — | V |
| `inaw <offset> <value>` | Write INA226 register; help calls this socw. | L:D | — | V |
| `inash` | Show INA226 registers; help calls this socsh. | L:D | — | V |
| `inacal <arguments...>` | INA226 current-calibration handler; help incorrectly names currcal and omits a possible argument. | L:D | — | V |
| `currcal [value]` | Separate current-calibration handler; do not alias to inacal. | L:D | — | V |
| `socr <offset>` | Read C-image fuel-gauge register. | — | L:D | V |
| `socw <offset> <value>` | Write C-image fuel-gauge register. | — | L:D | V |
| `socsh` | Show C-image fuel-gauge registers. | — | L:D | V |
| `soccfg <subclass> <offset> <value>` | Write fuel-gauge subclass/data configuration. | — | L:D | V |
| `soccal <quantity> <value>` | Calibrate voltage/current/temperature or current-counter/board offsets. | — | L:D | V |
| `socd [arguments...]` | Show fuel-gauge data; table permits two arguments absent from help. | — | L:D | V |
| `socclr [argument]` | Clear bq34z100 data flash and reload defaults according to help; separate from eepe. | — | L:C | V |
| `soct [arguments...]` | Show fuel-gauge Ra table; table permits two arguments absent from help. | — | L:D | V |
| `tsoc` | Gauge test that can run embedded programming script and reset; C only. | — | L:E | V |

### Reset, power control and firmware transfer

| Command / compact syntax | Purpose | E2 | C | Evidence |
| --- | --- | --- | --- | --- |
| `trst` | Soft system reset; E2 ultimately requests Cortex-M SYSRESETREQ. | L:U | L:U | V |
| `shut` | Request shutdown; confirmation/repetition behavior must follow the handler. | L:U | L:U | V |
| `tsoftdsg` | Run soft-discharge test routine; distinct from ordinary status reads. | L:D | L:D | V |
| `updata` | Write bootloader marker and reset; PC transfer protocol is traced in the supplement, but the receiver is absent from these images. | L:U | L:U | V |

### Manufacturing and hardware tests

| Command / compact syntax | Purpose | E2 | C | Evidence |
| --- | --- | --- | --- | --- |
| `tbar <barcode>` | Validate/write barcode; E2 requires 16 alphanumeric characters and checks selected cell-count cases. | L:E | L:E | V |
| `tbuz` | Run buzzer test. | L:E | L:E | V |
| `tchgc [current [limit]]` | Charge-current test; E2 and C argument limits differ. | L:E | L:E | V |
| `tdisc [current [limit]]` | Discharge-current test; E2 and C argument limits differ. | L:E | L:E | V |
| `tvolt [value]` | Cell voltage test; E2 optional value is allowed spread in mV. | L:E | L:E | V |
| `tpwr` | Test total module voltage; C only. | — | L:E | V |
| `ttmp [value]` | Cell temperature test; E2 optional value is allowed spread in mC. | L:E | L:E | V |
| `tetmp` | Compare two temperature sensors against the cell-temperature average; E2 accepts −10/+30 °C offsets. | L:E | L:E | V |
| `tinput <rv\|dcov\|absent\|present>` | Test selected input condition; present/absent branches invoke hardware callbacks. | L:E | L:E | V |
| `tmos <cfet\|dfet>` | Test selected MOSFET. | L:E | L:E | V |
| `teepr` | EEPROM write/read test; E2 temporarily writes 0x55 at offset 0x26 on both chips, then restores it. | L:E | L:E | V |
| `tflash` | Destructive sector-zero erase/program test; also clears record metadata. | L:E | L:E | V |
| `ti2c` | Run I2C test routine. | L:E | L:E | V |
| `tcan` | Run CAN test; help advertises port# but table rejects additional tokens. | L:E | L:E | H |
| `tusart` | Run USART test routine. | L:E | L:E | V |
| `tdip <expected>` | Compare DIP-switch state with a decimal value 0–15. | L:E | L:E | V |
| `tled <selector> [on\|off]` | Test/control LEDs using selector 0, LED number or on/off per help. | L:E | L:E | V |
| `tibcio <nc\|sc>` | Test IBC I/O; nc/sc meanings are not expanded by firmware help. | L:E | L:E | V |
| `tcbnio <nc\|sc>` | Test CBN I/O; nc/sc meanings are not expanded by firmware help. | L:E | L:E | V |
| `tmprctrl <flag> [bat-id value]` | Inject runtime temperature, voltage or a monitor-reference diagnostic by selector; short form restores measurement flags. | L:D | L:D | V |
| `tsto` | Report cached self-test faults; C only, no output drive. | — | L:E | V |
| `tver <version>` | Compare hexadecimal value with actual software version; C only, does not set it. | — | L:E | V |
| `tdct` | Run dry-contact test. | L:E | L:E | V |
| `tbld` | Run bleeding/balancing test; help advertises val but table accepts no extra token. | L:E | L:E | V |
| `twdg` | Stop feeding watchdog; help says wdg but only twdg is registered. | L:E | L:E | H |
| `tagevolt` | Run aging-voltage test; C only. | — | L:E | V |
| `trdagevolt` | Read recorded aging-voltage extrema/history. | L:E | L:E | V |

## Routing, framing and implementation notes

### Local and remote selection

For remote-capable names the frontend recognizes a decimal module address as the
first argument: `command N remaining-arguments`. The E2 dispatcher at
`0x080251f6`–`0x080252ac` removes the address before invoking the local handler
when it matches the current module, forwards other targets when connected to
module 1, or reports a target mismatch on a non-master. Forwarding can report
`Target device is Busy` or `Target device is not present`; retain these as
specific operational failures rather than generic parse errors.

The remote tables contain `config`, `ctrl`, `data`, `emptyvolt`, `info`, `login`,
`logout`, `prot`, `couls`, `soh`, `stat` and `statc`. **A remote-table entry alone
does not guarantee direct-console invocation:** the inspected frontend first
requires a local-table match. In particular, `couls` is remote-only in both
images, and E2 `soh` is remote-only. The reviewed E2 text frontend therefore rejects these names before their
handlers run; no alternate public text spelling was found.

`pwr [index]` and `getpwr [index]` have their own selection behavior and are not
registered in the remote table. The E2 `getpwr` handler at `0x0800ef84` accepts
a selected index, checks presence from module 1, and otherwise requires the
current module's index. Do not generalize either mechanism into a global
selection effect from `login N debug`.

### Response boundaries and retries

The E2 dispatcher at `0x080252be`–`0x08025320` checks the token ceiling and calls
the handler. A zero return produces `Command completed successfully`;
nonzero produces `Invalid command or fail to excute.` and usage. Unknown or
inaccessible names can produce `Unknown command`. Normal replies use `@`, `$$`
and a mode-dependent `pylon...>` prompt; paginated output additionally uses the
continuation message documented in [protocol notes](protocol.md).

A successful handler return is not proof of hardware effect: `tbar`, for example,
also prints an independent test result. Read an operation-specific result and
verify state when implementing a write. Tests, calibration, configuration,
record creation/clearing, storage writes and reset/update operations must not
inherit automatic read retries. A name beginning with `t` is not a read-only
classification, and `teepr` actively writes to EEPROM.

### Recorded-data selectors

The registered `data`/`datalist` help lists these kinds:

```text
event history pov puv plv bov buv inputov coc coca doc doca sc use
```

`data <kind> [item]` retrieves an individual/default item. The detailed-list
handler recognizes `datalist <kind> dtls <item>` despite omitting `dtls` from
help (E2 comparison at `0x0800ba8a`). Actual E2 field forms are `datalist kind bat field start` and
`datalist kind bat cell field start`; `item` is not a recognized literal.
The supplement records zero-based cell selection, current scaling differences
and paging behavior.
The `use` path can report its recording interval in days.

Do not confuse event/history records with the separate internal `log` ring.
`datac` advertises `event/history/event_log/use`; `logc` resets log bookkeeping.
The string `misc` is absent from both images. The BatteryView reset script sends
it, but that is not evidence these revisions support it.

### Protection and configuration selectors

The decoded `config` selector array has **66 names** in both images. The help
lists most of them without explaining all units or relationships. Names ending in `r` must not be automatically interpreted as
recovery thresholds without checking the corresponding handler branch.

```text
pov povr phv phvr plv plvr puv puvr pslp
bov bovr bhv bhvr blv blvr buv buvr bslp bsv bv
bot botr bht bhtr blt bltr but butr
coc coca cocar
eot eotr eht ehtr elt eltr eut eutr
doc doca docar ocd ocr oc2d oc2r sc scd scr clc
recinv shuttime uvtime save default recuse idle
sleep record hwsleep
softtime mot motr cocp docp ocpd
```

The final six names above are present in the selector table but omitted from
help. In E2, `softtime`, `cocp`, `docp` and `ocpd` dispatch directly to a successful
exit without implementing a setting. Recognized names do not guarantee effects.
Exact selector order and source addresses are retained in the JSON.

The advertised scheduling forms are `[sleep/record] [on/off/day/week/month]
[starttime] [endtime]` and `hwsleep [on/off] [sleeptime] [wakeuptime]`.

The decoded `prot` array has **34 selectors** in both images, with `en`/`dis`
actions. Its exact list is:

```text
default bov bhv blv buv bslp
cbot cbht cblt cbut dbot dbht dblt dbut
pov phv plv puv pslp pot pht plt put
sc doc2 doc doca coca coc coc2 buzz smartchg lcoul mot
```

`bslp`, `pslp`, `lcoul` and `mot` are recognized by this array but omitted from
its help. The decoded `ctrl` array has **11 targets** in both images:

```text
cfet dfet buzz heat pwmc pwmp softstart i2c afuse agelog mostest
```

`pwmc`, `pwmp`, `softstart`, `i2c`, `agelog` and `mostest` are absent from help.
Actions/values are target-specific: do not infer PWM units or I2C semantics from
these names. The no-argument `ctrl` path displays status. Its E2 output also
includes `CFETFLAG`, `DFETFLAG`, `SOFT` and `dryct1`–`dryct4`; these display labels
are **not** additional selectors in that array. Ordinary output branches use
`on`/`off`, while other targets require separate handler review.

The decoded `datalist` field-selector array is `id`, `volt`, `curr`, `temp`,
`coul` in both images. This is separate from the record-kind strings and from
the `item`/`bat` syntax advertised in help. The arrays prove recognized names,
not that every argument combination will succeed.

### Confirmed state-changing details

- **`eepe`:** both images accept chip 0/1 and zero 2048 bytes in 16-byte writes.
  This is broad EEPROM clearing. See the [field map](protocol.md#confirmed-e2-persistent-fields).
- **`setsoc`:** E2 validates 0–100, then updates per-cell runtime coulomb and
  percentage fields at `0x0800fc0a`–`0x0800fc40`. This handler has no EEPROM
  write call; later periodic persistence is a separate question. This is not
  the erase-and-reset sequence used by BatteryView's SOC-reset button.
- **`totalcoul`:** E2's no-value path reads nominal capacity from chip 1 offset
  `0x021`. The setter accepts 50/74/100 Ah, writes the capacity and check byte,
  and updates related model data. Do not substitute arbitrary learned capacity.
- **`setlowcfg`:** E2's no-argument path reports `ShutSoc` and `ShutSocTime`;
  `shutsoc`/`sstime` change their runtime fields. `sstime` is stored internally
  in two-second increments (`value >> 1`, displayed `stored << 1`). The `save`
  path explicitly prints `LowConfig Save Not Support`; a zero return does not
  mean persistent configuration was saved.
- **`statc`:** E2 clears 60 halfwords starting at module-structure offset
  `0x08c`, restores fields at `0x0ce`, `0x0de` and `0x0e0` (reset, life-warning
  and life-alarm counts), then calls the module's `+0x280` callback via
  `0x080073dc`. The resolved callback immediately attempts a 124-byte write to EEPROM 0
  `0x38f`; the statc handler ignores the driver status.
  It does not preserve all statistics and is not an alias for `datac` or `eepe`.
- **`logc`:** E2 zeros internal log index/wrap state and writes a two-byte count
  at EEPROM-0 offset `0x387`; that is bookkeeping clearing, not a proven erase
  of every underlying log record.
- **`teepr`:** E2 reads, overwrites with `0x55`, reads back, and restores one byte
  at offset `0x026` on each EEPROM chip. Restoration attempts do not make this
  a passive diagnostic.
- **`tbar`:** E2 requires a 16-character alphanumeric barcode. It checks selected
  fourth-character/cell-count combinations, writes chip 0 offset `0x021`, then
  reads it back and prints `Test result:pass` or failure. Other revisions may
  accept different serial formats.
- **`trst`:** E2 prepares state, masks faults, and requests a Cortex-M system
  reset. It is unrelated to `logout` and to closing a host serial handle.

These handler observations are E2-specific unless both images are explicitly
mentioned. Shared names/help do not establish identical hardware effects.

## Differences and help inconsistencies to preserve

- E2 contains `inar`, `inaw`, `inash`, `inacal` and `currcal`, with INA226 help.
  `inacal` and `currcal` have distinct handlers and different maximum token counts.
- C contains `socr`, `socw`, `socsh`, `soccfg`, `soccal`, `socd`, `socclr`, `soct`
  and `tsoc`, with bq34z100-related help. `socclr` actually invokes a recovered 182-step
  embedded programming script, broader than a descriptor reset and separate
  from `eepe`.
- Other C-only names are `blocksoc`, `tagevolt`, `tpwr`, `tsoh`, `tsto` and `tver`.
- E2 `tchgc` and `tdisc` allow three total tokens and advertise current/limit.
  C allows only two and its help omits the parameter meaning. Do not copy E2's
  two-argument form into a C implementation without checking the handler.
- `tcan` accepts one total token although help advertises a port number;
  `tbld` likewise accepts one token although help advertises a value. `twdg`,
  not `wdg`, is the registered watchdog command.
- `inacal` help calls it `currcal`; `inar`/`inaw`/`inash` help calls them
  `socr`/`socw`/`socsh`. These are stale descriptions, not registered aliases.
- Neither image registers `cmdquit`, and neither contains that literal string.
  Retaining BatteryView's disconnect sequence does not imply these firmwares
  implement it. The supported session-exit command here is `logout`; that is
  not established as a substitute for the console-mode-switch operation.

## BatteryView descriptions and application compatibility

[BatteryView's control reference](protocol.md#command-meanings-from-batteryviews-controls)
adds descriptions of protection/alarm/release selectors, AFUSE, ageing logging,
current-sensor calibration, MOS-failure monitoring and model-specific UI actions.
It also records XML command typos and the application's collection-addressing
bug. Those are application findings, separate from this catalog's firmware
registration evidence; do not treat every bundled script spelling as supported.

## Remaining work before implementation

The [parameter reference](firmware-parameters.md) and
[handler supplement](firmware-behavior.md) record completed analysis and the
remaining board/consumer/source limitations. Use the recorded handler addresses to
establish unresolved parameter units, numeric bases,
full accepted forms, persistence timing and per-model hardware behavior for each
new write/test command. Identify operation-specific result messages and recovery
requirements, then test with synthetic replies before live verification. This
catalog proves registration, help metadata and the explicitly traced behaviors;
it is not a complete decompilation of every command handler or an endorsement of
running every command as a discovery probe.
