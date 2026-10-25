Logging and troubleshooting
===========================

.. _README-diagnostic-logging:

Diagnostic logging
------------------

.. code:: sh

   batteryview snapshot --port /dev/ttyUSB0 --debug
   batteryview --debug snapshot --port /dev/ttyUSB0 --log-file debug.log
   batteryview snapshot --port /dev/ttyUSB0 --trace-serial --log-file serial-trace.log

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

Raw I/O uses the separate ``batteryview.serial`` logger at level 5 (``TRACE``), below ``DEBUG``.
Enable it explicitly with ``logging.getLogger("batteryview.serial").setLevel(5)`` and a handler
that accepts that level. The library installs no output handlers or root-logger configuration.
