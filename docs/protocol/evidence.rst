Evidence, model differences and limitations
===========================================

.. _protocol-evidence-and-limits:

Evidence and limits
-------------------

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

.. _protocol-acceptance-still-requiring-hardware:

Acceptance still requiring hardware
-----------------------------------

- Confirm 1200-to-115200 switching, serial adapter behavior, and debug login.
- Compare a newly collected History and a nonempty Event report with BatteryView on the same
  firmware; compare structure and captured device data, allowing counters/timestamps to change
  between runs.
- Validate module selection with a chain and live ``pwr``/``getpwr`` readings.
- Exercise the explicitly requested reset on an appropriate device, check barcode restoration
  and changed address, and retain both recovery state and transcript.
- Have Pylontech confirm that newly generated reports meet its requirements.

Replay equality proves serialization and command sequencing for recorded responses; it cannot
prove physical operation or vendor acceptance.

This reference covers **all registered text-console command names** in the two reviewed firmware
images: **96 names total**, with 81 in E2 V2.5 and 91 in C V3.1. It is an implementation
reference, not a claim that every command is available on every Pylontech model or firmware
revision. Binary inverter/bootloader protocol opcodes and unregistered internal routines are
outside this inventory.

The source is the firmware supplied in ``Firmwareupdate-Pylontech-US2000_3000-V6_1.zip``. No
commands were sent to hardware to prepare this document. Firmware binaries, updater executables
and the archive’s example logs are not included in the repository.

.. _firmware-commands-differences-and-help-inconsistencies-to-preserve:

Differences and help inconsistencies to preserve
------------------------------------------------

- E2 contains ``inar``, ``inaw``, ``inash``, ``inacal`` and ``currcal``, with INA226 help.
  ``inacal`` and ``currcal`` have distinct handlers and different maximum token counts.
- C contains ``socr``, ``socw``, ``socsh``, ``soccfg``, ``soccal``, ``socd``, ``socclr``,
  ``soct`` and ``tsoc``, with bq34z100-related help. ``socclr`` actually invokes a recovered
  182-step embedded programming script, broader than a descriptor reset and separate from
  ``eepe``.
- Other C-only names are ``blocksoc``, ``tagevolt``, ``tpwr``, ``tsoh``, ``tsto`` and ``tver``.
- E2 ``tchgc`` and ``tdisc`` allow three total tokens and advertise current/limit. C allows only
  two and its help omits the parameter meaning. Do not copy E2’s two-argument form into a C
  implementation without checking the handler.
- ``tcan`` accepts one total token although help advertises a port number; ``tbld`` likewise
  accepts one token although help advertises a value. ``twdg``, not ``wdg``, is the registered
  watchdog command.
- ``inacal`` help calls it ``currcal``; ``inar``/``inaw``/``inash`` help calls them
  ``socr``/``socw``/``socsh``. These are stale descriptions, not registered aliases.
- Neither image registers ``cmdquit``, and neither contains that literal string. Retaining
  BatteryView’s disconnect sequence does not imply these firmwares implement it. The supported
  session-exit command here is ``logout``; that is not established as a substitute for the
  console-mode-switch operation.

.. _firmware-commands-remaining-work-before-implementation:

Remaining work before implementation
------------------------------------

The :doc:`parameter reference </protocol/index>` and :doc:`handler supplement </protocol/index>`
record completed analysis and the remaining board/consumer/source limitations. Use the recorded
handler addresses to establish unresolved parameter units, numeric bases, full accepted forms,
persistence timing and per-model hardware behavior for each new write/test command. Identify
operation-specific result messages and recovery requirements, then test with synthetic replies
before live verification. This catalog proves registration, help metadata and the explicitly
traced behaviors; it is not a complete decompilation of every command handler or an endorsement
of running every command as a discovery probe.

This supplements the :doc:`complete command catalog </protocol/commands>`. It records what the
handlers actually parse, including differences from their help strings. The reviewed images,
hashes, access modes and remote-routing rules are defined there. Addresses below are runtime
Thumb-code addresses, with the Thumb bit cleared. **E2 means US_E2_V2.5_Crc.bin; C means
US_C_V3.1_Crc.bin.**

Unless explicitly marked C or both, detailed observations are **E2-specific**. A shared command
name does not establish the same contract on another board. The
:doc:`handler and persistence supplement </protocol/index>` resolves the later record-query,
callback, calibration, diagnostic and model-comparison findings. Analysis was static; none of
these operations was tried on a battery. Remaining unknowns are called out rather than filled in
from command names.
:ref:`BatteryView’s control descriptions <protocol-command-meanings-from-batteryviews-controls>`
add vendor UI meanings, model-specific workflows and known configuration defects; those
application labels do not supersede the firmware contracts below.

This continues the :doc:`parameter reference </protocol/index>` with the remaining dispatch
branches and storage callbacks. **E2** and **C** identify the exact reviewed images and hashes
in the :doc:`catalog </protocol/commands>`. Addresses are runtime addresses with the Thumb bit
cleared. Findings describe static code paths, not successful tests on hardware. Logical storage
layouts, callback wiring and limits can differ on other firmware versions.

.. _firmware-behavior-independently-checked-c-image-differences:

Independently checked C-image differences
-----------------------------------------

Shared names do not imply shared electrical procedures. These contracts were checked directly in
C rather than copied from E2:

+-----------------------------------------------+-----------------------------------------------+
| Area                                          | C finding and evidence                        |
+===============================================+===============================================+
| Persistence                                   | Callback ``0x080109e2``, wired at             |
|                                               | initialization ``0x08012218``, uses the same  |
|                                               | 124-byte EEPROM-0 ``0x38f`` / 296-byte        |
|                                               | EEPROM-1 ``0x658`` split. Extended checksum   |
|                                               | covers 294 bytes, stored at module ``0x22a``. |
+-----------------------------------------------+-----------------------------------------------+
| Record query grammar                          | C ``datalist`` has the same                   |
|                                               | 3/4/5/6-total-token dispatch: summary, dtls,  |
|                                               | all-cell bat field, single-cell bat field.    |
|                                               | Detailed branch ``0x0800ba3c``; field         |
|                                               | branches ``0x0800c100/0x0800c274``. Do not    |
|                                               | infer field units from the table header       |
|                                               | alone.                                        |
+-----------------------------------------------+-----------------------------------------------+
| Charge-current test                           | No operand uses **10000 ±50 mA**; one D       |
|                                               | operand uses supplied current ±50. Only two   |
|                                               | total tokens allowed. ``0x0800f700``.         |
+-----------------------------------------------+-----------------------------------------------+
| Discharge-current test                        | No operand uses **−1000 ±100 mA**; one D      |
|                                               | magnitude is negated but uses **±50 mA**,     |
|                                               | unlike E2’s ±100 default tolerance for the    |
|                                               | one-operand form. ``0x0800f7c4``.             |
+-----------------------------------------------+-----------------------------------------------+
| SOC tests                                     | ``tsoh``, ``tpwr``, ``tagevolt``, ``tsto``    |
|                                               | are cached/read comparisons described above;  |
|                                               | ``tsoc`` can program/reset the gauge. These   |
|                                               | are materially different mutation             |
|                                               | classifications.                              |
+-----------------------------------------------+-----------------------------------------------+
| Fuel-gauge hardware                           | C uses one-byte ``socr/socw`` register        |
|                                               | operations, descriptor-based ``soccfg`` and   |
|                                               | the embedded gauge-programming script. E2 INA |
|                                               | operations are not aliases of these C         |
|                                               | handlers.                                     |
+-----------------------------------------------+-----------------------------------------------+

The catalog still defines exact command availability and argument ceilings for both images.
Board-specific pin behavior, external fixtures and every common handler’s full cross-image
equivalence are not assumed by this table. The E2-specific sections above retain their explicit
scope.

.. _firmware-behavior-boundaries-of-this-additional-analysis:

Boundaries of this additional analysis
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

C independently has the same missing lower-bound check and two raw stores in its ``oc2d`` setter
(``0x0800e31c``–``0x0800e340``). The signedness issue therefore affects both reviewed images.

The negative ``oc2d`` setter still demonstrably accepts and stores a signed value, but a
complete route from that field through hardware programming/protection timing was not
established. The ordinary software protection dispatch uses indirect callback/index tables;
finding a signed comparison elsewhere does not prove it consumes this particular field. **No
claim of immediate protection, infinite delay, or harmless no-op is justified.** A future client
should still accept only 0–5000 ms. This remains a specific downstream-analysis gap.

Physical sensor/pin identities, power-loss/wake behavior, live fault recovery, and the absent
bootloader remain outside what these application paths prove. The later updater analysis narrows
the transfer-protocol gap to receiver-side behavior; it does not supply those missing receiver
bytes.
