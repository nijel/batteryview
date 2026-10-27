Individual read-only commands
=============================

Use individual methods when your application needs a particular measurement,
setting, record, or diagnostic. They use the same connection, locking, bounded
read recovery, and exceptions as :doc:`python`. The combined
:meth:`~pylontech_tools.BatteryClient.diagnostics` method calls these individual
methods, retaining its existing command list and report format.

.. code-block:: python

   from pylontech_tools import BatteryClient, UnsupportedCommand

   with BatteryClient("/dev/ttyUSB0") as battery:
       capacity = battery.nominal_capacity()
       print(capacity.nominal_capacity_ah)
       print(battery.statistics().cycle_count)
       print(battery.read_clock().timestamp)
       try:
           result = battery.check_pack_voltage()
           print(result.passed)  # True, False, or None if no result was recognized.
       except UnsupportedCommand:
           print("This firmware does not provide the pack-voltage check.")

Results and compatibility
-------------------------

New result classes extend :class:`~pylontech_tools.ConsoleReadResult`. All retain
``command``, the complete ``text``, and original string ``fields``. Existing
statistics, clock, log, and configuration methods now return subclasses with
additional parsed attributes; their existing attributes remain available.
The CLI, combined diagnostics JSON, and saved doctor evidence keep their
existing schemas. Use ``to_console_dict()`` for that stable raw-evidence schema.

:class:`~pylontech_tools.ParsedReadResult` additionally provides:

* ``values``: integer, decimal, hexadecimal, and explicitly unit-bearing labeled
  values parsed into Python numbers; unfamiliar values remain strings.
* ``quantities``: :class:`~pylontech_tools.Quantity` objects with the value and
  firmware-printed unit, without inferred conversion.
* ``masks``: hexadecimal bitmasks, retaining their accompanying flag descriptions
  in ``fields``.
* ``rows``: parsed measurement-table columns, retaining unfamiliar columns.
* ``unparsed_lines``: remaining display text, including layouts without a verified
  structured parser. The original response is always in ``text``.

Family-specific attributes provide normalized measurements in V, A, degrees C,
and Ah, integer counters and registers, byte dumps, and battery-local
``datetime.datetime`` values without an assumed timezone. Two-digit console
years use 2000 as their base. Optional/unrecognized fields are ``None``; missing
measurements do not become zero. Unknown layouts remain available as evidence
rather than being assigned guessed meanings.

``statistics().soh_pct`` is the firmware's reported value, including zero.
``soh_diagnostics()`` returns per-cell diagnostic accounting, **not measured
per-cell health percentages**. See :doc:`/protocol/health` for SOH and cycle-count
interpretation. For passive checks, ``passed`` is independent of command
completion: a successful footer can accompany a failed check, and no recognized
pass/fail result produces ``None``.

Command inventory
-----------------

Names below are methods on :class:`~pylontech_tools.BatteryClient`. Firmware
availability and exact response contracts are described in :doc:`/protocol/commands`
and the linked topic chapters. Individual methods raise ``UnsupportedCommand``;
only combined diagnostics treats unsupported reads as optional. No automatic
aliases substitute one firmware family's command for another.

Communication and measurements
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

.. list-table::
   :header-rows: 1
   :widths: 52 48

   * - Python method
     - Wire form
   * - ``command_help(name=None)``
     - ``help [name]``
   * - ``communication_info()``
     - ``ci``
   * - ``communication_frame(port)``
     - ``ct port``; port 0 or 1
   * - ``unit_baud_rate()``
     - Bare ``urates``; unit/RS485 rate, not console baud
   * - ``inverter_protocol()`` / ``lg_configuration()``
     - Bare ``setprt`` / ``lg``
   * - ``info()``
     - ``info [module]``; existing typed identity API
   * - ``power_summary()`` / ``power_details()``
     - ``pwr [module]`` / ``getpwr [module]``
   * - ``cell_readings(cell=None)``
     - ``bat [module [cell]]``
   * - ``system_status()``
     - Bare local ``pwrsys``
   * - ``soh_diagnostics()``
     - ``soh [module]``; unavailable through the inspected E2 frontend

Measurement results contain existing ``ModuleReading``, ``CellReading``, and
``SystemReading`` models. ``power_details()`` uses the selected monitoring profile;
without an explicit profile or cached identity it reads ``info`` first.
Selecting a cell reads identity to verify its zero-based index and, for a local
connection, obtain the required module address. The first ``bat`` operand is a
module address, never a cell index. See :doc:`/protocol/console`.

Settings, counters and accounting
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

.. list-table::
   :header-rows: 1

   * - Python method
     - Wire form
   * - ``statistics()`` / ``read_clock()`` / ``diagnostic_log(count=None)``
     - ``stat [module]`` / bare ``time`` / ``log [count]`` (1–32)
   * - ``configuration(selector=None)``
     - ``config [module] [selector]``; documented query selectors only
   * - ``control_status(target=None)`` / ``protection_status()``
     - ``ctrl [module] [target]`` / bare ``prot [module]``
   * - ``nominal_capacity()`` / ``cycle_statistics()``
     - Bare ``totalcoul`` / ``tcycle``
   * - ``empty_voltage()`` / ``low_soc_configuration()``
     - ``emptyvolt [module]`` / bare ``setlowcfg``
   * - ``automatic_switch_status()`` / ``blocking_soc()``
     - Bare ``autoswitch`` / ``blocksoc`` (C)
   * - ``lifetime_statistics()`` / ``self_discharge_state()``
     - Bare ``euro`` / ``eurostub``
   * - ``aging_voltage_history()`` / ``manufacturing_time()``
     - ``trdagevolt`` / bare ``cmudtesttime``

``configuration`` rejects actions such as ``save`` and ``default`` and the
unimplemented selectors. Supported ``control_status`` targets are ``cfet``,
``dfet``, ``buzz``, ``heat``, ``pwmc``, ``softstart``, ``agelog``, and ``mostest``.
``i2c`` and ``afuse`` are excluded because even their bare target forms change
state; ``pwmp`` has no implemented query. These APIs never accept setter values.
See :doc:`/protocol/configuration`, :doc:`/protocol/calibration`, and
:doc:`/protocol/records`.

Records and storage
~~~~~~~~~~~~~~~~~~~

.. code-block:: python

   with BatteryClient("/dev/ttyUSB0") as battery:
       latest = battery.read_record()  # Latest event; no count preflight.
       first = battery.read_record("history", 0)
       history = battery.list_records("history", start=0, detailed=True)
       voltages = battery.list_records("event", field="volt", cell=0)
       block = battery.read_eeprom(0, 0x20, 16)
       print(block.data.hex())

``read_record(kind="event", index=None)`` uses ``data [module] kind [index]``.
An explicit index triggers a count check first. ``list_records(kind, start=0,
detailed=False, field=None, cell=None)`` uses the corresponding verified
``datalist`` form. Kinds are ``event``, ``history``, ``pov``, ``puv``, ``plv``,
``bov``, ``buv``, ``inputov``, ``coc``, ``coca``, ``doc``, ``doca``, ``sc``, and
``use``. Lists are local-only. Field selectors are ``id``, ``volt``, ``curr``,
``temp``, and ``coul``; a cell requires a field, and field selection cannot be
combined with detailed mode.

Counts come from ``stat`` for event/history and the latest selected record for
other kinds. Cell selection also reads identity for its bound. An empty list
returns an empty result after reading its count. Lists consume every continuation
using CR+LF through the final prompt and verify the returned record indices.
A timeout can retry the entire list after verified prompt synchronization;
it never retries just a failed continuation or combines pages from two attempts.
Errors retain partial response text. Unknown field-list scaling is preserved
rather than silently applying module-summary units; see :doc:`/protocol/records`.

``read_eeprom(chip, offset, size)`` uses ``eepr`` and restricts chip to 0/1 and
the byte range to the 2048-byte device. ``read_flash(offset, size)`` uses
``flar 0``; firmware validates the detected flash capacity. Both use Python integer
arguments, encode offsets in hexadecimal and sizes in decimal, and return
``StorageResult.data`` as bytes. Missing, malformed, repeated, or truncated dump
rows raise ``ProtocolError`` even with a successful footer. See :doc:`/protocol/storage`.

Monitor ICs and fuel gauges
~~~~~~~~~~~~~~~~~~~~~~~~~~~

.. list-table::
   :header-rows: 1

   * - Python method
     - Wire form and restrictions
   * - ``monitor_configuration(ic_count)`` / ``monitor_communication(ic_count)``
     - ``bmicrdcfg count`` / ``bmicrdcomm count``; count 1–2
   * - ``ina_register(offset)`` / ``ina_registers()``
     - ``inar offset`` / ``inash`` (E2)
   * - ``ina_calibration()`` / ``current_calibration()``
     - Bare ``inacal`` / ``currcal`` (E2), reporting only
   * - ``gauge_register(offset)`` / ``gauge_registers()``
     - ``socr offset`` / ``socsh`` (C)
   * - ``gauge_data()`` / ``gauge_resistance_table()``
     - Bare ``socd`` / ``soct`` (C)
   * - ``gauge_configuration()``
     - Bare ``soccfg`` (C), descriptor report only

The caller must match monitor count to the installed hardware. Counts above two
overflow the inspected firmware's caller buffer and are rejected. Register offsets
are integers 0–0x7F, encoded in hexadecimal. INA reads report two-byte values;
C gauge register reads report one byte. ``RegisterResult.registers`` maps integer
addresses to integer values for recognized register-row formats. Other layouts,
including unfamiliar monitor blocks, remain in the raw evidence.
See :doc:`/protocol/calibration` and :doc:`/protocol/diagnostics`.

Passive manufacturing checks
~~~~~~~~~~~~~~~~~~~~~~~~~~~~

.. list-table::
   :header-rows: 1

   * - Python method
     - Wire form
   * - ``check_charge_current(current_ma=None, tolerance_ma=None)``
     - ``tchgc [current [tolerance]]``
   * - ``check_discharge_current(magnitude_ma=None, tolerance_ma=None)``
     - ``tdisc [magnitude [tolerance]]``; positive discharge magnitude
   * - ``check_cell_voltage(spread_mv=None)``
     - ``tvolt [spread]``
   * - ``check_cell_temperature(spread_mc=None)``
     - ``ttmp [spread]``
   * - ``check_environment_temperature()`` / ``check_dip_switch(expected)``
     - ``tetmp`` / ``tdip expected`` (0–15)
   * - ``check_input(condition)``
     - ``tinput rv`` or ``tinput dcov`` only
   * - ``check_ibc_inputs(expected)`` / ``check_cbn_inputs(expected)``
     - ``tibcio nc|sc`` / ``tcbnio nc|sc``
   * - ``check_pack_voltage()`` / ``check_soh_events()``
     - ``tpwr`` / ``tsoh`` (C)
   * - ``check_system_faults()`` / ``check_version(expected)``
     - ``tsto`` / ``tver expected`` (C); hexadecimal version
   * - ``check_aging_voltage()``
     - ``tagevolt`` (C)

Current tolerance is keyword-only and requires a reference current: charge 50–500
mA, discharge 100–500 mA. The two-operand current form is supported by E2; the
inspected C dispatcher rejects it. Omit tolerance for cross-family use. Checks
retain their built-in firmware conditions and defaults. They do not certify
battery health. See :doc:`/protocol/diagnostics` for each comparison and its limits.

Addressing, failures and exclusions
-----------------------------------

Only ``info``, ``statistics``, ``configuration``, ``control_status``,
``protection_status``, ``empty_voltage``, ``soh_diagnostics``, ``read_record``,
``power_summary``, ``power_details``, and ``cell_readings`` support an addressed
client. Other individual reads reject ``module=...`` before transmitting.

Arguments are validated before requests, apart from identity/count preflights
needed to obtain hardware bounds. Booleans do not count as integer arguments.
Firmware narrowing, wraparound, arbitrary operands, and action-looking selectors
are not reproduced. Ordinary failures and cancellation propagate; use the client
as a context manager to ensure disconnect.

No raw MCU ``md`` method is exposed: reads can touch MMIO with side effects.
Addressed ``euro`` and ``pwrsys`` forms are omitted because of the documented
pointer/presence bugs. ``couls`` has no working public text dispatch in the
inspected images. Display selection, calibration, storage writes, and active
hardware tests are outside this API. In particular, ``soccal`` can issue control
writes even on query-looking branches, and ``tsoc`` can program the gauge.
The separate existing ``reset_soc`` workflow remains explicitly mutating.
