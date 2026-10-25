Development and validation
==========================

.. _README-development-and-validation:

Development and validation
--------------------------

.. code:: sh

   python -m pip install -e '.[test]'
   python -m pytest -q
   python -m ruff check .
   python -m ruff format --check .

All distributed test data is synthetic: invented identities, timestamps, counts, and
measurements. Private files in ``Logs/``, the vendor bundle, and editor recovery files are
ignored by Git. Package builds use an explicit source-file allowlist that excludes private
recordings and editor backups.

Local comparison with the three original recordings is opt-in:

.. code:: sh

   python -m pytest -q --private-logs=Logs

These tests read recordings at runtime without copying them into public fixtures. Complete
references are compared byte-for-byte. The historical History capture contains missing records:
its replay now verifies rejection and byte-exact partial output instead of accepting an
incomplete report. Failures omit private payloads. Without that option, the three private
reference tests are skipped. CI uses only synthetic data on Windows, macOS, and Linux with
Python 3.11 and 3.14.

See :doc:`protocol notes </protocol/index>` for the recovered command sequences, framing
details, and remaining hardware acceptance checks. The
:doc:`firmware command reference </protocol/commands>` catalogs all registered console commands
in the two reviewed firmware images, including access modes, model differences and confirmed
effects. Exact extracted metadata is available in :download:`JSON </firmware-commands.json>`.
The :doc:`parameter reference </protocol/index>` adds accepted forms, numeric bases, ranges,
defaults, storage effects and known firmware validation bugs. The
:doc:`handler supplement </protocol/index>` traces record queries, persistence, calibration and
test side effects; its `detail
extractor <https://github.com/nijel/batteryview/blob/main/scripts/extract_firmware_details.py>`__
reproduces decoded metadata without including firmware payloads or original logs.

GUI, TCP adapters, XLSX exports, parameter editing, firmware updating, and arbitrary service
scripts are outside this first implementation.

Building the documentation
--------------------------

Documentation builds require Python 3.13 or newer (the library supports Python 3.11+).
Read the Docs builds on Ubuntu 26.04 with Python 3.14.

Install the pinned documentation dependencies and build HTML with warnings treated
as errors. The same command runs in CI; Read the Docs uses the frozen lockfile.

.. code-block:: sh

   uv sync --group docs --frozen
   uv run --group docs --frozen sphinx-build -n -W --keep-going -b html docs docs/_build/html

Open ``docs/_build/html/index.html`` to browse the result locally. Documentation
sources use reStructuredText. Keep protocol evidence and unverified details explicit.
