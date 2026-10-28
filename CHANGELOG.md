# Changelog

Notable changes to Pylontech Tools are recorded here. Unreleased changes are
grouped below; dated version sections provide the GitHub release notes.

## [0.2.0] - 2026-10-28

### Added

- Expose verified read-only protocol commands as individual Python methods with
  typed results for measurements, settings, accounting, records, storage, registers,
  and passive checks. Preserve raw evidence and existing CLI/doctor JSON schemas.
- Gather capacity bookkeeping, control/protection status, usage metrics, voltage
  extrema, and existing diagnostic reads with one read-only `diagnostics` command.
  Unsupported commands, including unavailable `soh`, are skipped; text and JSON
  output retain successful evidence and partial acquisition failures.
- Maintain a curated changelog and use each version's entry for GitHub release notes.
- Automate dependency updates with Renovate.

### Changed

- Give all files from a support collection a shared barcode, UTC timestamp, and UUID prefix.
  Repeated collections of the same battery within one second no longer collide.
- Generate History and Event filenames with a single `.txt` extension. Explicit output
  paths are unchanged, and doctor still accepts older collections and `.txt.txt` reports.
- Recommend `uvx` for occasional CLI use and `uv tool install` for regular use, with
  PyPI installation and upgrade instructions for library users.
- Build release distributions and documentation in CI with Python 3.15.
- Simplify maintainer release instructions around GitHub Actions, with separate
  guidance for verifying downloaded artifacts.

## [0.1.0] - 2026-10-26

### Added

- Introduce the `pylontech-tools` Python library and `pylontech-console` CLI for
  Windows, Linux, and macOS with Python 3.11 or newer.
- Read battery identity, module and cell measurements, statistics, clock,
  diagnostic logs, and configuration through the serial console.
- Monitor measurements as JSON, JSON Lines, or CSV, and export BatteryView-compatible
  UTF-16 History and Event reports with pagination and per-record fallbacks.
- Collect identity, History, Event, and snapshot files into a shared support directory,
  preserving per-run manifests, partial reports, and earlier collections.
- Analyze battery health online or from saved logs with doctor, combining evidence by
  verified identity and reporting cell imbalance, recorded alarms, system faults,
  and suspected balancing difficulty in text or JSON.
- Decode verified firmware system-fault conditions while preserving raw masks and
  unknown bits; distinguish operational flags from fault conditions.
- Provide the BatteryView-compatible SOC reset workflow with saved recovery information,
  barcode validation and restoration, and explicit failure handling.
- Include connection diagnostics and opt-in raw serial tracing, with debug-session
  detection, matching RTS/DTR defaults, and the vendor disconnect sequence.
- Document the Python API and CLI with Sphinx and Read the Docs, alongside a
  communication manual covering firmware commands, parameters, persistence,
  firmware-update transfers, fault meanings, and SOH/cycle accounting.
- Publish tagged releases to PyPI through trusted publishing with attestations,
  generate build provenance, and attach distributions to GitHub releases.
- Test protocol behavior using synthetic replay fixtures across supported platforms.

### Fixed

- Support labeled power summaries and absent module slots when reading snapshots.
- Avoid redundant serial-port reopen operations at an unchanged baud rate.
- Retrieve complete event/history records across supported firmware command formats
  and reject incomplete exports while retaining their original partial transcripts.
- Keep doctor text summaries readable by grouping measurements, wrapping actionable
  findings, and leaving routine supporting details available in JSON.
