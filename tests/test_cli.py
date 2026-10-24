import csv
import io
import json
import logging
from pathlib import Path

import pytest

from batteryview import BatteryViewError, DeviceInfo, ReportResult, Snapshot
from batteryview.cli import main
from batteryview.models import CellReading, ModuleReading


class FakeClient:
    options = None
    failure = None

    def __init__(self, port, **kwargs):
        type(self).options = {"port": port, **kwargs}

    def __enter__(self):
        if self.failure:
            raise self.failure
        return self

    def __exit__(self, *args):
        pass

    def info(self):
        return DeviceInfo(
            name="SYNTHETIC_MODEL", barcode="TEST", fields={"Device name": "SYNTHETIC_MODEL"}
        )

    def snapshot(self):
        return Snapshot(
            "2000-01-01T00:00:00+00:00",
            [
                ModuleReading(
                    address=3, voltage_v=50, cells=[CellReading(index=0, voltage_v=3.101)]
                ),
            ],
        )

    def watch(self, *, interval, count):
        assert interval == 0.1
        yield from [self.snapshot()] * count

    def export_history(self, output, *, progress):
        progress("history", 15, 15)
        return ReportResult(output or Path("default.txt.txt"), "history", 15, 5)

    export_events = export_history
    reset_soc = export_history


@pytest.fixture(autouse=True)
def fake_client(monkeypatch):
    FakeClient.failure = None
    monkeypatch.setattr("batteryview.cli.BatteryClient", FakeClient)


def test_ports_does_not_connect(monkeypatch, capsys):
    monkeypatch.setattr("batteryview.cli.list_ports", lambda: [{"port": "COM3"}])
    assert main(["ports"]) == 0
    assert json.loads(capsys.readouterr().out) == [{"port": "COM3"}]


def test_info_arguments_and_json(capsys):
    assert main(["info", "--port", "COM3", "--module", "3", "--no-shift"]) == 0
    assert json.loads(capsys.readouterr().out)["name"] == "SYNTHETIC_MODEL"
    assert FakeClient.options == {
        "port": "COM3",
        "module": 3,
        "baudrate": 115200,
        "timeout": 5,
        "shift": False,
    }


def test_watch_streams_json_lines(capsys):
    assert main(["watch", "--port", "COM3", "--count", "2", "--interval", "0.1"]) == 0
    rows = [json.loads(line) for line in capsys.readouterr().out.splitlines()]
    assert len(rows) == 2
    assert rows[0]["modules"][0]["voltage_v"] == 50


def test_csv_has_module_cell_rows_and_empty_missing_values(tmp_path, capsys):
    path = tmp_path / "readings.csv"
    assert main(["snapshot", "--port", "COM3", "--format", "csv", "--output", str(path)]) == 0
    rows = list(csv.DictReader(io.StringIO(path.read_text())))
    assert [row["type"] for row in rows] == ["module", "cell"]
    assert rows[0]["current_a"] == ""
    assert rows[1]["voltage_v"] == "3.101"
    assert capsys.readouterr().out == ""


@pytest.mark.parametrize("command", ["history", "event", "reset-soc"])
def test_report_progress_goes_to_stderr(command, capsys):
    assert main([command, "--port", "COM3"]) == 0
    out, err = capsys.readouterr()
    assert json.loads(out)["complete"]
    assert "15/15" in err


def test_existing_output_is_not_overwritten(tmp_path, capsys):
    path = tmp_path / "info.json"
    path.write_text("original")
    assert main(["info", "--port", "COM3", "--output", str(path)]) == 1
    assert path.read_text() == "original"
    assert capsys.readouterr().out == ""


def test_errors_are_nonzero_and_stderr_only(capsys):
    FakeClient.failure = BatteryViewError("disconnected")
    assert main(["snapshot", "--port", "COM3"]) == 1
    out, err = capsys.readouterr()
    assert not out and "disconnected" in err


def test_interruption_exit_code(capsys):
    FakeClient.failure = KeyboardInterrupt()
    assert main(["watch", "--port", "COM3"]) == 130
    assert "Interrupted" in capsys.readouterr().err


@pytest.mark.parametrize(
    "args",
    [
        ["watch", "--port", "COM3", "--interval", "0"],
        ["watch", "--port", "COM3", "--interval", "nan"],
        ["watch", "--port", "COM3", "--count", "0"],
        ["info", "--port", "COM3", "--module", "17"],
        ["info"],
    ],
)
def test_invalid_cli_arguments(args):
    with pytest.raises(SystemExit) as exc:
        main(args)
    assert exc.value.code == 2


@pytest.mark.parametrize("flag", ["--debug", "--trace-serial"])
@pytest.mark.parametrize("before", [True, False])
def test_diagnostic_flags_before_or_after_command(flag, before, capsys):
    args = [flag, "info", "--port", "COM3"] if before else ["info", "--port", "COM3", flag]
    assert main(args) == 0
    out, err = capsys.readouterr()
    assert json.loads(out)["name"] == "SYNTHETIC_MODEL"
    assert "Diagnostics enabled" in err
    assert f"serial tracing={flag == '--trace-serial'}" in err


@pytest.mark.parametrize("before", [True, False])
def test_log_file_implies_debug_and_leaves_stderr_clean(tmp_path, before, capsys):
    log_file = tmp_path / "debug.log"
    flags = ["--log-file", str(log_file)]
    args = flags + ["info", "--port", "COM3"] if before else ["info", "--port", "COM3"] + flags
    assert main(args) == 0
    out, err = capsys.readouterr()
    assert json.loads(out)["name"] == "SYNTHETIC_MODEL"
    assert not err
    assert "Diagnostics enabled" in log_file.read_text(encoding="utf-8")


def test_mixed_global_and_command_logging_options(tmp_path, capsys):
    log_file = tmp_path / "debug.log"
    assert main(["--trace-serial", "info", "--port", "COM3", "--log-file", str(log_file)]) == 0
    assert "serial tracing=True" in log_file.read_text()
    assert not capsys.readouterr().err


def test_logging_file_is_not_overwritten(tmp_path, capsys):
    log_file = tmp_path / "debug.log"
    log_file.write_text("original")
    assert main(["--log-file", str(log_file), "ports"]) == 1
    assert log_file.read_text() == "original"
    out, err = capsys.readouterr()
    assert not out and "Cannot configure diagnostic logging" in err


def test_failure_diagnostics_stay_on_stderr(capsys):
    FakeClient.failure = BatteryViewError("disconnected")
    assert main(["--debug", "snapshot", "--port", "COM3"]) == 1
    out, err = capsys.readouterr()
    assert not out
    assert "Operation failed command=snapshot error=BatteryViewError" in err


def test_default_cli_does_not_configure_root_logger(capsys):
    root = logging.getLogger()
    previous = root.level, root.handlers[:]
    assert main(["info", "--port", "COM3"]) == 0
    assert (root.level, root.handlers) == previous
    assert not capsys.readouterr().err
