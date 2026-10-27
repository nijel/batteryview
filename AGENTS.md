# Repository Guidelines

## Project Structure & Module Organization

`src/pylontech_tools/` contains the client, transport, framing, parsers, CLI,
reports, and collection workflows.
`tests/` contains pytest tests and synthetic replay helpers; its `README.md`
defines the fixture privacy policy. `docs/software/` documents the library and
CLI; `docs/protocol/` contains the communication manual and reverse-engineering
evidence. `scripts/` contains firmware metadata extractors. CI lives in
`.github/workflows/`.

## Build, Test, and Development Commands

- `uv sync --frozen`: install the project and default `dev` tools from the lockfile.
- `uv run --frozen pytest -q`: run the synthetic test suite.
- `uv run --frozen ruff check .`: check lint and import ordering.
- `uv run --frozen ruff format --check .`: verify formatting; omit `--check` to format.
- `uv run --frozen pylontech-console --help`: inspect CLI commands without hardware.
- `uv build`: build wheel and source distributions using Hatchling.
- `uv run --group docs --frozen sphinx-build -n -W --keep-going -b html docs docs/_build/html`:
  build documentation with warnings treated as errors.

The library supports Python 3.11+; documentation tooling requires Python 3.13+.
Keep direct documentation dependencies exactly pinned and update `uv.lock` when
changing dependencies.

## Coding Style & Naming Conventions

Use four-space indentation, type annotations for public interfaces, `snake_case`
for functions/modules, and `PascalCase` for classes. Ruff targets Python 3.11 and
100-character lines. Preserve console text and explicit wire terminators;
platform newline conversion must not alter protocol or transcript bytes.

## Testing Guidelines

Name tests `test_*.py` and functions `test_*`. Add regression tests for changed
command sequences, framing, parsing, and failure behavior. Use replay transports
instead of hardware in ordinary tests. CI covers Windows, macOS, and Linux on Python 3.11 and 3.14.

Use invented identities, timestamps, counters, and measurements. Never commit
private logs, vendor firmware, executables, or editor recovery files. Private
replays are explicitly opt-in via `--private-logs=Logs`. Never automatically retry
mutating commands or infer hardware success from a success footer alone.

## Commit & Pull Request Guidelines

Keep commits focused on one change. Use Conventional Commits:
`<type>(<optional scope>): <description>`, for example
`fix(protocol): retain partial responses`. Include a concise body explaining
motivation; mark breaking changes explicitly. Add `Fixes #123` when resolving an
issue. PR descriptions should explain the problem, resulting behavior, validation,
and firmware-specific limitations.

Update `CHANGELOG.md` under `Unreleased` for user-visible or compatibility changes
and significant documentation/development changes. Use concise entries under the
applicable Added, Changed, Fixed, Removed, or Security heading; routine internal
cleanup needs no entry. Before releasing, move entries into a dated version
section and retain an empty Unreleased section. Never include private log data.

## Documentation Guidelines

Document user-visible changes alongside code. Use direct instructional prose,
short paragraphs, sentence-case headings, and semantic Sphinx `:doc:`/`:ref:`
links. Extend existing sections where practical. Preserve protocol evidence,
uncertainty, source hashes, and existing anchors.
