Development and validation
==========================

.. _README-development-and-validation:

Development and validation
--------------------------

For normal use, :doc:`install the released package from PyPI <installation>`.
To work on the code, clone the source repository and install the locked
development dependencies:

.. code:: sh

   git clone https://github.com/nijel/pylontech-tools.git
   cd pylontech-tools
   uv sync --frozen
   uv run --frozen python -m pytest -q
   uv run --frozen python -m ruff check .
   uv run --frozen python -m ruff format --check .

All distributed test data is synthetic: invented identities, timestamps, counts, and
measurements. Private files in ``Logs/``, the vendor bundle, and editor recovery files are
ignored by Git. Package builds use an explicit source-file allowlist that excludes private
recordings and editor backups.

Local comparison with the three original recordings is opt-in:

.. code:: sh

   uv run --frozen python -m pytest -q --private-logs=Logs

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
extractor <https://github.com/nijel/pylontech-tools/blob/main/scripts/extract_firmware_details.py>`__
reproduces decoded metadata without including firmware payloads or original logs.

GUI, TCP adapters, XLSX exports, parameter editing, firmware updating, and arbitrary service
scripts are outside this first implementation.

Publishing releases
-------------------

Pushing a tag such as ``v0.1.0`` runs ``.github/workflows/release.yml``. The tag
must match the exact version in ``pyproject.toml``, prefixed with ``v``. Releases
wait for the reusable test workflow's full platform/Python matrix and the strict
documentation build. Branch pushes and pull requests run those checks without
publishing.

The workflow builds one wheel and source distribution with locked release tools,
checks their identities and metadata, and smoke-tests the installed wheel outside
the checkout. Separate jobs attest and publish these same files. No project code
is checked out or executed in the PyPI publishing job. Distributions and the
provenance bundle are retained as workflow artifacts for 30 days.

Configure trusted publishing once
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

Before pushing the first release tag:

1. Create the GitHub environment ``pypi`` in ``nijel/pylontech-tools``. Under its
   deployment rules, select specific branches/tags and allow only **tags** matching
   ``v*``. Maintainers can add required reviewers if desired.
2. On PyPI, configure a GitHub trusted publisher with these exact values:

   * Project: ``pylontech-tools``.
   * Owner: ``nijel``.
   * Repository: ``pylontech-tools``.
   * Workflow filename: ``release.yml``.
   * Environment: ``pypi``.

   If the project does not exist yet, register a pending publisher through the
   PyPI account's Publishing settings using the same values. The first successful
   publication creates the project. Renaming the workflow, repository, owner, or
   environment requires updating the publisher registration.

The workflow uses GitHub OIDC credentials; do not configure a PyPI API token or
password. See PyPI's `trusted publishing guide
<https://docs.pypi.org/trusted-publishers/using-a-publisher/>`__ and
`pending publisher instructions
<https://docs.pypi.org/trusted-publishers/creating-a-project-through-oidc/>`__.

Create a release
~~~~~~~~~~~~~~~~

Update the static project version and lockfile, commit the changes, then tag that
commit. For example, after setting the version to ``0.1.0``:

.. code-block:: sh

   uv lock
   uv sync --locked --group release
   uv run --locked --group release python scripts/check_release.py v0.1.0
   uv build --no-build-isolation --no-create-gitignore
   uv run --locked --group release python scripts/check_release.py v0.1.0 --dist dist
   uv run --locked --group release twine check --strict dist/*
   git tag -a v0.1.0 -m "Release 0.1.0"
   git push origin v0.1.0

Use a clean ``dist/`` directory for these local checks. Do not commit build
artifacts. The release workflow creates them independently from the tagged commit.
Local version identifiers such as ``0.1.0+local`` are rejected because PyPI does
not accept them. Development and prerelease versions, such as ``0.2.0rc1``,
publish to PyPI and create a GitHub **prerelease**. Post releases are ordinary
GitHub releases.

After PyPI succeeds, the workflow creates a GitHub release for the existing tag
with generated release notes and attaches the wheel, source distribution, and
``provenance.json`` verification bundle. Existing releases and files are never
overwritten. Runs for the same tag are serialized without cancellation.

Verify provenance and recover failures
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

GitHub's ``actions/attest`` generates SLSA build provenance for both distributions.
The publishing action separately generates and uploads PyPI publish attestations
using the trusted publisher identity. These establish origin and artifact
digests; they are not a guarantee that the software is free of defects.

Download the release assets into ``dist/``, then verify each distribution using
the GitHub CLI:

.. code-block:: sh

   for artifact in dist/*.whl dist/*.tar.gz; do
       gh attestation verify "$artifact" --repo nijel/pylontech-tools
   done

The attached bundle can also be passed using ``--bundle dist/provenance.json``.
See `GitHub attestation verification
<https://cli.github.com/manual/gh_attestation_verify>`__ and `PyPI package
provenance <https://docs.pypi.org/attestations/consuming-attestations/>`__.

If validation or authentication fails before upload, fix the underlying issue
and rerun failed jobs where possible. A code or version change requires a new
commit/tag; do not move a published tag. If PyPI completed successfully and only
the GitHub release job failed, use **Re-run failed jobs** so PyPI is not uploaded
again. If a GitHub release already exists after a partial asset upload, inspect
its assets and complete it from the original workflow artifacts without replacing
existing files.

If PyPI accepted only some files, or publication status is ambiguous, inspect the
PyPI files and attestations before retrying. The workflow intentionally does not
skip existing files: an ordinary retry will fail on duplicates. Preserve the
original artifacts; resolve a partial publication manually or issue a new version
if necessary. Never rebuild and replace an already-published distribution.

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
