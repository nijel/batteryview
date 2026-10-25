# Firmware handler and persistence details

This continues the [parameter reference](firmware-parameters.md) with the
remaining dispatch branches and storage callbacks. **E2** and **C** identify the
exact reviewed images and hashes in the [catalog](firmware-commands.md).
Addresses are runtime addresses with the Thumb bit cleared. Findings describe
static code paths, not successful tests on hardware. Logical storage layouts,
callback wiring and limits can differ on other firmware versions.

## Recorded-data query grammar

E2 `datalist` (`0x0800b094`) dispatches by **total token count**:

| Form | Output / validation |
| --- | --- |
| `datalist kind start` | Summary records from zero-based D `start`, strictly below the selected count. |
| `datalist kind dtls start` | Expanded rows from D `start`, including per-cell state. `dtls` must match literally. |
| `datalist kind bat field start` | Selected field for **all cells**, beginning at D record index `start`. |
| `datalist kind bat cell field start` | Selected field for one **zero-based D cell**, bounded by current module cell count; D `start` below the record count. |

Fields are `id`, `volt`, `curr`, `temp`, `coul`. Record kinds are those listed in
the parameter reference. `item` is **not** a recognized literal in these E2
branches, despite its appearance in help. No-argument and kind-only calls do not
select an implicit start: they fail. Do not translate the help's brackets into
arbitrary optional arguments.

The two all-record list forms load records through module callback `+0x288`,
check the `55 AA` record prefix and report `Error!` on a bad record. The all-cell
field form formats two records per output chunk; the single-cell form formats
up to sixteen. Continuation is controlled by the output/pager helper, so stopping
at one chunk does not mean the collection ends there. Summary/detail loops also
validate the record and cell buffer boundaries; retain error output rather than
silently treating a corrupt record as absent.

The all-cell `curr` branch divides stored current by **1000 using signed integer
division** (`0x0800c280`–`0x0800c28c`). The single-cell branch prints the stored
integer directly (`0x0800c3f0`–`0x0800c408`). Thus those two forms have different
current scales/truncation. Other fields are printed as raw integers. Client
normalization must depend on the selected form, not only the `curr` name.

The summary/detail start parsers do not consistently test their error flag
before using the value. Supply strictly validated decimal tokens. The explicit
field forms do test the flag. Evidence: E2 summary `0x0800b17e`, detailed
`0x0800ba84`, all-cell `0x0800c148`, single-cell `0x0800c2b8`.

## What the persistence callbacks actually do

### Statistics and extended state

E2 module initialization wires callbacks at `0x0801237c`–`0x0801239c`:

| Module field | Function | Role |
| --- | --- | --- |
| `+0x280` | `0x08010a0e` | Persist statistics or extended state. |
| `+0x284` | `0x08010928` | Store an event/history/other record. |
| `+0x288` | `0x08010a6a` | Read recorded data. |

`0x080073dc` passes a null mode pointer to the persistence callback. That branch
**synchronously writes 124 bytes from module `+0x88` to EEPROM 0 `0x38f`** and
returns the EEPROM driver's status. `statc` therefore attempts to persist the cleared
statistics block immediately; it is not merely a runtime reset. Its handler
discards that driver status before returning zero.

`0x0800457a` supplies mode value 1 to the same callback. This branch computes a
checksum with seed `0xffff` over **294 bytes** at module `+0x104`, stores the
checksum at module `+0x22a`, and writes the full **296-byte block to EEPROM 1
`0x658`**. `tclear` calls both modes, so its zeroed extended state also reaches
persistent storage. The helper at `0x0800457a` itself does not perform an
additional flash-payload erase.

The extended-state startup loader (`0x080108ea`–`0x0801091c`) reads this block,
recomputes its checksum and clears the runtime copy on a mismatch. `datac event_log`/`datac use` modify only part of that stored block; they do not
recompute its trailing checksum in their command handlers. A later startup can
therefore invalidate more extended state than the command's immediate RAM write
suggests. This is a consequence of the loader/checksum code, not a hardware
observation.

Periodic code at `0x080153f0`–`0x08015424` decrements a save countdown by the
module's base interval, saves ordinary statistics when it expires and reloads
120. It saves extended state at a separate point in that countdown. Shutdown
and reset paths also call both helpers. Consequently, **absence of an EEPROM
write in a command handler does not mean its effects cannot survive a reset**.
For `setsoc`, the eventual persisted module-level charge fields also depend on
subsequent aggregation; the command does not directly save each injected cell
field. Precise wall-clock save timing depends on the scheduler/base interval.

### `save` and the record writer

`save [event|history]` builds a record through `0x080073ec`: a `55 AA` prefix,
RTC timestamp, module measurements and state, per-cell data, recommended-current
fields and a trailing `0xaa55aa55` word. The callback argument combines payload
length in the low halfword and record kind in the high halfword.

The E2 writer (`0x08010928`) stores event/history records in **512-byte slots**.
It computes the slot from count plus write index, wrapping at the allocation's
capacity. When full, it advances/persists the oldest index, reduces the count by
one erase unit's worth of slots, and erases on the relevant erase boundary before
writing the new payload. Other record kinds tail-call `0x08010724` instead.

This is synchronous driver invocation, not just an enqueue flag. However:

- The count increments after the payload-write call **even if that write returns
  an error** (`0x080109f8`–`0x08010a04`).
- The count increment itself is initially in RAM; the statistics-save callback
  makes the count persistent later.
- Index updates and erasure can happen before a failed payload write. Retrying
  can therefore create another slot/change bookkeeping; it is not idempotent.

The flash initializer (`0x0801fe78`–`0x0801fea6`) accepts capacity ID 0x16
and sets capacity **4 MiB**, small erase size **4096 bytes** and large erase
size **32768 bytes**. The 0x20/0x52 helpers implement those two erasures.
The descriptor initialization at `0x0801239e`–`0x080123d0` assigns E2 event
storage `0x4b000..0x11efff` (1696 slots) and history
`0x11f000..0x1fffff` (1800 slots). `0x080108b0` allocates further event-specific
and use-record regions after history. These addresses are **external-flash byte
addresses**, not MCU addresses, and are specific to this image's layout.

## C gauge data-flash types

C `soccfg` uses 12-byte descriptors at `0x08020ee4`, with name pointer,
subclass/offset/type bytes and a final default-value word. Subclass and offset
arguments are **decimal**, even when the field's value is hexadecimal.

| Type | Value input | Stored encoding |
| --- | --- | --- |
| 0 | Signed decimal | 8-bit integer |
| 1 | Signed decimal | 16-bit integer, high byte first |
| 2 | Unsigned decimal | 8-bit integer |
| 3 | Unsigned decimal | 16-bit integer, high byte first |
| 4 | Hexadecimal | 8-bit integer |
| 5 | Hexadecimal | 16-bit integer, high byte first |
| 6 | Hexadecimal | 32-bit integer, high byte first |
| 7 | **Decimal fraction** | Four-byte gauge floating-point encoding via `0x0801fd24` |

Type 7 calls the decimal-fraction parser at `0x080199a8`; the apparent base-16
register value passed by its caller is not used as a radix by that parser.
It accepts digits and at most one decimal point, not signed/scientific notation.
Do not send raw hex float bits as the value. Width-limited integer paths discard
high bits rather than checking representability; clients should enforce the
corresponding signed/unsigned bounds.

Unknown subclass/offset lookup reaches the descriptor sentinel but checks the
**descriptor address**, not its null name pointer, before continuing. It does
not reliably reject unsupported pairs. Likewise the value-parser error flag is
not consistently checked before the write helper. A client must restrict writes
to known descriptors and validate the complete typed value locally.

### Supported subclass/offset pairs

The following 38 descriptor entries are firmware constants, not captured battery
settings. Type numbers refer to the encoding table above. The final word is
recorded verbatim as a **descriptor default**, not a recommended live value and
not a claim that `socclr` only changes these fields.

| Name | Subclass (D) | Offset (D) | Type | Default word (hex) |
| --- | --- | --- | --- | --- |
| Taper Current | 36 | 0 | 1 | `0x000003e8` |
| Min Taper Capacity | 36 | 2 | 1 | `0x00000019` |
| Cell Taper Voltage | 36 | 4 | 1 | `0x00000019` |
| Current Taper Window | 36 | 6 | 2 | `0x00000028` |
| Cycle Count | 48 | 6 | 3 | `0x00000000` |
| CC Threshold | 48 | 8 | 1 | `0x00000384` |
| Design Capacity | 48 | 11 | 1 | `0x000003e8` |
| Design Energy | 48 | 13 | 1 | `0x00001518` |
| Design Scale | 48 | 30 | 2 | `0x00000001` |
| Cell Charge Voltage T1-T2 | 48 | 17 | 3 | `0x00001068` |
| Cell Charge Voltage T2-T3 | 48 | 19 | 3 | `0x00001068` |
| Cell Charge Voltage T3-T4 | 48 | 21 | 3 | `0x00001004` |
| SOH Load I | 48 | 15 | 1 | `0xfffffe70` |
| JEITA T1 | 48 | 26 | 0 | `0xfffffff6` |
| JEITA T2 | 48 | 27 | 0 | `0x0000000a` |
| JEITA T3 | 48 | 28 | 0 | `0x0000002d` |
| JEITA T4 | 48 | 29 | 0 | `0x00000037` |
| Firmware Version | 56 | 4 | 5 | `0x00000000` |
| Pack Configuration | 64 | 0 | 5 | `0x00000161` |
| Pack Configuration B | 64 | 2 | 4 | `0x000000ff` |
| Pack Configuration C | 64 | 3 | 4 | `0x00000030` |
| Number Of Series Cell | 64 | 7 | 2 | `0x00000001` |
| Sleep Current | 68 | 2 | 1 | `0x0000000a` |
| Fullsleep Waittime | 68 | 11 | 2 | `0x0000000a` |
| Default Load select | 80 | 0 | 2 | `0x00000001` |
| Load Mode | 80 | 1 | 2 | `0x00000001` |
| Cell Terminate Voltage | 80 | 53 | 1 | `0x00000bb8` |
| Cell term V delta | 80 | 55 | 1 | `0x000000c8` |
| Min % Passed Chg For 1st Qmax | 80 | 47 | 2 | `0x0000005a` |
| Qmax Cell 0 | 82 | 0 | 1 | `0x000003e8` |
| Cycle Count | 82 | 2 | 3 | `0x00000000` |
| Update Status | 82 | 4 | 4 | `0x00000000` |
| Cell V at Chg Term | 82 | 5 | 1 | `0x00001068` |
| CC Gain | 104 | 0 | 7 | `0x7b638e39` |
| CC Delta | 104 | 4 | 7 | `0x9001742b` |
| CC Offset | 104 | 8 | 1 | `0xfffffb50` |
| Board Offset | 104 | 10 | 0 | `0x00000000` |
| Voltage Divider | 104 | 14 | 3 | `0x00001388` |

### `socclr` runs an embedded programming script

C `socclr` at `0x0802dc28` supplies the pointer array at RAM `0x20000744` to
interpreter `0x080202ec`. This array is in **compressed initialized data**, not a
plain pointer table in the image. Reconstructing the startup decoder
`0x08003a82` using its descriptor at `0x08003bcc` produces the initialized RAM
bytes; the array's null sentinel is at `0x20000a1c`.

There are **182 script steps: 91 W writes, 47 C comparisons and 44 X delays**.
The strings are embedded at `0x0803b7a4` onward. The interpreter:

- Decodes a W/C line into hex bytes. The first byte is an address shifted right
  by one for the bus callback; the next byte is the register/command; remaining
  bytes are write payload or comparison data.
- W calls the configured bus-write function and accumulates errors, but does not
  abort the script on a write error.
- C calls `0x080202a6` to read/compare and stops on a failed comparison.
- X parses a decimal delay; each iteration also services the firmware helper.

The script addresses both encoded targets `AA` and `16` (bus addresses `0x55`
and `0x0b`). It contains **32 indexed nonzero programming chunks** beginning
`W: 16 00 0A 00` through `W: 16 00 0A 1F`, additional programming transactions,
verification signatures, and a final delay of 4000. It is therefore a broad
embedded baseline/programming sequence, **not an EEPROM zero-fill or just a
reset of the 38 soccfg descriptors**. Exact physical gauge-memory region names
require the gauge's programming specification; the command-byte/chunk behavior
above follows directly from this firmware. Raw programming payloads are not
copied into this repository.

The interpreter's accumulated status is discarded by `socclr`, which returns
zero unconditionally. The same script is invoked by the `tsoc` test if its gauge
firmware-version check does not equal 6. `tsoc` is thus potentially mutating too.

### `soccal`: selectors, writes and termination

C `soccal` at `0x080212d8` recognizes six case-sensitive selectors. Before
selector dispatch it sends two control-register writes containing `14 04` and
`72 36`, even for branches that later only report values. These query-looking
forms are not pure bus reads. Missing/unknown selector fails with handler return 1; ordinary
selected branches usually return zero, including printed calibration failures.

| Form | Confirmed procedure |
| --- | --- |
| `soccal volt` | Reports voltage-divider value, subclass 104 offset 14, two bytes. |
| `soccal volt reference` | D reference, compared with register-8 voltage by computing `reference * old_divider / measured_voltage`; writes the low 16 bits to subclass 104 offset 14, then calls the gauge-reset helper. No reference-range or measured-zero guard was found. The scale matches the raw pack-voltage register; the user-facing unit must follow that register's device scaling. |
| `soccal current` | Reads/reports four-byte CC Gain and CC Delta at subclass 104 offsets 0 and 4. |
| `soccal current reference` | S reference; enters calibration mode, collects **eight samples with distinct sequence bytes**, exits mode, reads CC/board offsets and computes gain/delta. Accepts the calculated sample-resistor result **450–550 inclusive**, then writes gain and delta using the gauge float encoder. No explicit reference-range check. |
| `soccal tempr [value]` | Selector is recognized, but its jump-table entry goes directly to successful exit after the common control writes. **No temperature-calibration body is implemented** in this image. |
| `soccal ccoffset` | Sends control command `0x000a`, waits for CCA to set then clear, sends `0x000b`, reads subclass 104 offset 8 (two bytes), and calls the reset helper. |
| `soccal bdoffsetP1` | Requires internal phase flag 1. Sends `0x0009`, waits for CCA and BCA bits together, then sets phase flag 0 for P2. This flag is changed even on the printed failure path. |
| `soccal bdoffsetP2` | Requires phase flag 0; waits for BCA clear, sends `0x000b`, reads subclass 104 offset 10 (one byte), calls reset and restores phase flag 1. Without P1 it reports that P1 is needed. |

Extra numeric operands on offset branches are not consumed. This does not make
them adjustable numerical offset setters. The entry loops for calibration/CCA
have up to five passes; the clear-bit loops for CCA/BCA have up to 102 polls.
The current-sample collection loop has **no overall timeout if the sample
sequence never advances**. A failure to enter calibration can still fall through
into that sampling loop, so a client timeout does not prove the device stopped
working on the operation.

Reset helper `0x080204f0` sends the two control writes above and command `0x0041`,
then delays by 3000 helper units. This documents software ordering and delay
arguments; exact elapsed time and external-current fixture requirements need
hardware/gauge validation. Calibration results and writes are not transactional,
and the success footer does not establish successful cleanup on every path.

## Remaining configuration comparisons

These are E2 **setter acceptance conditions**, using the signed-decimal value x.
They describe the code's limits, not recommended operating thresholds. Named
fields mean the related current setting unless a raw field offset is specified.

| Key | Condition (mC) |
| --- | --- |
| `bot` | `max(bht, botr) < x <= 100000` |
| `botr` | `−40000 <= x < bot` |
| `bht` | `max(blt, bhtr) < x < bot` |
| `bhtr` | `−40000 <= x < bht` |
| `blt` | `but < x < min(bht, bltr)` |
| `bltr` | `blt < x <= 100000` |
| `but` | `−40000 <= x < min(butr, blt)` |
| `butr` | `but < x <= 100000` |
| `eot` | `max(P[0x2c], eotr) < x <= 100000` |
| `eotr` | `−40000 <= x < eot` |
| `eht` | `ehtr < x <= 100000` |
| `ehtr` | `−40000 <= x < eht` |
| `elt` | `eut < x < min(eltr, P[0x2c])` |
| `eltr` | `elt < x <= 100000` |
| `eut` | **`−39999 <= x < min(eutr, elt)`** |
| `eutr` | **`eut < x < 100000`** |
| `mot` | `motr < x < 100000` |
| `motr` | **`−39999 <= x < mot`** |

Battery-temperature setters mirror their values into both charge and discharge
parameter fields. Environment OT/LT branches similarly mirror selected fields.
Do not promise independent charge/discharge thresholds through these setters.

`P` is the pack parameter structure. **Reported `eht` is at P+0xb8**, while the
EOT/ELT comparisons above read **P+0x2c**, a distinct legacy field. Their error
messages suggest EHT but the code does not compare against the reported EHT
field. These mismatches and asymmetric −39999/100000 endpoints must not be
“corrected” in a description of actual firmware behavior.

Evidence: E2 battery branches `0x0800d1c6`–`0x0800d456`, environment/MOT
`0x0800e5b4`–`0x0800e878`. Physical mapping of the extra MOT sensor still depends
on board wiring; these offsets and mC comparisons are established independently.

| Key | Condition (mA) |
| --- | --- |
| `coc` | `coca < x`, `x < −sc`, `x <= 150000` |
| `coca` | `cocar < x < coc` |
| `cocar` | **`1 <= x < coca`**, despite the message advertising a lower bound of 0 |
| `doc` | `−150000 <= x`, `sc < x < doca` |
| `doca` | `doc < x < docar` |
| `docar` | **`doca < x < 0`**, so zero itself is rejected |

These setters mirror pack/cell parameter values and use the cell-parameter copy
for the related-field comparisons. Evidence: `0x0800d456`–`0x0800d6b4`.

### Daily, weekly and monthly schedules

E2 accepts the following complete setter forms for `sleep` and `record`:

```text
config sleep day sh sm eh em
config sleep week sd sh sm ed eh em
config sleep month sd sh sm ed eh em
config record day sh sm eh em
config record week sd sh sm ed eh em
config record month sd sh sm ed eh em
```

All numbers are D, narrowed to bytes before validation. Hours are 0–23, minutes
0–59. Weekdays are **1=Mon, 2=Tue, 3=Wed, 4=Thu, 5=Fri, 6=Sat, 7=Sun**;
monthly days are **1–31**. A monthly day is not validated against a particular
month's length. Start and end must differ; an earlier end receives a wrap-to-next
period flag. Scheduling a period does not imply the same enabled-state polarity
for sleep and record: `sleep on` clears its disabled flag, while `record on`
sets its enable flag. Queries `config sleep`/`config record` print the state.

E2 weekday labels were recovered from initialized data at RAM `0x20000818`–
`0x20000830`; weekly/monthly sleep validation is at `0x0800da30`/`0x0800db48`.
Firmware validates the truncated byte, so clients must reject values outside the
normal ranges before serialization.

### `config save/default` and `prot` storage

The E2 configuration callback is `0x08010dc8`. Its persistence helper
`0x080201de` stores each four-byte data word followed by a **one-byte check
value**, so serialized EEPROM blocks occupy five bytes per runtime word:

| Callback operation | EEPROM 0 start | Runtime data bytes | Meaning |
| --- | --- | --- | --- |
| `0x0f` | `0x5a9` | 192 | Cell/battery parameters |
| `0x11` | `0x699` | 192 | Pack parameters |
| `0x15` | `0x59a` | 12 | Additional configuration block |
| `0x17` | `0x58b` | 12 | Sleep-control block |
| `0x19` | `0x581`, `0x586` | 4 each | Battery and pack protection-enable masks |
| `0x1d` | `0x78b` | 16 | Hardware-sleep/scheduling configuration block |
| `0x21` | `0x7a6` | 4 | Under-voltage time; also updates a GPIO output |

`config save` invokes 0x0f/0x11/0x17/0x21/0x1d/0x15 and writes the raw two-byte
record interval at `0x38d`. It does **not** invoke operation 0x19: `prot` writes
its masks through 0x19 as part of its own command path. `config default` supplies
restore flags to the parameter callbacks, sets additional scheduling defaults,
and persists the resulting blocks. This establishes direct EEPROM effects;
it is not just a dirty flag waiting for a reset.

The word/check helper ignores individual EEPROM write return values and itself
returns zero. Several callers also discard callback status, so the footer cannot
verify every configuration word was saved. A later readback is needed for a
future implementation to confirm persistence.

### Communication settings and hidden modes

`couls`' handler maps `iah` to runtime mode 1, `vah` to mode 3, `asic` to mode 4,
and `default` to mode 3. It reports `IAH`, `IAH_VOL` or `ASIC`; no direct EEPROM
write appears in this handler (`0x0800f25c`–`0x0800f2fc`). The naming establishes
selection, not a complete mathematical specification of the SOC algorithms.

The reviewed E2 console frontend at `0x080251d8` **requires a local-table match
before consulting the remote table**. `couls`, and E2 `soh`, have no such local
entry; ordinary text invocation is rejected before their handler can run.
A remote-table entry/help listing alone does not make them callable. No
alternate public text spelling was found; do not expose invented aliases.

The live communication activation and stored bytes are distinguished in
[Communication activation and electrical controls](#communication-activation-and-electrical-controls).

## Display and Euro diagnostics

E2 `disp` (`0x0800a000`) accepts:

```text
disp pwrs module
disp dtls module
disp pwrs module bats cell
disp pwrs module volt
disp pwrs module curr
disp pwrs module temp
disp value
```

Module/cell/value are D; cells are **zero-based**. The master checks module
presence; another module requires its own address. The explicit-cell bound is
checked using the connected module's cell count, which may differ from the
selected module's count: validate against the selected module in a future client.
Selection forms enable a background display and initialize its row counter.
Bare `disp` fails; literal `bats` is not itself a top-level selection.

`disp 0` clears the enable/type/selection/counter state and stops display.
`disp 1..300` stores the value at state `+0x14` and sets `+0x10` to 1; it does
not itself choose/enable a display type. The reviewed output consumer
`0x0800a3cc` does **not read those two fields**, so the setter alone does not
establish “seconds between updates.” It is not justified to assign it time units
or promise an effective cadence control. The scheduler calls the enabled display
from `0x0801543a`–`0x08015442`.

`euro` with no arguments reports manufacturing/service dates, storage days,
remaining capacity/power, efficiency/self-discharge, resistance, throughput,
deep-discharge counts, extreme-temperature durations and cycle counts.
`euro module` parses D and checks presence/own-address selection. The E2
non-master explicit-address branch at `0x0801941c` assigns the parsed address
itself to the report pointer, instead of the report-structure pointer. This
appears to be a pointer bug; prefer bare local `euro` there. `euro clear` calls
the Euro-state initializer, **so it is a mutating form**. It is tested before
the two-token count branch; do not rely on ignored extra operands.

`eurostub` with no arguments reports internal self-discharge/capacity-estimation
state. Other forms (`0x08019686` onward):

| Form | Effect |
| --- | --- |
| `eurostub init` | Calls the same initializer as `euro clear`. |
| `eurostub off` | Clears eight injection-enable bytes. |
| `eurostub slot magnitude sign` | All D; slot **0–7**, sign **0** enables positive magnitude, **1** enables its negation, **other** disables the selected slot. Stores a 32-bit runtime value. |

The handler does not verify the full required operand count before loading all
three numeric operands and does not consistently inspect conversion errors.
The E2 consumers resolve all eight slots. Enable bytes are at `0x2000d004 +
slot`; injected words are at `+0x34 + 4*slot`. These affect the **Euro analyzer's
inputs/state**, rather than replacing the module's physical measurements.

| Slot | Consumer / units | Evidence |
| --- | --- | --- |
| 0 | Module current, signed mA | `0x08017e0e`–`0x08017e2a`, normally module `+0x58`. |
| 1 | Highest cell voltage, mV | `0x08017e2c`–`0x08017e64`. |
| 2 | Lowest cell voltage, mV | `0x08017e66`–`0x08017e9e`. |
| 3 | Module SOC, percent | `0x08017ea0`–`0x08017ebc`, normally module `+0x4c`. |
| 4 | Accumulated charge throughput, whole Ah | `0x08018948`–`0x08018962`; replaces the whole counter and zeros its mAs remainder, including the mirror. |
| 5 | Accumulated discharge throughput, whole Ah | `0x08018964`–`0x0801897c`; analogous discharge counter/remainder. |
| 6 | Both reported charge/discharge cycle estimates, raw integer counts | `0x08018ab0`–`0x08018aba`; replaces the fields reported as `Chg. Dsg. Cycle` and `Chg. Dsg. Cycle2`. |
| 7 | Lowest cell temperature, mC | `0x08017dd4`–`0x08017e0c`. |

Slots 4/5 are assignments at the start of an integration pass, **not one-time
counter edits**: the routine can then add the current pass's contribution. It
integrates twice the current magnitude into an mAs remainder, carrying at
3,600,000 mAs per Ah (`0x0801897e`–`0x08018a4c`). This establishes their units
without guessing from the command's help. Slot 7 also feeds extreme-temperature
accounting (`0x08018908`). Disabling injection stops these overrides; it does not
restore previous accumulated values. Do not treat `eurostub off` as an undo.

## Hardware-test procedures visible in the application

The following describes firmware operations, not a validated external test
fixture. GPIO addresses establish software pin access; electrical connector
pinouts, active power-path polarity and safe load arrangements require board
schematics or hardware measurements.

| Command / image | Confirmed operations, result and restoration |
| --- | --- |
| `tbuz` E2 | Sets buzzer GPIO, waits 1000 delay-helper units, clears it, prints pass. It does not restore an arbitrary previous buzzer state or verify sound. `0x0802afec`. |
| `tled` E2 | Bare command cycles LED outputs with 500-unit delays and releases its test flag afterward. `tled on`/`off` drive all eight outputs; `tled 1..8 on|off` drives one (D→u16, bounds 1–8). **`tled 0` clears the test flag**; it is not a zero-indexed LED. All-output and individual controls normally leave the test flag set, unlike the bare sequence. Every successful path also invokes module control operation 0. `0x0802aa34`. |
| `tibcio nc|sc` E2 | Reads SLAVED, HOSTED and DCIN logical inputs; `nc` expects all 1, `sc` all 0. No GPIO writes in the handler; prints the readings and pass/fail, returns zero on mismatch. `0x0802b2e0`. |
| `tcbnio nc|sc` E2 | Same comparison convention for SLAVED/HOSTED, without DCIN. No GPIO writes in the handler. `0x0802b408`. |
| `tmos cfet|dfet` E2 | Requires matching charge/discharge state and initial current strictly between **0 and +100000 mA**, or **−100000 and 0 mA**, respectively. Clears selected FET GPIO, waits 2500 helper units, resamples, sets GPIO, waits 2500 more; pass requires sampled off-current exactly zero. It restores the GPIO to set, not a saved prior level. State/current failures can still return zero. `0x0800f998`. |
| `tdct` E2 | Clears GPIO masks `0x1000/0x2000/0x4000` on peripheral base `0x40011800`, then sets/clears each in turn and checks input `0x4001180f`, with 500-unit delays. Leaves all three cleared; reports accumulated mismatch count through pass/fail, returns zero. `0x080293b4`. |
| `tflash` E2 | Reads flash ID and requires capacity byte **0x16**. Erases the sector at flash address **0**, verifies byte 0 is FF, programs **55**, verifies it, erases again and checks FF. It does **not restore that sector's old contents**. After the successful test path it clears event/history indices/count metadata even though their payload allocations are elsewhere. Several failed test paths print failure and return zero. `0x0802b598`. |
| `ti2c` E2 | Reads EEPROM identification bytes through bus 2, then **writes six bytes of the built-in Pylon identification string to EEPROM 1 offset 0** and checks five bytes through bus 3. No restoration in this handler. Reports failure flags for EEPROM/current-IC/I2C categories; returns zero. `0x0802a8c0`. |
| `tcan` E2 | Builds a four-byte test frame with identifier **0x101**, transmits through CAN peripheral `0x40006800`, waits for a four-byte receive pattern equal to **0x55aaaa55** from `0x40006400`, with a 5000-iteration timeout. Reinitializes communication afterward. This requires a working return path between those interfaces, not a console-port number argument. `0x0802a5f0`. |
| `tusart` E2 | Manipulates USART1 at `0x40013800`, sends a four-byte built-in pattern and compares returned bytes. Some transmit-ready/complete loops have **no timeout**. Reinitialization is attempted at the end; exact external loopback wiring is not encoded as a command parameter. `0x0802a760`. |
| `tbld` E2 | Chooses monitor-IC masks according to monitor type 0x0d/0x0b, enables balancing through monitor drivers and waits 2000 helper units. No explicit disable/restore follows in the handler; prints pass regardless of driver return. No value operand is accepted. `0x0802b50c`. |
| `tsoftdsg` E2 | Disables normal discharge control flag, manipulates soft-start GPIO, samples current three times and checks the sum **−4500..−1500 mA inclusive**. Clears soft-start, waits and requires current **>= −500 mA**. Finally forces normal control flags/FET output on; it does not restore a saved state. Multiple 2000/100-unit delays. Prints diagnostic sums on failure, returns zero. `0x0802b73c`. |
| `trdagevolt` E2 | Reads EEPROM 0: eight bytes at `0x7e8` for maximum-difference extrema; four voltage/current sample pairs at `0x7b8+8*i` and `0x7d8+4*i`; lowest/highest aged OV voltages at `0x7b3/0x7f6`. No writes in this handler; EEPROM read statuses are ignored. `0x0802a30c`. |
| `tagevolt` C | Reads the four-byte aged minimum from EEPROM 0 `0x7b3`; prints pass for **>=3451 mV**, failure below it. Read return is ignored; no writes. `0x0802da18`. |
| `tpwr` C | Pass if current cached module voltage **>=50000 mV**; no upper bound and no explicit fresh-sample request. No write. `0x0800fac8`. |
| `tsoh` C | Checks the SOH-event count at module `+0xd4`; zero passes, nonzero fails with count. No write; footer still successful on mismatch. `0x0800fa86`. |
| `tsto` C | Reads cached self-test/system-fault word at module `+0x40`, filters with mask **0xfffeffbf** and prints fault categories. **It does not drive a self-test output**. No writes. `0x0800fb28`. |
| `tsoc` C | Queries gauge identity/version, invokes the embedded programming script when version is not 6, checks voltage/SOC and may issue gauge reset. Pass requires successful transfers, expected identity, and version 6. Not a pure gauge read. `0x08021e0c`. |

Delay helpers implement repeated waits of 1000 hardware-timer counts per unit
(E2 `0x08017006`, C `0x08016db0`). The application must initialize the timer
correctly for the intended real-time duration; the numeric arguments above are
retained without promising exact wall-clock time on every board/clock setup.

### Communication activation and electrical controls

E2 `setprt sma|lg` updates the live protocol structure immediately: mode byte
1/0, two scheduling fields 1000/5000, and transmit/receive function pointers
(SMA `0x08037710/0x08037746`; LG `0x08028108/0x080286de`). It calls CAN
configuration `0x08022ed6` with rate **500000** and mode 1/0, then stores EEPROM
0 `0x7ab`. Unchanged selection does not reconfigure. This is not merely a
“take effect after reboot” persistent setting.

`urates` only updates its RAM value and EEPROM in its own handler. UART
initializer `0x0801f926` reads that value to configure USART1, while retaining
115200 for the other USART. A separate initializer `0x080211a4` can overwrite
the RAM value with **9600 or 115200 based on a GPIO input**. Consequently,
printing the requested cached rate proves neither immediate UART change nor
that it will override hardware-selected startup behavior. Reinitialization and
board inputs must be considered when implementing or testing this setting.

`ctrl afuse` callback 0x29 has persistent effects: argument zero sets a GPIO,
sets a runtime flag and writes `0x5a5a5a5a` to EEPROM 0 `0x7f0`; it may write a
55/AA marker at `0x7f5` according to current state bits. The opposite branch
clears the flag/markers and fault-state bits. The command inverts on/off before
this callback, as described in the parameter reference. This is more than a
transient current-limit flag, but the circuit action must not be called a
physical fuse blow without board-level evidence.

## Reset, shutdown and the missing update receiver

E2 `trst` sets reset/system-event flags, creates a history record, persists both
state blocks, then reaches the Cortex-M reset request. Erase commands are not an
implicit part of reset. This explains why a software reset can save runtime
changes before restarting.

E2 `shut` sets a shutdown flag. On module 1 it initiates broadcast address FF
and sets manager state 2 or 3 according to rack state; non-master execution calls
`0x08014ecc` directly. That sequence requests measurement/control operations,
creates a history record, updates shutdown statistics and persists state. It
changes output/control flags, waits, and can return with **`Power Input OK,
Cannot shut down!`** (`0x0801507a`). The footer therefore does not prove that
power was removed. There is no two-command confirmation guard in the handler.
Actual loss of power and subsequent wake sources depend on external power and
board circuitry; an unpowered MCU cannot report its own wake logic through this
application. Neither a reliable “off after N seconds” guarantee nor a universal
wake sequence follows from these application images alone.

E2 `updata` at `0x08028d1e`:

1. Prints the version and restart notice and invokes module control operation
   `0x13` with zero.
2. Prepares MCU flash at **0x0803f000**, unlocks flash control and writes marker
   **0x55aa55aa** there.
3. Checks programming status **6**. Failure relocks and returns 1; success
   relocks, delays 1000 helper units and requests system reset.

It does **not** receive a firmware image through this console handler. The
reviewed images begin at **0x08003800**; the preceding bootloader region
`0x08000000..0x080037ff` is absent. The marker page is also outside the E2 image
payload. Thus the bootloader transfer commands, validation/recovery rules and
update-mode timeout cannot be recovered from the supplied application bytes.
Closing that gap needs the matching bootloader or a separate updater/protocol
analysis; it is a source limitation, not an undocumented optional `updata`
parameter. No live update was attempted.

## Independently checked C-image differences

Shared names do not imply shared electrical procedures. These contracts were
checked directly in C rather than copied from E2:

| Area | C finding and evidence |
| --- | --- |
| Persistence | Callback `0x080109e2`, wired at initialization `0x08012218`, uses the same 124-byte EEPROM-0 `0x38f` / 296-byte EEPROM-1 `0x658` split. Extended checksum covers 294 bytes, stored at module `0x22a`. |
| Record query grammar | C `datalist` has the same 3/4/5/6-total-token dispatch: summary, dtls, all-cell bat field, single-cell bat field. Detailed branch `0x0800ba3c`; field branches `0x0800c100/0x0800c274`. Do not infer field units from the table header alone. |
| Charge-current test | No operand uses **10000 ±50 mA**; one D operand uses supplied current ±50. Only two total tokens allowed. `0x0800f700`. |
| Discharge-current test | No operand uses **−1000 ±100 mA**; one D magnitude is negated but uses **±50 mA**, unlike E2's ±100 default tolerance for the one-operand form. `0x0800f7c4`. |
| SOC tests | `tsoh`, `tpwr`, `tagevolt`, `tsto` are cached/read comparisons described above; `tsoc` can program/reset the gauge. These are materially different mutation classifications. |
| Fuel-gauge hardware | C uses one-byte `socr/socw` register operations, descriptor-based `soccfg` and the embedded gauge-programming script. E2 INA operations are not aliases of these C handlers. |

The catalog still defines exact command availability and argument ceilings for
both images. Board-specific pin behavior, external fixtures and every common
handler's full cross-image equivalence are not assumed by this table. The
E2-specific sections above retain their explicit scope.

## Reproducing the data-derived findings

The stdlib-only [detail extractor](../scripts/extract_firmware_details.py) checks
the same reviewed hashes as the command extractor, reconstructs bounded
initialized-data streams and emits the [detail metadata](firmware-details.json):
weekday labels, all 38 C gauge descriptors, initialized-data fingerprints and
programming-script counts/targets/delays/fingerprint. It emits **no programming
payloads, RAM contents or original logs**.

```sh
python scripts/extract_firmware_details.py Firmwareupdate-Pylontech-US2000_3000-V6_1.zip > /tmp/firmware-details.json
cmp docs/firmware-details.json /tmp/firmware-details.json
```

The decoder's synthetic regression tests cover literals, overlapping/extended
back-references, truncation, invalid distances and output bounds. Disassembled
handler addresses above provide the evidence for control-flow findings; decoded
tables alone are not proof of effects. Remaining gaps now concern specific
consumer/driver behavior or missing hardware/bootloader evidence, rather than
an assumption that all help-listed forms work.

## Additional E2 calibration and SOC consumers

INA initialization at `0x080214b2` installs calibration callback
**`0x080215f8`**. Its operations resolve the previously opaque `currcal` calls:

- Operation **2**, used by bare `currcal`, reads/reports stored coefficient and
  offset through module operations 0x53/0x2f. It does not run the sampling
  procedure.
- Operation **0** samples zero-current **50 times**, separated by 100 delay
  units, and stores their signed integer average as a runtime zero offset.
- Operation **1** collects another 50 samples, averages them, computes the
  coefficient/offset against the supplied reference and zero average, requires
  coefficient **800–1200 inclusive**, then persists both parameters.

The wrapper `currcal value` controls MOS outputs and delays between the zero and
reference measurements; a warning about reference !=10000 does not abort it.
Successful calibration operations 0x54/0x30 store the four-byte coefficient at
**EEPROM 1 `0x30`** and offset at **EEPROM 1 `0x35`**, each followed by a check
byte. The same storage callbacks serve manual `inacal currcoe/curroffset` and
automatic `inacal 10000`. The word/check helper's ignored driver statuses apply
here too. There is no transactional rollback to the former coefficient/offset.

The `emptyvolt` setting is consumed in cell SOC/coulomb calculation at
`0x08004e46`–`0x08004e58`, compared directly with the cell-voltage field
`+0x20`, whose displayed unit is **mV**. This establishes a **cell-mV** threshold,
not a pack-voltage setting. Below the threshold, the path replaces the working
remaining-charge value with an internal floor before recomputing cell SOC.
It does not itself send a gauge reset, erase data, or implement BatteryView's
SOC-reset sequence. The full charge-estimator algorithm has other conditions;
this comparison alone must not be presented as the entire SOC model.

`cmudtesttime` (`0x08028b70`) has the same six decimal date/time components and
byte-before-validation behavior as `time`, including two-digit year 0–99,
month/day checks and the year-modulo-four February rule. It writes **seven
bytes** to EEPROM 0 `0x3d`, or reads/displays that field with no operands.
It does not call the RTC setter. The six displayed components are established;
the seventh byte is not supplied by a seventh user argument. Unlike the ordinary
`time` form, this records a manufacturing/test timestamp rather than setting
current RTC time.

### Monitor-read count bounds

E2 `bmicrdcfg` allocates a **16-byte caller buffer**. Its reader at
`0x0801564e` receives and copies **eight bytes per IC** (six data plus two
check bytes) into that buffer. No caller limit guards the count: **copying three
or more ICs overflows the command's buffer**. The driver's own receive buffer is
256 bytes, providing a second insufficient bound for unrestricted counts.

`bmicrdcomm` uses the same 16-byte caller allocation and an analogous count-based
reader. The count is narrowed to u8 only after a setup call using the full parsed
value. Thus these are not safe “arbitrary count” diagnostics; a future client
must restrict count to the board's actual monitor configuration and no more than
**two** for these handlers. This is a software buffer bound, not evidence that
every supported board physically has two ICs. It resolves the handler/driver
limit without requiring a live overflow probe.


## Further runtime-consumer findings

### `mostest` enables active background fault checks (E2)

The stored markers enable byte `0x20000967`, tested at
`0x08011a84`–`0x08011a8a`. The periodic module path calls this check at
`0x080072ea`; a separate readiness byte (`0x20000d44`) must also be nonzero.
Thus enabling the flag is not merely changing a report label or running the
one-shot `tmos` procedure.

The gated routines are `0x0801182c` and `0x080118ec`:

- The first checks module `+0x270`, two digital input levels, and current below
  **−999 mA**. It accumulates a byte counter using the module interval; at 6 it
  starts reporting the condition, and at 10 it sets fault bit `0x800`, resets
  the counter and invokes callback operation `0x29` with value zero.
- The second checks module `+0x26f` and another digital input. With current
  **at least 1000 mA**, it uses a similar 6/10 counter and sets fault bit
  `0x400` before invoking the same operation. A further branch checks module
  voltage **at least 60000 mV** or a cell voltage **at least 4200 mV**, with a
  counter threshold of 16, and can invoke that operation too. Its cell loop
  includes index equal to the cell count (`0x080119b8`–`0x080119be`), an apparent
  off-by-one bug; do not copy it into a client implementation.
- Operation `0x29` is the AFUSE GPIO/persistent-marker operation described in
  the parameter reference and above. If either routine reports a condition,
  the caller stores an event and requests both statistics and extended-state
  persistence (`0x08011aac`–`0x08011aca`).

These are counter thresholds, not a claim of exact seconds. The board's circuit
and pin polarity are still needed to name the electrical failure precisely or
prove what the AFUSE circuit physically does. The code does establish that
`mostest on` can enable consequential background actions.

### `tmprctrl 97/98` and measurement refresh (E2)

Selector **98** writes module `+0x60` and clears the refresh-enable byte at
`0x20000ccd`. The ordinary measurement path obtains callback operation `0x11`
into that same module field (`0x0800535a`–`0x08005366`). Both the callback wrapper
(`0x08011d62`) and reader (`0x080162e4`–`0x0801630c`) consult the enable byte.
This explains why the supplied value persists across ordinary refreshes; the
physical identity/location of that second module temperature sensor still needs
board evidence. Selector 99 similarly shares its refresh gate with cell
thermometry, so these overrides are not independent channels.

Selector **97** instead sets the override-enable byte at `0x20000ccf` and stores
its value at `0x20000ce0`. The consumer at `0x08005378` copies it into
`0x20000cd8`, then tests the unsigned interval **2980–3020 inclusive**. Outside
that interval it increments a saturating counter; at ten observations it sets
module fault bit **`0x40`**. An in-range value clears the counter; that branch
does not itself clear an already-set fault bit.

The normal source for `0x20000cd8` is the monitor auxiliary ADC read at
`0x08016378`–`0x0801638c`, divided by ten. Selector 97 therefore overrides this
**monitor-reference diagnostic**, not a cell/environment temperature used by the
ordinary temperature protection checks. Although the command reuses the signed
−40000..100000 validation, that does not make this diagnostic's value mC. The
nominal 3000 and ADC path suggest a reference voltage; its exact physical input
and calibration require board/monitor evidence. `tmprctrl 0` disables the
override and re-enables measurement refresh; it does not restore a saved reading
or explicitly clear the latched fault.

### `tinput present/absent` temporarily drives outputs (E2)

The handler at `0x0802b22c`–`0x0802b290` passes value 3 to module callback
`+0x28c`, first operation **4**, then operation **5** after a 100-unit delay and
one input sample. Initialization at `0x08012398`–`0x0801239c` wires that callback
to `0x08010dc8`. Its jump table resolves those operations to:

| Operation | Visible software action |
| --- | --- |
| 4, `0x080111be` | Clear GPIO port `0x40011400` masks `0x40` and `0x20`. |
| 5, `0x080111e6` | Set the same port's `0x20` mask and clear the halfword at `0x20000d48`. |

The low-level helper at `0x0801e772` writes the set/reset registers, confirming
actual output writes rather than mere cached-state updates. Neither branch
saves previous levels; operation 5 does not explicitly restore `0x40`.
`present` passes when the input identified by `0x40011404` reads zero; `absent`
passes when it reads nonzero. Thus these forms are **active test sequences with
forced final levels**, not passive input queries. The physical circuit attached
to those pins still requires board evidence. `rv`/`dcov` use direct input reads
and do not take this bracketing path. Pass/fail text matters: both successful
parsing paths can return zero even when the electrical comparison fails.

### Gauge report scaling (C)

The driver initializer at `0x08022444` passes **4** to `0x080203a8`, which stores
that byte at `0x20000b48` while installing bus callbacks. `socd` then uses:

| Gauge register | Decoding / reported value |
| --- | --- |
| `0x08`, two bytes | Little-endian unsigned pack voltage, mV, no multiplier. |
| `0x10`, two bytes | Little-endian **signed 16-bit** current multiplied by 4, mA. |
| `0x02`, one byte | SOC percent, no multiplier. |
| `0x04`, two bytes | Little-endian unsigned remaining capacity multiplied by 4, mAh. |

Evidence: handler `0x0802117a`–`0x08021204`, initializer
`0x08022456`–`0x08022462`, scale store `0x080203c0`. This is the initialized
scale for the reviewed C image, not a universal bq34z100 convention or a detected
value from the connected battery. `socd` does not check each bus-read return
before formatting the result; a successful console footer alone does not prove
all four measurements were read successfully.

### Display cadence and additional cross-image checks

All identified E2 literal references to the display state at `0x20000ce4` are in
the selection setter, output routine and scheduler. The scheduler only checks
the enable byte and calls the output routine; neither consumer uses the scalar
at `+0x14` or the flag at `+0x10`. No effective interval control was established.
The C setter independently has the same two writes at
`0x0800a248`–`0x0800a24c`. Keep the positive scalar form documented as a stored
value, without promising a cadence change.

C `tmprctrl` independently preserves the 97/98 setter layout at
`0x0800ee9c`–`0x0800eeb2`, using control base `0x200003dc`; its reference consumer
at `0x0800539c` has the same 2980–3020 check. This verifies that particular
behavior in both images, not every common command's full equivalence.

### Boundaries of this additional analysis

C independently has the same missing lower-bound check and two raw stores in
its `oc2d` setter (`0x0800e31c`–`0x0800e340`). The signedness issue therefore
affects both reviewed images.

The negative `oc2d` setter still demonstrably accepts and stores a signed value,
but a complete route from that field through hardware programming/protection
timing was not established. The ordinary software protection dispatch uses
indirect callback/index tables; finding a signed comparison elsewhere does not
prove it consumes this particular field. **No claim of immediate protection,
infinite delay, or harmless no-op is justified.** A future client should still
accept only 0–5000 ms. This remains a specific downstream-analysis gap.

Physical sensor/pin identities, power-loss/wake behavior, live fault recovery,
and the absent bootloader remain outside what these application paths prove.
