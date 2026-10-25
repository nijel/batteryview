Diagnostics and hardware tests
==============================

Use this chapter for display, communication diagnostics, injected readings, and
hardware-test procedures. The tables state operands, units, operating effects,
and result interpretation. A test-like name does not imply a passive read:
commands can drive outputs, alter storage, or enter loops.

Interpret an operation-specific result independently of the standard success
footer. For ordinary read-only counters, clock, logs, and configuration, see
:doc:`console`, :doc:`records`, :doc:`calibration`, and :doc:`configuration`.

.. _firmware-parameters-manufacturing-tests-and-injected-readings:

Manufacturing tests and injected readings
-----------------------------------------

Tests may change output state, sample hardware, modify storage, or stop normal operation. A
printed ``Test result:pass/fail`` must be interpreted independently of the standard console
footer.

.. _firmware-parameters-parameters-confirmed-from-e2-handlers:

E2 test-command parameters
~~~~~~~~~~~~~~~~~~~~~~~~~~

+-----------------------------------------------+-----------------------------------------------+
| Form                                          | Parameters and behavior                       |
+===============================================+===============================================+
| ``tbar barcode``                              | Exactly **16 alphanumeric characters**.       |
|                                               | Fourth character ``1`` requires 15 cells;     |
|                                               | ``4`` requires 16. Other fourth characters    |
|                                               | skip those particular checks. Writes 16 bytes |
|                                               | at EEPROM 0 ``0x21``, reads back and          |
|                                               | compares. Inspect the test result, not just   |
|                                               | the footer.                                   |
+-----------------------------------------------+-----------------------------------------------+
| ``tdip expected``                             | D **0–15**, required. Reads four active-low   |
|                                               | GPIO bits and compares the assembled DIP      |
|                                               | value with the expected value. Does not set   |
|                                               | DIP switches. Mismatch can still return zero. |
+-----------------------------------------------+-----------------------------------------------+
| ``tinput {rv\|dcov\|present\|absent}``        | Compares hardware input against the selected  |
|                                               | condition. The present/absent paths clear two |
|                                               | GPIO outputs, delay/sample, then force one    |
|                                               | output high and reset a counter; they do not  |
|                                               | restore saved levels. See the supplement for  |
|                                               | callback/pin evidence.                        |
+-----------------------------------------------+-----------------------------------------------+
| ``tchgc [current [limit]]``                   | Both D, mA. No operands uses **10000 ± 50     |
|                                               | mA**. One operand uses supplied current ±50.  |
|                                               | Two use supplied current ±limit, with **limit |
|                                               | 50–500 inclusive**. Requires charging state;  |
|                                               | otherwise prints ``not chg``.                 |
+-----------------------------------------------+-----------------------------------------------+
| ``tdisc [magnitude [limit]]``                 | Both D, mA; supplied magnitude is **negated   |
|                                               | internally**. No operands uses **−1000 ±100   |
|                                               | mA**; one uses negative supplied magnitude    |
|                                               | ±100. Explicit limit must be **100–500        |
|                                               | inclusive**. Requires discharge state;        |
|                                               | otherwise prints ``not dsg``.                 |
+-----------------------------------------------+-----------------------------------------------+
| ``tvolt [spread]``                            | Optional D **maximum cell-voltage spread in   |
|                                               | mV**, not a target voltage. Compares          |
|                                               | max-minus-min with supplied spread, prints    |
|                                               | cell values/difference. Also checks sampling  |
|                                               | stability and can report                      |
|                                               | ``Batt Volt data instability``.               |
+-----------------------------------------------+-----------------------------------------------+
| ``ttmp [spread]``                             | Optional D **maximum cell-temperature spread  |
|                                               | in mC**, not a target temperature. Without    |
|                                               | it, the test uses built-in                    |
|                                               | spread/plausibility checks; supplied spread   |
|                                               | changes the printed pass/fail comparison.     |
|                                               | Prints cell temperatures/difference.          |
+-----------------------------------------------+-----------------------------------------------+
| ``teepr``                                     | No operands. On each EEPROM chip, reads byte  |
|                                               | ``0x26``, writes ``0x55``, reads back and     |
|                                               | attempts restoration. This actively writes,   |
|                                               | including a location within the chip-0        |
|                                               | barcode field.                                |
+-----------------------------------------------+-----------------------------------------------+
| ``twdg``                                      | No operands accepted; stops watchdog feeding  |
|                                               | according to help. Exact reset delay depends  |
|                                               | on watchdog configuration, not a command      |
|                                               | parameter.                                    |
+-----------------------------------------------+-----------------------------------------------+
| ``tcan``, ``tbld``                            | **No operands accepted by the dispatcher**.   |
|                                               | Help advertises a port/value which cannot be  |
|                                               | supplied under the registered one-token       |
|                                               | ceiling. Hardware test effects still require  |
|                                               | deeper review.                                |
+-----------------------------------------------+-----------------------------------------------+

.. admonition:: Firmware evidence

   Evidence: E2 ``tbar`` ``0x0802b080``, ``tinput`` ``0x0802b1b8``, ``tchgc`` ``0x0800f75c``,
   ``tdisc`` ``0x0800f888``, ``tvolt`` ``0x0800f418``, ``ttmp`` ``0x0800f548``, ``teepr``
   ``0x0801045a``. C ``tchgc``/``tdisc`` permit at most **one** operand; do not send the E2
   tolerance operand there. C defaults/tolerances were independently traced and are tabulated in
   the supplement; notably its one-operand discharge test uses ±50 mA.

.. _firmware-parameters-tmprctrl-the-selector-also-chooses-the-quantity:

``tmprctrl``: the selector also chooses the quantity
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

E2 handler ``0x0800ee1c`` accepts these forms:

.. code:: text

   tmprctrl 0
   tmprctrl 1 selector value

The short form accepts **zero only** and restores several normal-measurement flags; it is not a
generic Boolean toggle. In the long form the flag must be 1, selector is D and value is S:

+-----------------------------------------------+-----------------------------------------------+
| Selector                                      | Inspected operation                           |
+===============================================+===============================================+
| ``0 .. cell-count-1``                         | Writes that cell’s temperature field.         |
+-----------------------------------------------+-----------------------------------------------+
| ``99``                                        | Writes the module environment-temperature     |
|                                               | field.                                        |
+-----------------------------------------------+-----------------------------------------------+
| ``98``                                        | Writes another module temperature field;      |
|                                               | physical sensor mapping unverified.           |
+-----------------------------------------------+-----------------------------------------------+
| ``97``                                        | Overrides a monitor auxiliary-ADC diagnostic; |
|                                               | feeds a monitor-reference diagnostic with a   |
|                                               | 2980–3020 acceptance window and fault         |
|                                               | counter, rather than ordinary thermometry;    |
|                                               | see the supplement.                           |
+-----------------------------------------------+-----------------------------------------------+
| ``100 .. 100+cell-count-1``                   | Subtracts 100 and writes that cell’s          |
|                                               | **voltage** field.                            |
+-----------------------------------------------+-----------------------------------------------+

Temperature-path values are accepted from **−40000 through 100000 inclusive** (mC for
thermometry; selector 97 reuses this bound for a different diagnostic). The voltage path checks
signed value ``< 5001`` but lacks an explicit nonnegative check; a client should reject negative
voltage. These are runtime injected readings/flags, not temperature calibration EEPROM writes.

.. _firmware-parameters-other-parameterized-handlers-remaining-limits:

Other test-command parameters
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

+-----------------------------------------------+-----------------------------------------------+
| Command                                       | Known form and unresolved details             |
+===============================================+===============================================+
| ``bmicrdcfg total-ic``,                       | Required **D** IC-count operand. E2           |
| ``bmicrdcomm total-ic``                       | ``bmicrdcfg`` rejects zero; ``bmicrdcomm``    |
|                                               | has no corresponding zero check. Both pass a  |
|                                               | u8 count after setup; no upper bound is       |
|                                               | enforced. The reader copies eight bytes per   |
|                                               | IC into the command’s 16-byte buffer: **count |
|                                               | >=3 overflows it**. Restrict to the actual    |
|                                               | board count and at most two; details in       |
|                                               | supplement.                                   |
+-----------------------------------------------+-----------------------------------------------+
| ``disp ...``                                  | Repeated-display selections include ``pwrs``, |
|                                               | ``bats``, ``volt``, ``curr``, ``temp``;       |
|                                               | numeric selection and scalar forms exist.     |
|                                               | Complete selection forms and ``disp 0`` stop  |
|                                               | behavior are in the supplement; a positive    |
|                                               | scalar writes fields not consulted by the     |
|                                               | reviewed display consumer, so time units are  |
|                                               | not assumed. The timer path now establishes a |
|                                               | nominal two-second display cadence in both    |
|                                               | reviewed images.                              |
+-----------------------------------------------+-----------------------------------------------+
| ``euro ...``, ``eurostub ...``                | Report/clear and init/off/three-number        |
|                                               | injection forms, all eight slot               |
|                                               | meanings/units and the non-master Euro        |
|                                               | pointer bug are in the supplement.            |
+-----------------------------------------------+-----------------------------------------------+
| ``tled selector [on\|off]``                   | ``tled``, ``tled on|off``,                    |
|                                               | ``tled 1..8 on|off`` and ``tled 0`` are       |
|                                               | traced in the supplement, including           |
|                                               | persistent test-mode flag behavior.           |
+-----------------------------------------------+-----------------------------------------------+
| ``tmos {cfet\|dfet}``                         | Selects FET test; initial-current bounds,     |
|                                               | clear/set sequence, delays and forced         |
|                                               | restoration level are in the supplement.      |
|                                               | External fixture requirements remain          |
|                                               | board-specific.                               |
+-----------------------------------------------+-----------------------------------------------+
| ``tibcio {nc\|sc}``, ``tcbnio {nc\|sc}``      | Passive logical-input comparisons: nc expects |
|                                               | 1, sc expects 0; tested SLAVED/HOSTED/DCIN    |
|                                               | signals and status handling are in the        |
|                                               | supplement.                                   |
+-----------------------------------------------+-----------------------------------------------+
| ``tver version`` (C)                          | Required **H** value, compared with the       |
|                                               | runtime software-version word; it **does not  |
|                                               | set a version**. Prints pass/fail and the     |
|                                               | actual version as                             |
|                                               | ``V(high bits).(low byte)``, then returns     |
|                                               | zero even on mismatch. C                      |
|                                               | ``0x0800fbdc``–``0x0800fc34``.                |
+-----------------------------------------------+-----------------------------------------------+

.. _firmware-parameters-no-operand-hardware-handlers:

Hardware commands without operands
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

The registered token ceiling confirms that the following accept **no additional console
operands**. Handler-confirmed details are identified explicitly; the remaining help-based
purposes do not establish a complete electrical test procedure:

+-----------------------------------------------+-----------------------------------------------+
| Command                                       | Advertised role / remaining question          |
+===============================================+===============================================+
| ``tbuz``                                      | Drives buzzer set, delays 1000 helper units,  |
|                                               | then clears it; no sound verification or      |
|                                               | arbitrary prior-state restoration.            |
+-----------------------------------------------+-----------------------------------------------+
| ``tetmp``                                     | E2 computes the signed integer average of     |
|                                               | cell temperatures, refreshes two module       |
|                                               | sensor fields via callbacks and checks **each |
|                                               | lies between average −10000 and average       |
|                                               | +30000 mC inclusive**. Prints pass/fail and   |
|                                               | sensor/average values, but returns zero even  |
|                                               | on test failure. Handler                      |
|                                               | ``0x0800f654``–``0x0800f70a``; physical       |
|                                               | identity of the two sensors remains           |
|                                               | unverified.                                   |
+-----------------------------------------------+-----------------------------------------------+
| ``tflash``                                    | Erases sector at address 0, writes/checks 55, |
|                                               | erases/checks FF, then clears record          |
|                                               | metadata; no restoration of old sector        |
|                                               | contents. See supplement.                     |
+-----------------------------------------------+-----------------------------------------------+
| ``ti2c``                                      | Checks buses 2/3 and EEPROM identity,         |
|                                               | including an un-restored six-byte write to    |
|                                               | EEPROM 1 offset 0. See supplement.            |
+-----------------------------------------------+-----------------------------------------------+
| ``tusart``                                    | USART1 four-byte send/receive test with       |
|                                               | unbounded transmit-ready loops; see           |
|                                               | supplement for peripheral and cleanup limits. |
+-----------------------------------------------+-----------------------------------------------+
| ``tdct``                                      | Steps three GPIO outputs while testing a      |
|                                               | logical return input, leaves outputs cleared; |
|                                               | sequence and masks in supplement.             |
+-----------------------------------------------+-----------------------------------------------+
| ``tclear``                                    | E2 zeros event/history write indices at       |
|                                               | EEPROM 0 ``0x389/0x38b``, diagnostic-log      |
|                                               | index at ``0x387`` (two bytes each), and      |
|                                               | associated RAM count/wrap fields. Clears the  |
|                                               | same runtime statistics as ``statc``,         |
|                                               | preserving reset/life-warning/life-alarm      |
|                                               | counts, then invokes its state callback. Also |
|                                               | zeroes 0x128 runtime bytes at module          |
|                                               | ``0x104`` and calls ``0x0800457a``; that      |
|                                               | callee saves the 296-byte extended-state      |
|                                               | block with its checksum, as resolved in the   |
|                                               | supplement. No flash-erasure loop in this     |
|                                               | handler. Prints the pass string and returns   |
|                                               | zero without checking EEPROM write results;   |
|                                               | **not equivalent to datac or full EEPROM      |
|                                               | erase**. E2 ``0x0800fb00``–``0x0800fbb2``.    |
+-----------------------------------------------+-----------------------------------------------+
| ``tsoftdsg``                                  | Controls soft-start/FET flags, checks         |
|                                               | three-sample current sum and later            |
|                                               | off-current, then forces controls on; see     |
|                                               | supplement.                                   |
+-----------------------------------------------+-----------------------------------------------+
| ``trdagevolt``                                | Reads EEPROM-0 extrema, four voltage/current  |
|                                               | pairs and aged OV limits; offsets in          |
|                                               | supplement.                                   |
+-----------------------------------------------+-----------------------------------------------+
| ``tagevolt`` (C)                              | Read-only EEPROM minimum-voltage comparison;  |
|                                               | passes at >=3451 mV. See supplement.          |
+-----------------------------------------------+-----------------------------------------------+
| ``tpwr`` (C)                                  | Cached pack-voltage comparison, >=50000 mV    |
|                                               | passes; no write or upper bound.              |
+-----------------------------------------------+-----------------------------------------------+
| ``tsoh`` (C)                                  | Read-only SOH-event count check; zero passes, |
|                                               | nonzero fails. Footer still succeeds.         |
+-----------------------------------------------+-----------------------------------------------+
| ``tsto`` (C)                                  | Read-only cached system-fault report, **does  |
|                                               | not drive an output**. Mask and categories in |
|                                               | supplement.                                   |
+-----------------------------------------------+-----------------------------------------------+
| ``tsoc`` (C)                                  | Can run the embedded gauge-programming script |
|                                               | when version !=6 and issue gauge reset; see   |
|                                               | supplement.                                   |
+-----------------------------------------------+-----------------------------------------------+

.. _firmware-behavior-display-and-euro-diagnostics:

Display and Euro diagnostics
----------------------------

E2 ``disp`` (``0x0800a000``) accepts:

.. code:: text

   disp pwrs module
   disp dtls module
   disp pwrs module bats cell
   disp pwrs module volt
   disp pwrs module curr
   disp pwrs module temp
   disp value

Module/cell/value are D; cells are **zero-based**. The master checks module presence; another
module requires its own address. The explicit-cell bound is checked using the connected module’s
cell count, which may differ from the selected module’s count: validate against the selected
module in a future client. Selection forms enable a background display and initialize its row
counter. Bare ``disp`` fails; literal ``bats`` is not itself a top-level selection.

``disp 0`` clears the enable/type/selection/counter state and stops display. ``disp 1..300``
stores the value at state ``+0x14`` and sets ``+0x10`` to 1; it does not itself choose/enable a
display type. The reviewed output consumer ``0x0800a3cc`` does **not read those two fields**, so
the setter alone does not establish “seconds between updates.” It is not justified to assign it
time units or promise an effective cadence control. The scheduler calls the enabled display from
``0x0801543a``–``0x08015442``.

``euro`` with no arguments reports manufacturing/service dates, storage days, remaining
capacity/power, efficiency/self-discharge, resistance, throughput, deep-discharge counts,
extreme-temperature durations and cycle counts. ``euro module`` parses D and checks
presence/own-address selection. The E2 non-master explicit-address branch at ``0x0801941c``
assigns the parsed address itself to the report pointer, instead of the report-structure
pointer. This appears to be a pointer bug; prefer bare local ``euro`` there. ``euro clear``
calls the Euro-state initializer, **so it is a mutating form**. It is tested before the
two-token count branch; do not rely on ignored extra operands.

``eurostub`` with no arguments reports internal self-discharge/capacity-estimation state. Other
forms (``0x08019686`` onward):

+-----------------------------------------------+-----------------------------------------------+
| Form                                          | Effect                                        |
+===============================================+===============================================+
| ``eurostub init``                             | Calls the same initializer as ``euro clear``. |
+-----------------------------------------------+-----------------------------------------------+
| ``eurostub off``                              | Clears eight injection-enable bytes.          |
+-----------------------------------------------+-----------------------------------------------+
| ``eurostub slot magnitude sign``              | All D; slot **0–7**, sign **0** enables       |
|                                               | positive magnitude, **1** enables its         |
|                                               | negation, **other** disables the selected     |
|                                               | slot. Stores a 32-bit runtime value.          |
+-----------------------------------------------+-----------------------------------------------+

The handler does not verify the full required operand count before loading all three numeric
operands and does not consistently inspect conversion errors. The E2 consumers resolve all eight
slots. Enable bytes are at ``0x2000d004 + slot``; injected words are at ``+0x34 + 4*slot``.
These affect the **Euro analyzer’s inputs/state**, rather than replacing the module’s physical
measurements.

+-------------------------------+-------------------------------+--------------------------------+
| Slot                          | Consumer / units              | Evidence                       |
+===============================+===============================+================================+
| 0                             | Module current, signed mA     | ``0x08017e0e``–``0x08017e2a``, |
|                               |                               | normally module ``+0x58``.     |
+-------------------------------+-------------------------------+--------------------------------+
| 1                             | Highest cell voltage, mV      | ``0x08017e2c``–``0x08017e64``. |
+-------------------------------+-------------------------------+--------------------------------+
| 2                             | Lowest cell voltage, mV       | ``0x08017e66``–``0x08017e9e``. |
+-------------------------------+-------------------------------+--------------------------------+
| 3                             | Module SOC, percent           | ``0x08017ea0``–``0x08017ebc``, |
|                               |                               | normally module ``+0x4c``.     |
+-------------------------------+-------------------------------+--------------------------------+
| 4                             | Accumulated charge            | ``0x08018948``–``0x08018962``; |
|                               | throughput, whole Ah          | replaces the whole counter and |
|                               |                               | zeros its mAs remainder,       |
|                               |                               | including the mirror.          |
+-------------------------------+-------------------------------+--------------------------------+
| 5                             | Accumulated discharge         | ``0x08018964``–``0x0801897c``; |
|                               | throughput, whole Ah          | analogous discharge            |
|                               |                               | counter/remainder.             |
+-------------------------------+-------------------------------+--------------------------------+
| 6                             | Both reported                 | ``0x08018ab0``–``0x08018aba``; |
|                               | charge/discharge cycle        | replaces the fields reported   |
|                               | estimates, raw integer counts | as ``Chg. Dsg. Cycle`` and     |
|                               |                               | ``Chg. Dsg. Cycle2``.          |
+-------------------------------+-------------------------------+--------------------------------+
| 7                             | Lowest cell temperature, mC   | ``0x08017dd4``–``0x08017e0c``. |
+-------------------------------+-------------------------------+--------------------------------+

Slots 4/5 are assignments at the start of an integration pass, **not one-time counter edits**:
the routine can then add the current pass’s contribution. It integrates twice the current
magnitude into an mAs remainder, carrying at 3,600,000 mAs per Ah
(``0x0801897e``–``0x08018a4c``). This establishes their units without guessing from the
command’s help. Slot 7 also feeds extreme-temperature accounting (``0x08018908``). Disabling
injection stops these overrides; it does not restore previous accumulated values. Do not treat
``eurostub off`` as an undo.

.. _firmware-behavior-hardware-test-procedures-visible-in-the-application:

Hardware-test procedures and side effects
-----------------------------------------

The following describes firmware operations, not a validated external test fixture. GPIO
addresses establish software pin access; electrical connector pinouts, active power-path
polarity and safe load arrangements require board schematics or hardware measurements.

+-----------------------------------------------+-----------------------------------------------+
| Command / image                               | Confirmed operations, result and restoration  |
+===============================================+===============================================+
| ``tbuz`` E2                                   | Sets buzzer GPIO, waits 1000 delay-helper     |
|                                               | units, clears it, prints pass. It does not    |
|                                               | restore an arbitrary previous buzzer state or |
|                                               | verify sound. ``0x0802afec``.                 |
+-----------------------------------------------+-----------------------------------------------+
| ``tled`` E2                                   | Bare command cycles LED outputs with 500-unit |
|                                               | delays and releases its test flag afterward.  |
|                                               | ``tled on``/``off`` drive all eight outputs;  |
|                                               | ``tled 1..8 on|off`` drives one (D→u16,       |
|                                               | bounds 1–8). **``tled 0`` clears the test     |
|                                               | flag**; it is not a zero-indexed LED.         |
|                                               | All-output and individual controls normally   |
|                                               | leave the test flag set, unlike the bare      |
|                                               | sequence. Every successful path also invokes  |
|                                               | module control operation 0. ``0x0802aa34``.   |
+-----------------------------------------------+-----------------------------------------------+
| ``tibcio nc|sc`` E2                           | Reads SLAVED, HOSTED and DCIN logical inputs; |
|                                               | ``nc`` expects all 1, ``sc`` all 0. No GPIO   |
|                                               | writes in the handler; prints the readings    |
|                                               | and pass/fail, returns zero on mismatch.      |
|                                               | ``0x0802b2e0``.                               |
+-----------------------------------------------+-----------------------------------------------+
| ``tcbnio nc|sc`` E2                           | Same comparison convention for SLAVED/HOSTED, |
|                                               | without DCIN. No GPIO writes in the handler.  |
|                                               | ``0x0802b408``.                               |
+-----------------------------------------------+-----------------------------------------------+
| ``tmos cfet|dfet`` E2                         | Requires matching charge/discharge state and  |
|                                               | initial current strictly between **0 and      |
|                                               | +100000 mA**, or **−100000 and 0 mA**,        |
|                                               | respectively. Clears selected FET GPIO, waits |
|                                               | 2500 helper units, resamples, sets GPIO,      |
|                                               | waits 2500 more; pass requires sampled        |
|                                               | off-current exactly zero. It restores the     |
|                                               | GPIO to set, not a saved prior level.         |
|                                               | State/current failures can still return zero. |
|                                               | ``0x0800f998``.                               |
+-----------------------------------------------+-----------------------------------------------+
| ``tdct`` E2                                   | Clears GPIO masks ``0x1000/0x2000/0x4000`` on |
|                                               | peripheral base ``0x40011800``, then          |
|                                               | sets/clears each in turn and checks input     |
|                                               | ``0x4001180f``, with 500-unit delays. Leaves  |
|                                               | all three cleared; reports accumulated        |
|                                               | mismatch count through pass/fail, returns     |
|                                               | zero. ``0x080293b4``.                         |
+-----------------------------------------------+-----------------------------------------------+
| ``tflash`` E2                                 | Reads flash ID and requires capacity byte     |
|                                               | **0x16**. Erases the sector at flash address  |
|                                               | **0**, verifies byte 0 is FF, programs        |
|                                               | **55**, verifies it, erases again and checks  |
|                                               | FF. It does **not restore that sector’s old   |
|                                               | contents**. After the successful test path it |
|                                               | clears event/history indices/count metadata   |
|                                               | even though their payload allocations are     |
|                                               | elsewhere. Several failed test paths print    |
|                                               | failure and return zero. ``0x0802b598``.      |
+-----------------------------------------------+-----------------------------------------------+
| ``ti2c`` E2                                   | Reads EEPROM identification bytes through bus |
|                                               | 2, then **writes six bytes of the built-in    |
|                                               | Pylon identification string to EEPROM 1       |
|                                               | offset 0** and checks five bytes through bus  |
|                                               | 3. No restoration in this handler. Reports    |
|                                               | failure flags for EEPROM/current-IC/I2C       |
|                                               | categories; returns zero. ``0x0802a8c0``.     |
+-----------------------------------------------+-----------------------------------------------+
| ``tcan`` E2                                   | Builds a four-byte test frame with identifier |
|                                               | **0x101**, transmits through CAN peripheral   |
|                                               | ``0x40006800``, waits for a four-byte receive |
|                                               | pattern equal to **0x55aaaa55** from          |
|                                               | ``0x40006400``, with a 5000-iteration         |
|                                               | timeout. Reinitializes communication          |
|                                               | afterward. This requires a working return     |
|                                               | path between those interfaces, not a          |
|                                               | console-port number argument. ``0x0802a5f0``. |
+-----------------------------------------------+-----------------------------------------------+
| ``tusart`` E2                                 | Manipulates USART1 at ``0x40013800``, sends a |
|                                               | four-byte built-in pattern and compares       |
|                                               | returned bytes. Some transmit-ready/complete  |
|                                               | loops have **no timeout**. Reinitialization   |
|                                               | is attempted at the end; exact external       |
|                                               | loopback wiring is not encoded as a command   |
|                                               | parameter. ``0x0802a760``.                    |
+-----------------------------------------------+-----------------------------------------------+
| ``tbld`` E2                                   | Chooses monitor-IC masks according to monitor |
|                                               | type 0x0d/0x0b, enables balancing through     |
|                                               | monitor drivers and waits 2000 helper units.  |
|                                               | No explicit disable/restore follows in the    |
|                                               | handler; prints pass regardless of driver     |
|                                               | return. No value operand is accepted.         |
|                                               | ``0x0802b50c``.                               |
+-----------------------------------------------+-----------------------------------------------+
| ``tsoftdsg`` E2                               | Disables normal discharge control flag,       |
|                                               | manipulates soft-start GPIO, samples current  |
|                                               | three times and checks the sum **−4500..−1500 |
|                                               | mA inclusive**. Clears soft-start, waits and  |
|                                               | requires current **>= −500 mA**. Finally      |
|                                               | forces normal control flags/FET output on; it |
|                                               | does not restore a saved state. Multiple      |
|                                               | 2000/100-unit delays. Prints diagnostic sums  |
|                                               | on failure, returns zero. ``0x0802b73c``.     |
+-----------------------------------------------+-----------------------------------------------+
| ``trdagevolt`` E2                             | Reads EEPROM 0: eight bytes at ``0x7e8`` for  |
|                                               | maximum-difference extrema; four              |
|                                               | voltage/current sample pairs at ``0x7b8+8*i`` |
|                                               | and ``0x7d8+4*i``; lowest/highest aged OV     |
|                                               | voltages at ``0x7b3/0x7f6``. No writes in     |
|                                               | this handler; EEPROM read statuses are        |
|                                               | ignored. ``0x0802a30c``.                      |
+-----------------------------------------------+-----------------------------------------------+
| ``tagevolt`` C                                | Reads the four-byte aged minimum from EEPROM  |
|                                               | 0 ``0x7b3``; prints pass for **>=3451 mV**,   |
|                                               | failure below it. Read return is ignored; no  |
|                                               | writes. ``0x0802da18``.                       |
+-----------------------------------------------+-----------------------------------------------+
| ``tpwr`` C                                    | Pass if current cached module voltage         |
|                                               | **>=50000 mV**; no upper bound and no         |
|                                               | explicit fresh-sample request. No write.      |
|                                               | ``0x0800fac8``.                               |
+-----------------------------------------------+-----------------------------------------------+
| ``tsoh`` C                                    | Checks the SOH-event count at module          |
|                                               | ``+0xd4``; zero passes, nonzero fails with    |
|                                               | count. No write; footer still successful on   |
|                                               | mismatch. ``0x0800fa86``.                     |
+-----------------------------------------------+-----------------------------------------------+
| ``tsto`` C                                    | Reads cached self-test/system-fault word at   |
|                                               | module ``+0x40``, filters with mask           |
|                                               | **0xfffeffbf** and prints fault categories.   |
|                                               | **It does not drive a self-test output**. No  |
|                                               | writes. ``0x0800fb28``.                       |
+-----------------------------------------------+-----------------------------------------------+
| ``tsoc`` C                                    | Queries gauge identity/version, invokes the   |
|                                               | embedded programming script when version is   |
|                                               | not 6, checks voltage/SOC and may issue gauge |
|                                               | reset. Pass requires successful transfers,    |
|                                               | expected identity, and version 6. Not a pure  |
|                                               | gauge read. ``0x08021e0c``.                   |
+-----------------------------------------------+-----------------------------------------------+

Delay helpers implement repeated waits of 1000 hardware-timer counts per unit (E2
``0x08017006``, C ``0x08016db0``). The application must initialize the timer correctly for the
intended real-time duration; the numeric arguments above are retained without promising exact
wall-clock time on every board/clock setup.

.. _firmware-behavior-communication-activation-and-electrical-controls:

Communication activation and electrical controls
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

E2 ``setprt sma|lg`` updates the live protocol structure immediately: mode byte 1/0, two
scheduling fields 1000/5000, and transmit/receive function pointers (SMA
``0x08037710/0x08037746``; LG ``0x08028108/0x080286de``). It calls CAN configuration
``0x08022ed6`` with rate **500000** and mode 1/0, then stores EEPROM 0 ``0x7ab``. Unchanged
selection does not reconfigure. This is not merely a “take effect after reboot” persistent
setting.

``urates`` only updates its RAM value and EEPROM in its own handler. UART initializer
``0x0801f926`` reads that value to configure USART1, while retaining 115200 for the other USART.
A separate initializer ``0x080211a4`` can overwrite the RAM value with **9600 or 115200 based on
a GPIO input**. Consequently, printing the requested cached rate proves neither immediate UART
change nor that it will override hardware-selected startup behavior. Reinitialization and board
inputs must be considered when implementing or testing this setting.

``ctrl afuse`` callback 0x29 has persistent effects: argument zero sets a GPIO, sets a runtime
flag and writes ``0x5a5a5a5a`` to EEPROM 0 ``0x7f0``; it may write a 55/AA marker at ``0x7f5``
according to current state bits. The opposite branch clears the flag/markers and fault-state
bits. The command inverts on/off before this callback, as described in the parameter reference.
This is more than a transient current-limit flag, but the circuit action must not be called a
physical fuse blow without board-level evidence.

.. _firmware-behavior-tmprctrl-9798-and-measurement-refresh-e2:

``tmprctrl 97/98`` and measurement refresh (E2)
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

Selector **98** writes module ``+0x60`` and clears the refresh-enable byte at ``0x20000ccd``.
The ordinary measurement path obtains callback operation ``0x11`` into that same module field
(``0x0800535a``–``0x08005366``). Both the callback wrapper (``0x08011d62``) and reader
(``0x080162e4``–``0x0801630c``) consult the enable byte. This explains why the supplied value
persists across ordinary refreshes; the physical identity/location of that second module
temperature sensor still needs board evidence. Selector 99 similarly shares its refresh gate
with cell thermometry, so these overrides are not independent channels.

Selector **97** instead sets the override-enable byte at ``0x20000ccf`` and stores its value at
``0x20000ce0``. The consumer at ``0x08005378`` copies it into ``0x20000cd8``, then tests the
unsigned interval **2980–3020 inclusive**. Outside that interval it increments a saturating
counter; at ten observations it sets module fault bit **``0x40``**. An in-range value clears the
counter; that branch does not itself clear an already-set fault bit.

The normal source for ``0x20000cd8`` is the monitor auxiliary ADC read at
``0x08016378``–``0x0801638c``, divided by ten. Selector 97 therefore overrides this
**monitor-reference diagnostic**, not a cell/environment temperature used by the ordinary
temperature protection checks. Although the command reuses the signed −40000..100000 validation,
that does not make this diagnostic’s value mC. The nominal 3000 and ADC path suggest a reference
voltage; its exact physical input and calibration require board/monitor evidence. ``tmprctrl 0``
disables the override and re-enables measurement refresh; it does not restore a saved reading or
explicitly clear the latched fault.

.. _firmware-behavior-tinput-presentabsent-temporarily-drives-outputs-e2:

``tinput present/absent`` temporarily drives outputs (E2)
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

The handler at ``0x0802b22c``–``0x0802b290`` passes value 3 to module callback ``+0x28c``, first
operation **4**, then operation **5** after a 100-unit delay and one input sample.
Initialization at ``0x08012398``–``0x0801239c`` wires that callback to ``0x08010dc8``. Its jump
table resolves those operations to:

================= ===========================================================================
Operation         Visible software action
================= ===========================================================================
4, ``0x080111be`` Clear GPIO port ``0x40011400`` masks ``0x40`` and ``0x20``.
5, ``0x080111e6`` Set the same port’s ``0x20`` mask and clear the halfword at ``0x20000d48``.
================= ===========================================================================

The low-level helper at ``0x0801e772`` writes the set/reset registers, confirming actual output
writes rather than mere cached-state updates. Neither branch saves previous levels; operation 5
does not explicitly restore ``0x40``. ``present`` passes when the input identified by
``0x40011404`` reads zero; ``absent`` passes when it reads nonzero. Thus these forms are
**active test sequences with forced final levels**, not passive input queries. The physical
circuit attached to those pins still requires board evidence. ``rv``/``dcov`` use direct input
reads and do not take this bracketing path. Pass/fail text matters: both successful parsing
paths can return zero even when the electrical comparison fails.

.. _firmware-behavior-display-cadence-and-additional-cross-image-checks:

Display cadence and model differences
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

All identified E2 literal references to the display state at ``0x20000ce4`` are in the selection
setter, output routine and scheduler. The scheduler only checks the enable byte and calls the
output routine; neither consumer uses the scalar at ``+0x14`` or the flag at ``+0x10``. The
positive scalar does not control this path; the actual nominal cadence is now traced in
:ref:`the scheduler analysis below <firmware-behavior-actual-display-scheduling>`. The C setter
independently has the same two writes at ``0x0800a248``–``0x0800a24c``. Keep the positive scalar
form documented as a stored value, without promising a cadence change.

C ``tmprctrl`` independently preserves the 97/98 setter layout at ``0x0800ee9c``–``0x0800eeb2``,
using control base ``0x200003dc``; its reference consumer at ``0x0800539c`` has the same
2980–3020 check. This verifies that particular behavior in both images, not every common
command’s full equivalence.

.. _firmware-behavior-actual-display-scheduling:

Display scheduling and output
-----------------------------

The E2 display runs from a timer interrupt, rather than a scalar-controlled console loop. The
complete reviewed path is:

+-----------------------------------------------+-----------------------------------------------+
| Stage                                         | E2 evidence                                   |
+===============================================+===============================================+
| Timer setup                                   | ``0x0801f528``–``0x0801f584``: prescaler =    |
|                                               | clock / 10000 − 1; reload = **4999**;         |
|                                               | peripheral base ``0x40000400``.               |
+-----------------------------------------------+-----------------------------------------------+
| Register writes                               | ``0x08024868``–``0x0802486e`` write the       |
|                                               | reload and prescaler. The configured clock    |
|                                               | variable starts at **72000000**; startup      |
|                                               | fallback stores **8000000** at                |
|                                               | ``0x08037ca8``.                               |
+-----------------------------------------------+-----------------------------------------------+
| Interrupt wiring                              | Vector word at ``0x080038b4`` =               |
|                                               | ``0x080377f9``; handler ``0x080377f8`` checks |
|                                               | the pending source and calls ``0x080153a8``.  |
+-----------------------------------------------+-----------------------------------------------+
| Scheduler                                     | ``0x080153c2``–``0x08015442`` increments a    |
|                                               | phase counter, resets it at **4**, and calls  |
|                                               | the enabled display at phase **3**.           |
+-----------------------------------------------+-----------------------------------------------+

Under the configured timer-clock assumptions this is a **500 ms tick**, with one display
invocation per **four ticks**, nominally **2 seconds**. It is a code-derived invocation cadence,
not a promise that every selection emits a complete table on each call or measured wall-clock
precision: interrupt masking, blocking work and the scheduler’s early-exit flag can delay or
skip processing. The scalar form ``disp 1..300`` does not change the prescaler, reload, phase
count or invocation gate in this path. Do not implement it as a firmware-supported interval
selector merely because the value looks like a duration.

C independently uses the same four-phase scheme and phase-3 display call
(``0x08015116``–``0x080151a8``). Its timer initializer ``0x0801eda6`` uses clock / 1000 − 1 and
reload **499**, also nominally 500 ms under its clock setup. Vector ``0x080038b4`` points to
``0x0803625e``; the timer IRQ helper calls ``0x0801676c``, which selects ``0x40000400`` and
calls scheduler ``0x080150fc``. Thus the nominal 2-second display cadence is independently
supported in both images, despite different timer-driver implementations.

.. _protocol-monitor-ic-read-limits:

Monitor IC read limits
----------------------

E2 ``bmicrdcfg`` allocates a **16-byte caller buffer**. Its reader at ``0x0801564e`` receives
and copies **eight bytes per IC** (six data plus two check bytes) into that buffer. No caller
limit guards the count: **copying three or more ICs overflows the command’s buffer**. The
driver’s own receive buffer is 256 bytes, providing a second insufficient bound for unrestricted
counts.

``bmicrdcomm`` uses the same 16-byte caller allocation and an analogous count-based reader. The
count is narrowed to u8 only after a setup call using the full parsed value. Thus these are not
safe “arbitrary count” diagnostics; a future client must restrict count to the board’s actual
monitor configuration and no more than **two** for these handlers. This is a software buffer
bound, not evidence that every supported board physically has two ICs. It resolves the
handler/driver limit without requiring a live overflow probe.
