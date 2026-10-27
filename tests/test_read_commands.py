"""Synthetic diagnostic replies; no device recordings or identities are used."""

import json
from dataclasses import FrozenInstanceError

import pytest
from conftest import ScriptedSession
from test_monitoring import GETPWR, PWR
from test_reports import INFO, reply, stat

from pylontech_tools import (
    BatteryClient,
    ConsoleReadResult,
    DeviceBusyError,
    DeviceNotPresentError,
    ProtocolError,
    UnsupportedCommand,
)
from pylontech_tools.cli import main
from pylontech_tools.diagnostics import command_label
from pylontech_tools.protocol import CONTINUATION


def response(command, body="Future field : synthetic\r\nCounter : 12"):
    return f"{command}\r\n@\r\n{body}\r\nCommand completed successfully\r\n$$\r\npylon_debug>"


@pytest.mark.parametrize(
    "method,args,module,command",
    [
        ("statistics", (), None, "stat"),
        ("statistics", (), 4, "stat 4"),
        ("configuration", (), None, "config"),
        ("configuration", (), 4, "config 4"),
        ("read_clock", (), None, "time"),
        ("diagnostic_log", (), None, "log"),
        ("diagnostic_log", (1,), None, "log 1"),
        ("diagnostic_log", (32,), None, "log 32"),
    ],
)
def test_diagnostic_commands_preserve_response_and_fields(replay, method, args, module, command):
    text = response(command)
    session, transport = replay([(command.encode() + b"\n", text)], chunk_size=1)
    result = getattr(BatteryClient(session=session, module=module), method)(*args)
    assert isinstance(result, ConsoleReadResult)
    assert result.to_console_dict() == {
        "command": command,
        "text": text,
        "fields": {"Future field": "synthetic", "Counter": "12"},
    }
    assert result.values["Counter"] == 12
    with pytest.raises(FrozenInstanceError):
        result.command = "save"
    assert not transport.exchanges
    assert command_label(command) == command


def test_unstructured_clock_and_empty_log_remain_raw(replay):
    clock = response("time", "00-01-02 03:04:05")
    log = response("log", "")
    session, _ = replay([(b"time\n", clock), (b"log\n", log)])
    client = BatteryClient(session=session)
    clock_result = client.read_clock()
    assert clock_result.to_console_dict() == ConsoleReadResult("time", clock, {}).to_console_dict()
    assert clock_result.timestamp.year == 2000
    assert (
        client.diagnostic_log().to_console_dict()
        == ConsoleReadResult("log", log, {}).to_console_dict()
    )


@pytest.mark.parametrize("count", [True, False, 0, 33, -1, 1.0, "2"])
def test_invalid_log_count_sends_nothing(replay, count):
    session, transport = replay([])
    with pytest.raises(ValueError, match="Log count"):
        BatteryClient(session=session).diagnostic_log(count)
    assert not transport.writes


@pytest.mark.parametrize("method", ["read_clock", "diagnostic_log"])
def test_local_reads_reject_module_before_sending(replay, method):
    session, transport = replay([])
    with pytest.raises(ValueError, match="direct module connection"):
        getattr(BatteryClient(session=session, module=4), method)()
    assert not transport.writes


@pytest.mark.parametrize("module", [True, False, 1.0, "2", 0, 17])
def test_module_validation_is_strict(replay, module):
    session, transport = replay([])
    with pytest.raises(ValueError, match="Module"):
        BatteryClient(session=session, module=module)
    assert not transport.writes


@pytest.mark.parametrize(
    "body,error",
    [
        ("Target device is Busy", DeviceBusyError),
        ("Target device is not present", DeviceNotPresentError),
        ("Device 4 is not present", DeviceNotPresentError),
    ],
)
@pytest.mark.parametrize("allow_unsupported", [True, False])
def test_target_errors_override_success_footer_and_rejection(
    replay, body, error, allow_unsupported
):
    text = response("stat 4", body + "\r\nInvalid command or fail to excute.")
    session, transport = replay([(b"stat 4\n", text)], chunk_size=1)
    with pytest.raises(error) as caught:
        session.exchange("stat 4", allow_unsupported=allow_unsupported)
    assert caught.value.response == text
    assert caught.value.context["command"] == "stat 4"
    assert caught.value.context["boundary"] == "prompt"
    assert session.synchronized
    assert transport.writes == [b"stat 4\n"]


@pytest.mark.parametrize(
    "message,error",
    [
        ("Target device is Busy", DeviceBusyError),
        ("Target device is not present", DeviceNotPresentError),
    ],
)
def test_target_errors_are_not_retried(replay, message, error):
    session, transport = replay([(b"stat\n", response("stat", message))])
    with pytest.raises(error):
        BatteryClient(session=session, read_retries=2).statistics()
    assert transport.writes == [b"stat\n"]


def test_read_timeout_uses_existing_recovery(replay):
    text = response("stat")
    session, transport = replay(
        [
            (b"stat\n", "unfinished"),
            (b"\n", "\rpylon_debug>"),
            (b"stat\n", text),
        ],
        timeout=0.005,
    )
    result = BatteryClient(session=session, read_retries=1).statistics()
    assert result.text == text
    assert transport.writes == [b"stat\n", b"\n", b"stat\n"]


def test_target_phrase_inside_a_field_is_not_an_error(replay):
    text = response("config", "Label : Target device is Busy")
    session, _ = replay([(b"config\n", text)])
    assert BatteryClient(session=session).configuration().fields == {
        "Label": "Target device is Busy"
    }


def test_unsupported_read_is_explicit(replay):
    session, transport = replay([(b"time\n", response("time", "Unknown command"))])
    with pytest.raises(UnsupportedCommand):
        BatteryClient(session=session, read_retries=2).read_clock()
    assert transport.writes == [b"time\n"]


@pytest.mark.parametrize(
    "message,error",
    [
        ("Device 4 is not present", DeviceNotPresentError),
        ("Target device is Busy", DeviceBusyError),
    ],
)
def test_optional_pwrsys_target_failure_is_not_silently_omitted(replay, message, error):
    session, transport = replay(
        [
            (b"getpwr 4\n", GETPWR),
            (b"pwr 4\n", PWR.replace("1 50000", "4 50000").split("2 50000")[0] + "\rpylon_debug>"),
            (b"pwrsys 4\n", response("pwrsys 4", message)),
        ]
    )
    with pytest.raises(error):
        BatteryClient(session=session, module=4, profile="generic").snapshot()
    assert transport.writes[-1] == b"pwrsys 4\n"


def test_absent_detail_never_queries_pwrsys(replay):
    session, transport = replay([(b"getpwr 4\n", response("getpwr 4", "Device 4 is not present"))])
    with pytest.raises(DeviceNotPresentError):
        BatteryClient(session=session, module=4, profile="generic").snapshot()
    assert transport.writes == [b"getpwr 4\n"]


def test_invalid_discovered_address_never_queries_pwrsys():
    session = ScriptedSession(
        [
            ("pwr", reply("Power Volt Curr Tempr Base.St\n99 50000 0 20000 Idle")),
            ("getpwr 99", reply(GETPWR)),
        ]
    )
    with pytest.raises(ProtocolError, match="invalid module address"):
        BatteryClient(session=session, profile="generic", monitoring_mode="parallel").snapshot()
    assert [command for command, _ in session.calls] == ["pwr", "getpwr 99"]


@pytest.mark.parametrize("stage", ["latest", "page", "detail"])
def test_corrupt_record_retains_partial_report(tmp_path, stage):
    corrupt = "\rError!\r\npylon_debug>"
    exchanges = [("info", reply(INFO)), ("stat", stat(1))]
    if stage == "latest":
        exchanges += [("data history", reply("Item Index : 0" + corrupt))]
    else:
        exchanges += [("data history", reply("Item Index : 0"))]
        if stage == "page":
            exchanges += [("datalist history dtls 0", reply("0 00-01-01 00:00:00 50000" + corrupt))]
        else:
            exchanges += [
                ("datalist history dtls 0", UnsupportedCommand("unsupported", response="rejected")),
                (
                    "datalist history 0",
                    reply(f"0 00-01-01 00:00:00 50000\r{CONTINUATION}", page=True),
                ),
                ("", reply()),
                ("data history 0", reply("Item Index : 0" + corrupt)),
            ]
    session = ScriptedSession(exchanges)
    path = tmp_path / "report.txt"
    with pytest.raises(ProtocolError, match="corrupt record") as caught:
        BatteryClient(session=session).export_history(path)
    assert corrupt in caught.value.response
    assert corrupt.encode("utf-16-le") in path.read_bytes()
    assert not session.exchanges


@pytest.mark.parametrize("command", ["stat", "time", "log", "config"])
@pytest.mark.parametrize("fmt", ["text", "json"])
def test_cli_diagnostic_output(monkeypatch, replay, capsys, command, fmt):
    text = response(command)
    session, transport = replay([(command.encode() + b"\n", text), (b"cmdquit\n", "cmdquit")])
    monkeypatch.setattr(
        "pylontech_tools.cli.BatteryClient", lambda *a, **kw: BatteryClient(session=session, **kw)
    )
    assert main([command, "--port", "SYNTHETIC", "--format", fmt]) == 0
    output = capsys.readouterr()
    assert not output.err
    if fmt == "text":
        assert output.out == text
    else:
        assert json.loads(output.out) == {
            "command": command,
            "text": text,
            "fields": {"Future field": "synthetic", "Counter": "12"},
        }
    assert not transport.exchanges


def test_cli_default_text_and_exclusive_file(monkeypatch, replay, tmp_path):
    text = response("log 2")
    session, transport = replay([(b"log 2\n", text), (b"cmdquit\n", "cmdquit")])
    monkeypatch.setattr(
        "pylontech_tools.cli.BatteryClient", lambda *a, **kw: BatteryClient(session=session, **kw)
    )
    path = tmp_path / "log.txt"
    assert main(["log", "--port", "SYNTHETIC", "--count", "2", "--output", str(path)]) == 0
    assert path.read_bytes() == text.encode()
    assert not transport.exchanges
    session2, transport2 = replay([(b"cmdquit\n", "cmdquit")])
    monkeypatch.setattr(
        "pylontech_tools.cli.BatteryClient", lambda *a, **kw: BatteryClient(session=session2, **kw)
    )
    assert main(["log", "--port", "SYNTHETIC", "--output", str(path)]) == 1
    assert path.read_bytes() == text.encode()
    assert transport2.writes == [b"cmdquit\n"]


@pytest.mark.parametrize(
    "args",
    [
        ["log", "--count", "0"],
        ["log", "--count", "33"],
        ["time", "--module", "4"],
        ["log", "--module", "4"],
        ["config", "--format", "csv"],
        ["time", "00", "1", "1", "0", "0", "0"],
        ["config", "pov", "60000"],
    ],
)
def test_cli_rejects_setter_operands_and_invalid_options_before_connect(monkeypatch, args):
    def unexpected(*a, **kw):
        pytest.fail("Invalid arguments must not open a connection")

    monkeypatch.setattr("pylontech_tools.cli.BatteryClient", unexpected)
    with pytest.raises(SystemExit):
        main([*args, "--port", "SYNTHETIC"])


@pytest.mark.parametrize("command", ["stat", "config"])
def test_cli_routes_addressed_diagnostic(monkeypatch, replay, capsys, command):
    text = response(f"{command} 4")
    session, transport = replay([(f"{command} 4\n".encode(), text), (b"cmdquit\n", "cmdquit")])
    monkeypatch.setattr(
        "pylontech_tools.cli.BatteryClient", lambda *a, **kw: BatteryClient(session=session, **kw)
    )
    assert main([command, "--port", "SYNTHETIC", "--module", "4"]) == 0
    assert capsys.readouterr().out == text
    assert not transport.exchanges
