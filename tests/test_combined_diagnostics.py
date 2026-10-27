"""Combined diagnostics use only invented commands' replies and measurements."""

import json
from datetime import datetime, timezone

import pytest
from conftest import ScriptedSession
from test_read_commands import response
from test_reports import reply

from pylontech_tools import (
    BatteryClient,
    CommandCancelled,
    CommandTimeout,
    DeviceBusyError,
    DeviceNotPresentError,
    DiagnosticReadResult,
    DiagnosticsReport,
    ProtocolError,
    UnsupportedCommand,
)
from pylontech_tools.cli import main
from pylontech_tools.diagnostic_reads import format_diagnostics
from pylontech_tools.diagnostics import command_label

EXPECTED = (
    "stat",
    "time",
    "log",
    "config",
    "totalcoul",
    "tcycle",
    "emptyvolt",
    "setlowcfg",
    "ctrl",
    "prot",
    "euro",
    "trdagevolt",
    "soh",
)


@pytest.fixture(autouse=True)
def synthetic_time(monkeypatch):
    class Clock(datetime):
        @classmethod
        def now(cls, tz=None):
            return datetime(2000, 1, 2, 3, 4, 5, tzinfo=timezone.utc).astimezone(tz)

    monkeypatch.setattr("pylontech_tools.diagnostic_reads.datetime", Clock)


def exchanges(unavailable=()):
    return [
        (
            command.encode() + b"\n",
            response(command, "Unknown command" if command in unavailable else "Value : 123 mV"),
        )
        for command in EXPECTED
    ]


def test_all_reads_are_bare_ordered_and_preserve_raw_fields(replay):
    wire = exchanges()
    session, transport = replay(wire, chunk_size=1)
    client = BatteryClient(session=session)
    report = client.diagnostics()
    assert isinstance(report, DiagnosticsReport)
    assert report.timestamp == "2000-01-02T03:04:05+00:00" and report.complete
    assert transport.writes == [command for command, _ in wire]
    assert not transport.exchanges and client.last_failure is None
    for read, (command, text) in zip(report.reads, wire):
        assert isinstance(read, DiagnosticReadResult)
        assert read.command == command.decode().strip() and read.status == "complete"
        assert read.text == text and read.fields == {"Value": "123 mV"}
        assert read.error is None and command_label(read.command) == read.command


@pytest.mark.parametrize("unavailable", [("soh",), ("time", "euro", "soh"), EXPECTED])
def test_unsupported_reads_continue_without_retries_or_aliases(replay, unavailable):
    wire = exchanges(unavailable)
    session, transport = replay(wire)
    report = BatteryClient(session=session, read_retries=2).diagnostics()
    assert report.complete == (len(unavailable) < len(EXPECTED))
    assert len(report.reads) == len(EXPECTED)
    assert transport.writes == [command for command, _ in wire]
    for read in report.reads:
        if read.command in unavailable:
            assert read.status == "unavailable" and "Unknown command" in read.text
            assert read.error["type"] == "UnsupportedCommand"
            assert read.context["boundary"] == "prompt"


@pytest.mark.parametrize(
    ("body", "error"),
    [
        ("Target device is Busy", DeviceBusyError),
        ("Device 4 is not present", DeviceNotPresentError),
    ],
)
def test_target_errors_are_fatal_even_alongside_unsupported_text(replay, body, error):
    text = response("time", body + "\r\nInvalid command or fail to excute.")
    session, transport = replay([exchanges()[0], (b"time\n", text)])
    client = BatteryClient(session=session, read_retries=2)
    result = client.diagnostics()
    assert not result.complete and isinstance(client.last_failure, error)
    assert [r.status for r in result.reads] == ["complete", "failed"]
    assert result.reads[-1].text == text
    assert result.reads[-1].context["command"] == "time"
    assert transport.writes == [b"stat\n", b"time\n"]


@pytest.mark.parametrize("error_type", [ProtocolError, CommandTimeout, OSError, ValueError])
def test_read_failure_returns_partial_report_and_original_exception(error_type):
    error = (
        error_type("synthetic failure", response="partial response", context={"command": "time"})
        if issubclass(error_type, ProtocolError)
        else error_type("synthetic failure")
    )
    session = ScriptedSession([("stat", reply(response("stat"))), ("time", error)])
    client = BatteryClient(session=session)
    with client:
        report = client.diagnostics()
    assert not report.complete and client.last_failure is error
    assert [r.command for r in report.reads] == ["stat", "time"]
    assert report.reads[-1].status == "failed" and session.disconnected
    if isinstance(error, ProtocolError):
        assert report.reads[-1].text == "partial response"
        assert report.reads[-1].context == {"command": "time"}


def test_missing_prompt_is_not_treated_as_an_optional_rejection(replay):
    session, transport = replay(
        [(b"stat\n", "Unknown command without a final prompt")], timeout=0.005
    )
    client = BatteryClient(session=session)
    report = client.diagnostics()
    assert not report.complete and isinstance(client.last_failure, CommandTimeout)
    assert report.reads[0].status == "failed" and transport.writes == [b"stat\n"]


def test_read_recovery_repeats_only_the_failed_read_after_verified_prompt(replay):
    wire = [
        (b"stat\n", "unfinished response"),
        (b"\n", "\rpylon_debug>"),
        *exchanges(),
    ]
    session, transport = replay(wire, timeout=0.005)
    assert BatteryClient(session=session, read_retries=1).diagnostics().complete
    assert transport.writes == [command for command, _ in wire]


def test_local_only_rejection_sends_no_commands(replay):
    session, transport = replay([])
    with pytest.raises(ValueError, match="direct module connection"):
        BatteryClient(session=session, module=4).diagnostics()
    assert not transport.writes


@pytest.mark.parametrize("error_type", [KeyboardInterrupt, CommandCancelled])
def test_interruption_propagates_and_disconnects(error_type):
    session = ScriptedSession([("stat", error_type("synthetic interruption"))])
    with pytest.raises(error_type), BatteryClient(session=session) as client:
        client.diagnostics()
    assert session.disconnected and len(session.calls) == 1


def test_text_preserves_long_replies_and_uses_short_unavailable_notices():
    raw = response("stat", "Long field : " + "X" * 1200)
    report = DiagnosticsReport(
        "2000-01-01T00:00:00+00:00",
        True,
        [
            DiagnosticReadResult("stat", "complete", raw),
            DiagnosticReadResult("soh", "unavailable", "verbose unsupported usage"),
        ],
    )
    text = format_diagnostics(report)
    assert "[stat]" in text and raw in text
    assert "[soh]\nUnavailable:" in text and "verbose unsupported usage" not in text


@pytest.mark.parametrize("format", ["text", "json"])
@pytest.mark.parametrize("outcome", ["complete", "unavailable", "failed"])
def test_cli_outputs_full_report_and_exit_status(monkeypatch, capsys, tmp_path, format, outcome):
    session = ScriptedSession(
        [
            (
                c,
                UnsupportedCommand("unsupported", response="Unknown command")
                if outcome == "unavailable"
                else CommandTimeout("synthetic timeout", response="partial")
                if outcome == "failed"
                else reply(response(c, "00-01-02 03:04:05" if c == "time" else "Value : 123 mV")),
            )
            for c in EXPECTED
        ]
    )
    client = BatteryClient(session=session)
    monkeypatch.setattr("pylontech_tools.cli.BatteryClient", lambda *a, **k: client)
    path = tmp_path / f"diagnostics.{format}"
    assert main(
        ["diagnostics", "--port", "SYNTHETIC", "--format", format, "--output", str(path)]
    ) == (0 if outcome == "complete" else 1)
    text = path.read_text()
    if format == "json":
        data = json.loads(text)
        assert data["complete"] == (outcome == "complete")
        assert data["reads"][0]["command"] == "stat"
        if outcome == "complete":
            assert data["reads"][1]["fields"] == {}
    else:
        assert "[stat]" in text
        if outcome == "failed":
            assert "partial" in text
    assert session.disconnected and not capsys.readouterr().out


def test_cli_optional_soh_is_successful_and_defaults_to_text(monkeypatch, capsys):
    session = ScriptedSession(
        [
            (c, UnsupportedCommand("unsupported") if c == "soh" else reply(response(c)))
            for c in EXPECTED
        ]
    )
    monkeypatch.setattr(
        "pylontech_tools.cli.BatteryClient", lambda *a, **k: BatteryClient(session=session)
    )
    assert main(["diagnostics", "--port", "SYNTHETIC"]) == 0
    output = capsys.readouterr()
    assert "[soh]\nUnavailable:" in output.out and not output.err


def test_cli_existing_output_is_preserved(monkeypatch, tmp_path):
    session = ScriptedSession([])
    monkeypatch.setattr(
        "pylontech_tools.cli.BatteryClient", lambda *a, **k: BatteryClient(session=session)
    )
    path = tmp_path / "diagnostics.txt"
    path.write_text("existing report")
    assert main(["diagnostics", "--port", "SYNTHETIC", "--output", str(path)]) == 1
    assert path.read_text() == "existing report" and not session.calls and session.disconnected


@pytest.mark.parametrize(
    "extra", [["--module", "4"], ["clear"], ["--count", "8"], ["--format", "csv"]]
)
def test_cli_rejects_routing_and_arbitrary_operands(extra):
    with pytest.raises(SystemExit) as caught:
        main(["diagnostics", "--port", "SYNTHETIC", *extra])
    assert caught.value.code == 2


def test_cli_interruption_exits_130_and_disconnects(monkeypatch):
    session = ScriptedSession([("stat", CommandCancelled("synthetic interruption"))])
    monkeypatch.setattr(
        "pylontech_tools.cli.BatteryClient", lambda *a, **k: BatteryClient(session=session)
    )
    assert main(["diagnostics", "--port", "SYNTHETIC"]) == 130
    assert session.disconnected
