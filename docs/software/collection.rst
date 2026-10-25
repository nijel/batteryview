Support collection
==================

.. _README-support-collection-for-several-modules:

Support collection for several modules
--------------------------------------

.. code:: sh

   pylontech-console collect --port /dev/ttyUSB0 --output support/

This collects **identity → History → Event → snapshot** using one connection. Connect the
console cable to each module separately and repeat the same command with the same output
directory. Complete support exports through addressed module selection are not verified, so
``collect`` does not accept ``--module``. The command performs no reset or configuration writes.

The directory is created if needed and may already contain earlier collections. All artifacts
are written directly into it:

- ``<run-id>_info.json``: device identity and firmware fields.
- ``<barcode>_history_<timestamp>.txt.txt``: BatteryView-compatible History transcript.
- ``<barcode>_event_<timestamp>.txt.txt``: BatteryView-compatible Event transcript.
- ``<run-id>_snapshot.json``: the ordinary JSON snapshot, including raw responses.
- ``<run-id>_manifest.json``: status, identity, file references, and report counts for this run.

Each run ID combines its UTC start time with a random identifier. Earlier files are never
overwritten. Reports retain their existing filename convention and use ``UnknownSN`` when no
barcode is available. A report filename collision fails that step rather than replacing a file
from an earlier run.

Collection stops at the first failed step. Completed files and partial report files remain, and
subsequent steps are marked ``skipped``. The per-run manifest is updated atomically as work
progresses; it records failure type and message without embedding console response payloads.
Cancellation records an interrupted step and retains existing files. A filesystem failure
writing the manifest is reported as an error, and its last valid state may remain ``running``.

Progress goes to stderr and stdout contains a JSON summary with ``directory``,
``manifest_path``, and ``complete``. Exit codes are ``0`` for complete collection, ``1`` for
failure, and ``130`` for interruption. Connection setup failures create no collection artifacts.
Normal disconnect cleanup still runs after collection.

Existing ``--debug``, ``--trace-serial``, and ``--log-file`` options also work with ``collect``;
raw serial tracing remains opt-in. Collection files contain private device information and
telemetry. The example ``support/`` directory is ignored by Git, and package source allowlists
exclude generated collections.
