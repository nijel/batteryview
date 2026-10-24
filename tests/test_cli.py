import csv
import io
import json
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
