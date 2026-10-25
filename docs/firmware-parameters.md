# Firmware command parameters and effects

This supplements the [complete command catalog](firmware-commands.md). It records
what the handlers actually parse, including differences from their help strings.
The reviewed images, hashes, access modes and remote-routing rules are defined
there. Addresses below are runtime Thumb-code addresses, with the Thumb bit
cleared. **E2 means US_E2_V2.5_Crc.bin; C means US_C_V3.1_Crc.bin.**

Unless explicitly marked C or both, detailed observations are **E2-specific**.
A shared command name does not establish the same contract on another board.
Analysis was static; none of these operations was tried on a battery. Remaining
unknowns are called out rather than filled in from command names.

## Reading the contracts

- `D`: unsigned decimal; `S`: signed decimal; `H`: hexadecimal, with an optional
  `0x`/`0X` prefix. Bare `10` means sixteen in an H parameter and ten in a D parameter.
- `[argument]` is optional. Values in braces are literal choices. Commands and
  selectors are case-sensitive string comparisons unless stated otherwise.
- `u8`/`u16` describe firmware truncation to 8/16 bits, **not a recommended input
  range**. A client should reject overflow instead of reproducing it.
- Storage addresses are byte offsets on the named logical chip. A direct EEPROM
  write is persistent; a runtime update alone does not prove either persistence
  or loss on reboot because other tasks can save state later.
- A successful console footer only means the handler returned zero. Several
  tests and drivers print failure and still return zero. Preserve their output
  and interpret the operation-specific result.

The E2 unsigned conversion routine is `0x08019d2e`: it checks digits against the
requested base, accumulates a 32-bit value, and reports invalid/trailing input
through a caller-provided error pointer. It rejects nine or more digits after
stripping an optional hexadecimal prefix. The signed wrapper at `0x08019e08`
recognizes a leading minus. Some callers do not provide robust error handling;
validate complete tokens, signs, lengths and bounds before sending them. Do not
use malformed inputs to discover firmware limits.

The table's token ceiling includes the command word. It does not establish a
minimum: some storage handlers load missing operands without checking them.
Remote addressing is a frontend operation: for eligible commands, `command N ...`
can remove decimal module address N before the handler sees the remaining
arguments. The forms here describe those **remaining handler arguments**.

## Session and communication

| Form | Parameters, defaults and effect |
| --- | --- |
| `help [name]` | With no name, lists commands accessible in the current mode. With a name, prints its help. Help is not a reliable argument specification. |
| `login {config\|equipment\|debug}` | Valid from user mode; sets access mask 3, 5 or 15. An already elevated session reports `Quit current mode`; it does not silently switch modes. Unknown modes report `wrong mode`. |
| `logout` | Returns to user mask 1. Does not close the host serial port or request a reset. |
| `ci` | No operands. Displays communication state; distinct from the buffered-frame dump below. |
| `ct port` | Port is D, **0 or 1**. Dumps a buffered protocol frame, including SOI, VER, ADR, CID1/CID2/RTN, LENGTH, CHKSUM and EOI. The inspected handler does not enable a continuous trace stream. |
| `urates [rate]` | No argument reports the unit/RS485-port rate. D rate must be **9600, 115200 or 500000**. A changed value is written as four bytes to EEPROM 0 at `0x7ae` and cached in RAM. Immediate peripheral reinitialization is not established by this handler. This is not the console baud rate. |
| `setprt [sma\|lg]` | No argument reports the selected protocol. The setter changes protocol-related runtime settings and writes a byte at EEPROM 0 `0x7ab`. Full dependent flag changes and activation timing remain to be traced. |
| `lg [cstm\|sys en\|dis]` | No arguments reports customer/system CAN-ID state. Setters use separate EEPROM-1 flags/check bytes: customer `0x3a/0x3b`, system `0x3c/0x3d`; enabled marker `0x55`, disabled marker zero. These flags are not a console baud setting. |

Evidence: E2 `login` `0x08025578`, `logout` `0x08025604`, `ct`
`0x0801e0f8`; other entry addresses are in the catalog JSON.

## Module and cell selection

`pwr`, `getpwr`, `bat` and `pwrsys` implement their own selection; do not infer a
persistent selected module from a previous `login N debug`. Module 1 has rack
lookup/forwarding behavior; non-master modules often accept only their own
address. Presence checks matter independently of numeric bounds.

| Form | Parameters, defaults and output |
| --- | --- |
| `info` | No handler operands; identity, versions, barcode and specifications. Remote module address, when used, belongs to the frontend. |
| `pwr [module]` | Module is D. On module 1, no argument prints the rack table, including absent slots; an explicit module is checked for presence. On a non-master, selection must match the current module. Readings use native mV, mA, mC and percent fields. |
| `getpwr [module]` | D selection, presence checked on the master; other modules require their own address. No selection uses the current module. Outputs hash-delimited details. `Device N is not present` can coexist with a success footer. |
| `bat [module [cell]]` | Both numbers are D. The first operand selects a module, **not a cell**. The two-operand branch checks cell **0 through cell-count−1** and directly indexes the cell array. No operands displays the current module’s cells; one module operand displays that module’s cells. |
| `pwrsys [module]` | No argument displays system information on the master or local recommended charge/discharge values on another module. Explicit module is parsed D then narrowed to u8; the inspected lookup lacks a corresponding presence/null check. A client must validate the rack address and presence. Output includes recommended mV/mA limits. |
| `soh [module]` | D module selection and presence/own-address checks in the handler. E2 registration is remote-only, so the handler contract alone does not establish a working local-console spelling. |
| `stat` | No handler operands. Displays record counts, operating/fault counts, cycle count, SOH and SOC/coulomb fields. Read these counts before enumerating records. |

Evidence: E2 `bat` `0x080075a8`, `pwr` `0x08007a1c`, `getpwr`
`0x0800ef84`. `Power N` in a selected summary is an address label, not proof of N
installed modules. Reject absent placeholders when building a collection list.

## Recorded data, logs and counters

| Form | Parameters, defaults and effect |
| --- | --- |
| `data [kind [index]]` | No arguments selects the latest event. `data kind` selects that kind's latest item. An explicit index is D, narrowed to u16, and must be **less than the selected count**; indices are zero-based. An empty collection has a separate no-data path. |
| `datalist kind [start]` | Start is a decimal record index, not a requested count. Lists summary rows and may paginate. Determine the available count instead of probing arbitrarily high indices. |
| `datalist kind dtls start` | Handler-recognized detailed form omitted from help. `start` is D. This is separate from `data kind index`, which retrieves an individual record. |
| `datalist kind ...` | Additional `item`/`bat` selections and `id/volt/curr/temp/coul` field selectors exist. Their complete positional combinations, per-cell numbering and limits remain unverified; do not derive a query builder from the help string alone. |
| `save [event\|history]` | No argument defaults to event; `event` selects callback argument 0 and `history` selects 1. Unknown names fail. Tail-calls the module record-save callback, propagating its return status. Actual payload completion/persistence still depends on that callback. |
| `datac [event\|history\|event_log\|use]` | No argument resets **both event and history bookkeeping without entering the flash-erasure loop**. Explicit event/history also erases the corresponding flash allocation. The other kinds clear separate counters/metadata. See the storage map below; this is not a general EEPROM erase. |
| `log [count]` | Separate diagnostic ring. Count is D, **1–32**. No argument uses the available count, or 32 for a wrapped ring. Traverses newest first; records are 20 bytes at EEPROM 0 `0x6c + index*20`. Behavior when requesting more than the available entries should not be used to infer valid historical records. |
| `logc` | Clears diagnostic-ring index/wrap state and writes a two-byte zero at EEPROM 0 `0x387`. This does not establish that old payload bytes are erased. |
| `logt value` | Value is H. Injects an internal test-log event through the logger with code `0x600`, source/argument 1 and the supplied 32-bit value. |
| `statc` | Clears 60 halfword statistics fields starting at module offset `0x08c`, preserving/restoring reset, life-warning and life-alarm fields at `0x0ce/0x0de/0x0e0`. Calls a state callback afterward; its full persistence semantics remain unverified. |
| `tcycle [count]` | No argument reports cycle count and real coulomb value. D count **0–10000** changes the cycle field and recalculates related runtime coulomb state; this is not just a counter display. No direct EEPROM write was found in the handler. |

Supported record kinds advertised by the firmware are `event`, `history`, `pov`,
`puv`, `plv`, `bov`, `buv`, `inputov`, `coc`, `coca`, `doc`, `doca`, `sc`, `use`.
The `use` path also reports an interval in days. Internal `log` is a different
ring from these recorded-data collections.

Evidence: E2 `data` `0x080092f8` (default/index logic `0x08009324`–`0x080093e0`),
`datalist` comparison `0x0800ba8a`, `log` `0x080175b8`, `logc`
`0x08017794`, `statc` `0x08009036`, `tcycle` `0x0800f32c`. C `statc`
`0x08008ff0` has the same preservation pattern.

### `datac`: bookkeeping and payload erasure are different operations

E2 handler `0x08029d08`–`0x08029edc` accepts no operand or one of the four
literal names. It initializes a zero-filled temporary buffer, selects a storage
descriptor for the requested kind, and performs these operations:

| Form | Confirmed runtime and persistent changes |
| --- | --- |
| `datac` | Zeros event write-index at EEPROM 0 `0x389`, event count at `0x38f`, history write-index at `0x38b`, history count at `0x391` (two bytes each), with corresponding RAM fields. Skips the flash-erasure loop because both kinds were selected. Old payload bytes are not physically erased by this path. |
| `datac event` | Same event-index/count clearing, then flash-erasure loop over the event descriptor's allocation. |
| `datac history` | Same history-index/count clearing, then flash-erasure loop over the history descriptor's allocation. |
| `datac event_log` | Clears 22 bytes of runtime event-specific counters beginning at module offset `0x104`, then writes 22 zero bytes at EEPROM **1** `0x658`. No event/history flash-erasure loop. This is separate from the internal diagnostic `logc` ring. |
| `datac use` | Zeros the two runtime halfwords at module `0x11a/0x11c`, four EEPROM-1 bytes at `0x66e`, and seven EEPROM-0 bytes at `0x40d`. No event/history flash-erasure loop. |

The explicit event/history paths get their start address, allocation length and
erase granularities from runtime storage descriptors. The loop calls flash
helpers `0x0801fd48` / `0x0801fd98`, which emit address-bearing SPI commands
`0x20` / `0x52`. Exact allocation addresses and chip-specific erase geometry
remain to be established; neither is a command parameter.

Bookkeeping is reset **before** payload erasure. EEPROM return codes are
accumulated; a nonzero total produces handler return 5. The erase-helper results
are not accumulated into that total. Bad alignment can return 1 after prior
changes. Consequently a failed command can already have changed counts, and a
success footer alone does not verify every erase completed. Do not retry this
operation as though it were a read or claim transactional clearing.

`save` at `0x08009074` dispatches through `0x080073ec`; no argument selects an
event. It requests a fresh record, rather than flushing every existing record or
saving configuration. The callback's physical storage sequence remains a
separate analysis task.

## SOC, capacity and small configuration settings

| Form | Parameters, validation and storage |
| --- | --- |
| `setsoc percent` | D, narrowed to u16, then checked **0–100**. Updates each cell's runtime remaining-charge and percentage fields using configured capacity. No direct EEPROM write in this handler. Distinct from BatteryView's erase/restart SOC-reset sequence. |
| `totalcoul [capacity]` | No argument reads eight bytes from EEPROM 1 `0x21` and displays capacity in mAh after dividing internal coulomb units by 3600. Setter is D **50, 74 or 100 Ah**; multiplies by 3,600,000, updates runtime capacity and related model data, writes capacity at `0x21` and check byte `0x29`. It is nominal configuration, not an arbitrary learned-capacity value. |
| `emptyvolt [threshold]` | No argument reports `Coul:0% Volt`. D → u16; accepts **500–3300 inclusive**, writes two bytes to EEPROM 0 `0x7a3` and updates RAM. The scale resembles cell mV, but the physical interpretation/consumer still needs confirmation. |
| `blocksoc [percent]` (C) | No argument reports the recommended block-current SOC. D → u16, **1–100 inclusive**; a change writes two bytes at EEPROM 0 `0x7ac`. |
| `setlowcfg` | Reports `ShutSoc` and `ShutSocTime`. |
| `setlowcfg shutsoc value` | D → u16; stores a runtime shutdown-SOC field. No additional percentage bound was found in this branch; a client should not accept arbitrary 16-bit values merely because firmware does. |
| `setlowcfg sstime seconds` | D → u16, then divides by two using a right shift. Stores two-second ticks; reporting doubles the stored value. Odd seconds are rounded down. |
| `setlowcfg save` | Prints `LowConfig Save Not Support` and returns zero. It does **not** implement persistent saving. |

Evidence: E2 `setsoc` `0x0800fbd0`, `setlowcfg` `0x0800fc58`, `totalcoul`
`0x08029f10`. For erase/restart and the persistent field map see
[SOC-reset analysis](protocol.md#firmware-evidence-for-soc-reset).

### RTC and manufacturing timestamp

`time` reads the RTC. `time yy month day hour minute second` sets it; all six
operands are D. E2 stores each parsed value as a byte **before** checking it.
For normal, non-overflowing input the checks are:

| Operand | Accepted normal range |
| --- | --- |
| `yy` | 0–99, two-digit year |
| `month` | 1–12 |
| `day` | 1 through the month length; February depends on `yy & 3` |
| `hour` | 0–23 |
| `minute`, `second` | 0–59 |

Do not reproduce the byte-wrap acceptance bug. Send six separate tokens, not an
ISO timestamp. E2 handler `0x080289cc`, validation through `0x08028ac4`.
`cmudtesttime [year month day hour minute second]` is a separate manufacturing
timestamp with an EEPROM-0 field at `0x3d`; its exact format/range and relation to
RTC time still need independent validation.

## EEPROM, flash and raw MCU memory

These commands have different address spaces. Chip numbers do not identify MCU
internal flash banks. See the [EEPROM map](protocol.md#confirmed-e2-persistent-fields)
before interpreting the contents.

| Form | Exact parameter contract and effect |
| --- | --- |
| `eepr chip offset size` | Chip D **0 or 1**; offset H; size D **bytes**. Requires `offset + size <= 0x800`. Size zero gives an empty read. Prints eight bytes per row with an ASCII column. |
| `eepw chip offset value [repeat]` | Chip D **0 or 1**; offset H; value H truncated to u8. Optional repeat is **H**, default **1**. Requires `offset + repeat <= 0x800`. Writes the **same byte** repeatedly, not a multibyte numeric value or hex blob. Repeat zero performs no writes. Client values should be 00–FF. |
| `eepe chip` | Chip **0 or 1**; the selector is converted in decimal and again in hexadecimal in the handler, with the same result for these choices. Zeros **all 2048 bytes**, using 128 writes of 16 zero bytes. There is no offset/count operand or confirmation branch. |
| `flar chip offset size` | Chip D **0 only**; offset H; size D bytes. Bounds use the detected runtime flash capacity, not the EEPROM 2 KiB bound. Read-driver status is not reliably propagated as a failed footer. |
| `flaw chip offset value` | Chip D **0 only**; offset H; value H → u8. Writes **one byte**, checking it fits the runtime capacity. No repeat operand. Driver status is ignored by the handler. |
| `flae chip` | Chip D **0 only**. Sends external-flash chip-erase opcode `0x60` and polls status with a finite retry counter. A timeout message can still lead to a success footer. Exact elapsed timeout depends on the delay implementation. |
| `md width address count` | Width D **1, 2 or 4 bytes**; address H; count D **elements**, not bytes. Aligns address downward to width. No address whitelist; a read can touch MMIO. Wider values are byte-swapped for display, so the printed hex is not simply a host-endian integer load. |
| `mm width address value` | Width D **1, 2 or 4 bytes**; address H, aligned downward; value H. Raw MCU-address-space write; no address whitelist. Narrow stores discard high bits. Do not map this to an EEPROM write API. |

For example, `eepr 0 20 16` requests sixteen bytes at **hexadecimal 0x20**.
`eepw 0 20 AA 10` requests **sixteen copies** of 0xAA. These are explanatory
examples, not steps required to inspect a connected battery.

Evidence: E2 `eepe` `0x08010410`, erase helper `0x080101ee`, EEPROM read/write
bounds `0x0800ffe4`/`0x0801004a`. C `eepe` `0x080103dc`, erase helper
`0x08010142`: the same full-2-KiB zeroing. Detailed flash/memory contracts above
are E2 observations; entry addresses for each command are in the JSON.

## Fuel-gauge registers and calibration

### E2 INA226 path

| Form | Parameters and effect |
| --- | --- |
| `inar offset` | H offset **00–7F**; reads a two-byte INA register. |
| `inaw offset value` | H offset **00–7E**; value H for the register write. Do not copy the read handler's larger offset limit. |
| `inash` | No operands; register report. Stale help calls it `socsh`, which is not an E2 registered alias. |
| `inacal` | Reads/reports the current coefficient, offset and calibration mode through module callbacks. |
| `inacal 10000` | Signed-decimal input is parsed, but this branch accepts **10000 only**. Performs current calibration, including measurement sampling and coefficient/offset calculation; coefficient acceptance includes **800–1200**. Requires INA226 hardware identity. Invalid calibration conditions can print failure and return zero. |
| `inacal currcoe value` | D value sets the coefficient through callback operation `0x54`. This manual branch does not apply the automatic calibration branch's 800–1200 check. Full callback persistence requires further tracing. |
| `inacal curroffset value` | D value sets the offset through callback operation `0x30`. Despite the signed-looking output label, this manual setter calls the **unsigned** parser. |
| `currcal [value]` | Separate handler, signed-decimal value. Intended reference is **10000**, but other values merely print `Err Val != 10000` and **continue into the calibration path**. The routine can close/reopen MOS outputs and invoke calibration callbacks. No argument calls a separate callback operation 2; its exact effect remains unverified. A client must not rely on the error message to prevent mutation. |

E2 `inacal` `0x0802190c`; manual setters `0x08021b26`–`0x08021ba6`,
read path `0x08021ba8`–`0x08021bea`. The procedure manipulates hardware state;
it is not a harmless report with an optional numeric filter.

### C bq34z100 path

| Form | Parameters and effect |
| --- | --- |
| `socr offset` | H offset **00–7F**; reads **one byte**, unlike E2 `inar`. |
| `socw offset value` | H offset **00–7E**; H value → u8; writes **one byte**. |
| `socsh` | No operands; fuel-gauge register report. |
| `socd` | Reads gauge data including pack voltage, signed current, SOC and remaining capacity. The table permits two extra tokens, but the inspected handler does not consume them. Current/capacity scaling uses a runtime factor. |
| `soct` | Reads chemistry ID and Ra/resistance-table information, including flags and table entries. Permitted extra tokens are not consumed by this handler. |
| `soccfg` | Lists named data-flash fields, subclass, offset and decoded value using a descriptor table. |
| `soccfg subclass offset [value]` | Subclass and offset are **D**, narrowed to u16 and matched to descriptor fields. A matching descriptor controls width and signed/unsigned/other value encoding. This is **not** a generic arbitrary-width raw-memory write. Complete type-specific write formats and behavior for an unknown descriptor remain unverified. |
| `soccal {volt\|current\|tempr\|ccoffset\|bdoffsetP1\|bdoffsetP2} [value]` | Separate quantity-specific calibration paths; board-offset phases have state/ordering requirements. Full units, required values, limits, timing and cleanup remain unverified. Do not expose a generic numerical setter based on these names. |
| `socclr` | Calls the gauge clear/default-restoration routine. Registered help says it clears bq34z100 data flash and reloads defaults. The handler ignores permitted extra tokens and returns zero regardless of the callee result. Exact changed subclasses/bytes remain unverified. |

C `soccfg` `0x080208d4`, descriptor lookup `0x08020ae6`–`0x08020b56`;
`socclr` calls `0x080202ec`. Gauge data flash is separate from either `eepe` chip.

## Protection configuration and control

### `config`: thresholds are related, not independent scalars

`config` prints the full configuration. Most scalar selectors accept
`config key` to read and `config key value` to change runtime state. The common
value parser is **signed decimal**, so negative current/temperature values are
meaningful. Numeric parsing is attempted before some selector-specific string
branches; a robust client must validate the intended form rather than use the
parser's permissiveness.

E2 dispatch is at `0x0800cc14`, using the selector order retained in JSON.
Threshold branches validate against **other current settings**, not just fixed
minimum/maximum constants. The following pack/cell-voltage bounds are taken from the
comparisons, including endpoint strictness:

| Key | Unit | Setter condition for value x |
| --- | --- | --- |
| `pov` | mV | `max(phv, povr) < x <= 65000` |
| `povr` | mV | `20000 <= x < pov` |
| `phv` | mV | `max(plv, phvr) < x < pov` |
| `phvr` | mV | `20000 <= x < phv` |
| `plv` | mV | `puv < x < min(phv, plvr)` |
| `plvr` | mV | `plv < x < 65000` |
| `puv` | mV | `pslp < x < min(plv, puvr)` |
| `puvr` | mV | `puv < x <= 65000` |
| `pslp` | mV | `20000 <= x < puv` |
| `bov` | mV | `max(bhv, bovr) < x <= 7000` |
| `bovr` | mV | `100 <= x < bov` |
| `bhv` | mV | `max(blv, bhvr) < x < bov` |
| `bhvr` | mV | `100 <= x < bhv` |
| `blv` | mV | `buv < x < min(bhv, blvr)` |
| `blvr` | mV | `blv < x <= 7000` |
| `buv` | mV | `bslp < x < min(blv, buvr)` |
| `buvr` | mV | `buv < x <= 7000` |
| `bslp` | mV | `100 <= x < buv` |

E2 pack/cell-voltage branches: `0x0800cc9c`–`0x0800d1c2`. These limits describe
firmware acceptance, not recommended battery operating values.

The other selector groups and their confirmed units/roles are:

| Selectors | Meaning and parameter status |
| --- | --- |
| `bot botr bht bhtr blt bltr but butr` | Battery temperature protection/recovery fields, mC. Branches operate on charge/discharge-related fields; do not assume a single universal temperature limit. |
| `eot eotr eht ehtr elt eltr eut eutr` | Environment temperature thresholds/recovery; individual cross-field and constant bounds need completion. Some diagnostic strings contain incorrect field names. |
| `mot motr` | Additional temperature-protection/recovery branches. Physical sensor mapping and exact bounds remain unverified. |
| `coc coca cocar` | Charge current protection/alarm/recovery values, mA. Ordering depends on the current related fields and short-circuit threshold. |
| `doc doca docar` | Discharge current protection/alarm/recovery values, **negative mA** in the validation strings and signed parser. Do not send unsigned magnitudes as charge/discharge-interchangeable values. |
| `sc` | Short-circuit threshold, negative mA: **−300000 <= x < min(0, doc, −coc)**. Strictly below both related thresholds. |
| `ocd ocr oc2d oc2r scd scr` | Protection delay/recovery values, ms; exact bounds and the `oc2d` signedness bug are listed below. |
| `clc` | Current-limit value, mA: **1–10000 inclusive**. Stores the same value in pack and cell parameter structures. |
| `bsv bv` | Balancing-related voltage parameters, mV: **BSV 2800–3600 inclusive**, **BV 30–100 inclusive**. Both endpoints confirmed by unsigned subtraction/range comparisons. |
| `recinv` | D interval multiplier **1–65536 inclusive**. Displayed recording interval is the supplied multiplier times the module's base interval; the raw value is not necessarily seconds. |
| `uvtime` | D seconds **0–864000 inclusive** (ten days). Updates a runtime under-voltage timer field. |
| `recuse idle` | S values **1–365 inclusive**, displayed in days. Change the use-record interval / idle-time fields. |
| `shuttime` | E2 branch prints `NO IDLE SHUT`; it does not implement the implied numeric setter. |
| `softtime cocp docp ocpd` | E2 jump-table entries point straight to the common successful exit. Recognized names, **no implemented setter/read branch** in this image. |
| `save default` | Actions, described below; no numeric value. |
| `sleep record hwsleep` | Scheduling forms below. |

This accounts for all 66 selector-table names. Four recognized no-op selectors
are especially important: help/registration alone must not be treated as proof
that a setting changed. E2 jump table `0x0800cc18`, common exit `0x0800e8ee`.

`config save` calls several parameter-save callbacks and writes the record
interval field at EEPROM 0 `0x38d`. `config default` calls the corresponding
restore-default callbacks, changes scheduling values and writes that interval
field too. These are state-changing actions, not ways to display defaults.
The full callback storage map is not yet established; do not describe either as
an erase of all settings. Branches `0x0800e472`–`0x0800e5b2`.

### Delay/recovery limits and a signedness bug

All setters have form `config key value`, using the common **S** parser; the
query form omits value. Accepted conditions below describe the comparisons,
not merely the diagnostic strings:

| Key | Accepted value in milliseconds | E2 setter branch |
| --- | --- | --- |
| `ocd` | 2000–300000 inclusive | `0x0800d6d8` |
| `ocr` | 2000–300000 inclusive | `0x0800d744` |
| `scd` | 0–31 inclusive | `0x0800d818` |
| `scr` | 2000–300000 inclusive | `0x0800d860` |
| `oc2d` | Signed comparison accepts **any parsed value <= 5000**, including negative values | `0x0800e35c` |
| `oc2r` | 500–60000 inclusive | `0x0800e3a8` |

The unsigned subtraction checks in the bounded branches reject negative values.
`oc2d` instead uses a signed `< 5001` comparison and has **no zero lower check**,
despite printing `0 ~ 5000 ms` on error. Future clients should enforce 0–5000;
the effect of a negative stored delay on timer consumers remains unverified.
Successful setters copy the raw value to pack and cell parameter structures;
there is no rounding at this point. Later timer resolution and persistence are
separate from the parser contract.

`clc` bounds are at `0x0800d8b4`; `bsv`/`bv` at `0x0800e3f8`/`0x0800e44c`.

### Scheduling forms

E2 `config sleep` reads the sleep schedule; `config sleep on` / `off` toggles it.
The daily setter has separate hour/minute tokens:

```text
config sleep day start-hour start-minute end-hour end-minute
```

All four numbers are D; normal values are hour 0–23, minute 0–59. Firmware
narrows them to bytes before checking. Start and end must differ; an end earlier
than start sets an internal next-period flag. Weekly/monthly paths also exist
and carry day fields, but day numbering and complete token validation remain to
be documented before exposing those setters. `config record` has corresponding
on/off/day/week/month paths; do not assume its state polarity matches sleep.

Hardware sleep uses a **different syntax than the help suggests**:

```text
config hwsleep
config hwsleep on
config hwsleep off
config hwsleep sleep-seconds wake-seconds
```

The two-number form uses D, requires **sleep 5–10 inclusive** and **wake >= 7**,
and enables hardware sleep. No upper wake bound was found in this branch.
It does not require an additional `on` token. Display labels explicitly use
seconds. E2 branches `0x0800dd64`–`0x0800de3a`.

### `prot`, `ctrl`, `autoswitch`, `couls`

`prot` displays protection state. `prot default` requests defaults.
`prot key en` / `prot key dis` choose a named protection enable bit, not a
numeric threshold. The [34-selector list](firmware-commands.md#protection-and-configuration-selectors)
includes battery charge/discharge temperature protections separately, pack
protections, buzzer and smart-charge controls. The masks are not simply
`1 << selector_index`: the jump table maps names to bits with gaps. E2 handler
`0x0800e96c`, selector dispatch `0x0800ea0c`. Exact persistence and each special
control's effect remain to be traced.

`ctrl` displays state. E2 accepts `ctrl target` queries and, for implemented
setters, `ctrl target on|off` or the numeric form below. Dispatch is at
`0x080297ca`; the common parser turns `on` into 1 and `off` into 0. Invalid
other action strings are rejected except on the numeric PWM paths.

| Target | Handler behavior and limits |
| --- | --- |
| `cfet`, `dfet` | Query reads output state. `on`/`off` invoke different module-control operation codes; these are active charge/discharge-path controls. |
| `buzz` | Query reads GPIO state; `on`/`off` directly sets/clears the buzzer GPIO. |
| `heat` | Query reports OFF. Setter branches go to the common exit without changing hardware in E2. |
| `pwmc` | Query reports state and a percentage with one decimal place. D numeric setter clamps to **0–1000**, representing **0.0–100.0%**; `on`/`off` also parse but store 1/0 in the same numeric field. The setter changes a runtime field, not a proven PWM-enable flag. |
| `pwmp` | Numeric parser clamps to **20000–200000**, but the E2 dispatch entry goes straight to the exit; no implemented effect. Do not infer frequency units or a working setter. |
| `softstart` | Query reads GPIO. Both `on` and `off` reach a branch that compares the **argument count with 1**, instead of the parsed action. Since a setter has three total tokens, both take the same output-control path. Treat as a firmware bug, not a reliable Boolean setter. |
| `i2c` | Bare target calls a peripheral-control helper with argument zero; it is **not a status query**. The `on`/`off` forms do not reach that call. Exact peripheral semantics still need driver tracing. |
| `afuse` | Passes inverse on/off state to module callback operation `0x29`, then reports the cached AFUSE flag. The handler prints `Nonsupport currlimit mode` as well; physical fuse semantics remain unverified. Bare target follows the same default-zero action path rather than a pure query. |
| `agelog` | Query reads EEPROM 0 `0x7b7`; marker `0x5a` enables the cached flag. Setter persists `0x5a` for on, zero for off. |
| `mostest` | Query reads EEPROM 0 `0x7f4` and EEPROM 1 `0x2a`; either `0x5a` marker enables the cached flag. Setter writes both locations with `0x5a` or zero. Actual MOS-test consumer behavior remains unverified. |

These observations are specific to E2 `0x08029500`–`0x08029bcc`. Display labels
such as `CFETFLAG`, `DFETFLAG` and `dryct1`–`dryct4` are not additional selectors.
Several **bare target forms change state**, so they cannot all be exposed as
read-only queries.

`autoswitch` queries the EEPROM-0 byte at `0x7fa`. Setters accept **literal strings**
`autoswitch 0` or `autoswitch 1`, not arbitrary decimal representations. Zero
stores **0x5a = OFF**, one stores **0 = ON**, updates RAM and reads the byte back
for reporting. E2 `0x0800fce8`–`0x0800fd8c`; this inverted stored marker is not
an ordinary persisted Boolean.

`couls [iah|vah|asic|default]` advertises coulomb-calculation modes but is
remote-only in both images; transport entry and mode semantics remain unresolved.

## Manufacturing tests and injected readings

Tests may change output state, sample hardware, modify storage, or stop normal
operation. A printed `Test result:pass/fail` must be interpreted independently
of the standard console footer.

### Parameters confirmed from E2 handlers

| Form | Parameters and behavior |
| --- | --- |
| `tbar barcode` | Exactly **16 alphanumeric characters**. Fourth character `1` requires 15 cells; `4` requires 16. Other fourth characters skip those particular checks. Writes 16 bytes at EEPROM 0 `0x21`, reads back and compares. Inspect the test result, not just the footer. |
| `tdip expected` | D **0–15**, required. Reads four active-low GPIO bits and compares the assembled DIP value with the expected value. Does not set DIP switches. Mismatch can still return zero. |
| `tinput {rv\|dcov\|present\|absent}` | Compares hardware input against the selected condition. The present/absent paths bracket the read with module callbacks and a delay; this is not established as a purely passive read or a forced input simulation. |
| `tchgc [current [limit]]` | Both D, mA. No operands uses **10000 ± 50 mA**. One operand uses supplied current ±50. Two use supplied current ±limit, with **limit 50–500 inclusive**. Requires charging state; otherwise prints `not chg`. |
| `tdisc [magnitude [limit]]` | Both D, mA; supplied magnitude is **negated internally**. No operands uses **−1000 ±100 mA**; one uses negative supplied magnitude ±100. Explicit limit must be **100–500 inclusive**. Requires discharge state; otherwise prints `not dsg`. |
| `tvolt [spread]` | Optional D **maximum cell-voltage spread in mV**, not a target voltage. Compares max-minus-min with supplied spread, prints cell values/difference. Also checks sampling stability and can report `Batt Volt data instability`. |
| `ttmp [spread]` | Optional D **maximum cell-temperature spread in mC**, not a target temperature. Without it, the test uses built-in spread/plausibility checks; supplied spread changes the printed pass/fail comparison. Prints cell temperatures/difference. |
| `teepr` | No operands. On each EEPROM chip, reads byte `0x26`, writes `0x55`, reads back and attempts restoration. This actively writes, including a location within the chip-0 barcode field. |
| `twdg` | No operands accepted; stops watchdog feeding according to help. Exact reset delay depends on watchdog configuration, not a command parameter. |
| `tcan`, `tbld` | **No operands accepted by the dispatcher**. Help advertises a port/value which cannot be supplied under the registered one-token ceiling. Hardware test effects still require deeper review. |

Evidence: E2 `tbar` `0x0802b080`, `tinput` `0x0802b1b8`, `tchgc`
`0x0800f75c`, `tdisc` `0x0800f888`, `tvolt` `0x0800f418`, `ttmp`
`0x0800f548`, `teepr` `0x0801045a`. C `tchgc`/`tdisc` permit at most **one**
operand; do not send the E2 tolerance operand there. C defaults/tolerances need
independent tracing.

### `tmprctrl`: the selector also chooses the quantity

E2 handler `0x0800ee1c` accepts these forms:

```text
tmprctrl 0
tmprctrl 1 selector value
```

The short form accepts **zero only** and restores several normal-measurement
flags; it is not a generic Boolean toggle. In the long form the flag must be 1,
selector is D and value is S:

| Selector | Inspected operation |
| --- | --- |
| `0 .. cell-count-1` | Writes that cell's temperature field. |
| `99` | Writes the module environment-temperature field. |
| `98` | Writes another module temperature field; physical sensor mapping unverified. |
| `97` | Enables an additional simulated-temperature field; consumer mapping unverified. |
| `100 .. 100+cell-count-1` | Subtracts 100 and writes that cell's **voltage** field. |

Temperature-path values are accepted from **−40000 through 100000 inclusive**
(raw mC fields). The voltage path checks signed value `< 5001` but lacks an
explicit nonnegative check; a client should reject negative voltage. These are
runtime injected readings/flags, not temperature calibration EEPROM writes.

### Other parameterized handlers: remaining limits

| Command | Known form and unresolved details |
| --- | --- |
| `bmicrdcfg total-ic`, `bmicrdcomm total-ic` | Required **D** IC-count operand. E2 `bmicrdcfg` rejects zero; `bmicrdcomm` has no corresponding zero check. Both pass a u8 count to a driver with a fixed local buffer; no upper bound is enforced in the handler. Hardware-supported maximum and driver bounds remain unverified; do not expose unrestricted counts. |
| `disp ...` | Repeated-display selections include `pwrs`, `bats`, `volt`, `curr`, `temp`; numeric selectors/intervals exist. Complete positional syntax, interval units and stop behavior remain unverified. |
| `euro ...`, `eurostub ...` | Optional module/test operands exist; full field meanings and effects remain unverified. `eurostub` must not be classified as a read. |
| `tled selector [on\|off]` | Numeric LED selection and special group/all paths exist; complete selector/action combinations remain unverified. |
| `tmos {cfet\|dfet}` | Chooses the charge/discharge MOSFET test. Timing, restoration and required external conditions remain unverified. |
| `tibcio {nc\|sc}`, `tcbnio {nc\|sc}` | Exact string choices; electrical meaning, expected fixture conditions and side effects remain unverified. |
| `tver version` (C) | Required **H** value, compared with the runtime software-version word; it **does not set a version**. Prints pass/fail and the actual version as `V(high bits).(low byte)`, then returns zero even on mismatch. C `0x0800fbdc`–`0x0800fc34`. |

### No-operand hardware handlers

The registered token ceiling confirms that the following accept **no additional
console operands**. Handler-confirmed details are identified explicitly; the
remaining help-based purposes do not establish a complete electrical test procedure:

| Command | Advertised role / remaining question |
| --- | --- |
| `tbuz` | Buzzer test; duration/restoration unverified. |
| `tetmp` | E2 computes the signed integer average of cell temperatures, refreshes two module sensor fields via callbacks and checks **each lies between average −10000 and average +30000 mC inclusive**. Prints pass/fail and sensor/average values, but returns zero even on test failure. Handler `0x0800f654`–`0x0800f70a`; physical identity of the two sensors remains unverified. |
| `tflash` | Flash test; modified region/restoration unverified. |
| `ti2c` | I2C test; buses/devices and writes unverified. |
| `tusart` | USART test; loopback/port requirements unverified. |
| `tdct` | Dry-contact test; output sequence/restoration unverified. |
| `tclear` | E2 zeros event/history write indices at EEPROM 0 `0x389/0x38b`, diagnostic-log index at `0x387` (two bytes each), and associated RAM count/wrap fields. Clears the same runtime statistics as `statc`, preserving reset/life-warning/life-alarm counts, then invokes its state callback. Also zeroes 0x128 runtime bytes at module `0x104` and calls `0x0800457a`; that callee’s further effects remain unverified. No flash-erasure loop in this handler. Prints the pass string and returns zero without checking EEPROM write results; **not equivalent to datac or full EEPROM erase**. E2 `0x0800fb00`–`0x0800fbb2`. |
| `tsoftdsg` | Soft-discharge test; power-path effects and duration unverified. |
| `trdagevolt` | Recorded aging-voltage report; record format and scope unverified. |
| `tagevolt` (C) | Aging-voltage test; storage/output effects unverified. |
| `tpwr` (C) | Total-voltage test; acceptance limits unverified. |
| `tsoh` (C) | SOH test; mutation versus reporting unverified. |
| `tsto` (C) | Self-test output; electrical sequence unverified. |
| `tsoc` (C) | Gauge test; writes/calibration changes unverified. |

## Reset, shutdown and update

`trst`, `shut` and `updata` accept no operands and are available in user mode.
They are actions, not session-exit commands.

- `trst`: E2 `0x0802b024` prepares state, masks faults and ultimately writes
  Cortex-M AIRCR with the key and SYSRESETREQ. It restarts the MCU; it does not
  itself mean “clear SOC” or “erase EEPROM.”
- `shut`: E2 `0x0800c498` sets shutdown-related module flags; the master has a
  broadcast path and non-master handling differs. No “type twice to confirm”
  guard was found inside this handler. Exact physical shutdown timing and wake
  conditions remain unverified.
- `updata`: enters the firmware-update workflow. Subsequent transfer framing,
  image validation and completion/recovery are separate from text-console
  parameters and remain outside this parameter reference.

Do not automatically repeat state-changing commands after a timeout. For future
implementation, use the confirmed forms above, validate inputs more strictly
than firmware, preserve specific failure messages, and finish the explicitly
unresolved handler/callback analysis before exposing additional write operations.
