SOH and cycle accounting
========================

Use ``stat`` to read ``SOH``, ``CYCLE Times``, and ``Dsg Cap`` together. In the
reviewed E2 and C applications, SOH is a **cycle-based bookkeeping estimate**,
not the result of a measured usable-capacity test. Cycle count measures cumulative
discharge throughput, not days in service or the number of charging sessions.

The calculations below are confirmed in both ``US_E2_V2.5_Crc.bin`` and
``US_C_V3.1_Crc.bin``. Their hashes are listed in :doc:`research`. Other releases
can implement different calculations or initialization behavior; a common field
name does not establish the same algorithm.

.. _protocol-health-fields:

Read the correct fields
-----------------------

.. list-table:: Health-related outputs
   :header-rows: 1
   :widths: 24 76

   * - Output
     - Meaning in the reviewed applications
   * - ``stat``: ``SOH``
     - Integer percentage derived from the cycle accounting below.
   * - ``stat``: ``CYCLE Times``
     - Completed nominal-capacity equivalents of accumulated discharged charge.
       The printer masks bit ``0x8000`` of the stored 16-bit field.
   * - ``stat``: ``Dsg Cap``
     - Cumulative discharged charge in mAh, used to calculate cycle count.
   * - ``stat``: ``SOH Times``
     - A separate diagnostic event counter; neither SOH percentage nor cycle count.
   * - ``pwr``: ``Soh. Status``
     - A separate Normal/Abnormal diagnostic state, not a percentage.
   * - ``soh [addr]``
     - Per-cell ``Battery``, ``Voltage``, ``SOHCount``, ``SOHStatus`` columns.
       These are diagnostic counters/states, not per-cell health percentages.

The Python doctor's ``SOH (reported)`` comes directly from ``stat``'s ``SOH``.
It does not calculate capacity retention or substitute zero for a missing field.
Its cycle count prefers ``stat``'s ``CYCLE Times`` when available.

.. _protocol-cycle-calculation:

Cycle calculation
-----------------

Let ``Q`` be configured nominal capacity in the firmware's internal mA·s units,
and ``N = Q // 3600`` the nominal capacity in mAh. For example, an invented
74 Ah module has ``N = 74000``. This is configured nominal capacity, not a
measured full-charge capacity. The configuration is stored separately from the
statistics, in EEPROM chip 1; see :ref:`protocol-confirmed-e2-persistent-fields`.

The common accounting routine takes module current ``I`` in mA, with negative
current denoting discharge. For each invocation with ``I < 0`` it performs:

.. code-block:: python

   remainder += 2 * (-I)
   if remainder > 3600:
       discharged_mah += remainder // 3600
       remainder %= 3600

The multiplier is literally **2** in the instruction sequence, representing a
two-second contribution. The routine does not measure elapsed wall-clock time
for this integration. The comparison is strictly greater than 3600: an exact
3600 remainder is carried until a later discharge update. Positive or zero
current contributes nothing to this discharge accumulator and does not subtract
previously discharged charge.

It then calculates:

.. code-block:: python

   raw_cycles = (discharged_mah // N) & 0xffff
   displayed_cycles = raw_cycles & 0x7fff

Thus a partial discharge contributes toward a later cycle. Several smaller
discharges can total one cycle without ever reaching 0% or 100% SOC. The routine
does not wait for a full-charge/full-discharge transition, and the displayed
integer omits the fractional cycle.

For an invented 74 Ah module, ``Dsg Cap = 111000`` mAh gives one displayed cycle:
1.5 nominal-capacity equivalents have been discharged. A useful consistency check
for ordinary values is ``CYCLE Times == Dsg Cap // nominal_mAh``. Check both fields
from the same module and statistics response, before interpreting an unexpectedly
small cycle count as a parsing problem.

The storage operations do not saturate the 32-bit discharged-mAh accumulator or
the 16-bit cycle field. Overflow and the printer's high-bit mask are further
limits on interpreting these fields as an unlimited lifetime counter.

.. _protocol-soh-calculation:

SOH calculation
---------------

After updating cycle count, the same routine derives an effective coulomb capacity
and the reported SOH. For normal positive nominal capacity and counters below
overflow ranges, the integer operations are:

.. code-block:: python

   N = Q // 3600
   raw_cycles = (discharged_mah // N) & 0xffff
   aging_steps = raw_cycles // 10
   effective_mah = max(1, N - aging_steps * (N // 1000))
   reported_soh = min(100, (100 * effective_mah) // N + 1)

Every ten accounted cycles subtracts approximately 0.1% of nominal capacity from
the effective capacity. Both divisions truncate, and the final **+1**, followed
by a cap at 100, matters: this is not simply a rounded capacity ratio. The SOH
calculation uses the raw stored cycle field; the ``stat`` display separately
masks its high bit. For nominal capacity 74000 mAh, the displayed SOH first
drops from 100 to 99 at 110 accounted cycles.

.. list-table:: Synthetic examples with nominal capacity 74000 mAh
   :header-rows: 1
   :widths: 20 40 40

   * - Raw cycles
     - Effective capacity (mAh)
     - Reported SOH
   * - 0
     - 74000
     - 100
   * - 1
     - 74000
     - 100
   * - 100
     - 73260
     - 100
   * - 250
     - 72150
     - 98
   * - 1000
     - 66600
     - 91

These numbers describe a fixed firmware model. They do not establish actual
remaining energy, cell capacity, resistance, balancing ability, or service life.
The effective capacity also feeds the charge-estimator bookkeeping; it is more
than a cosmetic value printed by ``stat``.

Under the stated conditions, the completed calculation produces **1–100**, not
zero. A raw ``SOH : 0`` therefore cannot be explained as the ordinary output of
this reviewed formula. Possible differences in another release or an
uninitialized/unrefreshed runtime field need separate evidence. Do not interpret
zero as proof of zero physical capacity, or silently replace it with 100.

.. _protocol-health-persistence:

Persistence, resets, and unexpectedly low counts
------------------------------------------------

Both images load a 124-byte statistics block from EEPROM chip 0 offset ``0x38f``
into the module structure at ``+0x88``. The statistics-save callback writes the
same block back. Relevant fields are:

.. list-table:: Accounting storage
   :header-rows: 1
   :widths: 30 20 20 30

   * - Field
     - Module offset
     - EEPROM 0 offset
     - Storage
   * - Raw cycle count
     - ``0xd8``
     - ``0x3df``
     - 16-bit
   * - Discharge remainder
     - ``0xe4``
     - ``0x3eb``
     - 32-bit, mA·s contribution
   * - ``Dsg Cap``
     - ``0xe8``
     - ``0x3ef``
     - 32-bit, mAh

The SOH percentage is a runtime word at module ``+0x14``. It is recomputed by the
common routine rather than read as a percentage from that statistics block.
Startup also reconstructs effective capacity from nominal capacity and the saved
cycle count. That startup reconstruction does not itself establish that the
runtime SOH percentage has already been refreshed.

The :ref:`BatteryView SOC reset <protocol-soc-reset-button>` executes ``eepe 0``
and restarts the processor. This clears all 2048 bytes of EEPROM chip 0, including
cycle count, discharge remainder, and discharged capacity. It preserves the
separate chip-1 nominal-capacity configuration at the erase-handler level.
Subsequent startup and accounting can therefore rebuild SOH from cleared
bookkeeping and start accumulating cycles again. It cannot recover prior
throughput from months of use merely because older records remain in flash.

Other mutating commands affect the same accounting:

* ``statc`` clears the cycle/discharge fields as part of its statistics reset and
  saves the block, while preserving selected other counters.
* E2 ``tcycle count`` accepts 0–10000, sets raw cycle count, reconstructs effective
  capacity using the same aging formula, and replaces discharged mAh with
  ``count * N``. It does not directly write EEPROM in that handler. The next
  common update can recompute SOH from this new accounting state.

See :doc:`records` for these command contracts. These are explanations of side
effects, not procedures to run when investigating a surprising reading.

A cycle count of one is consistent with retained discharged capacity between
one and two nominal-capacity equivalents, even on a battery installed months
ago. A prior bookkeeping clear is one possible explanation; a low count alone
cannot prove that a reset occurred or identify when it happened. Acquisition,
accounting, and persistence behavior must also be considered. Save ``info`` and
``stat`` together and compare pre/post-maintenance reports when available.

A high SOH after a reset does not prove rejuvenation. Equally, the reviewed
reset/recompute path does not establish why another release reports zero SOH.

Firmware evidence and verification
----------------------------------

The following are runtime code addresses in the hash-identified images, not
console operands. Static inspection was used; neither image was executed or
flashed. Subtract image base ``0x08003800`` to obtain a binary file offset.

.. list-table:: Producer, display, and persistence paths
   :header-rows: 1
   :widths: 40 30 30

   * - Operation
     - E2
     - C
   * - Common accounting routine
     - ``0x0800465a``–``0x08004822``
     - Same addresses
   * - Negative-current integration and remainder
     - ``0x08004772``–``0x080047a0``
     - Same addresses
   * - Derive/store cycles
     - ``0x080047a2``–``0x080047bc``
     - Same addresses
   * - Effective capacity and SOH, including +1/cap
     - ``0x080047be``–``0x0800481e``
     - Same addresses
   * - Common routine call in module update
     - ``0x080073c2``–``0x080073c4``
     - ``0x080073dc``–``0x080073de``
   * - Print cycle count with high bit masked
     - ``0x08008c82``–``0x08008c90``
     - ``0x08008c36``–``0x08008c44``
   * - Print runtime SOH
     - ``0x08008c94``–``0x08008c9a``
     - ``0x08008c48``–``0x08008c4e``
   * - Print discharged capacity
     - ``0x08008cbe``–``0x08008cca``
     - ``0x08008c72``–``0x08008c7e``
   * - Load saved statistics
     - ``0x08012654``–``0x0801265e``
     - ``0x080124e6``–``0x080124f0``
   * - Startup effective-capacity reconstruction
     - ``0x080126b6``–``0x080126de``
     - ``0x08012548``–``0x08012570``
   * - Save statistics callback
     - ``0x08010a0e``–``0x08010a38``
     - ``0x080109e2``–``0x08010a0c``
   * - E2 cycle override and discharge-total replacement
     - ``0x0800f32c``–``0x0800f3ec``
     - Not used to establish the C contract

The 64-bit signed division helper is E2 ``0x0800fe68`` or C ``0x08003950``.
The current contribution, nominal-capacity divisions, cycle halfword store,
subtract/multiply aging step, minimum effective capacity, and SOH +1/cap can be
checked directly in the common routine. Inspect both callers and print paths
when validating the field association; matching labels alone is insufficient.
The :ref:`metadata extraction procedure
<firmware-behavior-reproducing-the-data-derived-findings>` identifies the source
images before disassembly. Formula examples above use invented inputs, and no
private battery recordings are distributed with this documentation.
