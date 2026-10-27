Logging and troubleshooting
===========================

.. _README-diagnostic-logging:

Diagnostic logging
------------------

.. code:: sh

   pylontech-console snapshot --port /dev/ttyUSB0 --debug
   pylontech-console --debug snapshot --port /dev/ttyUSB0 --log-file debug.log
   pylontech-console snapshot --port /dev/ttyUSB0 --trace-serial --log-file serial-trace.log

On failure, stderr shows the failed command, available timing/framing context, and the last 4096
bytes of its response, including timeout fragments. Control characters are escaped, truncation
is marked, and an empty reply is explicit. This also applies to failures caught by ``collect``;
its manifest does not contain response tails. **Failure output can contain private identifiers
and telemetry.** Successful traffic is not printed by default. Library protocol exceptions
expose ``response`` and ``context``; collection clients expose ``last_failure``.

``--debug`` logs connection stages, baud changes, command names, recognized prompts, timing,
byte counts, and failure types. It excludes response contents and redacts identity-bearing
arguments such as barcodes. ``--trace-serial`` additionally logs escaped raw sent/received
bytes, making CR and LF visible. **Raw traces may contain private battery identities and
telemetry.** Keep them local and review them before sharing; do not copy them into public test
fixtures.

Both ``--trace-serial`` and ``--log-file`` imply debug logging. Options work before or after the
subcommand. Diagnostics go to stderr unless ``--log-file`` selects a new UTF-8 file; existing
log files are never overwritten. JSON/CSV on stdout and vendor transcript files remain separate
from diagnostic output. Error messages and report progress still go to stderr when diagnostics
are directed to a file.

Library callers configure standard Python logging themselves. For metadata:

.. code:: python

   import logging

   logging.basicConfig(level=logging.DEBUG)

Raw I/O uses the separate ``pylontech_tools.serial`` logger at level 5 (``TRACE``), below ``DEBUG``.
Enable it explicitly with ``logging.getLogger("pylontech_tools.serial").setLevel(5)`` and a handler
that accepts that level. The library installs no output handlers or root-logger configuration.

Read-only battery diagnostics
-----------------------------

Use ``diagnostics`` to gather the available diagnostic reads in one session:

.. code-block:: sh

   pylontech-console diagnostics --port /dev/ttyUSB0
   pylontech-console diagnostics --port COM3 --format json --output diagnostics.json

It sends these exact bare commands in order: ``stat``, ``time``, ``log``,
``config``, ``totalcoul``, ``tcycle``, ``emptyvolt``, ``setlowcfg``, ``ctrl``,
``prot``, ``euro``, ``trdagevolt``, and ``soh``. No setter operands or target
selectors are accepted. A direct connection is required; ``--module`` is not
available. In particular, bare ``euro`` avoids the documented E2 addressed-form
bug, and bare ``ctrl`` avoids target-specific forms that can change state.

The additional reads report nominal capacity and cycle/effective-capacity
bookkeeping, empty-voltage and low-SOC settings, control/protection states,
extended usage metrics, stored voltage extrema, and per-cell SOH diagnostic
counters/states. ``soh`` does not report measured per-cell health percentages.
Firmware-derived capacity and resistance metrics are estimates, not capacity
test results. See :doc:`/protocol/health` and :doc:`/protocol/diagnostics` for
interpretation and firmware limitations.

An explicitly unsupported command is marked ``unavailable`` and acquisition
continues. This includes ``soh`` on firmware where it cannot be invoked. Other
errors, including busy or absent targets, timeouts, and malformed responses,
stop subsequent reads. Completed responses and the failed response/context
remain in the partial report; stderr shows the failure diagnostics.

Text output separates commands into sections and uses short unavailable notices,
without truncating successful responses. JSON contains ``timestamp`` (UTC),
``complete``, and ordered ``reads``. Each read has ``command``, ``status``
(``complete``, ``unavailable``, or ``failed``), original ``text``, string-valued
``fields``, optional ``error`` type/message, and failure ``context``. Units are
not converted. Unsupported responses remain available in JSON.

Exit status is **0** if acquisition finishes with at least one successful read,
even when other commands are unavailable; **1** if a read fails or every command
is unavailable; **130** on interruption. Interruption propagates normally and
does not produce a completed combined report. Normal disconnect cleanup still
runs. ``--output`` creates a new UTF-8 file and never overwrites an existing one.
The existing logging and bounded ``--read-retries`` options apply. Default
``collect`` and doctor acquisition are unchanged.

Python callers use :meth:`~pylontech_tools.BatteryClient.diagnostics`:

.. code-block:: python

   from pylontech_tools import BatteryClient

   with BatteryClient("/dev/ttyUSB0") as battery:
       report = battery.diagnostics()
       for read in report.reads:
           print(read.command, read.status, read.fields)
       if not report.complete:
           print(battery.last_failure)

An ordinary acquisition failure returns an incomplete report and retains its
exception in ``last_failure``. Cancellation raises instead of returning a report.

Individual reads
~~~~~~~~~~~~~~~~

These explicit reads display information without setting the clock, changing
configuration, or clearing counters or logs:

.. code-block:: sh

   pylontech-console stat --port /dev/ttyUSB0
   pylontech-console time --port /dev/ttyUSB0
   pylontech-console log --port /dev/ttyUSB0
   pylontech-console log --port /dev/ttyUSB0 --count 8
   pylontech-console config --port /dev/ttyUSB0

``stat`` reads operating/fault counters, record counts, SOH, and SOC fields.
``time`` reads the battery RTC; its timezone is not inferred. ``log`` reads the
internal diagnostic ring, which is separate from the recorded events exported
by ``event``. It traverses newest first. Omit ``--count`` to use the firmware's
available-entry count; an explicit count must be 1–32 and does not establish that
all requested entries contain valid historical data. ``config`` displays the
full configuration without accepting selector or setter operands.

``stat`` and ``config`` accept ``--module 1..16`` using explicit command routing.
The master must be able to reach that module; a non-master cannot be assumed to
forward requests. ``time`` and ``log`` require a direct connection and do not
accept ``--module``. Firmware availability and access permissions still apply;
unsupported commands are reported without speculative aliases or mode changes.

The default output is the complete console response, including echoes and
framing. Use ``--format json`` for an object containing ``command``, ``text``, and
``fields``. Fields retain labeled values as strings without unit conversion;
unstructured output remains in ``text``. Bare timestamps are not treated as
labeled fields. Use ``--output diagnostic.txt`` to create a new UTF-8 output file;
existing files are never overwritten. These outputs can contain private device
information. The reads are not added to default support collection.

The existing ``--debug``, ``--trace-serial``, and ``--read-retries`` options apply.
Only timeout/connection failures qualify for bounded read recovery after a debug
prompt has been verified. Busy-target and absent-device failures are explicit,
even if the firmware also emits a success footer; neither is retried or treated
as an unsupported optional command.
