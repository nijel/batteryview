System faults and event flags
=============================

Read fault words together with their source field. A nonzero fault word reports
a firmware condition; it does not by itself prove that a named physical component
has failed. Historical records describe the state when they were saved, not
necessarily the state of the battery now.

Field layouts
-------------

The reviewed E2 and C applications use the same module fault/status word at
module offset ``0x40``. The record writer copies it, without remapping, to
record offset ``0x3c``. These outputs expose that word:

* ``pwr`` labeled ``System Fault``: the current module word.
* ``data`` labeled ``System Fault``: the saved record word.
* ``datalist`` summary ``SysErrCode``: the saved record word.
* ``datalist ... dtls ...`` ``ErrCode``: the saved record word, including the
  compact layout's hexadecimal scalar before MOS-temperature state and SOC.
* The reviewed ``getpwr`` handlers: the decimal first trailer after the cells.

For example, a recorded ``System Fault : 0x240 VOLT err`` contains both ``0x200``
and ``0x40``. The record printer only supplies text for a subset of the bits;
a missing textual label does not mean that a bit is undefined.

``Power Events`` and ``Bat Events`` are different words. In particular,
``Power Events`` ``SYSERR`` is a summary indication, not the detailed system
fault code. Do not decode a power-event ``0x200`` as the system-fault ``0x200``.

The original BatteryView :ref:`indicator labels
<protocol-fault-labels-are-tied-to-their-source-field>` describe an application
configuration for ``getpwr``. They are not a universal replacement for the actual
firmware layout. For example, the reviewed word's ``0x4`` is labeled an RTC error,
whereas the older indicator configuration calls that index a hardware-version
error. UP2500's configured fuse indicator likewise must not replace the reviewed
E2/C ``0x1000`` measurement-IC condition.

.. _protocol-system-fault-meanings:

Verified conditions
-------------------

These meanings apply to the reviewed fault word. Code meanings are assumed stable
across firmware revisions when reporting other releases; this is a compatibility
assumption, not evidence that every board has identical hardware or every possible
fault bit has been identified.

.. list-table:: System fault/status masks
   :header-rows: 1
   :widths: 15 32 53

   * - Mask
     - Condition
     - Interpretation and limits
   * - ``0x1``
     - Reversed input polarity
     - Firmware display label ``RV``.
   * - ``0x2``
     - Input overvoltage
     - Firmware display label ``DCOV``.
   * - ``0x4``
     - RTC error
     - Firmware label ``Rtc eer``; not proof of a failed clock component.
   * - ``0x8``
     - Lock-state error
     - Firmware label ``lock eer``; the underlying lock mechanism remains unresolved.
   * - ``0x20``
     - Temperature-sensor error
     - Firmware display label ``TMPR err``.
   * - ``0x40``
     - Voltage-sensor error
     - Includes an auxiliary-voltage check; not a statement that a cell is overvoltage.
   * - ``0x100``
     - Address-allocation error
     - Firmware display label ``ADDR err``.
   * - ``0x200``
     - Internal communication/presence fault
     - Expected peer absent in five consecutive presence checks; see the trigger below.
   * - ``0x400``
     - Charge MOS monitoring fault
     - A gated current/GPIO check sets this bit. A monitoring condition is not proof
       that the MOSFET has physically failed.
   * - ``0x800``
     - Discharge MOS monitoring fault
     - A separate gated current/GPIO check sets this bit.
   * - ``0x1000``
     - Measurement-IC error
     - E2: ``CurrIC err`` (current-sensor path). C: ``34Z100 err`` (fuel-gauge path).
   * - ``0x2000``
     - LTC/monitor-IC error
     - Firmware label ``LTC err``; the label alone does not establish the exact board IC.
   * - ``0x4000``
     - EEPROM error
     - Firmware display label ``eep eer``.
   * - ``0x8000``
     - Flash error
     - Firmware display label ``flash eer``.
   * - ``0x10000``
     - Battery-state error
     - Firmware label ``bat eer``; the underlying cause remains unresolved.
   * - ``0x20000``
     - AFUSE status error
     - Firmware label ``afuse eer``; not proof that a replaceable fuse has blown.
   * - ``0x8000000``
     - Shutdown requested
     - An operational flag set by ``shut``, not a hardware fault diagnosis.
   * - ``0x20000000``
     - Reset in progress
     - An operational flag set by ``trst`` and cleared on its returning path.

Other bits remain undecoded. In particular, this analysis does not assign the
older indicator names HIB or I²C to ``0x10`` or ``0x80`` in the reviewed word.
Some higher bits are used internally too; absence from this table is not proof
that a bit is unused. Preserve the exact unknown remainder of a combined mask.

.. _protocol-system-fault-peer-presence:

Internal communication/presence: ``0x200``
------------------------------------------

The periodic manager examines expected peer modules using a presence bitmap.
For each expected peer, a present result resets its absence counter; an absent
result increments it. At **five consecutive absent checks**, the manager raises
the aggregate condition and sets bit ``0x200`` in module index zero's fault word.
When no examined absence counter meets that condition, it clears the bit.

The helper checks the module-address presence bitmap and the valid address range;
this producer is not a direct test that a serial cable, a transceiver, or a battery
cell has failed. Five checks must not be described as five seconds: elapsed time
depends on scheduling. Other communication/rack configuration conditions can lead
to the same missing-peer observation.

For investigation, compare the record time with rack presence/addressing and
communication-state information. A saved record can retain the bit after the
live condition has cleared. A ``SysError`` state without a nonzero detailed word
still warrants investigation, but it cannot identify a particular bit.

Other trigger and clearing behavior
-----------------------------------

The :ref:`MOS monitoring procedures
<protocol-mos-failure-monitoring-and-nominal-capacity-actions>` describe the E2
current/GPIO gates that set ``0x400`` and ``0x800``. These routines can invoke the
AFUSE operation; they are not passive tests to run as a discovery probe. The
setter paths shown there do not establish a general automatic clearing rule.

The :ref:`auxiliary-voltage consumer
<firmware-behavior-tmprctrl-9798-and-measurement-refresh-e2>` tests a scaled value
against **2980–3020 inclusive** and sets ``0x40`` at ten out-of-range observations.
An in-range branch clears its counter, not an already-set fault bit. Injected
``tmprctrl 97`` values can reach this same path, so the bit is not independent
proof of a physical sensor defect.

For the remaining display-derived conditions, the verified evidence establishes
the bit-to-label association; this chapter does not claim a complete hardware
trigger or clearing contract. ``shut`` and ``trst`` intentionally set their own
operational flags as part of their documented workflows.

Firmware evidence and reproduction
----------------------------------

Images and SHA-256 hashes are in :doc:`research`. No firmware was executed to
establish these findings.

.. list-table:: Field and producer evidence
   :header-rows: 1
   :widths: 36 32 32

   * - Operation
     - E2 addresses
     - C addresses
   * - Copy module ``+0x40`` to record ``+0x3c``
     - ``0x08007490``–``0x08007492``
     - ``0x080074a8``–``0x080074aa``
   * - Print record ``System Fault``
     - ``0x08009d36``–``0x08009d40``
     - ``0x08009cea``–``0x08009cf4``
   * - Print compact ``ErrCode`` from the same saved word
     - ``0x0800bf1c``–``0x0800bf26``
     - ``0x0800bed4``–``0x0800bede``
   * - Print summary ``SysErrCode``
     - ``0x0800b5a4``–``0x0800b5aa``
     - Same branch in ``datalist`` handler ``0x0800b048``
   * - Print ``getpwr`` fault trailer from module ``+0x40``
     - ``0x0800f226``–``0x0800f22a``
     - ``0x0800f1e6``–``0x0800f1ea``
   * - Live display bit tests and labels
     - ``0x080087de``–``0x080088d4``
     - ``0x08008790``–``0x0800888a``
   * - Peer absence threshold, set, clear
     - ``0x08014580``–``0x080145bc``
     - ``0x08014380``–``0x080143bc``
   * - Presence bitmap helper
     - ``0x0801716a``–``0x08017182``
     - ``0x08016f88``
   * - Charge/discharge monitor bit setters
     - ``0x0801195e`` / ``0x08011892``
     - ``0x08011890`` / ``0x080117a2``
   * - Shutdown/reset flag setters
     - ``0x0800c4a6`` / ``0x0802b036``
     - ``0x0800c462`` / ``0x0802e7e2``

The :download:`detail metadata </firmware-details.json>` now includes
``system_fault``: word offsets, field-copy and peer-presence evidence addresses,
and the display masks and exact labels. The standard-library detail extractor
checks each reviewed LSLS/BPL bit test and its literal/ADR string load against the
hash-identified image, rather than copying labels from the UI configuration.
Regenerate it using the existing :ref:`decoded-table verification commands
<firmware-behavior-reproducing-the-data-derived-findings>`. The metadata verifies
display associations; the producer and record-copy control-flow conclusions above
also rely on disassembly.
