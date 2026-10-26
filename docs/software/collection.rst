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

- ``<barcode>_<run-id>_info.json``: device identity and firmware fields.
- ``<barcode>_<run-id>_history.txt``: BatteryView-compatible History transcript.
- ``<barcode>_<run-id>_event.txt``: BatteryView-compatible Event transcript.
- ``<barcode>_<run-id>_snapshot.json``: the ordinary JSON snapshot, including raw responses.
- ``<barcode>_<run-id>_manifest.json``: status, identity, file references, and report counts.

Each run ID combines its UTC start time and a random UUID, for example
``20000102T030405Z_0123456789abcdef0123456789abcdef``. Every artifact from one run
shares the same barcode/run prefix. Characters outside letters, digits,
underscores, plus and minus signs are replaced with underscores in the filename;
the original barcode remains in the contents. Missing barcodes use ``UnknownSN``.
Repeated collections of the same battery within one second have distinct run IDs.
Earlier files are never overwritten; an artifact collision fails that step.

The initial identity read determines the prefix before the manifest is created.
If that read fails or is interrupted, an ``UnknownSN`` manifest records the
outcome and skipped steps. Manifest creation failures propagate without replacing
an existing manifest. No files are renamed midway through collection.

Manifest format version 1 and transcript contents are unchanged. Doctor accepts
both this layout and older collections with run-only JSON filenames and
``<barcode>_history_<timestamp>.txt.txt`` or Event equivalents. Existing files
need no renaming, and both layouts can coexist in the same directory.

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

Analyze the gathered files with :doc:`doctor` to combine each battery's evidence
and summarize voltage imbalance, recorded alarms, and possible balancing
difficulty. Doctor matches identities across repeated collections without
changing these files.
