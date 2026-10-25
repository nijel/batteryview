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
