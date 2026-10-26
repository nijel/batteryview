Battery health screening
========================

``doctor`` summarizes the latest available readings and recorded problems for
each battery. It can connect to a battery or analyze saved files without serial
hardware. Findings distinguish measured voltage spread, historical alarms, and
suspected balancing difficulty; they do not certify battery health or identify a
failed component from a fault mask alone.

Online analysis
---------------

.. code-block:: sh

   pylontech-console doctor --port /dev/ttyUSB0
   pylontech-console doctor --port /dev/ttyUSB0 --save-inputs support/

Online doctor assesses the directly connected battery. It reads identity, one
single-module snapshot, statistics, the clock, configuration, the diagnostic log,
and complete History/Event reports. It does not change settings, clear records,
run balancing tests, calibrate sensors, or reset the battery. Normal connection
setup and disconnect follow the existing client behavior.

Use the usual ``--baud``, ``--timeout``, ``--no-shift``, ``--profile``,
``--read-retries``, and debug options where needed. ``--module`` is not supported.
Completed command rejections are recorded and later reads continue. A failed or
interrupted read is not silently treated as an empty log: after a timeout, further
reads require successful prompt resynchronization. If synchronization fails,
remaining reads are skipped and available evidence is still analyzed.

Without ``--save-inputs``, report files are temporary and removed after analysis.
With it, a UTC/UUID run ID reserves new files and a ``*_doctor_manifest.json``
manifest in the chosen directory. Raw read responses, JSON readings, complete or
partial transcripts, and acquisition outcomes are retained for offline analysis.
Earlier artifacts are never overwritten. Cancellation records an interrupted run
when inputs are being saved. A filesystem failure can leave the last valid
manifest indicating an unfinished run.

Offline analysis and matching files
-----------------------------------

.. code-block:: sh

   pylontech-console doctor history.txt.txt
   pylontech-console doctor support/
   pylontech-console doctor support/run_manifest.json --format json

A file input can be a BatteryView-compatible text report, a collection/doctor
manifest, an identity or snapshot JSON file, or diagnostic command JSON containing
``command`` and ``text``. Text reports support BOM-marked UTF-16 (either byte order)
and UTF-8, including a UTF-8 BOM. Raw debug/serial traces and CSV/JSON Lines streams
are not input formats in this version. Each input file is limited to 64 MiB.

A directory is searched recursively for supported regular files, excluding hidden
directories and symlinks. Unrelated files are ignored. Malformed recognized inputs
and missing manifest artifacts are reported while usable files remain available.
Manifest references must stay inside the input directory and cannot use symlinks.
A manifest supplied individually loads only that run's referenced artifacts.

Files are combined by verified barcode from embedded identity or a manifest.
Filenames and module addresses do not establish identity. Repeated collections
of the same battery contribute historical evidence, with duplicate records and
page overlaps counted once. Conflicting identities remain isolated, and conflicting
record copies cannot establish balancing persistence. Unidentified inputs receive
separate summaries rather than being guessed into an existing battery.

In a manifest-associated rack snapshot, only the module matching the explicitly
identified local battery is attributed to that battery. Auxiliary rack entries
without verified barcodes do not create duplicate anonymous battery summaries.
A standalone rack snapshot has no such identity context and is reported as
separate unidentified modules. Collecting each module directly supplies the
identity association needed to summarize a whole installation.

The summary uses the latest dated snapshot when available. Otherwise it identifies
historical-only evidence explicitly. Battery RTC timestamps have no inferred
timezone; two-digit protocol years mean 2000–2099. Reversed record clocks,
conflicting samples, incomplete coverage, and reset boundaries limit persistence
conclusions. A quiet current snapshot does not hide earlier voltage alarms or
system faults.

Screening rules
---------------

``--imbalance-mv`` sets a positive integer cell-spread threshold, default **100 mV**.
This is a screening heuristic, not a manufacturer protection limit. Doctor reports
both the latest spread and the maximum recorded spread, including the lowest and
highest zero-based cell indices when individual cell readings are available.
Summary-only logs can establish a spread without identifying the affected cells.
SOC, current, and operating state provide context; large spread under load or at
low SOC does not prove a failed balancer.

A separate **suspected balancing difficulty** finding requires at least three
distinct, consistent observations spanning at least **24 battery-reported hours**,
all meeting these conditions:

* Spread at or above the selected threshold.
* SOC at least **90%**, minimum cell voltage at least **3.40 V**, and Charge/Idle state.
* Absolute current no more than **0.05C**, with C derived from an explicit nominal
  Ah specification, not a remaining-charge reading.
* Complete observations and a usable, consistent record timeline within the same
  reset epoch. When reset evidence exists, comparisons stay within each source.

A later qualifying low-spread observation ends that unresolved interval. Missing
prerequisites make balancing difficulty unproven. These deliberately conservative
rules can miss real balancing problems when suitable near-full samples were not
recorded; doctor still shows observed spread and alarm evidence independently.

Historical cell high-/low-voltage states and BMS counters produce explicit warning
findings, even when the latest snapshot is normal. Repeated system-error states
or nonzero historical system-fault masks also require attention. Recorded
observations and BMS counters are presented separately; neither is an exact count
of independent physical fault incidents. Historical faults are not labeled as
currently active. Known system-fault bits are decoded using the :doc:`firmware fault-word contracts
</protocol/faults>`; unknown remainders stay visible. Code meanings are assumed
stable across firmware revisions. Power/battery event words remain separate.
For hash-format ``getpwr`` output, US2000C/US3000C use the traced word; other
profiles retain explicitly labeled vendor-indicator mappings.

For example, ``0x200`` reports an internal communication/presence fault: an
expected peer was absent in five consecutive presence checks. The condition can
clear in live state while remaining in historical records. It does not identify
a specific failed cable or component. State-only ``SysError`` observations say
that a nonzero detailed code was unavailable, rather than inventing a bit meaning.
Operational shutdown/reset flags alone are informational, not hardware diagnoses.

SOH is shown as reported by the BMS. Cycle counts prefer statistics when available.
Doctor does not estimate remaining life, usable capacity, or the meaning of a
model's uninitialized SOH value. No charging, repair, or configuration changes are
performed or prescribed by the screening rules.

Output and exit status
----------------------

Text is the default and shows a short summary per battery, important findings,
and data limitations. Use JSON for all findings and their source references:

.. code-block:: sh

   pylontech-console doctor support/ --format json --output doctor.json
   pylontech-console doctor support/ --imbalance-mv 150

Output files are created exclusively. JSON includes ``schema_version`` and
``rules_version`` (schema 1, rules 2), the selected threshold, per-battery identity,
metrics, stable finding codes, severity, certainty, source references, limitations,
and input/acquisition issues. Fault findings additionally include ``details.faults``
with the source namespace, raw mask, decoded bits, unknown remainder, mapping
basis, and historical observation counts where applicable. Historical aliases of
the same word are counted once per observation and their source fields retained.
Source references name the artifact and a record,
line, or module within it. Collection files and generated reports can contain
private identities and telemetry.

Statuses are ``no_issues_detected``, ``attention``, ``insufficient_data``, or
``unusable`` for the overall report. A successful screen means no configured issue
was found in sufficient available evidence, not that every possible fault was
ruled out.

* **0**: sufficient evidence with no warning/error findings or input issues.
* **1**: findings requiring attention or limited/partial evidence.
* **2**: unusable inputs, invalid command options, or an operational failure that
  prevents analysis.
* **130**: interruption.

Python API
----------

.. code-block:: python

   from pylontech_tools import BatteryClient, analyze_logs

   report = analyze_logs("support", imbalance_mv=100)
   print(report.status, report.to_dict())

   with BatteryClient("/dev/ttyUSB0") as battery:
       report = battery.doctor(save_inputs="support", imbalance_mv=100)
       print(report.exit_code)

Both paths return :class:`~pylontech_tools.DoctorReport`. Offline analysis never
opens a serial port. Existing ``collect`` behavior and manifests are unchanged.
