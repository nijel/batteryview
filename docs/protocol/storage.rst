EEPROM, flash and persistence
=============================

.. _firmware-parameters-eeprom-flash-and-raw-mcu-memory:

EEPROM, flash and raw MCU memory
--------------------------------

These commands have different address spaces. Chip numbers do not identify MCU internal flash
banks. See the :ref:`EEPROM map <protocol-confirmed-e2-persistent-fields>` before interpreting
the contents.

+-----------------------------------------------+-----------------------------------------------+
| Form                                          | Exact parameter contract and effect           |
+===============================================+===============================================+
| ``eepr chip offset size``                     | Chip D **0 or 1**; offset H; size D           |
|                                               | **bytes**. Requires                           |
|                                               | ``offset + size <= 0x800``. Size zero gives   |
|                                               | an empty read. Prints eight bytes per row     |
|                                               | with an ASCII column.                         |
+-----------------------------------------------+-----------------------------------------------+
| ``eepw chip offset value [repeat]``           | Chip D **0 or 1**; offset H; value H          |
|                                               | truncated to u8. Optional repeat is **H**,    |
|                                               | default **1**. Requires                       |
|                                               | ``offset + repeat <= 0x800``. Writes the      |
|                                               | **same byte** repeatedly, not a multibyte     |
|                                               | numeric value or hex blob. Repeat zero        |
|                                               | performs no writes. Client values should be   |
|                                               | 00–FF.                                        |
+-----------------------------------------------+-----------------------------------------------+
| ``eepe chip``                                 | Chip **0 or 1**; the selector is converted in |
|                                               | decimal and again in hexadecimal in the       |
|                                               | handler, with the same result for these       |
|                                               | choices. Zeros **all 2048 bytes**, using 128  |
|                                               | writes of 16 zero bytes. There is no          |
|                                               | offset/count operand or confirmation branch.  |
+-----------------------------------------------+-----------------------------------------------+
| ``flar chip offset size``                     | Chip D **0 only**; offset H; size D bytes.    |
|                                               | Bounds use the detected runtime flash         |
|                                               | capacity, not the EEPROM 2 KiB bound.         |
|                                               | Read-driver status is not reliably propagated |
|                                               | as a failed footer.                           |
+-----------------------------------------------+-----------------------------------------------+
| ``flaw chip offset value``                    | Chip D **0 only**; offset H; value H → u8.    |
|                                               | Writes **one byte**, checking it fits the     |
|                                               | runtime capacity. No repeat operand. Driver   |
|                                               | status is ignored by the handler.             |
+-----------------------------------------------+-----------------------------------------------+
| ``flae chip``                                 | Chip D **0 only**. Sends external-flash       |
|                                               | chip-erase opcode ``0x60`` and polls status   |
|                                               | with a finite retry counter. A timeout        |
|                                               | message can still lead to a success footer.   |
|                                               | Exact elapsed timeout depends on the delay    |
|                                               | implementation.                               |
+-----------------------------------------------+-----------------------------------------------+
| ``md width address count``                    | Width D **1, 2 or 4 bytes**; address H; count |
|                                               | D **elements**, not bytes. Aligns address     |
|                                               | downward to width. No address whitelist; a    |
|                                               | read can touch MMIO. Wider values are         |
|                                               | byte-swapped for display, so the printed hex  |
|                                               | is not simply a host-endian integer load.     |
+-----------------------------------------------+-----------------------------------------------+
| ``mm width address value``                    | Width D **1, 2 or 4 bytes**; address H,       |
|                                               | aligned downward; value H. Raw                |
|                                               | MCU-address-space write; no address           |
|                                               | whitelist. Narrow stores discard high bits.   |
|                                               | Do not map this to an EEPROM write API.       |
+-----------------------------------------------+-----------------------------------------------+

For example, ``eepr 0 20 16`` requests sixteen bytes at **hexadecimal 0x20**.
``eepw 0 20 AA 10`` requests **sixteen copies** of 0xAA. These are explanatory examples, not
steps required to inspect a connected battery.

Evidence: E2 ``eepe`` ``0x08010410``, erase helper ``0x080101ee``, EEPROM read/write bounds
``0x0800ffe4``/``0x0801004a``. C ``eepe`` ``0x080103dc``, erase helper ``0x08010142``: the same
full-2-KiB zeroing. Detailed flash/memory contracts above are E2 observations; entry addresses
for each command are in the JSON.

.. _firmware-behavior-what-the-persistence-callbacks-actually-do:

What the persistence callbacks actually do
------------------------------------------

.. _firmware-behavior-statistics-and-extended-state:

Statistics and extended state
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

E2 module initialization wires callbacks at ``0x0801237c``–``0x0801239c``:

============ ============== =====================================
Module field Function       Role
============ ============== =====================================
``+0x280``   ``0x08010a0e`` Persist statistics or extended state.
``+0x284``   ``0x08010928`` Store an event/history/other record.
``+0x288``   ``0x08010a6a`` Read recorded data.
============ ============== =====================================

``0x080073dc`` passes a null mode pointer to the persistence callback. That branch
**synchronously writes 124 bytes from module ``+0x88`` to EEPROM 0 ``0x38f``** and returns the
EEPROM driver’s status. ``statc`` therefore attempts to persist the cleared statistics block
immediately; it is not merely a runtime reset. Its handler discards that driver status before
returning zero.

``0x0800457a`` supplies mode value 1 to the same callback. This branch computes a checksum with
seed ``0xffff`` over **294 bytes** at module ``+0x104``, stores the checksum at module
``+0x22a``, and writes the full **296-byte block to EEPROM 1 ``0x658``**. ``tclear`` calls both
modes, so its zeroed extended state also reaches persistent storage. The helper at
``0x0800457a`` itself does not perform an additional flash-payload erase.

The extended-state startup loader (``0x080108ea``–``0x0801091c``) reads this block, recomputes
its checksum and clears the runtime copy on a mismatch. ``datac event_log``/``datac use`` modify
only part of that stored block; they do not recompute its trailing checksum in their command
handlers. A later startup can therefore invalidate more extended state than the command’s
immediate RAM write suggests. This is a consequence of the loader/checksum code, not a hardware
observation.

Periodic code at ``0x080153f0``–``0x08015424`` decrements a save countdown by the module’s base
interval, saves ordinary statistics when it expires and reloads 120. It saves extended state at
a separate point in that countdown. Shutdown and reset paths also call both helpers.
Consequently, **absence of an EEPROM write in a command handler does not mean its effects cannot
survive a reset**. For ``setsoc``, the eventual persisted module-level charge fields also depend
on subsequent aggregation; the command does not directly save each injected cell field. Precise
wall-clock save timing depends on the scheduler/base interval.

.. _firmware-behavior-save-and-the-record-writer:

``save`` and the record writer
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

``save [event|history]`` builds a record through ``0x080073ec``: a ``55 AA`` prefix, RTC
timestamp, module measurements and state, per-cell data, recommended-current fields and a
trailing ``0xaa55aa55`` word. The callback argument combines payload length in the low halfword
and record kind in the high halfword.

The E2 writer (``0x08010928``) stores event/history records in **512-byte slots**. It computes
the slot from count plus write index, wrapping at the allocation’s capacity. When full, it
advances/persists the oldest index, reduces the count by one erase unit’s worth of slots, and
erases on the relevant erase boundary before writing the new payload. Other record kinds
tail-call ``0x08010724`` instead.

This is synchronous driver invocation, not just an enqueue flag. However:

- The count increments after the payload-write call **even if that write returns an error**
  (``0x080109f8``–``0x08010a04``).
- The count increment itself is initially in RAM; the statistics-save callback makes the count
  persistent later.
- Index updates and erasure can happen before a failed payload write. Retrying can therefore
  create another slot/change bookkeeping; it is not idempotent.

The flash initializer (``0x0801fe78``–``0x0801fea6``) accepts capacity ID 0x16 and sets capacity
**4 MiB**, small erase size **4096 bytes** and large erase size **32768 bytes**. The 0x20/0x52
helpers implement those two erasures. The descriptor initialization at
``0x0801239e``–``0x080123d0`` assigns E2 event storage ``0x4b000..0x11efff`` (1696 slots) and
history ``0x11f000..0x1fffff`` (1800 slots). ``0x080108b0`` allocates further event-specific and
use-record regions after history. These addresses are **external-flash byte addresses**, not MCU
addresses, and are specific to this image’s layout.
