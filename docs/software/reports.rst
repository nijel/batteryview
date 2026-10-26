History and Event reports
=========================

.. _README-pylontech-reports:

Pylontech reports
-----------------

.. code:: sh

   pylontech-console history --port /dev/ttyUSB0 --output history.txt
   pylontech-console event --port /dev/ttyUSB0 --output event.txt

On Windows, use a port such as ``--port COM3``. Full History/Event reports and SOC reset require
a direct connection and reject ``--module``. Addressed identity and monitoring use explicit
commands such as ``info 3`` and ``getpwr 3``; numbered login is not a substitute for addressing
reads.

Omit ``--output`` to derive ``<barcode>_<history-or-event>_<timestamp>.txt``
from the barcode and local time. New default names use a single ``.txt`` extension;
older exports and BatteryView files ending in ``.txt.txt`` remain valid doctor
inputs. Explicit output paths are used exactly as supplied. Existing files are
never overwritten. Progress is written to stderr; stdout contains a JSON result with the path,
record count, and response count.

Reports retain console echoes, prompts, spacing, and device line endings. Each response receives
BatteryView’s additional CRLF and the file has a single UTF-16LE BOM. Connection setup traffic
is excluded. No application metadata or JSON is inserted into a vendor report. Failed
collections retain partial files and exit nonzero; a partial file is not a completed report.

Reports first try ``datalist KIND dtls OFFSET``. Firmware that explicitly rejects that format
uses plain summary pages followed by ``data KIND INDEX`` for each record. The latest record’s
index determines the count, with ``stat`` as fallback. Missing, repeated or unexpected records
fail the export. A firmware-specific sixteenth row overlapping the next page is accepted; reads
never exceed the expected count. Failed attempts remain in the transcript.
