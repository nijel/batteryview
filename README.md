# Pylontech Tools

A portable Pylontech console library and command-line tool for Windows, Linux,
and macOS. Collect support reports, export History and Event transcripts, and
monitor battery modules using JSON, JSON Lines, or CSV.

The distribution is `pylontech-tools`, the Python package is `pylontech_tools`,
and the CLI is `pylontech-console`.

Requires Python 3.11 or newer. With
[uv installed](https://docs.astral.sh/uv/getting-started/installation/), run the
CLI directly from [PyPI](https://pypi.org/project/pylontech-tools/):

```sh
uvx --from pylontech-tools pylontech-console ports
uvx --from pylontech-tools pylontech-console info --port /dev/ttyUSB0
```

For regular use, install the CLI into a dedicated environment managed by uv:

```sh
uv tool install pylontech-tools
pylontech-console collect --port /dev/ttyUSB0 --output support/
pylontech-console doctor support/
```

Use the battery console connection and an appropriate serial cable. See the
[installation guide](https://pylontech-tools.readthedocs.io/en/latest/software/installation.html) for connection options.

## Documentation

Use [battery doctor](https://pylontech-tools.readthedocs.io/en/latest/software/doctor.html)
for read-only health screening online or from saved logs.

Browse the [online documentation](https://pylontech-tools.readthedocs.io/en/latest/).

- [Python library and CLI](https://pylontech-tools.readthedocs.io/en/latest/software/index.html): installation, reports,
  support collection, monitoring, SOC reset, API, and troubleshooting.
- [Communication manual](https://pylontech-tools.readthedocs.io/en/latest/protocol/index.html): console commands, parameters,
  firmware behavior, BatteryView workflows, evidence, and remaining unknowns.
- [Development and documentation builds](https://pylontech-tools.readthedocs.io/en/latest/software/development.html).

The protocol was recovered from BatteryView 3.0.28 and firmware analysis.
Firmware variants and acceptance of support reports require hardware validation.
Distributed tests use synthetic data; private recordings and vendor firmware
are excluded from package builds.
