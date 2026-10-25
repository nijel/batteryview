Firmware compatibility and limitations
======================================

.. _protocol-evidence-and-limits:

Compatibility scope
-------------------

This chapter defines the supported firmware scope, differences between the two
reviewed images, and behavior that still needs hardware verification. Consult it
before applying a command contract to another model or firmware release.

This reference covers **all registered text-console command names** in the two reviewed firmware
images: **96 names total**, with 81 in E2 V2.5 and 91 in C V3.1. It is an implementation
reference, not a claim that every command is available on every Pylontech model or firmware
revision. Binary inverter/bootloader protocol opcodes and unregistered internal routines are
outside this inventory.

The source is the firmware supplied in ``Firmwareupdate-Pylontech-US2000_3000-V6_1.zip``. No
commands were sent to hardware to prepare this document. Firmware binaries, updater executables
and the archive’s example logs are not included in the repository.

.. _firmware-commands-differences-and-help-inconsistencies-to-preserve:

Model differences and misleading help
-------------------------------------

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

.. _firmware-behavior-independently-checked-c-image-differences:

C-firmware behavior differences
-------------------------------

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

Unresolved protection timing and hardware behavior
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

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

.. _firmware-commands-remaining-work-before-implementation:

Contract limits and unresolved behavior
---------------------------------------

The :doc:`command reference <commands>` lists registration and access rules; the
topic chapters give accepted parameters, units, ranges, side effects, and known
validation defects. They do not establish every common handler's behavior on
every board. In particular, a shared name does not prove cross-model equivalence.

**E2 means US_E2_V2.5_Crc.bin; C means US_C_V3.1_Crc.bin.** Unless explicitly
marked C or both, detailed firmware contracts are **E2-specific**. Runtime code
addresses have the Thumb bit cleared; reviewed image hashes and extraction
methods are in :doc:`research`. Storage layouts and callback wiring can differ
on other firmware releases.

The contracts come from static code paths, not successful hardware execution or
a complete decompilation of every handler. For a new write or test operation,
resolve any unknown units, numeric bases, accepted forms, persistence timing,
operation-specific result messages, and recovery requirements before relying on
it. Preserve explicit unknowns rather than inferring behavior from command names;
registration is not an endorsement of discovery probes. Test with synthetic
replies before hardware verification.

:ref:`BatteryView's control descriptions <protocol-command-meanings-from-batteryviews-controls>`
explain vendor UI meanings, model workflows, and configuration defects. Application
labels do not supersede firmware contracts. Use :doc:`records`, :doc:`storage`,
:doc:`calibration`, and :doc:`diagnostics` for the corresponding command behavior.

.. _protocol-acceptance-still-requiring-hardware:

Hardware validation requirements
--------------------------------

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
