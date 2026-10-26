"""Fault masks and protocol words are constants; all observations are invented."""

import json

import pytest
from test_doctor import bundle, frame, info, record

from pylontech_tools import analyze_logs
from pylontech_tools.faults import decode_faults, describe_faults, fault_severity


@pytest.mark.parametrize("source", ["System Fault", "SysErrCode", "ErrCode"])
def test_fault_word_aliases_decode_internal_presence(source):
    result = decode_faults(0x200, source)
    assert result["namespace"] == "system_fault"
    assert result["raw_mask"] == "0x200" and result["unknown_mask"] == "0x0"
    assert result["decoded_bits"][0]["code"] == "internal_communication"
    assert "five consecutive" in result["decoded_bits"][0]["explanation"]
    assert "undecoded" not in describe_faults(result)


def test_combined_known_and_unknown_bits_preserve_only_unknown_remainder():
    result = decode_faults(0x80000240, "System Fault")
    assert {bit["code"] for bit in result["decoded_bits"]} == {
        "internal_communication",
        "voltage_sensor",
    }
    assert result["unknown_mask"] == "0x80000000"
    assert "undecoded system fault bits 0x80000000" in describe_faults(result)
    assert result["raw_mask"] == "0x80000240"


@pytest.mark.parametrize("source", ["Power Events", "Bat Events", "unverified_field"])
def test_unrelated_fields_do_not_borrow_fault_word_meanings(source):
    result = decode_faults(0x200, source)
    assert not result["decoded_bits"] and result["unknown_mask"] == "0x200"
    assert result["namespace"] == "event_flags" and fault_severity(result) == "info"
    assert "communication" not in describe_faults(result)


def test_getpwr_source_and_model_choose_firmware_or_vendor_indicator_layout():
    traced = decode_faults(0x4, "getpwr", model="US3000C")
    legacy = decode_faults(0x4, "getpwr", model="SYNTHETIC_MODEL")
    assert traced["decoded_bits"][0]["code"] == "rtc_error"
    assert legacy["decoded_bits"][0]["label"] == "Hardware Version Err"
    assert "vendor indicator mapping" in describe_faults(legacy)
    assert "RTC" in describe_faults(traced)


def test_different_measurement_hardware_and_up2500_fuse_indicator_are_not_aliases():
    reviewed = decode_faults(0x1000, "System Fault")
    up2500 = decode_faults(0x1000, "getpwr", model="UP2500")
    assert reviewed["decoded_bits"][0]["code"] == "measurement_ic"
    assert (
        "E2" in reviewed["decoded_bits"][0]["explanation"]
        and "C labels" in reviewed["decoded_bits"][0]["explanation"]
    )
    assert up2500["decoded_bits"][0]["code"] == "fuse_indicator"


@pytest.mark.parametrize("mask", [0x8000000, 0x20000000, 0x28000000])
def test_operational_flags_alone_are_information(mask):
    decoded = decode_faults(mask, "System Fault")
    assert decoded["unknown_mask"] == "0x0"
    assert all(bit["kind"] == "status" for bit in decoded["decoded_bits"])
    assert fault_severity(decoded) == "info"
    assert fault_severity(decode_faults(mask | 0x200, "System Fault")) == "warning"


@pytest.mark.parametrize("mask", [0x10, 0x80])
def test_unproven_firmware_bits_do_not_inherit_old_indicator_labels(mask):
    decoded = decode_faults(mask, "System Fault")
    assert not decoded["decoded_bits"]
    assert int(decoded["unknown_mask"], 16) == mask


@pytest.mark.parametrize("bad", [-1, True, 0.5, "512"])
def test_invalid_masks_rejected(bad):
    with pytest.raises(ValueError):
        decode_faults(bad, "System Fault")


def test_zero_word_has_no_fault_or_unknown_bits():
    result = decode_faults(0, "System Fault")
    assert not result["decoded_bits"] and result["unknown_mask"] == "0x0"
    assert fault_severity(result) == "info"


def test_historical_communication_fault_has_specific_text_and_structured_evidence(tmp_path):
    path = tmp_path / "record.txt"
    path.write_text(info() + frame("data event 0", record(0, mask="0x200")), encoding="utf-16")
    report = analyze_logs(path)
    finding = next(f for f in report.batteries[0].findings if f.code == "historical_system_fault")
    assert "Internal communication/presence fault" in finding.message
    assert "five consecutive presence checks" in finding.message
    assert "Unknown fault bits" not in finding.message and "undecoded" not in finding.message
    assert finding.details["faults"][0]["unknown_mask"] == "0x0"
    assert finding.details["faults"][0]["observations"] == 1
    assert report.schema_version == 1 and report.rules_version == 2


def test_state_only_error_has_no_invented_bit_meaning(tmp_path):
    path = tmp_path / "state.txt"
    path.write_text(info() + frame("data event 0", record(0, state="SysError")))
    report = analyze_logs(path)
    finding = next(f for f in report.batteries[0].findings if f.code == "historical_system_fault")
    assert finding.details["state_only_observations"] == 1
    assert "no nonzero detailed fault code" in finding.message
    assert (
        "Internal communication" not in finding.message
        and "Unknown fault bits" not in finding.message
    )


def test_current_unknown_remainder_is_available_in_json(tmp_path):
    manifest = bundle(tmp_path)
    path = tmp_path / "one_snapshot.json"
    data = json.loads(path.read_text())
    data["modules"][0]["raw"] = {"System Fault": "0x80000200"}
    path.write_text(json.dumps(data))
    report = analyze_logs(manifest)
    finding = next(f for f in report.batteries[0].findings if f.code == "fault_mask")
    assert finding.details["faults"][0]["unknown_mask"] == "0x80000000"
    assert "Internal communication/presence fault" in finding.message


def test_repeated_representations_count_the_same_word_once(tmp_path):
    row = "0 00-01-01 12:00:00 51800 0 25000 25000 25000 3450 3460 Idle Normal Normal Normal 0x200 Normal 95% 100000 1 3450 25000 Normal Normal 95% 2 3460 25000 Normal Normal 95%"
    path = tmp_path / "aliases.txt"
    path.write_text(
        info()
        + frame("data history 0", record(0, mask="0x200"))
        + frame("datalist history dtls 0", row)
    )
    report = analyze_logs(path)
    finding = next(f for f in report.batteries[0].findings if f.code == "historical_system_fault")
    masks = finding.details["faults"]
    assert len(masks) == 1 and masks[0]["observations"] == 1
    assert masks[0]["source_fields"] == ["ErrCode", "System Fault"]


def test_summary_code_is_not_lost_when_recommended_current_columns_follow(tmp_path):
    path = tmp_path / "summary.txt"
    row = "0 00-01-01 12:00:00 51800 0 25000 24000 26000 3450 3460 SysError Normal Normal Normal 95% SYSERR 0x200 10/ 12 20/ 24"
    path.write_text(info() + frame("datalist event 0", row))
    finding = next(
        f for f in analyze_logs(path).batteries[0].findings if f.code == "historical_system_fault"
    )
    assert finding.details["faults"][0]["raw_mask"] == "0x200"
    assert finding.details["faults"][0]["source_fields"] == ["SysErrCode"]


def test_historical_operational_flags_do_not_create_a_hardware_alarm(tmp_path):
    path = tmp_path / "shutdown.txt"
    path.write_text(info() + frame("data event 0", record(0, mask="0x8000000")))
    report = analyze_logs(path)
    finding = next(f for f in report.batteries[0].findings if f.code == "historical_system_fault")
    assert finding.severity == "info" and report.exit_code == 0
    assert "Shutdown requested" in finding.message
