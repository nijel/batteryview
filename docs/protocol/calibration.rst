Clock, SOC and fuel-gauge commands
==================================

Use bare ``time`` to read the battery clock. SOC/capacity setters, sensor
calibration, gauge programming, and the SOC-reset workflow are separate
operations with different effects. A command that changes a displayed percentage
is not interchangeable with clearing persistent state or recalibrating a sensor.

Check the firmware family before using gauge commands: E2 uses the INA226 path,
while C uses the bq34z100 path. The sections below give accepted arguments, units,
write locations, completion conditions, and limitations for each.

.. _firmware-parameters-soc-capacity-and-small-configuration-settings:

SOC, capacity and small configuration settings
----------------------------------------------

+-----------------------------------------------+-----------------------------------------------+
| Form                                          | Parameters, validation and storage            |
+===============================================+===============================================+
| ``setsoc percent``                            | D, narrowed to u16, then checked **0–100**.   |
|                                               | Updates each cell’s runtime remaining-charge  |
|                                               | and percentage fields using configured        |
|                                               | capacity. No direct EEPROM write in this      |
|                                               | handler. Distinct from BatteryView’s          |
|                                               | erase/restart SOC-reset sequence.             |
+-----------------------------------------------+-----------------------------------------------+
| ``totalcoul [capacity]``                      | No argument reads eight bytes from EEPROM 1   |
|                                               | ``0x21`` and displays capacity in mAh after   |
|                                               | dividing internal coulomb units by 3600.      |
|                                               | Setter is D **50, 74 or 100 Ah**; multiplies  |
|                                               | by 3,600,000, updates runtime capacity and    |
|                                               | related model data, writes capacity at        |
|                                               | ``0x21`` and check byte ``0x29``. It is       |
|                                               | nominal configuration, not an arbitrary       |
|                                               | learned-capacity value.                       |
+-----------------------------------------------+-----------------------------------------------+
| ``emptyvolt [threshold]``                     | No argument reports ``Coul:0% Volt``. D →     |
|                                               | u16; accepts **500–3300 inclusive**, writes   |
|                                               | two bytes to EEPROM 0 ``0x7a3`` and updates   |
|                                               | RAM. The SOC consumer compares it directly    |
|                                               | with the **cell voltage in mV**; see the      |
|                                               | supplement for the clamp path.                |
+-----------------------------------------------+-----------------------------------------------+
| ``blocksoc [percent]`` (C)                    | No argument reports the recommended           |
|                                               | block-current SOC. D → u16, **1–100           |
|                                               | inclusive**; a change writes two bytes at     |
|                                               | EEPROM 0 ``0x7ac``.                           |
+-----------------------------------------------+-----------------------------------------------+
| ``setlowcfg``                                 | Reports ``ShutSoc`` and ``ShutSocTime``.      |
+-----------------------------------------------+-----------------------------------------------+
| ``setlowcfg shutsoc value``                   | D → u16; stores a runtime shutdown-SOC field. |
|                                               | No additional percentage bound was found in   |
|                                               | this branch; a client should not accept       |
|                                               | arbitrary 16-bit values merely because        |
|                                               | firmware does.                                |
+-----------------------------------------------+-----------------------------------------------+
| ``setlowcfg sstime seconds``                  | D → u16, then divides by two using a right    |
|                                               | shift. Stores two-second ticks; reporting     |
|                                               | doubles the stored value. Odd seconds are     |
|                                               | rounded down.                                 |
+-----------------------------------------------+-----------------------------------------------+
| ``setlowcfg save``                            | Prints ``LowConfig Save Not Support`` and     |
|                                               | returns zero. It does **not** implement       |
|                                               | persistent saving.                            |
+-----------------------------------------------+-----------------------------------------------+

.. admonition:: Firmware evidence

   Evidence: E2 ``setsoc`` ``0x0800fbd0``, ``setlowcfg`` ``0x0800fc58``, ``totalcoul``
   ``0x08029f10``. For erase/restart and the persistent field map see
   :ref:`SOC-reset analysis <protocol-firmware-evidence-for-soc-reset>`.

.. _firmware-parameters-rtc-and-manufacturing-timestamp:

RTC and manufacturing timestamp
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

``time`` reads the RTC. ``time yy month day hour minute second`` sets it; all six operands are
D. E2 stores each parsed value as a byte **before** checking it. For normal, non-overflowing
input the checks are:

====================== ==========================================================
Operand                Accepted normal range
====================== ==========================================================
``yy``                 0–99, two-digit year
``month``              1–12
``day``                1 through the month length; February depends on ``yy & 3``
``hour``               0–23
``minute``, ``second`` 0–59
====================== ==========================================================

Do not reproduce the byte-wrap acceptance bug. Send six separate tokens, not an ISO timestamp.
E2 handler ``0x080289cc``, validation through ``0x08028ac4``.
``cmudtesttime [year month day hour minute second]`` is a separate manufacturing timestamp with
an EEPROM-0 field at ``0x3d``; the supplement confirms the same component bounds as ``time``,
writing seven EEPROM bytes rather than setting RTC.

.. _firmware-parameters-fuel-gauge-registers-and-calibration:

Fuel-gauge registers and calibration
------------------------------------

.. _firmware-parameters-e2-ina226-path:

E2 INA226 path
~~~~~~~~~~~~~~

+-----------------------------------------------+-----------------------------------------------+
| Form                                          | Parameters and effect                         |
+===============================================+===============================================+
| ``inar offset``                               | H offset **00–7F**; reads a two-byte INA      |
|                                               | register.                                     |
+-----------------------------------------------+-----------------------------------------------+
| ``inaw offset value``                         | H offset **00–7E**; value H for the register  |
|                                               | write. Do not copy the read handler’s larger  |
|                                               | offset limit.                                 |
+-----------------------------------------------+-----------------------------------------------+
| ``inash``                                     | No operands; register report. Stale help      |
|                                               | calls it ``socsh``, which is not an E2        |
|                                               | registered alias.                             |
+-----------------------------------------------+-----------------------------------------------+
| ``inacal``                                    | Reads/reports the current coefficient, offset |
|                                               | and calibration mode through module           |
|                                               | callbacks.                                    |
+-----------------------------------------------+-----------------------------------------------+
| ``inacal 10000``                              | Signed-decimal input is parsed, but this      |
|                                               | branch accepts **10000 only**. Performs       |
|                                               | current calibration, including measurement    |
|                                               | sampling and coefficient/offset calculation;  |
|                                               | coefficient acceptance includes **800–1200**. |
|                                               | Requires INA226 hardware identity. Invalid    |
|                                               | calibration conditions can print failure and  |
|                                               | return zero.                                  |
+-----------------------------------------------+-----------------------------------------------+
| ``inacal currcoe value``                      | D value sets the coefficient through callback |
|                                               | operation ``0x54``. This manual branch does   |
|                                               | not apply the automatic calibration branch’s  |
|                                               | 800–1200 check. Persists four bytes plus a    |
|                                               | check byte at EEPROM 1 ``0x30``.              |
+-----------------------------------------------+-----------------------------------------------+
| ``inacal curroffset value``                   | D value sets the offset through callback      |
|                                               | operation ``0x30``. Despite the               |
|                                               | signed-looking output label, this manual      |
|                                               | setter calls the **unsigned** parser.         |
+-----------------------------------------------+-----------------------------------------------+
| ``currcal [value]``                           | Separate handler, signed-decimal value.       |
|                                               | Intended reference is **10000**, but other    |
|                                               | values merely print ``Err Val != 10000`` and  |
|                                               | **continue into the calibration path**. The   |
|                                               | routine can close/reopen MOS outputs and      |
|                                               | invoke calibration callbacks. No argument     |
|                                               | calls callback operation 2, now traced as     |
|                                               | coefficient/offset reporting. See the         |
|                                               | supplement for the zero/reference sampling    |
|                                               | and persistent fields. A client must not rely |
|                                               | on the error message to prevent mutation.     |
+-----------------------------------------------+-----------------------------------------------+

E2 ``inacal`` ``0x0802190c``; manual setters ``0x08021b26``–``0x08021ba6``, read path
``0x08021ba8``–``0x08021bea``. The procedure manipulates hardware state; it is not a harmless
report with an optional numeric filter.

.. _firmware-parameters-c-bq34z100-path:

C bq34z100 path
~~~~~~~~~~~~~~~

+-----------------------------------------------------------------------------+-----------------------------------------------+
| Form                                                                        | Parameters and effect                         |
+=============================================================================+===============================================+
| ``socr offset``                                                             | H offset **00–7F**; reads **one byte**,       |
|                                                                             | unlike E2 ``inar``.                           |
+-----------------------------------------------------------------------------+-----------------------------------------------+
| ``socw offset value``                                                       | H offset **00–7E**; H value → u8; writes      |
|                                                                             | **one byte**.                                 |
+-----------------------------------------------------------------------------+-----------------------------------------------+
| ``socsh``                                                                   | No operands; fuel-gauge register report.      |
+-----------------------------------------------------------------------------+-----------------------------------------------+
| ``socd``                                                                    | Reads gauge data including pack voltage,      |
|                                                                             | signed current, SOC and remaining capacity.   |
|                                                                             | The table permits two extra tokens, but the   |
|                                                                             | inspected handler does not consume them. The  |
|                                                                             | reviewed C initializer sets the               |
|                                                                             | current/capacity factor to **4**; register    |
|                                                                             | decoding and read-error limitations are in    |
|                                                                             | the supplement.                               |
+-----------------------------------------------------------------------------+-----------------------------------------------+
| ``soct``                                                                    | Reads chemistry ID and Ra/resistance-table    |
|                                                                             | information, including flags and table        |
|                                                                             | entries. Permitted extra tokens are not       |
|                                                                             | consumed by this handler.                     |
+-----------------------------------------------------------------------------+-----------------------------------------------+
| ``soccfg``                                                                  | Lists named data-flash fields, subclass,      |
|                                                                             | offset and decoded value using a descriptor   |
|                                                                             | table.                                        |
+-----------------------------------------------------------------------------+-----------------------------------------------+
| ``soccfg subclass offset [value]``                                          | Subclass and offset are **D**, narrowed to    |
|                                                                             | u16 and matched to descriptor fields. A       |
|                                                                             | matching descriptor controls width and        |
|                                                                             | signed/unsigned/other value encoding. This is |
|                                                                             | **not** a generic arbitrary-width raw-memory  |
|                                                                             | write. All eight encodings, the 38 supported  |
|                                                                             | pairs, and the faulty sentinel/parser         |
|                                                                             | validation are documented in the supplement.  |
+-----------------------------------------------------------------------------+-----------------------------------------------+
| ``soccal {volt\|current\|tempr\|ccoffset\|bdoffsetP1\|bdoffsetP2} [value]`` | Separate quantity-specific calibration paths; |
|                                                                             | board-offset phases have state/ordering       |
|                                                                             | requirements. See the supplement for          |
|                                                                             | query/set forms, offset phases, no-op         |
|                                                                             | ``tempr`` path, sampling and timeout/cleanup  |
|                                                                             | bugs. These are not generic numerical         |
|                                                                             | setters.                                      |
+-----------------------------------------------------------------------------+-----------------------------------------------+
| ``socclr``                                                                  | Calls the gauge clear/default-restoration     |
|                                                                             | routine. Registered help says it clears       |
|                                                                             | bq34z100 data flash and reloads defaults. The |
|                                                                             | handler ignores permitted extra tokens and    |
|                                                                             | returns zero regardless of the callee result. |
|                                                                             | Runs the recovered **182-step programming     |
|                                                                             | script**, broader than the descriptor         |
|                                                                             | settings; script targets, chunk counts and    |
|                                                                             | interpreter behavior are in the supplement.   |
+-----------------------------------------------------------------------------+-----------------------------------------------+

C ``soccfg`` ``0x080208d4``, descriptor lookup ``0x08020ae6``–``0x08020b56``; ``socclr`` calls
``0x080202ec``. Gauge data flash is separate from either ``eepe`` chip.

.. _firmware-behavior-gauge-report-scaling-c:

Gauge report scaling (C)
~~~~~~~~~~~~~~~~~~~~~~~~

The driver initializer at ``0x08022444`` passes **4** to ``0x080203a8``, which stores that byte
at ``0x20000b48`` while installing bus callbacks. ``socd`` then uses:

=================== ===============================================================
Gauge register      Decoding / reported value
=================== ===============================================================
``0x08``, two bytes Little-endian unsigned pack voltage, mV, no multiplier.
``0x10``, two bytes Little-endian **signed 16-bit** current multiplied by 4, mA.
``0x02``, one byte  SOC percent, no multiplier.
``0x04``, two bytes Little-endian unsigned remaining capacity multiplied by 4, mAh.
=================== ===============================================================

.. admonition:: Firmware evidence

   Evidence: handler ``0x0802117a``–``0x08021204``, initializer ``0x08022456``–``0x08022462``,
   scale store ``0x080203c0``. This is the initialized scale for the reviewed C image, not a
   universal bq34z100 convention or a detected value from the connected battery. ``socd`` does not
   check each bus-read return before formatting the result; a successful console footer alone does
   not prove all four measurements were read successfully.

.. _firmware-behavior-c-gauge-data-flash-types:

C gauge data-flash types
------------------------

C ``soccfg`` uses 12-byte descriptors at ``0x08020ee4``, with name pointer, subclass/offset/type
bytes and a final default-value word. Subclass and offset arguments are **decimal**, even when
the field’s value is hexadecimal.

==== ==================== ==========================================================
Type Value input          Stored encoding
==== ==================== ==========================================================
0    Signed decimal       8-bit integer
1    Signed decimal       16-bit integer, high byte first
2    Unsigned decimal     8-bit integer
3    Unsigned decimal     16-bit integer, high byte first
4    Hexadecimal          8-bit integer
5    Hexadecimal          16-bit integer, high byte first
6    Hexadecimal          32-bit integer, high byte first
7    **Decimal fraction** Four-byte gauge floating-point encoding via ``0x0801fd24``
==== ==================== ==========================================================

Type 7 calls the decimal-fraction parser at ``0x080199a8``; the apparent base-16 register value
passed by its caller is not used as a radix by that parser. It accepts digits and at most one
decimal point, not signed/scientific notation. Do not send raw hex float bits as the value.
Width-limited integer paths discard high bits rather than checking representability; clients
should enforce the corresponding signed/unsigned bounds.

Unknown subclass/offset lookup reaches the descriptor sentinel but checks the **descriptor
address**, not its null name pointer, before continuing. It does not reliably reject unsupported
pairs. Likewise the value-parser error flag is not consistently checked before the write helper.
A client must restrict writes to known descriptors and validate the complete typed value
locally.

.. _firmware-behavior-supported-subclassoffset-pairs:

Supported subclass/offset pairs
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

The following 38 descriptor entries are firmware constants, not captured battery settings. Type
numbers refer to the encoding table above. The final word is recorded verbatim as a **descriptor
default**, not a recommended live value and not a claim that ``socclr`` only changes these
fields.

============================= ============ ========== ==== ==================
Name                          Subclass (D) Offset (D) Type Default word (hex)
============================= ============ ========== ==== ==================
Taper Current                 36           0          1    ``0x000003e8``
Min Taper Capacity            36           2          1    ``0x00000019``
Cell Taper Voltage            36           4          1    ``0x00000019``
Current Taper Window          36           6          2    ``0x00000028``
Cycle Count                   48           6          3    ``0x00000000``
CC Threshold                  48           8          1    ``0x00000384``
Design Capacity               48           11         1    ``0x000003e8``
Design Energy                 48           13         1    ``0x00001518``
Design Scale                  48           30         2    ``0x00000001``
Cell Charge Voltage T1-T2     48           17         3    ``0x00001068``
Cell Charge Voltage T2-T3     48           19         3    ``0x00001068``
Cell Charge Voltage T3-T4     48           21         3    ``0x00001004``
SOH Load I                    48           15         1    ``0xfffffe70``
JEITA T1                      48           26         0    ``0xfffffff6``
JEITA T2                      48           27         0    ``0x0000000a``
JEITA T3                      48           28         0    ``0x0000002d``
JEITA T4                      48           29         0    ``0x00000037``
Firmware Version              56           4          5    ``0x00000000``
Pack Configuration            64           0          5    ``0x00000161``
Pack Configuration B          64           2          4    ``0x000000ff``
Pack Configuration C          64           3          4    ``0x00000030``
Number Of Series Cell         64           7          2    ``0x00000001``
Sleep Current                 68           2          1    ``0x0000000a``
Fullsleep Waittime            68           11         2    ``0x0000000a``
Default Load select           80           0          2    ``0x00000001``
Load Mode                     80           1          2    ``0x00000001``
Cell Terminate Voltage        80           53         1    ``0x00000bb8``
Cell term V delta             80           55         1    ``0x000000c8``
Min % Passed Chg For 1st Qmax 80           47         2    ``0x0000005a``
Qmax Cell 0                   82           0          1    ``0x000003e8``
Cycle Count                   82           2          3    ``0x00000000``
Update Status                 82           4          4    ``0x00000000``
Cell V at Chg Term            82           5          1    ``0x00001068``
CC Gain                       104          0          7    ``0x7b638e39``
CC Delta                      104          4          7    ``0x9001742b``
CC Offset                     104          8          1    ``0xfffffb50``
Board Offset                  104          10         0    ``0x00000000``
Voltage Divider               104          14         3    ``0x00001388``
============================= ============ ========== ==== ==================

.. _firmware-behavior-socclr-runs-an-embedded-programming-script:

``socclr`` runs an embedded programming script
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

C ``socclr`` at ``0x0802dc28`` supplies the pointer array at RAM ``0x20000744`` to interpreter
``0x080202ec``. This array is in **compressed initialized data**, not a plain pointer table in
the image. Reconstructing the startup decoder ``0x08003a82`` using its descriptor at
``0x08003bcc`` produces the initialized RAM bytes; the array’s null sentinel is at
``0x20000a1c``.

There are **182 script steps: 91 W writes, 47 C comparisons and 44 X delays**. The strings are
embedded at ``0x0803b7a4`` onward. The interpreter:

- Decodes a W/C line into hex bytes. The first byte is an address shifted right by one for the
  bus callback; the next byte is the register/command; remaining bytes are write payload or
  comparison data.
- W calls the configured bus-write function and accumulates errors, but does not abort the
  script on a write error.
- C calls ``0x080202a6`` to read/compare and stops on a failed comparison.
- X parses a decimal delay; each iteration also services the firmware helper.

The script addresses both encoded targets ``AA`` and ``16`` (bus addresses ``0x55`` and
``0x0b``). It contains **32 indexed nonzero programming chunks** beginning ``W: 16 00 0A 00``
through ``W: 16 00 0A 1F``, additional programming transactions, verification signatures, and a
final delay of 4000. It is therefore a broad embedded baseline/programming sequence, **not an
EEPROM zero-fill or just a reset of the 38 soccfg descriptors**. Exact physical gauge-memory
region names require the gauge’s programming specification; the command-byte/chunk behavior
above follows directly from this firmware. Raw programming payloads are not copied into this
repository.

The interpreter’s accumulated status is discarded by ``socclr``, which returns zero
unconditionally. The same script is invoked by the ``tsoc`` test if its gauge firmware-version
check does not equal 6. ``tsoc`` is thus potentially mutating too.

.. _firmware-behavior-soccal-selectors-writes-and-termination:

``soccal``: selectors, writes and termination
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

C ``soccal`` at ``0x080212d8`` recognizes six case-sensitive selectors. Before selector dispatch
it sends two control-register writes containing ``14 04`` and ``72 36``, even for branches that
later only report values. These query-looking forms are not pure bus reads. Missing/unknown
selector fails with handler return 1; ordinary selected branches usually return zero, including
printed calibration failures.

+-----------------------------------------------+-------------------------------------------------+
| Form                                          | Confirmed procedure                             |
+===============================================+=================================================+
| ``soccal volt``                               | Reports voltage-divider value, subclass 104     |
|                                               | offset 14, two bytes.                           |
+-----------------------------------------------+-------------------------------------------------+
| ``soccal volt reference``                     | D reference, compared with register-8 voltage   |
|                                               | by computing                                    |
|                                               | ``reference * old_divider / measured_voltage``; |
|                                               | writes the low 16 bits to subclass 104 offset   |
|                                               | 14, then calls the gauge-reset helper. No       |
|                                               | reference-range or measured-zero guard was      |
|                                               | found. The scale matches the raw pack-voltage   |
|                                               | register; the user-facing unit must follow that |
|                                               | register’s device scaling.                      |
+-----------------------------------------------+-------------------------------------------------+
| ``soccal current``                            | Reads/reports four-byte CC Gain and CC Delta at |
|                                               | subclass 104 offsets 0 and 4.                   |
+-----------------------------------------------+-------------------------------------------------+
| ``soccal current reference``                  | S reference; enters calibration mode, collects  |
|                                               | **eight samples with distinct sequence bytes**, |
|                                               | exits mode, reads CC/board offsets and computes |
|                                               | gain/delta. Accepts the calculated              |
|                                               | sample-resistor result **450–550 inclusive**,   |
|                                               | then writes gain and delta using the gauge      |
|                                               | float encoder. No explicit reference-range      |
|                                               | check.                                          |
+-----------------------------------------------+-------------------------------------------------+
| ``soccal tempr [value]``                      | Selector is recognized, but its jump-table      |
|                                               | entry goes directly to successful exit after    |
|                                               | the common control writes. **No                 |
|                                               | temperature-calibration body is implemented**   |
|                                               | in this image.                                  |
+-----------------------------------------------+-------------------------------------------------+
| ``soccal ccoffset``                           | Sends control command ``0x000a``, waits for CCA |
|                                               | to set then clear, sends ``0x000b``, reads      |
|                                               | subclass 104 offset 8 (two bytes), and calls    |
|                                               | the reset helper.                               |
+-----------------------------------------------+-------------------------------------------------+
| ``soccal bdoffsetP1``                         | Requires internal phase flag 1. Sends           |
|                                               | ``0x0009``, waits for CCA and BCA bits          |
|                                               | together, then sets phase flag 0 for P2. This   |
|                                               | flag is changed even on the printed failure     |
|                                               | path.                                           |
+-----------------------------------------------+-------------------------------------------------+
| ``soccal bdoffsetP2``                         | Requires phase flag 0; waits for BCA clear,     |
|                                               | sends ``0x000b``, reads subclass 104 offset 10  |
|                                               | (one byte), calls reset and restores phase flag |
|                                               | 1. Without P1 it reports that P1 is needed.     |
+-----------------------------------------------+-------------------------------------------------+

Extra numeric operands on offset branches are not consumed. This does not make them adjustable
numerical offset setters. The entry loops for calibration/CCA have up to five passes; the
clear-bit loops for CCA/BCA have up to 102 polls. The current-sample collection loop has **no
overall timeout if the sample sequence never advances**. A failure to enter calibration can
still fall through into that sampling loop, so a client timeout does not prove the device
stopped working on the operation.

Reset helper ``0x080204f0`` sends the two control writes above and command ``0x0041``, then
delays by 3000 helper units. This documents software ordering and delay arguments; exact elapsed
time and external-current fixture requirements need hardware/gauge validation. Calibration
results and writes are not transactional, and the success footer does not establish successful
cleanup on every path.

.. _firmware-behavior-additional-e2-calibration-and-soc-consumers:

E2 current scaling and SOC recovery
-----------------------------------

INA initialization at ``0x080214b2`` installs calibration callback **``0x080215f8``**. Its
operations resolve the previously opaque ``currcal`` calls:

- Operation **2**, used by bare ``currcal``, reads/reports stored coefficient and offset through
  module operations 0x53/0x2f. It does not run the sampling procedure.
- Operation **0** samples zero-current **50 times**, separated by 100 delay units, and stores
  their signed integer average as a runtime zero offset.
- Operation **1** collects another 50 samples, averages them, computes the coefficient/offset
  against the supplied reference and zero average, requires coefficient **800–1200 inclusive**,
  then persists both parameters.

The wrapper ``currcal value`` controls MOS outputs and delays between the zero and reference
measurements; a warning about reference !=10000 does not abort it. Successful calibration
operations 0x54/0x30 store the four-byte coefficient at **EEPROM 1 ``0x30``** and offset at
**EEPROM 1 ``0x35``**, each followed by a check byte. The same storage callbacks serve manual
``inacal currcoe/curroffset`` and automatic ``inacal 10000``. The word/check helper’s ignored
driver statuses apply here too. There is no transactional rollback to the former
coefficient/offset.

The ``emptyvolt`` setting is consumed in cell SOC/coulomb calculation at
``0x08004e46``–``0x08004e58``, compared directly with the cell-voltage field ``+0x20``, whose
displayed unit is **mV**. This establishes a **cell-mV** threshold, not a pack-voltage setting.
Below the threshold, the path replaces the working remaining-charge value with an internal floor
before recomputing cell SOC. It does not itself send a gauge reset, erase data, or implement
BatteryView’s SOC-reset sequence. The full charge-estimator algorithm has other conditions; this
comparison alone must not be presented as the entire SOC model.

``cmudtesttime`` (``0x08028b70``) has the same six decimal date/time components and
byte-before-validation behavior as ``time``, including two-digit year 0–99, month/day checks and
the year-modulo-four February rule. It writes **seven bytes** to EEPROM 0 ``0x3d``, or
reads/displays that field with no operands. It does not call the RTC setter. The six displayed
components are established; the seventh byte is not supplied by a seventh user argument. Unlike
the ordinary ``time`` form, this records a manufacturing/test timestamp rather than setting
current RTC time.

.. _firmware-behavior-monitor-read-count-bounds:

Monitor-read count bounds
~~~~~~~~~~~~~~~~~~~~~~~~~

For ``bmicrdcfg`` receive-buffer bounds and physical monitor-IC selection, see
:ref:`Monitor IC read limits <protocol-monitor-ic-read-limits>`. These hardware
read limits are separate from the fuel-gauge report scaling above.

.. _protocol-soc-reset-button:

SOC-reset workflow
------------------

The user-defined-data button loads ``Script.xml`` and names its output ``resetsoc``.
``OnGetUserData`` executes the following sequence:

1.  ``stat`` (CR).
2.  ``datalist event 0`` (LF), then CR+LF continuation until the console prompt.
3.  ``datalist misc 0`` with the same continuation behavior.
4.  ``datalist history 0`` with the same continuation behavior.
5.  ``info`` (CR); capture its barcode for a subsequent command.
6.  ``setlowcfg`` (CR).
7.  ``eepe 0`` (CR).
8.  ``trst`` (CR), waiting for ``pylon>``.
9.  The ``login`` script pseudo-command runs console switching/reconnection. On success it
    contributes no text to the report.
10. ``login debug`` (CR).
11. ``tbar ORIGINAL_BARCODE`` (CR).
12. ``info`` (CR).
13. ``setlowcfg`` (CR).

``RetrieveHistoryData`` sends at least one CR+LF after each initial datalist reply, including
empty and unsupported replies. The provided firmware rejects event and miscellaneous datalist
commands in this script; those responses and their following prompts are retained. Ordinary
report commands permit the specific detailed-list fallback described above; other rejections
remain failures.

The Python workflow additionally saves durable recovery information before clearing EEPROM,
validates the barcode before mutation, and checks identity after restoration. It never retries
``eepe``, ``trst``, or ``tbar`` automatically. It does not reselect the previous module address
after reset, since a reset can change it. Failure after a mutating write requires inspection of
the saved recovery state; there is no automatic resume command.

.. _protocol-firmware-evidence-for-soc-reset:

SOC-reset erase scope and persistent state
------------------------------------------

For all registered commands, access modes and per-image handler addresses, see the
:doc:`firmware command reference </protocol/commands>`. The
:ref:`handler supplement <firmware-behavior-what-the-persistence-callbacks-actually-do>`
resolves immediate statistics/extended-state saves and record-write behavior.

Static inspection of the user-supplied firmware archive now establishes the erase scope for two
specific images. Neither firmware was executed or flashed. The archive also contains an updater
and example update logs; none of those logs or firmware payloads are included in this
repository.

+---------------------------+-------------------------------------+----------------------------------------------------------------------+
| Image                     | Bytes                               | SHA-256                                                              |
+===========================+=====================================+======================================================================+
| ``US_E2_V2.5_Crc.bin``    | 217088                              | ``897c3326ab8905df75a7297905112958a07c0a2cbb0592e0ecc274b886b0c82e`` |
+---------------------------+-------------------------------------+----------------------------------------------------------------------+
| ``US_C_V3.1_Crc.bin``     | 242688                              | ``5450e3bd884ae63549fc3b278ecccc0126227234f7148c7961542755cbad2d7d`` |
+---------------------------+-------------------------------------+----------------------------------------------------------------------+

Both are readable ARM Thumb images mapped at ``0x08003800``. The inferred base is supported by
command-table string/function pointers and valid reset-vector code. Addresses below are runtime
addresses; subtract the base to obtain file offsets. The E2 board tag at file offset ``0x418``
is ``US2000C_NF4``; the other image’s tag is ``US2000C``. These findings establish behavior in
these images, not automatically in every installed firmware revision.

.. _protocol-erase-and-restart:

Erase and restart
~~~~~~~~~~~~~~~~~

The command table describes ``eepe`` as ``EEPROM erase - eepe [chip]``. In E2 V2.5, the handler
at ``0x08010410`` accepts logical chip 0 or 1 and calls ``0x080101ee``. That routine zeroes a
16-byte buffer through ``0x08017dcc``, then writes that buffer 128 times at offsets ``i << 4``.
Thus ``eepe 0`` attempts to overwrite **all 2048 bytes of logical EEPROM chip 0 with zero**,
rather than clearing a single SOC field. Write statuses are combined for the command result. The
driver at ``0x0801004a`` checks the 2048-byte boundary and handles page writes/readiness waits.

C V3.1 has the same loop: handler ``0x080103dc``, erase routine ``0x08010142``, zero helper
``0x08017c50``, and EEPROM write routine ``0x0800ffa2``. Erasing chip 0 does not itself erase
chip 1, external history flash, or executable firmware. This is not a guarantee that restart
will leave all other storage unchanged: startup routines also initialize and update persistent
data.

In E2 V2.5, ``trst`` at ``0x0802b024`` performs preparatory calls and ultimately invokes
``0x0801719c``, then ``0x08016546``. The latter writes the AIRCR register at ``0xe000ed0c``,
preserving priority grouping and adding ``0x05fa0004``: the keyed Cortex-M ``SYSRESETREQ``
operation. This is a processor/system reset, not merely closing a console session. See `Arm’s
reset documentation <https://arm-software.github.io/CMSIS_5/Core/html/group__NVIC__gr.html>`__.

.. _protocol-confirmed-e2-persistent-fields:

Confirmed E2 persistent fields
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

The following addresses are **EEPROM byte offsets**, not firmware addresses. They are
established by tracing both EEPROM reads/writes and the firmware’s labeled output. A cleared
stored field may subsequently be recomputed or updated; this table does not assert that every
displayed value remains zero after restart.

+--------------------------+-------------------+--------------------------+--------------------------------+
| Chip                     | Offset            | Size                     | Evidence / meaning             |
+==========================+===================+==========================+================================+
| 0                        | ``0x021``         | 16                       | Barcode: ``tbar`` at           |
|                          |                   |                          | ``0x0802b080`` writes it at    |
|                          |                   |                          | ``0x0802b130`` and reads it    |
|                          |                   |                          | back at ``0x0802b13c``. This   |
|                          |                   |                          | explains BatteryView’s         |
|                          |                   |                          | explicit barcode restoration.  |
+--------------------------+-------------------+--------------------------+--------------------------------+
| 0                        | ``0x38f``         | 124                      | Saved statistics block:        |
|                          |                   |                          | startup reads it into the      |
|                          |                   |                          | per-module structure at        |
|                          |                   |                          | ``+0x88`` through              |
|                          |                   |                          | ``0x08012654``–``0x0801265e``; |
|                          |                   |                          | ``stat`` at ``0x08008a60``     |
|                          |                   |                          | labels its fields.             |
+--------------------------+-------------------+--------------------------+--------------------------------+
| 0                        | ``0x38f`` /       | 2 each                   | Event/history item counts in   |
|                          | ``0x391``         |                          | that block. Clearing these     |
|                          |                   |                          | affects record bookkeeping     |
|                          |                   |                          | even though the erase handler  |
|                          |                   |                          | does not erase the external    |
|                          |                   |                          | log payloads.                  |
+--------------------------+-------------------+--------------------------+--------------------------------+
| 0                        | ``0x39f``         | 2                        | Saved ``Pwr Percent``, read    |
|                          |                   |                          | for ``stat`` at                |
|                          |                   |                          | ``0x08008c9e``.                |
+--------------------------+-------------------+--------------------------+--------------------------------+
| 0                        | ``0x3a1``         | 4                        | Saved ``Pwr Coulomb``,         |
|                          |                   |                          | reconstructed from two         |
|                          |                   |                          | halfwords at                   |
|                          |                   |                          | ``0x08008caa``–``0x08008cae``. |
+--------------------------+-------------------+--------------------------+--------------------------------+
| 0                        | ``0x3df``         | 2                        | Cycle-count field, displayed   |
|                          |                   |                          | as ``CYCLE Times`` at          |
|                          |                   |                          | ``0x08008c82``–``0x08008c90``  |
|                          |                   |                          | after masking its high bit.    |
+--------------------------+-------------------+--------------------------+--------------------------------+
| 0                        | ``0x3ef``         | 4                        | Discharge-capacity             |
|                          |                   |                          | accumulator, labeled           |
|                          |                   |                          | ``Dsg Cap`` at                 |
|                          |                   |                          | ``0x08008cbe``–``0x08008cca``. |
+--------------------------+-------------------+--------------------------+--------------------------------+
| 1                        | ``0x021``         | 8                        | Configured nominal capacity,   |
|                          |                   |                          | read by ``totalcoul`` at       |
|                          |                   |                          | ``0x08029f5e``–``0x08029f80``; |
|                          |                   |                          | its check byte is at           |
|                          |                   |                          | ``0x029``. Startup validates   |
|                          |                   |                          | the supported capacity         |
|                          |                   |                          | constants and falls back to a  |
|                          |                   |                          | default if invalid. This is    |
|                          |                   |                          | separate from chip-0           |
|                          |                   |                          | SOC/counter storage.           |
+--------------------------+-------------------+--------------------------+--------------------------------+

The erased statistics block also contains charge/discharge and fault counters. Chip 0 holds
additional metadata/settings, so this procedure should be described as clearing a persistence
area used by SOC and diagnostics, not a narrowly scoped percentage reset. There is a separate
``setsoc`` command in both command tables; the bundled BatteryView reset script does not call
it.

The evidence explains why the procedure can discard stale SOC/coulomb state and why support
wants reports beforehand. It does **not** yet establish the exact post-reset SOC reconstruction
algorithm, whether every parameter or calibration value survives, whether log records can be
recovered after their bookkeeping is cleared, or why support requested the reset for a
particular module. Those need further firmware analysis and/or manufacturer confirmation.
