Development and validation
==========================

.. _README-development-and-validation:

Development and validation
--------------------------

For normal use, :doc:`run the released CLI with uvx or install it with uv <installation>`.
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

Pushing a version tag runs ``.github/workflows/release.yml``. GitHub Actions runs
the tests and documentation checks, builds and validates the distributions,
generates provenance, publishes to PyPI, and creates a GitHub release using the
matching changelog entry. The wheel, source distribution, and provenance bundle
are attached to the release. Workflow artifacts are retained for 30 days.

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

1. Move the relevant entries from ``Unreleased`` in
   `CHANGELOG.md <https://github.com/nijel/pylontech-tools/blob/main/CHANGELOG.md>`__
   into a section named ``## [VERSION] - YYYY-MM-DD``. Use the release date,
   retain an empty ``## [Unreleased]`` section, and use inline Markdown links
   so the release notes remain self-contained.
2. Set the same version in ``pyproject.toml`` and update ``uv.lock`` with
   ``uv lock``. The tag must be that exact version prefixed with ``v``.
3. Commit and push the changes, then create and push the tag. For example,
   after preparing version ``0.2.0``:

   .. code-block:: sh

      git add CHANGELOG.md pyproject.toml uv.lock
      git commit -m "chore: prepare 0.2.0 release" -m "Finalize release notes and package version."
      git push origin HEAD
      git tag -a v0.2.0 -m "Release 0.2.0"
      git push origin v0.2.0

4. Follow the Release workflow in GitHub Actions and confirm that both PyPI
   publication and the GitHub release succeed.

Actions rejects missing, duplicate, empty, or incorrectly dated changelog entries
before publishing. Development and prerelease versions such as ``0.2.0rc1``
create GitHub prereleases. No local build or manual upload is required.

.. _verify-provenance-and-recover-failures:

Recover failures
~~~~~~~~~~~~~~~~

If validation or authentication fails before upload, fix the underlying issue
and rerun failed jobs where possible. A code or version change requires a new
commit/tag; do not move a published tag.

If PyPI succeeded and only the GitHub release job failed, use **Re-run failed
jobs** so PyPI is not uploaded again. If asset uploads left a draft release,
complete it from the original workflow artifacts before publishing. Published
immutable release assets cannot be replaced.

If PyPI accepted only some files, or publication status is ambiguous, inspect its
files and attestations before retrying. The workflow does not skip existing
files, so duplicates fail. Preserve the original artifacts and resolve the
partial publication manually or issue a new version. Never rebuild and replace
an already-published distribution.

Verifying downloaded artifacts
------------------------------

Release distributions have GitHub build-provenance attestations and PyPI publish
attestations. To check the origin and digests of downloaded GitHub release assets,
save them in ``dist/`` and verify each distribution with the GitHub CLI:

.. code-block:: sh

   for artifact in dist/*.whl dist/*.tar.gz; do
       gh attestation verify "$artifact" --repo nijel/pylontech-tools
   done

The attached bundle can also be passed using ``--bundle dist/provenance.json``.
See `GitHub attestation verification
<https://cli.github.com/manual/gh_attestation_verify>`__ and `PyPI package
provenance <https://docs.pypi.org/attestations/consuming-attestations/>`__.

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
