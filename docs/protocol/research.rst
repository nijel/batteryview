Sources and verification
========================

This appendix preserves the provenance behind the communication contracts:
application methods, reviewed firmware hashes, handler and data addresses,
decoded metadata, and reproducible extraction steps. It is supporting material
for the manual; source addresses and table offsets are not console parameters.

Application and recording sources
---------------------------------

The application is an unobfuscated .NET Framework 4.5.2 WinForms assembly. The PDB lists source
paths but does not supply those source files. Inspection used managed metadata and IL,
specifically ``PylonSerialPort``, ``MsgBackgroundWorker``, ``HistoryGetInfo``, ``DataStorage``,
and the History-window button handlers. The Python package does not execute or depend on the
vendor assembly or its DLLs.

The private reference recordings cover History, Event, and SOC reset workflows. Device
identities, firmware inventories, timestamps, counters, and raw telemetry remain in the local
recordings, not in distributed fixtures. The recordings contain some truncated device text. Raw
export must preserve such text rather than reconstruct it from parsed fields. Tests do not infer
that truncation is desirable or intentionally reproduce missing serial bytes.

The following is confirmed by IL and/or the supplied files. Actual adapter timing, mode
switching, and reset execution require hardware validation.

.. _firmware-commands-evidence-and-reproduction:

Firmware images and command-table extraction
--------------------------------------------

The :download:`machine-readable catalog </firmware-commands.json>` preserves every local and
remote table entry: command name, exact firmware help, maximum token count, required access
mask, handler address and table-record offset, plus decoded selector tables for
config/prot/ctrl/datalist. The firmware hashes distinguish these observations from guesses based
on another revision. The :doc:`command reference <commands>` documents
handler-derived argument bases, ranges, defaults, storage effects and unresolved contracts. The
:doc:`storage and persistence chapter <storage>` adds full record-query forms, callback
storage layouts, calibration and hardware-test behavior, with
:download:`reproducible decoded metadata </firmware-details.json>`.
:ref:`Reset analysis <protocol-firmware-evidence-for-soc-reset>` provides the deeper EEPROM and
restart findings.

+-----------------------+-----------------------+----------------------------------------------------------------------+-----------------------+
| Image                 | Board tag             | SHA-256                                                              | Local / remote        |
|                       |                       |                                                                      | records               |
+=======================+=======================+======================================================================+=======================+
| US_E2_V2.5_Crc.bin    | ``US2000C_NF4``       | ``897c3326ab8905df75a7297905112958a07c0a2cbb0592e0ecc274b886b0c82e`` | 79 / 12               |
+-----------------------+-----------------------+----------------------------------------------------------------------+-----------------------+
| US_C_V3.1_Crc.bin     | ``US2000C``           | ``5450e3bd884ae63549fc3b278ecccc0126227234f7148c7961542755cbad2d7d`` | 90 / 12               |
+-----------------------+-----------------------+----------------------------------------------------------------------+-----------------------+

Both images use base address ``0x08003800`` and ARM Thumb handlers. Each command record is seven
little-endian 32-bit words (28 bytes):

.. code:: text

   name pointer, maximum token count, Thumb handler pointer, help pointer,
   reserved zero, reserved zero, required access mask

The mask is the **last** word, not the word before the name pointer. Table walking stops at a
null name pointer. Function addresses in the JSON clear the Thumb low bit; subtract the image
base for file offsets.

Regenerate the JSON with Python’s standard library:

.. code:: sh

   python scripts/extract_firmware_commands.py Firmwareupdate-Pylontech-US2000_3000-V6_1.zip > /tmp/firmware-commands.json
   cmp docs/firmware-commands.json /tmp/firmware-commands.json

The extractor also accepts the individual ``.bin`` files, requires a reviewed SHA-256, checks
both table sentinels, and independently scans the complete image for overlooked command records.
It skips unrelated archive entries, including logs.

.. _firmware-behavior-reproducing-the-data-derived-findings:

Decoded-table verification
--------------------------

The stdlib-only `detail
extractor <https://github.com/nijel/pylontech-tools/blob/main/scripts/extract_firmware_details.py>`__
checks the same reviewed hashes as the command extractor, reconstructs bounded initialized-data
streams and emits the :download:`detail metadata </firmware-details.json>`: weekday labels, all
38 C gauge descriptors, initialized-data fingerprints and programming-script
counts/targets/delays/fingerprint. It emits **no programming payloads, RAM contents or original
logs**.

.. code:: sh

   python scripts/extract_firmware_details.py Firmwareupdate-Pylontech-US2000_3000-V6_1.zip > /tmp/firmware-details.json
   cmp docs/firmware-details.json /tmp/firmware-details.json

The decoder’s synthetic regression tests cover literals, overlapping/extended back-references,
truncation, invalid distances and output bounds. Disassembled handler addresses above provide
the evidence for control-flow findings; decoded tables alone are not proof of effects. Remaining
gaps now concern specific consumer/driver behavior or missing hardware/bootloader evidence,
rather than an assumption that all help-listed forms work.
