import codecs
import json
from datetime import datetime, timezone
from functools import partial

import pytest
from conftest import ReplayTransport, ScriptedSession

from pylontech_tools import (
    BatteryClient,
    CommandCancelled,
    CommandTimeout,
    ConnectionError,
    ProtocolError,
)
from pylontech_tools.cli import main
from pylontech_tools.protocol import SHIFT_SEQUENCE, ConsoleSession, Response

FIXED_TIME = datetime(2000, 1, 2, 3, 4, 5, tzinfo=timezone.utc)


@pytest.fixture(autouse=True)
def synthetic_clock(monkeypatch):
    class Clock(datetime):
        @classmethod
        def now(cls, tz=None):
            return FIXED_TIME.astimezone(tz)

    monkeypatch.setattr("pylontech_tools.collection.datetime", Clock)
    monkeypatch.setattr("pylontech_tools.client.datetime", Clock)
    monkeypatch.setattr("pylontech_tools.collection._application_version", lambda: "0.0.test")


def response(command, body=""):
    return (
        f"{command}\n\r@\r\r\n{body}\r\n\rCommand completed successfully\r\n\r$$\r\n\rpylon_debug>"
    )


def info(barcode="TEST_A", address=8):
    barcode_line = f"Barcode : {barcode}\r\r\n" if barcode else ""
    return response(
        "info",
        f"Device address : {address}\r\r\nDevice name : SYNTHETIC_MODEL\r\r\n"
        f"{barcode_line}Cell Number : 2",
    )


def report_exchanges(kind, *, barcode="TEST_A", address=8):
    exchanges = [
        (b"info\n", info(barcode, address)),
        (b"stat\n", response("stat", "HisData Items : 1\r\r\nData Items : 0")),
        (f"data {kind}\n".encode(), response(f"data {kind}")),
    ]
    if kind == "history":
        exchanges += [
            (
                b"datalist history dtls 0\n",
                response(
                    "datalist history dtls 0",
                    "Item  Time  Vo(mV)  Cu(mA)  Tempr\r\r\n"
                    "0 00-01-01 00:00:00 50000 -2000 20000 20000 21000 3101 3102 "
                    "Dischg Normal Normal Normal 0x0 Normal 50% 100000 "
                    "0 3101 20000 Normal Normal 50% 1 3102 21000 Normal Normal 50%",
                ),
            ),
            (b"\n", "\n\rpylon_debug>"),
        ]
    return exchanges


def collection_exchanges(*, barcode="TEST_A", address=8):
    return (
        [(b"info\n", info(barcode, address))]
        + report_exchanges("history", barcode=barcode, address=address)
        + report_exchanges("event", barcode=barcode, address=address)
        + [
            (
                b"getpwr\n",
                response(
                    "getpwr",
                    "50000# -2000# 20000# 100000# Dischg# Normal# Normal# Normal#\r\r\n"
                    "3101# 20000# Normal# Normal#\r\r\n3102# 21000# Normal# Normal#",
                ),
            ),
            (
                b"pwr\n",
                response(
                    "pwr",
                    f"Power {address}\r\r\nVoltage : 50000 mV\r\r\n"
                    "Current : -2000 mA\r\r\nCoulomb : 50 %",
                ),
            ),
            (
                b"pwrsys\n",
                response(
                    "pwrsys", "Recommend chg current : 10000\r\r\nRecommend dsg current : -20000"
                ),
            ),
        ]
    )


def read_manifest(result):
    return json.loads(result.manifest_path.read_text(encoding="utf-8"))


def test_collection_uses_one_session_and_keeps_all_artifacts_flat(tmp_path, replay):
    exchanges = collection_exchanges() + [(b"cmdquit\n", "cmdquit\n")]
    session, transport = replay(exchanges)
    directory = tmp_path / "support"
    with BatteryClient(session=session) as client:
        progress = []
        result = client.collect(directory, progress=lambda *args: progress.append(args))
    manifest = read_manifest(result)
    assert result.complete and result.directory == directory
    assert manifest["format_version"] == 1
    assert manifest["application_version"] == "0.0.test"
    assert manifest["started_at"] == manifest["finished_at"] == FIXED_TIME.isoformat()
    assert manifest["status"] == "complete" and manifest["complete"]
    assert manifest["device"]["barcode"] == "TEST_A"
    assert [s["name"] for s in manifest["steps"]] == ["identity", "history", "event", "snapshot"]
    assert all(s["status"] == "complete" and s["error"] is None for s in manifest["steps"])
    artifacts = [directory / step["artifact"] for step in manifest["steps"]]
    assert set(directory.iterdir()) == {*artifacts, result.manifest_path}
    assert all(path.is_file() and path.parent == directory for path in directory.iterdir())
    assert artifacts[0].name.endswith("_info.json")
    prefix = f"TEST_A_{manifest['run_id']}"
    assert result.manifest_path.name == f"{prefix}_manifest.json"
    assert [p.name for p in artifacts] == [
        f"{prefix}_info.json",
        f"{prefix}_history.txt",
        f"{prefix}_event.txt",
        f"{prefix}_snapshot.json",
    ]
    assert artifacts[3].name.endswith("_snapshot.json")
    assert manifest["steps"][1]["records"] == 1
    assert manifest["steps"][2]["records"] == 0
    snapshot = json.loads(artifacts[3].read_text())
    assert snapshot["modules"][0]["address"] == 8
    assert snapshot["modules"][0]["cells"][0]["voltage_v"] == 3.101
    assert transport.writes == [command for command, _ in exchanges]
    assert transport.closed and not transport.exchanges
    assert progress[0] == ("identity", 0, 1) and progress[-1] == ("snapshot", 1, 1)


def test_collecting_different_modules_reuses_directory_without_changing_old_files(tmp_path, replay):
    directory = tmp_path / "support"
    directory.mkdir()
    (directory / "notes.txt").write_text("retain unrelated notes")
    session, _ = replay(collection_exchanges())
    first = BatteryClient(session=session).collect(directory)
    original = {p.name: p.read_bytes() for p in directory.iterdir()}
    session, _ = replay(collection_exchanges(barcode="TEST_B", address=9))
    second = BatteryClient(session=session).collect(directory)
    assert first.complete and second.complete
    assert first.manifest_path != second.manifest_path
    assert all((directory / name).read_bytes() == data for name, data in original.items())
    assert read_manifest(second)["device"]["barcode"] == "TEST_B"
    assert len(list(directory.glob("*_manifest.json"))) == 2
    assert not any(p.is_dir() for p in directory.iterdir())


def test_same_battery_collections_in_the_same_second_have_distinct_prefixes(tmp_path, replay):
    directory = tmp_path / "support"
    session, _ = replay(collection_exchanges())
    first = BatteryClient(session=session).collect(directory)
    original = {p.name: p.read_bytes() for p in directory.iterdir()}
    session, _ = replay(collection_exchanges())
    second = BatteryClient(session=session).collect(directory)
    assert first.complete and second.complete
    assert read_manifest(first)["started_at"] == read_manifest(second)["started_at"]
    assert read_manifest(first)["run_id"] != read_manifest(second)["run_id"]
    assert len(list(directory.iterdir())) == 10
    assert all((directory / name).read_bytes() == data for name, data in original.items())


def test_collection_sanitizes_barcode_in_every_artifact(tmp_path, replay):
    session, _ = replay(collection_exchanges(barcode="TEST/A: B"))
    result = BatteryClient(session=session).collect(tmp_path / "support")
    assert result.complete
    manifest = read_manifest(result)
    assert manifest["device"]["barcode"] == "TEST/A: B"
    prefix = f"TEST_A__B_{manifest['run_id']}_"
    assert all(p.name.startswith(prefix) for p in result.directory.iterdir())


def test_manifest_collision_does_not_replace_existing_collection(tmp_path, replay, monkeypatch):
    from uuid import UUID

    monkeypatch.setattr("pylontech_tools.collection.uuid4", lambda: UUID(int=1))
    directory = tmp_path / "support"
    session, _ = replay(collection_exchanges())
    first = BatteryClient(session=session).collect(directory)
    original = {p.name: p.read_bytes() for p in directory.iterdir()}
    session, transport = replay([(b"info\n", info())])
    with pytest.raises(FileExistsError):
        BatteryClient(session=session).collect(directory)
    assert first.complete and transport.writes == [b"info\n"]
    assert set(p.name for p in directory.iterdir()) == set(original)
    assert all((directory / name).read_bytes() == data for name, data in original.items())


def test_identity_progress_cancellation_still_creates_an_unknown_manifest(tmp_path, replay):
    session, transport = replay([])

    def cancel(*args):
        raise CommandCancelled("synthetic cancellation before identity")

    with pytest.raises(CommandCancelled):
        BatteryClient(session=session).collect(tmp_path / "support", progress=cancel)
    path = next((tmp_path / "support").glob("*_manifest.json"))
    manifest = json.loads(path.read_text())
    assert path.name == f"UnknownSN_{manifest['run_id']}_manifest.json"
    assert manifest["status"] == "interrupted" and manifest["device"] is None
    assert [s["status"] for s in manifest["steps"]] == ["interrupted"] + ["skipped"] * 3
    assert not transport.writes


def test_doctor_reads_new_and_legacy_collections_together(tmp_path, replay):
    from pylontech_tools import analyze_logs

    directory = tmp_path / "support"
    session, _ = replay(collection_exchanges())
    legacy = BatteryClient(session=session).collect(directory)
    manifest = read_manifest(legacy)
    # Recreate the original layout using only synthetic collection content.
    for step in manifest["steps"]:
        old = directory / step["artifact"]
        kind = step["name"]
        filename = (
            f"TEST_A_{kind}_20000102030405.txt.txt"
            if kind in {"history", "event"}
            else f"{manifest['run_id']}_{'info' if kind == 'identity' else kind}.json"
        )
        old.rename(directory / filename)
        step["artifact"] = filename
    legacy.manifest_path.unlink()
    legacy_path = directory / f"{manifest['run_id']}_manifest.json"
    legacy_path.write_text(json.dumps(manifest))
    before = analyze_logs(directory)
    assert len(before.batteries) == 1 and not before.input_issues
    for kind in ("history", "event"):
        path = next(directory.glob(f"TEST_A_{kind}_*.txt.txt"))
        assert len(analyze_logs(path).batteries) == 1

    session, _ = replay(collection_exchanges())
    current = BatteryClient(session=session).collect(directory)
    assert current.complete
    assert len(analyze_logs(current.manifest_path).batteries) == 1
    after = analyze_logs(directory)
    assert not after.input_issues and len(after.batteries) == 1
    assert (
        after.batteries[0].metrics["observation_count"]
        == before.batteries[0].metrics["observation_count"]
    )
    session, _ = replay(collection_exchanges(barcode="TEST_B"))
    assert BatteryClient(session=session).collect(directory).complete
    combined = analyze_logs(directory)
    assert not combined.input_issues
    assert {b.identity["barcode"] for b in combined.batteries} == {"TEST_A", "TEST_B"}


def test_bundled_transcripts_equal_standalone_exports(tmp_path, replay):
    session, _ = replay(collection_exchanges())
    result = BatteryClient(session=session).collect(tmp_path / "support")
    steps = {s["name"]: s for s in read_manifest(result)["steps"]}
    for kind in ("history", "event"):
        exchanges = report_exchanges(kind)
        session, _ = replay(exchanges)
        client = BatteryClient(session=session)
        export = client.export_history if kind == "history" else client.export_events
        standalone = export(tmp_path / f"standalone-{kind}.txt")
        bundled = result.directory / steps[kind]["artifact"]
        assert bundled.read_bytes() == standalone.path.read_bytes()
        assert bundled.read_bytes() == codecs.BOM_UTF16_LE + "".join(
            text + "\r\n" for _, text in exchanges
        ).encode("utf-16-le")


STAGE_POSITIONS = {"identity": 0, "history": 2, "event": 7, "snapshot": 10}


def failed_session(stage, error):
    exchanges = collection_exchanges()
    position = STAGE_POSITIONS[stage]
    scripted = [
        (command.decode().removesuffix("\n"), Response(text, "prompt"))
        for command, text in exchanges
    ]
    scripted[position] = (scripted[position][0], error)
    return ScriptedSession(scripted), position


@pytest.mark.parametrize("stage", STAGE_POSITIONS)
def test_failure_at_each_step_keeps_partial_results_and_skips_all_remaining(tmp_path, stage):
    session, position = failed_session(
        stage, CommandTimeout("synthetic timeout", response="SYNTHETIC_PARTIAL")
    )
    with BatteryClient(session=session) as client:
        result = client.collect(tmp_path / "support")
    manifest = read_manifest(result)
    names = list(STAGE_POSITIONS)
    step_index = names.index(stage)
    assert not result.complete and manifest["status"] == "failed"
    assert not manifest["complete"] and manifest["finished_at"]
    assert [s["status"] for s in manifest["steps"]] == (
        ["complete"] * step_index + ["failed"] + ["skipped"] * (3 - step_index)
    )
    failed = manifest["steps"][step_index]
    assert failed["error"] == {"type": "CommandTimeout", "message": "synthetic timeout"}
    assert "SYNTHETIC_PARTIAL" not in result.manifest_path.read_text()
    assert len(session.calls) == position + 1
    assert session.disconnected
    if stage in {"history", "event"}:
        assert (
            (result.directory / failed["artifact"])
            .read_bytes()
            .decode("utf-16")
            .endswith("SYNTHETIC_PARTIAL\r\n")
        )
    else:
        assert failed["artifact"] is None
    for step in manifest["steps"][:step_index]:
        assert (result.directory / step["artifact"]).is_file()


@pytest.mark.parametrize("stage", STAGE_POSITIONS)
@pytest.mark.parametrize("error_type", [KeyboardInterrupt, CommandCancelled])
def test_cancellation_finalizes_manifest_and_reraises(tmp_path, stage, error_type):
    session, position = failed_session(stage, error_type("synthetic interruption"))
    directory = tmp_path / "support"
    with pytest.raises(error_type), BatteryClient(session=session) as client:
        client.collect(directory)
    manifest = json.loads(next(directory.glob("*_manifest.json")).read_text())
    step_index = list(STAGE_POSITIONS).index(stage)
    assert manifest["status"] == "interrupted" and not manifest["complete"]
    assert manifest["finished_at"]
    assert [s["status"] for s in manifest["steps"]] == (
        ["complete"] * step_index + ["interrupted"] + ["skipped"] * (3 - step_index)
    )
    assert len(session.calls) == position + 1 and session.disconnected


def test_existing_report_collision_preserves_previous_run_and_does_not_claim_its_file(
    tmp_path, replay, monkeypatch
):
    from uuid import UUID

    directory = tmp_path / "support"
    session, _ = replay(collection_exchanges())
    first = BatteryClient(session=session).collect(directory)
    next_id = UUID(int=1)
    monkeypatch.setattr("pylontech_tools.collection.uuid4", lambda: next_id)
    collision = directory / f"TEST_A_20000102T030405Z_{next_id.hex}_history.txt"
    collision.write_bytes(b"existing unrelated report")
    original = {p.name: p.read_bytes() for p in directory.iterdir()}
    session, transport = replay([(b"info\n", info())])
    second = BatteryClient(session=session).collect(directory)
    assert not second.complete
    manifest = read_manifest(second)
    assert manifest["steps"][0]["status"] == "complete"
    assert manifest["steps"][1]["error"]["type"] == "FileExistsError"
    assert manifest["steps"][1]["artifact"] is None
    assert transport.writes == [b"info\n"]
    assert all((directory / name).read_bytes() == content for name, content in original.items())
    assert first.manifest_path != second.manifest_path


def test_output_file_is_not_replaced_by_directory(tmp_path):
    output = tmp_path / "file"
    output.write_text("unchanged")
    session = ScriptedSession([])
    with pytest.raises(FileExistsError):
        BatteryClient(session=session).collect(output)
    assert output.read_text() == "unchanged" and not session.calls


def test_collection_rejects_addressed_selection_and_unconnected_client_without_files(tmp_path):
    session = ScriptedSession([])
    directory = tmp_path / "support"
    with pytest.raises(ValueError, match="direct module connection"):
        BatteryClient(session=session, module=8).collect(directory)
    assert not session.calls and not directory.exists()
    with pytest.raises(ProtocolError, match="not connected"):
        BatteryClient("SYNTHETIC_PORT").collect(directory)
    assert not directory.exists()


def test_missing_barcode_keeps_vendor_unknown_sn_filenames(tmp_path, replay):
    session, _ = replay(collection_exchanges(barcode=None))
    result = BatteryClient(session=session).collect(tmp_path / "support")
    manifest = read_manifest(result)
    assert result.complete and manifest["device"]["barcode"] is None
    prefix = f"UnknownSN_{manifest['run_id']}"
    assert result.manifest_path.name == f"{prefix}_manifest.json"
    assert manifest["steps"][1]["artifact"] == f"{prefix}_history.txt"


def test_manifest_replacement_is_atomic_and_records_step_transitions(tmp_path, replay, monkeypatch):
    import pylontech_tools.collection as collection

    replace = collection.os.replace
    transitions = []

    def observe(source, target):
        old = json.loads(target.read_text())
        new = json.loads(source.read_text())
        assert old["run_id"] == new["run_id"]
        assert source.parent == target.parent
        transitions.append([s["status"] for s in new["steps"]])
        replace(source, target)

    monkeypatch.setattr(collection.os, "replace", observe)
    session, _ = replay(collection_exchanges())
    result = BatteryClient(session=session).collect(tmp_path / "support")
    assert transitions[0] == ["running", "pending", "pending", "pending"]
    assert transitions[-1] == ["complete"] * 4
    assert len(transitions) == 8
    assert not list(result.directory.glob("*.tmp"))


def test_artifact_write_failure_keeps_partial_and_stops(tmp_path, replay, monkeypatch):
    import pylontech_tools.collection as collection

    write_json = collection._write_json

    def fail_identity(path, data):
        if path.name.endswith("_info.json"):
            path.write_text('{"partial":')
            raise OSError("synthetic disk error")
        write_json(path, data)

    monkeypatch.setattr(collection, "_write_json", fail_identity)
    session, transport = replay([(b"info\n", info())])
    result = BatteryClient(session=session).collect(tmp_path / "support")
    manifest = read_manifest(result)
    assert not result.complete and manifest["steps"][0]["error"]["type"] == "OSError"
    assert (result.directory / manifest["steps"][0]["artifact"]).read_text() == '{"partial":'
    assert transport.writes == [b"info\n"]


def test_final_manifest_failure_raises_and_retains_previous_valid_state(
    tmp_path, replay, monkeypatch
):
    import pylontech_tools.collection as collection

    write_manifest = collection._write_manifest

    def fail_final(path, data, **kwargs):
        if data["complete"]:
            raise OSError("cannot finalize manifest")
        write_manifest(path, data, **kwargs)

    monkeypatch.setattr(collection, "_write_manifest", fail_final)
    session, _ = replay(collection_exchanges())
    directory = tmp_path / "support"
    with pytest.raises(OSError, match="cannot finalize manifest"):
        BatteryClient(session=session).collect(directory)
    manifest = json.loads(next(directory.glob("*_manifest.json")).read_text())
    assert not manifest["complete"] and manifest["steps"][-1]["status"] == "running"
    assert len(list(directory.iterdir())) == 5


@pytest.mark.parametrize("transition", ["start", "finish"])
def test_cancellation_during_manifest_updates_records_interruption(
    tmp_path, replay, monkeypatch, transition
):
    import pylontech_tools.collection as collection

    write_manifest = collection._write_manifest
    interrupted = False

    def interrupt_transition(path, data, **kwargs):
        nonlocal interrupted
        at_start = data["steps"][0]["status"] == "running"
        at_finish = data["complete"]
        if not interrupted and (at_start if transition == "start" else at_finish):
            interrupted = True
            raise KeyboardInterrupt()
        write_manifest(path, data, **kwargs)

    monkeypatch.setattr(collection, "_write_manifest", interrupt_transition)
    session, transport = replay(collection_exchanges())
    directory = tmp_path / "support"
    with pytest.raises(KeyboardInterrupt):
        BatteryClient(session=session).collect(directory)
    manifest = json.loads(next(directory.glob("*_manifest.json")).read_text())
    assert manifest["status"] == "interrupted" and not manifest["complete"]
    assert manifest["finished_at"]
    step_index = 0 if transition == "start" else 3
    assert manifest["steps"][step_index]["status"] == "interrupted"
    if transition == "start":
        assert transport.writes == [b"info\n"]
        assert all(s["status"] == "skipped" for s in manifest["steps"][1:])
    else:
        assert len(list(directory.iterdir())) == 5


def test_collect_cli_runs_one_handshake_and_disconnect_and_outputs_only_summary(
    tmp_path, monkeypatch, capsys
):
    transports = []

    def transport(*args):
        wire = ReplayTransport(
            [
                (SHIFT_SEQUENCE, ""),
                (b"\n", "\rpylon_debug>"),
                *collection_exchanges(),
                (b"cmdquit\n", "cmdquit"),
            ],
            chunk_size=65536,
        )
        transports.append(wire)
        return wire

    monkeypatch.setattr("pylontech_tools.client.SerialTransport", transport)
    monkeypatch.setattr(
        "pylontech_tools.client.ConsoleSession", partial(ConsoleSession, settle_time=0)
    )
    monkeypatch.setattr("pylontech_tools.protocol.time.sleep", lambda _: None)
    assert main(["collect", "--port", "SYNTHETIC_PORT", "--output", str(tmp_path / "support")]) == 0
    out, err = capsys.readouterr()
    summary = json.loads(out)
    assert summary["complete"] and "raw_responses" not in summary
    assert "identity" in err and "snapshot" in err
    assert len(transports) == 1 and transports[0].closed and not transports[0].exchanges
    assert transports[0].writes.count(SHIFT_SEQUENCE) == 1


def test_connection_setup_failure_does_not_create_collection_artifacts(
    tmp_path, monkeypatch, capsys
):
    def fail(*args):
        raise ConnectionError("synthetic connection failure")

    monkeypatch.setattr("pylontech_tools.client.SerialTransport", fail)
    directory = tmp_path / "support"
    assert main(["collect", "--port", "SYNTHETIC_PORT", "--output", str(directory)]) == 1
    assert not directory.exists()
    out, err = capsys.readouterr()
    assert not out and "synthetic connection failure" in err


def test_collection_snapshot_accepts_rack_with_unused_module_slots(tmp_path, replay):
    from test_monitoring import GETPWR, PWR_WITH_ABSENT

    exchanges = collection_exchanges()
    # Preserve the identity and report steps; replace only the snapshot exchange.
    snapshot_at = next(i for i, (cmd, _) in enumerate(exchanges) if cmd == b"getpwr\n")
    exchanges = exchanges[:snapshot_at] + [
        (b"getpwr\n", GETPWR),
        (b"pwr\n", PWR_WITH_ABSENT),
    ]
    for address in (1, 4):
        exchanges.extend(
            [
                (f"getpwr {address}\n".encode(), GETPWR),
                (
                    f"pwrsys {address}\n".encode(),
                    response("pwrsys", "Recommend chg current : 10000"),
                ),
            ]
        )
    exchanges.append((b"pwrsys\n", response("pwrsys", "system Recommend chg current : 20000")))
    session, wire = replay(exchanges)
    result = BatteryClient(session=session).collect(tmp_path / "support")
    manifest = read_manifest(result)
    assert result.complete and all(s["status"] == "complete" for s in manifest["steps"])
    snapshot_path = result.directory / manifest["steps"][-1]["artifact"]
    snapshot = json.loads(snapshot_path.read_text())
    assert [m["address"] for m in snapshot["modules"]] == [1, 4]
    assert snapshot["raw_responses"]["pwr"] == PWR_WITH_ABSENT
    assert not wire.exchanges
