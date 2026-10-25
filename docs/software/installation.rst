Installation and connection
===========================

A portable Pylontech console library and command-line tool. Its primary outputs are the UTF-16
text transcripts produced by BatteryView’s **History**, **Event**, and **SOC reset** buttons.
Monitoring supports JSON, JSON Lines, and CSV.

The protocol was recovered from BatteryView 3.0.28’s compiled .NET code, bundled XML
definitions, and private reference console reports. The supplied reports can be replayed in
opt-in local tests. **Live hardware behavior and acceptance of newly collected reports by
Pylontech have not yet been verified.** Other firmware variants need additional validation.

.. _README-install:

Install
-------

Requires Python 3.11 or newer on Windows, Linux, or macOS:

.. code:: sh

   python -m pip install .
   batteryview ports

Use the battery’s console connection and the appropriate serial cable. The default connection
sequence sends BatteryView’s mode-switch frame at 1200 baud, then opens the console at 115200
baud, 8N1, without flow control. Use ``--no-shift`` to connect to a console already in command
mode, or ``--baud`` for another console rate. Close other applications using the port before
connecting.

RTS and DTR are explicitly inactive, matching BatteryView’s .NET serial defaults. Their states
are set before the initial open and each baud-change reopen, and included in debug diagnostics.
When the port is already open at the requested baud rate it stays open, so ``--no-shift`` avoids
a redundant close/reopen and the associated input-buffer reset.

Connection setup recognizes a console that is already at ``pylon_debug>`` and skips redundant
login. Otherwise it sends ``login debug`` once and verifies the final prompt. A rejected login
is accepted only when that prompt independently confirms debug mode; a base prompt or timeout
still fails the connection.

On normal client/context-manager exit, the client follows BatteryView’s disconnect sequence:
send ``cmdquit`` with LF, wait up to five seconds for received text containing ``cmdquit``
(possibly its echo), then close the serial port. No subsequent prompt is required. Timeouts and
serial errors during disconnect are diagnostic only: the port is still closed, and an earlier
operation error is preserved. Some firmware rejects ``cmdquit``; diagnostics report that
rejection explicitly even when its echo matches. An echo alone does not confirm that console
mode ended. The disconnect response is excluded from report files. Repeated ``close()`` calls do
not send additional commands. Failed connection setup releases the port immediately without
attempting a console command.
