# BatteryView for Python

A portable Pylontech console library and command-line tool for Windows, Linux,
and macOS. Collect support reports, export History and Event transcripts, and
monitor battery modules using JSON, JSON Lines, or CSV.

Requires Python 3.11 or newer:

```sh
python -m pip install .
batteryview ports
batteryview info --port /dev/ttyUSB0
batteryview collect --port /dev/ttyUSB0 --output support/
```

Use the battery console connection and an appropriate serial cable. See the
[installation guide](docs/software/installation.rst) for connection options.

## Documentation

- [Python library and CLI](docs/software/index.rst): installation, reports,
  support collection, monitoring, SOC reset, API, and troubleshooting.
- [Protocol reference](docs/protocol/index.rst): console commands, parameters,
  firmware behavior, BatteryView workflows, evidence, and remaining unknowns.
- [Development and documentation builds](docs/software/development.rst).

The protocol was recovered from BatteryView 3.0.28 and firmware analysis.
Firmware variants and acceptance of support reports require hardware validation.
Distributed tests use synthetic data; private recordings and vendor firmware
are excluded from package builds.
