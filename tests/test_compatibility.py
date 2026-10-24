"""Constructed protocol scenarios; no captured identifiers or telemetry."""

import csv
import io
import json

import pytest
from conftest import ScriptedSession
from test_monitoring import GETPWR, PWR
from test_reports import INFO, reply, stat

from batteryview import (
    BatteryClient,
    CommandTimeout,
    ConnectionError,
    ProtocolError,
    ResetRecoveryError,
    UnsupportedCommand,
)
from batteryview.cli import CSV_FIELDS, _write_snapshot, main
from batteryview.diagnostics import failure_diagnostic
from batteryview.parsers import parse_getpwr
from batteryview.profiles import PROFILES, MonitoringProfile, monitoring_profile
from batteryview.protocol import Response


def rows(indices):
    return "\r\n".join(f"{i} 00-01-01 00:00:00 50000 -2000 20000" for i in indices)


def report_start(kind, count, *, stat_count=None):
    return [
        ("info", reply(INFO)),
        (
            "stat",
            stat(
                count if stat_count is None else stat_count,
                count if stat_count is None else stat_count,
            ),
        ),
        (f"data {kind}", reply(f"Item Index : {count - 1}")),
    ]


@pytest.mark.parametrize("kind", ["history", "event"])
@pytest.mark.parametrize("count", [1, 15, 16, 31])
def test_plain_fallback_collects_every_record_and_stops_at_count(tmp_path, kind, count):
    rejected = "Unknown command\r\npylon_debug>"
    exchanges = report_start(kind, count)
    exchanges.append((f"datalist {kind} dtls 0", UnsupportedCommand("rejected", response=rejected)))
    for offset in range(0, count, 15):
        indices = range(offset, min(offset + 15, count))
        exchanges.extend(
            [(f"datalist {kind} {offset}", reply(rows(indices), page=True)), ("", reply())]
        )
        exchanges.extend(
            (f"data {kind} {i}", reply(f"Item Index : {i}\r\nVoltage : 50000 mV")) for i in indices
        )
    session = ScriptedSession(exchanges)
    progress = []
    result = BatteryClient(session=session)._export(
        kind, tmp_path / "report.txt", progress=lambda *p: progress.append(p)
    )
    assert result.complete and result.records == count
    assert progress[-1] == (kind, count, count)
    assert len([c for c, _ in session.calls if c.startswith(f"data {kind} ")]) == count
    assert result.path.read_bytes().decode("utf-16").count(rejected) == 1
    assert not session.exchanges


@pytest.mark.parametrize("kind", ["history", "event"])
@pytest.mark.parametrize("counter", [0, 9])
def test_latest_index_overrides_stat_counter(tmp_path, kind, counter, caplog):
    session = ScriptedSession(
        report_start(kind, 1, stat_count=counter)
        + [(f"datalist {kind} dtls 0", reply(rows([0]))), ("", reply())]
    )
    with caplog.at_level("DEBUG", logger="batteryview.client"):
        result = BatteryClient(session=session)._export(
            kind, tmp_path / "report.txt", progress=None
        )
    assert result.records == 1 and "count disagreement" in caplog.text


@pytest.mark.parametrize("indices", [[0, 2], [0, 0], [1, 2], [], [0, 1, 2, 3]])
def test_detailed_export_rejects_missing_repeated_or_wrong_indices(tmp_path, indices):
    session = ScriptedSession(
        report_start("event", 3) + [("datalist event dtls 0", reply(rows(indices))), ("", reply())]
    )
    path = tmp_path / "partial.txt"
    with pytest.raises(ProtocolError, match="report incomplete") as error:
        BatteryClient(session=session).export_events(path)
    assert path.is_file()
    assert error.value.context["command"] == "datalist event dtls 0"


def test_detailed_page_may_overlap_next_page_by_one_record(tmp_path):
    session = ScriptedSession(
        report_start("history", 17)
        + [
            ("datalist history dtls 0", reply(rows(range(16)))),
            ("", reply()),
            ("datalist history dtls 15", reply(rows([15, 16]))),
            ("", reply()),
        ]
    )
    assert BatteryClient(session=session).export_history(tmp_path / "report.txt").records == 17


def test_latest_record_can_supply_count_when_stat_is_malformed(tmp_path):
    session = ScriptedSession(
        [
            ("info", reply(INFO)),
            ("stat", reply("HisData Items : ???")),
            ("data history", reply("Rec Item Index : 0")),
            ("datalist history dtls 0", reply(rows([0]))),
            ("", reply()),
        ]
    )
    assert BatteryClient(session=session).export_history(tmp_path / "report.txt").records == 1


def test_wrong_individual_record_is_not_complete(tmp_path):
    session = ScriptedSession(
        report_start("event", 1)
        + [
            ("datalist event dtls 0", UnsupportedCommand("no")),
            ("datalist event 0", reply(rows([0]))),
            ("", reply()),
            ("data event 0", reply("Item Index : 9")),
        ]
    )
    with pytest.raises(ProtocolError, match="record index"):
        BatteryClient(session=session).export_events(tmp_path / "partial.txt")


@pytest.mark.parametrize("operation", ["export_events", "export_history", "reset_soc"])
def test_addressed_reports_and_reset_fail_before_any_io(tmp_path, operation):
    session = ScriptedSession([])
    output = tmp_path / "must-not-exist.txt"
    with pytest.raises(ValueError, match="direct module connection"):
        getattr(BatteryClient(session=session, module=4), operation)(output)
    assert not output.exists() and not session.calls


def test_selected_identity_uses_explicit_address_without_login():
    session = ScriptedSession([("info 4", reply(INFO))])
    assert BatteryClient(session=session, module=4).info().name == "SYNTHETIC_MODEL"
    assert [c for c, _ in session.calls] == ["info 4"]


@pytest.mark.parametrize("mode", ["single", "auto"])
def test_local_monitoring_survives_explicitly_unsupported_extensions(mode):
    session = ScriptedSession(
        [
            ("getpwr", reply(GETPWR)),
            ("pwr", UnsupportedCommand("no pwr")),
            ("pwrsys", UnsupportedCommand("no pwrsys")),
        ]
    )
    result = BatteryClient(session=session, monitoring_mode=mode, profile="generic").snapshot()
    assert result.modules[0].voltage_v == 50
    assert len(result.modules[0].cells) == 2
    assert not session.exchanges


def test_automatic_profile_selection_changes_extensions(monkeypatch):
    monkeypatch.setitem(
        PROFILES,
        "SYNTHETIC_MODEL",
        MonitoringProfile(
            "SYNTHETIC_MODEL", pwr_extension=False, addressed_pwrsys=False, system_pwrsys=False
        ),
    )
    session = ScriptedSession(
        [
            ("info", reply(INFO)),
            ("getpwr", reply(GETPWR)),
            ("pwrsys", reply("Advise charge current : 10000")),
        ]
    )
    result = BatteryClient(session=session, monitoring_mode="single").snapshot()
    assert result.modules[0].recommended_charge_a == 10
    assert not session.exchanges


def test_profile_override_and_model_defaults():
    assert monitoring_profile("SYNTHETIC_UNKNOWN").name == "generic"
    assert not monitoring_profile("UP2500").addressed_pwrsys
    assert not monitoring_profile("2500LFP2").pwr_extension
    assert monitoring_profile("US2K").trailer_from_end
    session = ScriptedSession(
        [("getpwr 4", reply(GETPWR)), ("pwrsys", reply("Advise discharge current : -10000"))]
    )
    result = BatteryClient(session=session, module=4, profile="UP2500").snapshot()
    assert result.modules[0].address == 4
    assert result.modules[0].recommended_discharge_a == -10
    assert not session.exchanges
    with pytest.raises(ValueError, match="Unknown monitoring profile"):
        BatteryClient(session=session, profile="SYNTHETIC_UNKNOWN")


def test_parallel_mode_aggregates_only_complete_measurements_and_system_currents():
    sys_text = "system Recommend chg current : 30000\r\nsystem Recommend dsg current : -40000"
    session = ScriptedSession(
        [
            ("pwr", reply(PWR)),
            ("getpwr 1", reply(GETPWR)),
            ("pwrsys 1", reply("Recommend chg current : 10000")),
            ("getpwr 2", reply(GETPWR)),
            ("pwrsys 2", reply("Recommend chg current : 10000")),
            ("pwrsys", reply(sys_text)),
        ]
    )
    snapshot = BatteryClient(
        session=session, profile="generic", monitoring_mode="parallel"
    ).snapshot()
    assert snapshot.system.current_a == -4 and snapshot.system.voltage_v == 50
    assert snapshot.system.recommended_charge_a == 30
    assert snapshot.system.recommended_discharge_a == -40
    assert [m.address for m in snapshot.modules] == [1, 2]
    output = io.StringIO()
    writer = csv.DictWriter(output, CSV_FIELDS)
    writer.writeheader()
    _write_snapshot(snapshot, output, writer)
    records = list(csv.DictReader(io.StringIO(output.getvalue())))
    assert records[0]["type"] == "system" and records[0]["current_a"] == "-4.0"
    assert records[1]["min_cell_voltage_index"] == "0"


def test_missing_measurements_are_not_zero_aggregates():
    session = ScriptedSession(
        [
            ("getpwr", reply("Voltage : 50000 mV")),
            ("pwr", UnsupportedCommand("no")),
            ("pwrsys", reply("Recommend chg current : 10000")),
        ]
    )
    result = BatteryClient(session=session, profile="generic").snapshot()
    assert result.system.current_a is None
    assert result.modules[0].min_cell_voltage_v is None


def test_labeled_states_soc_errors_and_extrema_are_normalized():
    text = (
        "Voltage : 50000 mV\r\nPercent : 40 %\r\nVolt. State : OV\r\n"
        "System Fault : 0x8\r\nCycle Count : 7\r\n"
        "Battery Volt Curr Tempr Base State Volt. State Curr. State Temp. State Coulomb\r\n"
        "0 3200 -2000 -1000 Idle Normal Normal Normal 40%\r\n"
        "1 3300 -2000 20000 Idle Normal Normal Normal 40%\r\n"
    )
    module = parse_getpwr(text)
    assert module.soc_pct == 40 and module.states["Volt.St"] == "OV"
    assert module.error_code == 8 and module.cycle_count == 7
    assert {a.code for a in module.alarms} == {"OV", "BMIC ERR"}
    assert module.min_cell_voltage_v == 3.2 and module.max_cell_voltage_index == 1
    assert module.min_cell_temperature_c == -1 and module.max_cell_temperature_index == 1


def test_profile_uses_last_trailer_pair_for_older_layout():
    text = GETPWR.replace(
        "Command completed successfully", "99# 88# 8# 7#\r\nCommand completed successfully"
    )
    module = parse_getpwr(text, profile=monitoring_profile("US2K"))
    assert module.error_code == 8 and module.cycle_count == 7


def test_malformed_optional_pwr_is_still_a_failure():
    session = ScriptedSession([("getpwr", reply(GETPWR)), ("pwr", reply("garbled"))])
    with pytest.raises(ProtocolError) as error:
        BatteryClient(session=session, profile="generic").snapshot()
    assert error.value.context["command"] == "pwr"
    assert "garbled" in failure_diagnostic(error.value)


def test_failed_response_tail_is_bounded_and_terminal_safe():
    error = CommandTimeout(
        "timeout",
        response="PRIVATE_PREFIX" + "x" * 5000 + "\x1b[31m\r\nTAIL",
        context={"command": "info", "timeout_s": 5, "boundary": None},
    )
    rendered = failure_diagnostic(error)
    assert "PRIVATE_PREFIX" not in rendered and "truncated" in rendered
    assert "\\x1b" in rendered and "\x1b" not in rendered
    assert "TAIL" in rendered and "command='info'" in rendered
    assert "nothing received" in failure_diagnostic(CommandTimeout("timeout"))
    assert failure_diagnostic(None) == ""


def test_reset_wrapper_exposes_cause_diagnostics():
    try:
        raise CommandTimeout("timeout", response="SYNTHETIC_PARTIAL")
    except CommandTimeout as cause:
        error = ResetRecoveryError("recovery needed", recovery_path="synthetic.json")
        error.__cause__ = cause
    assert "SYNTHETIC_PARTIAL" in failure_diagnostic(error)


def test_serial_timeout_carries_partial_response_and_exchange_context(replay):
    session, transport = replay([(b"info\n", "info\n@SYNTHETIC_PARTIAL")], timeout=0.01)
    with pytest.raises(CommandTimeout) as error:
        session.exchange("info")
    assert error.value.context["command"] == "info"
    assert error.value.context["terminator"] == b"\n"
    assert error.value.context["boundary"] is None
    assert error.value.response.endswith("SYNTHETIC_PARTIAL")
    assert transport.writes == [b"info\n"]


def test_serial_read_failure_retains_received_data(replay):
    session, transport = replay([(b"info\n", "SYNTHETIC_PARTIAL")])
    original = transport.read

    def read():
        if transport.pending:
            return original()
        raise OSError("synthetic disconnect")

    transport.read = read
    with pytest.raises(ConnectionError) as error:
        session.exchange("info")
    assert error.value.response == "SYNTHETIC_PARTIAL"
    assert error.value.context["command"] == "info"


class RecoveringSession(ScriptedSession):
    def resynchronize(self, **kwargs):
        return self.exchange("")


@pytest.mark.parametrize("retries", [0, 1, 2])
def test_read_retries_are_bounded_and_require_debug_prompt(retries):
    exchanges = [("info", CommandTimeout("timeout"))]
    for _ in range(retries):
        exchanges.extend([("", reply()), ("info", CommandTimeout("timeout"))])
    session = RecoveringSession(exchanges)
    with pytest.raises(CommandTimeout):
        BatteryClient(session=session, read_retries=retries).info()
    assert len(session.calls) == 1 + retries * 2
    assert not session.exchanges


def test_retry_success_after_resynchronization():
    session = RecoveringSession(
        [("info", CommandTimeout("timeout")), ("", reply()), ("info", reply(INFO))]
    )
    assert BatteryClient(session=session, read_retries=1).info().name == "SYNTHETIC_MODEL"


def test_retry_does_not_accept_base_prompt():
    session = RecoveringSession(
        [("info", CommandTimeout("timeout")), ("", Response("pylon>", "prompt"))]
    )
    with pytest.raises(ProtocolError, match="debug prompt"):
        BatteryClient(session=session, read_retries=1).info()
    assert not session.exchanges


def test_rejected_read_is_never_retried():
    session = RecoveringSession([("info", UnsupportedCommand("no"))])
    with pytest.raises(UnsupportedCommand):
        BatteryClient(session=session, read_retries=2).info()
    assert len(session.calls) == 1


def test_report_retry_retains_failed_attempt_and_reissues_explicit_offset(tmp_path):
    session = RecoveringSession(
        report_start("event", 1)
        + [
            ("datalist event dtls 0", CommandTimeout("timeout", response="SYNTHETIC_PARTIAL")),
            ("", reply()),
            ("datalist event dtls 0", reply(rows([0]))),
            ("", reply()),
        ]
    )
    result = BatteryClient(session=session, read_retries=1).export_events(tmp_path / "event.txt")
    assert result.complete
    assert "SYNTHETIC_PARTIAL" in result.path.read_bytes().decode("utf-16")
    assert [c for c, _ in session.calls].count("datalist event dtls 0") == 2


@pytest.mark.parametrize("operation", ["export_events", "reset_soc"])
def test_pagination_continuations_and_reset_commands_are_not_retried(tmp_path, operation):
    if operation == "export_events":
        exchanges = report_start("event", 1) + [
            ("datalist event dtls 0", reply(rows([0]))),
            ("", CommandTimeout("timeout")),
        ]
        error = CommandTimeout
    else:
        exchanges = [("stat", CommandTimeout("timeout"))]
        error = ResetRecoveryError
    session = RecoveringSession(exchanges)
    with pytest.raises(error):
        getattr(BatteryClient(session=session, read_retries=2), operation)(tmp_path / "partial.txt")
    assert not session.exchanges


@pytest.mark.parametrize("value", [-1, 3, 1.0, True])
def test_invalid_retry_configuration(value):
    with pytest.raises(ValueError, match="Read retries"):
        BatteryClient(session=ScriptedSession([]), read_retries=value)


def test_cli_reports_failed_communication_without_debug(monkeypatch, capsys):
    class FailedClient:
        def __init__(self, *args, **kwargs):
            pass

        def __enter__(self):
            raise CommandTimeout(
                "synthetic timeout", response="SYNTHETIC_PARTIAL", context={"command": "getpwr"}
            )

        def __exit__(self, *args):
            pass

    monkeypatch.setattr("batteryview.cli.BatteryClient", FailedClient)
    assert main(["snapshot", "--port", "SYNTHETIC_PORT"]) == 1
    output = capsys.readouterr()
    assert not output.out
    assert "SYNTHETIC_PARTIAL" in output.err and "command='getpwr'" in output.err


@pytest.mark.parametrize("command", ["history", "event", "reset-soc"])
def test_cli_rejects_addressed_full_reports(command):
    with pytest.raises(SystemExit) as error:
        main([command, "--port", "SYNTHETIC_PORT", "--module", "4"])
    assert error.value.code == 2


def test_cli_collection_failure_shows_tail_without_serial_trace(monkeypatch, capsys, tmp_path):
    from batteryview import CollectionResult

    class FailedCollection:
        last_failure = CommandTimeout(
            "timeout", response="SYNTHETIC_PARTIAL", context={"command": "data event 0"}
        )

        def __init__(self, *args, **kwargs):
            pass

        def __enter__(self):
            return self

        def __exit__(self, *args):
            pass

        def collect(self, output, **kwargs):
            return CollectionResult(output, output / "synthetic_manifest.json", False)

    monkeypatch.setattr("batteryview.cli.BatteryClient", FailedCollection)
    assert main(["collect", "--port", "SYNTHETIC_PORT", "--output", str(tmp_path)]) == 1
    captured = capsys.readouterr()
    assert json.loads(captured.out)["complete"] is False
    assert "SYNTHETIC_PARTIAL" in captured.err and "command='data event 0'" in captured.err


def test_cleanup_does_not_replace_failure_exchange_context(replay):
    session, transport = replay(
        [(b"info\n", "SYNTHETIC_PARTIAL"), (b"cmdquit\n", "cmdquit")], timeout=0.01
    )
    with pytest.raises(CommandTimeout) as error:
        with BatteryClient(session=session) as client:
            client.info()
    assert transport.closed
    assert error.value.context["command"] == "info"
    assert "SYNTHETIC_PARTIAL" in failure_diagnostic(error.value)
    assert "cmdquit" not in failure_diagnostic(error.value)


def test_numbered_connection_does_not_send_numbered_login(monkeypatch):
    from functools import partial

    from conftest import ReplayTransport

    from batteryview.protocol import ConsoleSession

    transport = ReplayTransport(
        [(b"\n", "pylon_debug>"), (b"info 4\n", INFO), (b"cmdquit\n", "cmdquit")]
    )
    monkeypatch.setattr("batteryview.client.SerialTransport", lambda *args: transport)
    monkeypatch.setattr("batteryview.client.ConsoleSession", partial(ConsoleSession, settle_time=0))
    monkeypatch.setattr("batteryview.protocol.time.sleep", lambda _: None)
    with BatteryClient("SYNTHETIC_PORT", module=4, shift=False) as client:
        client.info()
    assert transport.writes == [b"\n", b"info 4\n", b"cmdquit\n"]


def test_malformed_pwrsys_remains_a_diagnosable_failure():
    session = ScriptedSession(
        [
            ("getpwr", reply(GETPWR)),
            ("pwr", UnsupportedCommand("no")),
            ("pwrsys", reply("SYNTHETIC_MALFORMED")),
        ]
    )
    with pytest.raises(ProtocolError) as error:
        BatteryClient(session=session, profile="generic").snapshot()
    assert error.value.context["command"] == "pwrsys"
    assert "SYNTHETIC_MALFORMED" in failure_diagnostic(error.value)
