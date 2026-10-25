Monitoring and profiles
=======================

.. _README-monitoring:

Monitoring
----------

.. code:: sh

   batteryview info --port /dev/ttyUSB0
   batteryview snapshot --port /dev/ttyUSB0
   batteryview snapshot --port /dev/ttyUSB0 --format csv --output snapshot.csv
   batteryview watch --port /dev/ttyUSB0 --interval 5 --count 10 --output readings.jsonl

JSON snapshots include timestamps, module/cell readings, alarms, unknown fields, and raw
responses. CSV has separate ``module`` and ``cell`` rows with explicit units. Missing values are
empty/null, not zero. Known alarms have ``warning`` or ``error`` severity; unfamiliar state
values are preserved with ``unknown`` severity.

``pwr`` can return a module table or a labeled summary headed ``Power N``. The header reports
the connected module’s address, not the number of installed modules. Labeled summaries support
voltage, signed current, temperature, SOC, capacity, and status fields; unknown fields remain
available in ``raw``.

For a single returned module without ``--module``, detailed reads use bare ``getpwr`` and
``pwrsys`` on the connected console, even when its reported address is greater than one.
Multiple returned modules or explicit ``--module N`` selection use addressed queries. Monitoring
supports hash-delimited ``getpwr`` responses and labeled responses with cell tables. Capacity
from ``pwr`` is retained if the detailed response omits it. Full snapshots still require
hardware verification.

Unsupported optional ``pwrsys`` queries, including firmware replies beginning with
``Unknown command``, do not discard other readings. Timeouts and malformed core responses stop
collection.

.. _README-monitoring-modes-and-profiles:

Monitoring modes and profiles
-----------------------------

.. code:: sh

   batteryview snapshot --port /dev/ttyUSB0 --monitoring-mode single
   batteryview watch --port /dev/ttyUSB0 --monitoring-mode parallel
   batteryview snapshot --port /dev/ttyUSB0 --module 3 --profile generic

``--monitoring-mode auto`` is the default: read local ``getpwr``, then discover modules with
``pwr``. Single mode uses the local reading and optional summary extensions; parallel mode
requires a module table and addressed detail reads. An explicit ``--module`` always uses
addressed reads and does not depend on a numbered login. Unsupported optional extensions are
retained as raw responses without discarding valid primary readings; malformed replies and
timeouts still fail. Module-table slots explicitly marked ``Absent`` are excluded from detail
queries and aggregates. Their original rows remain in the raw ``pwr`` response; missing voltage
in a present module still fails validation.

The first monitoring call reads identity to select a bundled native profile. ``--profile`` (or
the library’s ``profile=``) overrides this selection and skips that identity query. Profiles
cover ``generic``, ``US3000C``, ``UP2500``, ``2500LFP2``, ``US2K``, and ``Forcel_C``; unknown
device names use ``generic``. Profiles encode reviewed monitoring layouts and extension
enablement/addressing from the original XML, including older trailer placement. They do not load
executable scripts or arbitrary XML regexes. Disabled ``tsoh`` queries remain disabled.

Snapshots include cell voltage/temperature extrema and their zero-based indices, and a
``system`` summary with total current, average module voltage and available system recommended
currents. Aggregates describe only the modules in the snapshot, including a single selected
module. Missing inputs produce ``null``; unknown fields and alarm codes remain available. CSV
adds extrema columns and a ``type=system`` row before module/cell rows. Existing JSON keys
remain available. The library accepts ``monitoring_mode=``, ``profile=`` and ``read_retries=``
on ``BatteryClient``; ``SystemReading`` is also public.

Operations fail immediately by default. ``--read-retries 1`` or ``2`` permits that many
additional attempts for explicit read commands, after resynchronizing to a debug prompt. Reports
retry pages from their explicit offset and retain failed responses. Pagination continuations,
explicit rejections, login, disconnect and all SOC-reset commands are never retried. ``collect``
inherits this policy and stops if recovery fails. There is no automatic reconnect loop.
