"""Health screening with wholly synthetic identities, dates, and measurements."""

import codecs
import json
from dataclasses import asdict
from pathlib import Path

import pytest
from conftest import ScriptedSession

from pylontech_tools import (
    BatteryClient,
    CommandCancelled,
    CommandTimeout,
    DoctorReport,
    UnsupportedCommand,
    analyze_logs,
)
from pylontech_tools.cli import main
from pylontech_tools.doctor import format_doctor
from pylontech_tools.models import CellReading, ModuleReading, Snapshot
from pylontech_tools.protocol import Response


def identity(barcode="TEST_A", address=1, count=2):
    return {
        "name": "SYNTHETIC_MODEL",
        "barcode": barcode,
        "address": address,
        "cell_count": count,
        "fields": {"Specification": "48V/100AH"},
    }


def frame(command, body=""):
    return f"{command}\r\n@\r\n{body}\r\nCommand completed successfully\r\n$$\r\npylon_debug>"


def info(barcode="TEST_A", address=1):
    return frame(
        "info",
        f"Device name : SYNTHETIC_MODEL\nBarcode : {barcode}\nDevice address : {address}\nCell Number : 2\nSpecification : 48V/100AH",
    )


def record(
    index, date="00-01-01", low=3450, high=3460, soc=95, current=0, state="Idle", mask="0x0"
):
    return (
        f"Item Index : {index}\nTime : {date} 12:00:00\nVoltage : 51800 mV\nCurrent : {current} mA\n"
        f"Temperature : 25000 mC\nPercent : {soc} %\nBase State : {state}\nVolt. State : Normal\n"
        f"System Fault : {mask}\nBattery Volt Curr Tempr Base State Volt. State Curr. State Temp. State Coulomb\n"
        f"0 {low} {current} 25000 Idle Normal Normal Normal {soc}%\n"
        f"1 {high} {current} 25000 Idle Normal Normal Normal {soc}%"
    )


def report(path, records, *, barcode="TEST_A", count=None, encoding="utf-16"):
    data = (
        info(barcode)
        + "\r\n"
        + frame(
            "stat",
            f"HisData Items : {len(records) if count is None else count}\nData Items : 0\nSOH : 99\nCYCLE Times : 12",
        )
    )
    data += "\r\n" + frame("datalist history dtls 0", "\n".join(records))
    path.write_text(data, encoding=encoding)
    return path


def snapshot(spread=10, *, address=1, timestamp="2000-01-03T13:00:00+00:00", state="Idle"):
    return asdict(
        Snapshot(
            timestamp,
            [
                ModuleReading(
                    address=address,
                    voltage_v=51.8,
                    current_a=0,
                    soc_pct=95,
                    states={"Base.St": state},
                    cells=[
                        CellReading(0, voltage_v=3.45),
                        CellReading(1, voltage_v=(3450 + spread) / 1000),
                    ],
                )
            ],
        )
    )


def bundle(
    directory,
    *,
    barcode="TEST_A",
    run="one",
    spread=10,
    records=None,
    complete=True,
    timestamp="2000-01-03T13:00:00+00:00",
    address=1,
):
    directory.mkdir(exist_ok=True, parents=True)
    ident = identity(barcode, address)
    snap = directory / f"{run}_snapshot.json"
    snap.write_text(json.dumps(snapshot(spread, address=address, timestamp=timestamp)))
    steps = [{"name": "snapshot", "artifact": snap.name, "status": "complete"}]
    if records is not None:
        text = report(directory / f"{run}_history.txt.txt", records, barcode=barcode)
        steps.append({"name": "history", "artifact": text.name, "status": "complete"})
    manifest = directory / f"{run}_manifest.json"
    manifest.write_text(
        json.dumps(
            {
                "format_version": 1,
                "device": ident,
                "started_at": timestamp,
                "complete": complete,
                "steps": steps,
            }
        )
    )
    return manifest


def codes(result):
    return {f.code for b in result.batteries for f in b.findings}


@pytest.mark.parametrize("encoding", ["utf-16", "utf-16-be", "utf-8", "utf-8-sig"])
def test_single_report_encodings_and_historical_summary(tmp_path, encoding):
    path = report(tmp_path / "single.txt.txt", [record(0)], encoding="utf-8")
    text = path.read_text()
    if encoding == "utf-16-be":
        path.write_bytes(codecs.BOM_UTF16_BE + text.encode("utf-16-be"))
    else:
        path.write_text(text, encoding=encoding)
    result = analyze_logs(path)
    assert result.exit_code == 0
    battery = result.batteries[0]
    assert battery.identity["barcode"] == "TEST_A"
    assert battery.metrics["cell_spread_mv"] == 10
    assert battery.metrics["reported_soh_pct"] == 99
    assert battery.metrics["as_of"] == "historical_record"
    assert "Historical evidence only" in " ".join(battery.limitations)
    assert "historical_record" in format_doctor(result)


@pytest.mark.parametrize(
    "spread,threshold,expected",
    [(99, 100, False), (100, 100, True), (101, 100, True), (100, 101, False)],
)
def test_voltage_spread_threshold_boundaries(tmp_path, spread, threshold, expected):
    path = bundle(tmp_path, spread=spread)
    result = analyze_logs(path, imbalance_mv=threshold)
    assert ("cell_voltage_spread" in codes(result)) == expected
    assert result.exit_code == int(expected)


@pytest.mark.parametrize("bad", [0, -1, True, 1.0, "100"])
def test_invalid_threshold_before_loading(tmp_path, bad):
    with pytest.raises(ValueError, match="positive integer"):
        analyze_logs(tmp_path, imbalance_mv=bad)


def test_persistent_balancing_evidence_and_deduplication(tmp_path):
    records = [record(i, f"00-01-0{i + 1}", high=3600) for i in range(3)]
    path = report(tmp_path / "history.txt", records + [records[2]])
    result = analyze_logs(path)
    assert "suspected_balancing_difficulty" in codes(result)
    finding = next(
        f for f in result.batteries[0].findings if f.code == "suspected_balancing_difficulty"
    )
    assert finding.certainty == "suspected" and len(finding.evidence) == 3
    assert result.batteries[0].metrics["observation_count"] == 3
    assert result.exit_code == 1


@pytest.mark.parametrize(
    "changes",
    [
        {"soc": 20},
        {"current": 10000},
        {"state": "Dischg"},
        {"low": 3300},
    ],
)
def test_unqualified_spread_does_not_prove_balancing_problem(tmp_path, changes):
    records = [record(i, f"00-01-0{i + 1}", high=3600, **changes) for i in range(3)]
    result = analyze_logs(report(tmp_path / "history.txt", records))
    assert "cell_voltage_spread" in codes(result)
    assert "suspected_balancing_difficulty" not in codes(result)


def test_convergence_and_short_timespan(tmp_path):
    records = [record(i, high=3600) for i in range(3)]
    assert "suspected_balancing_difficulty" not in codes(
        analyze_logs(report(tmp_path / "short.txt", records))
    )
    records = [record(i, f"00-01-0{i + 1}", high=3600) for i in range(3)] + [record(3, "00-01-04")]
    assert "suspected_balancing_difficulty" not in codes(
        analyze_logs(report(tmp_path / "converged.txt", records))
    )


def test_nominal_capacity_must_be_explicit(tmp_path):
    path = report(
        tmp_path / "history.txt", [record(i, f"00-01-0{i + 1}", high=3600) for i in range(3)]
    )
    path.write_text(
        path.read_text(encoding="utf-16").replace(
            "Specification : 48V/100AH", "Total Coulomb : 100000 mAH"
        ),
        encoding="utf-16",
    )
    result = analyze_logs(path)
    assert result.batteries[0].metrics["nominal_capacity_ah"] is None
    assert "suspected_balancing_difficulty" not in codes(result)


def test_multiple_batteries_address_changes_and_latest_snapshot(tmp_path):
    bundle(
        tmp_path,
        run="a",
        barcode="TEST_A",
        spread=200,
        address=1,
        timestamp="2000-01-01T12:00:00+00:00",
    )
    bundle(tmp_path, run="b", barcode="TEST_A", spread=10, address=4)
    bundle(tmp_path / "nested", run="c", barcode="TEST_B", spread=150)
    result = analyze_logs(tmp_path)
    assert len(result.batteries) == 2
    a, b = result.batteries
    assert a.identity["address"] == 4 and a.metrics["cell_spread_mv"] == 10
    assert a.status == "no_issues_detected" and b.status == "attention"


def test_repeated_collections_combine_distinct_history(tmp_path):
    for i in range(3):
        bundle(tmp_path, run=f"run{i}", records=[record(i, f"00-01-0{i + 1}", high=3600)])
    result = analyze_logs(tmp_path)
    assert len(result.batteries) == 1
    assert "suspected_balancing_difficulty" in codes(result)
    assert result.batteries[0].metrics["historical_records"] == 3


def test_unknown_snapshots_do_not_merge_by_address_or_filename(tmp_path):
    for name in ("TEST_A_snapshot.json", "another.json"):
        (tmp_path / name).write_text(json.dumps(snapshot()))
    result = analyze_logs(tmp_path)
    assert len(result.batteries) == 2
    assert all(b.identity["barcode"] is None for b in result.batteries)
    assert result.exit_code == 1


def test_duplicate_records_and_conflicts_do_not_multiply_evidence(tmp_path):
    first = record(0, high=3600)
    path = report(tmp_path / "duplicates.txt", [first, first, first])
    result = analyze_logs(path)
    assert result.batteries[0].metrics["historical_records"] == 1
    path = report(tmp_path / "conflict.txt", [first, record(0, high=3650)])
    result = analyze_logs(path)
    assert "suspected_balancing_difficulty" not in codes(result)
    assert "Conflicting duplicate" in " ".join(result.batteries[0].limitations)


def test_clock_reversal_and_reset_epochs_withhold_persistence(tmp_path):
    records = [
        record(0, "00-01-03", high=3600),
        record(1, "00-01-02", high=3600),
        record(2, "00-01-04", high=3600),
    ]
    result = analyze_logs(report(tmp_path / "clock.txt", records))
    assert "suspected_balancing_difficulty" not in codes(result)
    assert "timestamps move backwards" in " ".join(result.batteries[0].limitations)
    first = info() + frame("data history 0", record(0, high=3600))
    second = (
        frame("eepe 0")
        + frame("trst")
        + info()
        + frame("data history 1", record(1, "00-01-02", high=3600))
        + frame("data history 2", record(2, "00-01-03", high=3600))
    )
    path = tmp_path / "reset.txt"
    path.write_text(first + "\n" + second)
    result = analyze_logs(path)
    assert "suspected_balancing_difficulty" not in codes(result)


def test_source_specific_fault_masks_are_not_indicator_aliases(tmp_path):
    path = report(tmp_path / "fault.txt", [record(0, mask="0x200")])
    result = analyze_logs(path)
    findings = result.batteries[0].findings
    assert any(f.code == "fault_mask" and "0x200" in f.message for f in findings)
    assert not any("InternalComm" in f.message for f in findings)
    # A known indicator bit in an actual snapshot retains its verified meaning.
    path = bundle(tmp_path, run="indicator")
    snap_path = tmp_path / "indicator_snapshot.json"
    data = json.loads(snap_path.read_text())
    data["modules"][0]["error_code"] = 1
    snap_path.write_text(json.dumps(data))
    result = analyze_logs(path)
    assert any(
        f.code == "indicator_fault" and "Input RV" in f.message
        for f in result.batteries[0].findings
    )


def test_summary_rows_and_unknown_fields(tmp_path):
    text = info() + frame(
        "datalist history 0",
        "Item Time Vo(mV) Cu(mA) Tempr Tlow Thigh Vlowest Vhighest Base.St Volt.St Curr.St Temp.St Per% Events SysErrCode\n0 00-01-01 12:00:00 51800 0 25000 24000 26000 3450 3600 Idle Normal Normal Normal 95% SYSERR 0x200",
    )
    path = tmp_path / "summary.txt"
    path.write_text(text)
    result = analyze_logs(path)
    assert result.batteries[0].metrics["cell_spread_mv"] == 150
    assert result.batteries[0].metrics["lowest_cell_index"] is None
    assert result.batteries[0].metrics["battery_timestamp"].startswith("2000-")


def test_incomplete_collection_and_truncated_report_are_not_healthy(tmp_path):
    manifest = bundle(tmp_path, complete=False)
    result = analyze_logs(manifest)
    assert result.exit_code == 1
    assert any(i["code"] == "incomplete_collection" for i in result.input_issues)
    path = report(tmp_path / "partial.txt", [record(0)], count=3)
    path.write_text(path.read_text(encoding="utf-16")[:-10], encoding="utf-16")
    result = analyze_logs(path)
    assert result.exit_code == 1
    assert {i["code"] for i in result.input_issues} >= {"incomplete_coverage", "truncated_exchange"}


def test_unsafe_manifest_references_and_symlinks(tmp_path):
    outside = tmp_path.parent / f"{tmp_path.name}-outside.json"
    outside.write_text(json.dumps(snapshot(200)))
    manifest = bundle(tmp_path)
    data = json.loads(manifest.read_text())
    data["steps"].append({"artifact": "../" + outside.name, "status": "complete"})
    manifest.write_text(json.dumps(data))
    result = analyze_logs(manifest)
    assert any(i["code"] == "unsafe_artifact" for i in result.input_issues)
    assert result.batteries[0].metrics["cell_spread_mv"] == 10
    link = tmp_path / "linked.json"
    try:
        link.symlink_to(outside)
    except OSError:
        pytest.skip("Symlinks are unavailable")
    with pytest.raises(ValueError, match="symbolic"):
        analyze_logs(link)
    data["steps"].append({"artifact": "linked.json", "status": "complete"})
    manifest.write_text(json.dumps(data))
    assert sum(i["code"] == "unsafe_artifact" for i in analyze_logs(manifest).input_issues) == 2


@pytest.mark.parametrize(
    "payload", [b"\xffnotutf8", b'{"modules":', b'{"modules":[{"voltage_v":NaN}]}']
)
def test_unusable_input_is_an_explicit_report(tmp_path, payload):
    path = tmp_path / "broken.json"
    path.write_bytes(payload)
    result = analyze_logs(path)
    assert result.exit_code == 2 and result.input_issues


def test_console_read_json_and_identity_only_input(tmp_path):
    path = tmp_path / "stat.json"
    path.write_text(
        json.dumps({"command": "stat", "text": frame("stat", "SOH : 75\nCYCLE Times : 500")})
    )
    result = analyze_logs(path)
    assert result.batteries[0].metrics["reported_soh_pct"] == 75
    assert result.exit_code == 1
    path.write_text(json.dumps(identity()))
    assert analyze_logs(path).exit_code == 1


def test_cli_offline_never_connects_and_supports_text_json_output(monkeypatch, tmp_path, capsys):
    path = bundle(tmp_path)

    def unexpected(*args, **kwargs):
        pytest.fail("Offline doctor must not connect")

    monkeypatch.setattr("pylontech_tools.cli.BatteryClient", unexpected)
    assert main(["doctor", str(path)]) == 0
    assert "TEST_A" in capsys.readouterr().out
    assert main(["doctor", str(path), "--format", "json"]) == 0
    assert json.loads(capsys.readouterr().out)["schema_version"] == 1
    output = tmp_path / "doctor.json"
    assert main(["doctor", str(tmp_path), "--format", "json", "--output", str(output)]) == 0
    assert json.loads(output.read_text())["status"] == "no_issues_detected"
    assert main(["doctor", str(path), "--output", str(output)]) == 2
    assert json.loads(output.read_text())["schema_version"] == 1


@pytest.mark.parametrize(
    "args",
    [
        [],
        ["--port", "SYNTHETIC", "input.txt"],
        ["input.txt", "--save-inputs", "out"],
        ["input.txt", "--no-shift"],
        ["--port", "SYNTHETIC", "--module", "1"],
        ["input.txt", "--imbalance-mv", "0"],
    ],
)
def test_invalid_cli_options_before_io(args):
    with pytest.raises(SystemExit):
        main(["doctor", *args])


def online_session(*, log_error=None):
    getpwr = "51800# 0# 25000# 100000# Idle# Normal# Normal# Normal#\n3450# 25000# Normal# Normal#\n3460# 25000# Normal# Normal#\n0# 12#"
    stat = frame("stat", "HisData Items : 0\nData Items : 0\nSOH : 99\nCYCLE Times : 12")
    replies = [
        ("info", Response(info(), "prompt")),
        ("getpwr", Response(frame("getpwr", getpwr), "prompt")),
        ("pwr", Response(frame("pwr", "Power 1\nVoltage : 51800 mV\nCoulomb : 95 %"), "prompt")),
        (
            "pwrsys",
            Response(
                frame(
                    "pwrsys", "Recommend Chg Current : 10000 mA\nRecommend Dsg Current : -10000 mA"
                ),
                "prompt",
            ),
        ),
        ("stat", Response(stat, "prompt")),
        ("time", Response(frame("time", "00-01-01 12:00:00"), "prompt")),
        ("config", Response(frame("config", "bsv : 3400\nbv : 30"), "prompt")),
        ("log", log_error or Response(frame("log"), "prompt")),
    ]
    for kind in ("history", "event"):
        replies += [
            ("info", Response(info(), "prompt")),
            ("stat", Response(stat, "prompt")),
            (f"data {kind}", Response(frame(f"data {kind}"), "prompt")),
        ]
    session = ScriptedSession(replies)
    session.synchronized = True
    session.current_prompt = "pylon_debug>"
    return session


def test_online_read_sequence_saved_inputs_and_offline_equivalence(tmp_path):
    session = online_session()
    client = BatteryClient(session=session, monitoring_mode="parallel")
    result = client.doctor(save_inputs=tmp_path)
    assert isinstance(result, DoctorReport) and result.exit_code == 0
    assert client.monitoring_mode == "parallel"
    assert [cmd for cmd, _ in session.calls] == [
        "info",
        "getpwr",
        "pwr",
        "pwrsys",
        "stat",
        "time",
        "config",
        "log",
        "info",
        "stat",
        "data history",
        "info",
        "stat",
        "data event",
    ]
    manifest = next(tmp_path.glob("*_doctor_manifest.json"))
    assert result.to_dict() == analyze_logs(manifest).to_dict()
    previous = {p.name: p.read_bytes() for p in tmp_path.iterdir()}
    BatteryClient(session=online_session()).doctor(save_inputs=tmp_path)
    assert all((tmp_path / name).read_bytes() == data for name, data in previous.items())
    assert len(list(tmp_path.glob("*_doctor_manifest.json"))) == 2


def test_online_continues_after_rejection(tmp_path):
    session = online_session(
        log_error=UnsupportedCommand("unsupported", response=frame("log", "Unknown command"))
    )
    result = BatteryClient(session=session).doctor(save_inputs=tmp_path)
    assert result.exit_code == 1 and result.batteries
    assert session.calls[-1][0] == "data event"
    assert any(i["code"] == "incomplete_collection" for i in result.input_issues)


def test_online_timeout_requires_resynchronization_and_stops_without_prompt(tmp_path):
    session = online_session(log_error=CommandTimeout("timeout", response="partial"))
    # Failure injection gives the state a real timeout leaves behind.
    original = session.exchange

    def exchange(command, **kwargs):
        if command == "log":
            session.synchronized = False
        return original(command, **kwargs)

    session.exchange = exchange

    def fail_sync(**kwargs):
        raise CommandTimeout("No prompt")

    session.resynchronize = fail_sync
    result = BatteryClient(session=session).doctor(save_inputs=tmp_path)
    assert result.exit_code == 1
    assert session.calls[-1][0] == "log"
    manifest = json.loads(next(tmp_path.glob("*_doctor_manifest.json")).read_text())
    assert [s["status"] for s in manifest["steps"]][-2:] == ["skipped", "skipped"]


def test_online_cancellation_retains_saved_evidence_and_restores_mode(tmp_path):
    session = online_session(log_error=CommandCancelled("cancelled", response="partial"))
    client = BatteryClient(session=session, monitoring_mode="auto")
    with pytest.raises(CommandCancelled):
        client.doctor(save_inputs=tmp_path)
    assert client.monitoring_mode == "auto"
    manifest = json.loads(next(tmp_path.glob("*_doctor_manifest.json")).read_text())
    assert manifest["status"] == "interrupted"
    assert any(s["status"] == "interrupted" for s in manifest["steps"])
    assert any(p.read_text() == "partial" for p in tmp_path.glob("*partial.txt"))


def test_direct_only_and_unconnected_before_files(tmp_path):
    with pytest.raises(ValueError, match="direct"):
        BatteryClient(session=online_session(), module=2).doctor(save_inputs=tmp_path / "out")
    assert not (tmp_path / "out").exists()
    with pytest.raises(Exception, match="not connected"):
        BatteryClient("SYNTHETIC").doctor(save_inputs=tmp_path / "out")
    assert not (tmp_path / "out").exists()


def compact_record(index, date="00-02-01", *, state="Idle", high_cell=None, low_cell=None, base=1):
    # Synthetic three-cell detailed layout: 15 module tokens, then six per cell.
    voltages = [3440, 3445, 3442]
    if high_cell is not None:
        voltages[high_cell] = 3680
    if low_cell is not None:
        voltages[low_cell] = 3200
    prefix = [
        "51300",
        "0",
        "22000",
        "21000",
        "23000",
        str(min(voltages)),
        str(max(voltages)),
        state,
        "Normal",
        "Normal",
        "Normal",
        "0x0",
        "Normal",
        "92%",
        "0",
    ]
    values = list(prefix)
    for cell, voltage in enumerate(voltages):
        volt_state = "High" if cell == high_cell else "Low" if cell == low_cell else "Normal"
        values += [str(cell + base), str(voltage), "22000", volt_state, "Normal", "92%"]
    return f"{index} {date} 12:00:00 " + " ".join(values)


def compact_log(path, barcode, rows):
    text = info(barcode).replace("Cell Number : 2", "Cell Number : 3")
    text += frame("stat", f"HisData Items : {len(rows)}\nData Items : 0")
    text += frame("datalist history dtls 0", "\n".join(rows))
    path.write_text(text, encoding="utf-16")
    return path


@pytest.mark.parametrize("base", [0, 1])
def test_compact_detail_cell_layout_and_index_normalization(tmp_path, base):
    path = compact_log(
        tmp_path / "compact.txt", "TEST_COMPACT", [compact_record(0, low_cell=2, base=base)]
    )
    result = analyze_logs(path)
    assert not result.input_issues
    battery = result.batteries[0]
    assert battery.metrics["lowest_cell_index"] == 2
    assert battery.metrics["highest_cell_index"] == 1
    assert battery.metrics["cell_spread_mv"] == 245
    assert "historical_cell_low_voltage" in codes(result)


def test_historical_findings_remain_visible_when_snapshot_is_quiet(tmp_path):
    rows = [
        compact_record(
            i, f"00-02-0{i + 1}", high_cell=0 if i % 2 else None, low_cell=2 if i % 2 == 0 else None
        )
        for i in range(4)
    ]
    path = compact_log(tmp_path / "history.txt", "TEST_RECURRENT", rows)
    manifest = bundle(tmp_path, barcode="TEST_RECURRENT")
    data = json.loads(manifest.read_text())
    data["device"]["cell_count"] = 3
    # Keep a complete current sample while historical alarms still require attention.
    snap_path = tmp_path / "one_snapshot.json"
    snap = json.loads(snap_path.read_text())
    snap["modules"][0]["cells"].append(asdict(CellReading(2, voltage_v=3.455)))
    snap_path.write_text(json.dumps(snap))
    data["steps"].append({"name": "history", "artifact": path.name, "status": "complete"})
    manifest.write_text(json.dumps(data))
    result = analyze_logs(tmp_path)
    assert len(result.batteries) == 1 and result.exit_code == 1
    assert result.batteries[0].metrics["cell_spread_mv"] == 10
    assert {
        "historical_cell_high_voltage",
        "historical_cell_low_voltage",
        "historical_cell_voltage_spread",
    } <= codes(result)


def test_historical_system_error_is_a_warning_without_bit_guessing(tmp_path):
    path = compact_log(
        tmp_path / "system.txt", "TEST_SYSTEM", [compact_record(0, state="SysError")]
    )
    result = analyze_logs(path)
    assert "historical_system_fault" in codes(result)
    finding = next(f for f in result.batteries[0].findings if f.code == "historical_system_fault")
    assert finding.severity == "warning" and "investigate" in finding.message


def test_individual_files_for_same_barcode_merge_without_manifests(tmp_path):
    compact_log(tmp_path / "unrelated_name.txt", "TEST_MERGE", [compact_record(0, low_cell=0)])
    compact_log(
        tmp_path / "another_name.txt", "TEST_MERGE", [compact_record(1, "00-02-02", high_cell=2)]
    )
    result = analyze_logs(tmp_path)
    assert len(result.batteries) == 1
    assert result.batteries[0].metrics["source_count"] == 2
    assert {"historical_cell_high_voltage", "historical_cell_low_voltage"} <= codes(result)


def test_rack_auxiliary_entries_do_not_create_anonymous_duplicate_batteries(tmp_path):
    manifest = bundle(tmp_path, barcode="TEST_LOCAL")
    path = tmp_path / "one_snapshot.json"
    data = json.loads(path.read_text())
    other = dict(data["modules"][0])
    other["address"] = 2
    data["modules"].append(other)
    path.write_text(json.dumps(data))
    result = analyze_logs(manifest)
    assert len(result.batteries) == 1 and result.batteries[0].identity["barcode"] == "TEST_LOCAL"
    assert any("Auxiliary rack" in note for note in result.batteries[0].limitations)
    # A standalone rack snapshot remains anonymous, with no inferred barcode mapping.
    assert len(analyze_logs(path).batteries) == 2


def test_conflicting_barcodes_in_one_file_remain_isolated(tmp_path):
    path = tmp_path / "mixed.txt"
    path.write_text(
        info("TEST_FIRST")
        + frame("data event 0", record(0))
        + info("TEST_SECOND")
        + frame("data event 0", record(0, high=3600))
    )
    result = analyze_logs(path)
    assert len(result.batteries) == 2
    assert all(b.identity["barcode"] is None for b in result.batteries)
    assert any(i["code"] == "identity_conflict" for i in result.input_issues)


def test_truncated_compact_cells_cannot_qualify_as_balancing_evidence(tmp_path):
    rows = [compact_record(i, f"00-02-0{i + 1}", high_cell=0).rsplit(" ", 6)[0] for i in range(3)]
    result = analyze_logs(compact_log(tmp_path / "truncated.txt", "TEST_INCOMPLETE", rows))
    assert "suspected_balancing_difficulty" not in codes(result)
    assert result.input_issues


def test_doctor_text_escapes_control_characters(tmp_path):
    path = bundle(tmp_path, barcode="TEST_\x1b[31m")
    text = format_doctor(analyze_logs(path))
    assert "\x1b" not in text and "\\x1b" in text


def test_missing_artifact_partial_directory_and_unrelated_files(tmp_path):
    path = bundle(tmp_path)
    data = json.loads(path.read_text())
    data["steps"].append({"name": "event", "status": "complete", "artifact": "missing.txt"})
    path.write_text(json.dumps(data))
    (tmp_path / "notes.txt").write_text("Unrelated notes")
    (tmp_path / "unrelated.json").write_text("not json")
    result = analyze_logs(tmp_path)
    assert len(result.batteries) == 1 and result.exit_code == 1
    assert len(result.input_issues) == 1 and result.input_issues[0]["source"] == "missing.txt"


def test_event_and_history_cannot_count_one_instant_twice(tmp_path):
    rows = [record(0, "00-03-01", high=3650), record(1, "00-03-03", high=3650)]
    path = report(tmp_path / "both.txt", rows)
    text = path.read_text(encoding="utf-16") + frame("datalist event dtls 0", "\n".join(rows))
    path.write_text(text, encoding="utf-16")
    result = analyze_logs(path)
    assert "suspected_balancing_difficulty" not in codes(result)


def test_successful_resync_continues_without_replaying_failed_read(tmp_path):
    session = online_session(log_error=CommandTimeout("timeout", response="partial"))
    original = session.exchange

    def exchange(command, **kwargs):
        if command == "log":
            session.synchronized = False
        return original(command, **kwargs)

    session.exchange = exchange

    def sync(**kwargs):
        session.synchronized = True
        session.current_prompt = "pylon_debug>"
        return Response("pylon_debug>", "prompt")

    session.resynchronize = sync
    result = BatteryClient(session=session).doctor(save_inputs=tmp_path)
    assert result.exit_code == 1
    assert [c for c, _ in session.calls].count("log") == 1 and session.calls[-1][0] == "data event"


def test_default_online_temp_inputs_are_removed(monkeypatch):
    import pylontech_tools.doctor_acquisition as acquisition

    seen = []
    analyze = acquisition.analyze_logs

    def track(path, **kwargs):
        seen.append(Path(path).parent)
        assert Path(path).is_file()
        return analyze(path, **kwargs)

    monkeypatch.setattr(acquisition, "analyze_logs", track)
    assert BatteryClient(session=online_session()).doctor().exit_code == 0
    assert seen and not seen[0].exists()


def test_online_cli_defaults_and_connection_error_status(monkeypatch, tmp_path, capsys):
    session = online_session()

    def client(*args, **kwargs):
        return BatteryClient(session=session, **kwargs)

    monkeypatch.setattr("pylontech_tools.cli.BatteryClient", client)
    assert main(["doctor", "--port", "SYNTHETIC", "--save-inputs", str(tmp_path)]) == 0
    assert "TEST_A" in capsys.readouterr().out

    def fail(*args, **kwargs):
        raise OSError("synthetic connection failure")

    monkeypatch.setattr("pylontech_tools.cli.BatteryClient", fail)
    assert main(["doctor", "--port", "SYNTHETIC"]) == 2


def test_manifest_transition_cancellation_does_not_claim_prior_artifact(monkeypatch, tmp_path):
    import pylontech_tools.doctor_acquisition as acquisition

    write = acquisition._write_manifest
    interrupted = False

    def cancel(path, data, **kwargs):
        nonlocal interrupted
        if not interrupted and data["steps"][1]["status"] == "running":
            interrupted = True
            raise KeyboardInterrupt()
        return write(path, data, **kwargs)

    monkeypatch.setattr(acquisition, "_write_manifest", cancel)
    with pytest.raises(KeyboardInterrupt):
        BatteryClient(session=online_session()).doctor(save_inputs=tmp_path)
    data = json.loads(next(tmp_path.glob("*_doctor_manifest.json")).read_text())
    assert data["steps"][0]["artifact"]
    assert data["steps"][1]["artifact"] is None
    assert data["steps"][1]["status"] == "interrupted"


def test_manifest_can_use_verified_identity_artifact_when_device_is_missing(tmp_path):
    manifest = bundle(tmp_path)
    ident = tmp_path / "identity.json"
    ident.write_text(json.dumps(identity()))
    data = json.loads(manifest.read_text())
    data["device"] = None
    data["steps"].append({"name": "identity", "status": "complete", "artifact": ident.name})
    manifest.write_text(json.dumps(data))
    result = analyze_logs(manifest)
    assert len(result.batteries) == 1 and result.batteries[0].identity["barcode"] == "TEST_A"
    assert result.exit_code == 0


def test_disagreeing_manifest_identity_does_not_attribute_snapshot(tmp_path):
    manifest = bundle(tmp_path)
    ident = tmp_path / "identity.json"
    ident.write_text(json.dumps(identity("TEST_OTHER")))
    data = json.loads(manifest.read_text())
    data["steps"].append({"name": "identity", "status": "complete", "artifact": ident.name})
    manifest.write_text(json.dumps(data))
    result = analyze_logs(manifest)
    assert any(i["code"] == "identity_conflict" for i in result.input_issues)
    assert not any(
        b.identity["barcode"] and b.metrics.get("cell_spread_mv") is not None
        for b in result.batteries
    )


def test_conflicting_snapshot_copies_with_same_time_do_not_select_one(tmp_path):
    bundle(tmp_path, run="a", spread=10)
    bundle(tmp_path, run="b", spread=180)
    result = analyze_logs(tmp_path)
    assert result.exit_code == 1
    assert result.batteries[0].metrics["cell_spread_mv"] is None
    assert "Conflicting duplicate" in " ".join(result.batteries[0].limitations)


def test_labeled_system_fault_does_not_use_indicator_mapping(tmp_path):
    path = bundle(tmp_path)
    source = tmp_path / "one_snapshot.json"
    data = json.loads(source.read_text())
    data["modules"][0]["error_code"] = 1
    data["modules"][0]["raw"] = {"System Fault": "0x1"}
    source.write_text(json.dumps(data))
    result = analyze_logs(path)
    assert "fault_mask" in codes(result) and "indicator_fault" not in codes(result)
