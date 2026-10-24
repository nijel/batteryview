import pytest
from conftest import ScriptedSession

from batteryview import BatteryClient, ProtocolError, UnsupportedCommand
from batteryview.parsers import parse_getpwr, parse_info, parse_pwr
from batteryview.protocol import Response

PWR = (
    "pwr\n\r@\r\nPower Volt Curr Tempr Base.St Volt.St Curr.St Temp.St Coulomb FutureField\r\n"
    "1 50000 -2000 -5000 Dischg Normal Normal Low 50% novel\r\n"
    "2 50000 1234 25000 Charge High Normal Normal 55% other\r\n\rpylon_debug>"
)
GETPWR = (
    "getpwr\n\r@\r\n50000# -2000# -5000# 100000# Dischg# Normal# Normal# Low#\r\n"
    "3101# 20000# Normal# Normal#\r\n3102# -3000# High# Low#\r\n"
    "Command completed successfully\r\n\r$$\r\n\rpylon_debug>"
)


def test_pwr_units_unknown_columns_and_alarms():
    modules = parse_pwr(PWR)
    assert len(modules) == 2
    assert modules[0].voltage_v == 50
    assert modules[0].current_a == -2
    assert modules[0].temperature_c == -5
    assert modules[0].soc_pct == 50
    assert modules[0].raw["FutureField"] == "novel"
    assert modules[0].alarms[0].code == "Low"
    assert modules[1].alarms[0].severity == "warning"


def test_getpwr_variable_cells_and_unit_conversion():
    module = parse_getpwr(GETPWR, address=1)
    assert module.voltage_v == 50
    assert module.current_a == -2
    assert module.capacity_ah == 100
    assert len(module.cells) == 2
    assert module.cells[0].voltage_v == 3.101
    assert module.cells[1].temperature_c == -3
    assert module.cells[0].current_a is None
    assert any(alarm.cell == 1 and alarm.code == "High" for alarm in module.alarms)


def test_getpwr_error_bits_cycles_and_unknown_bits():
    code = (1 << 3) | (1 << 14)
    text = GETPWR.replace(
        "Command completed successfully", f"{code}# 7#\r\nCommand completed successfully"
    )
    module = parse_getpwr(text)
    assert module.error_code == code and module.cycle_count == 7
    assert any(a.code == "BMIC ERR" and a.severity == "error" for a in module.alarms)
    assert any(a.code == "Unknown error bit 14" and a.severity == "unknown" for a in module.alarms)


def test_getpwr_labelled_response_with_cell_table():
    text = (
        "Voltage : 50000 mV\r\r\nCurrent : -2000 mA\r\r\nTemperature : 20000 mC\r\r\n"
        "Battery Volt Curr Tempr Base State Volt. State Curr. State Temp. State Coulomb\r\r\n"
        "0 3101 -2000 20000 Dischg Normal Normal Normal 50%\r\r\n"
    )
    module = parse_getpwr(text)
    assert module.current_a == -2
    assert module.cells[0].soc_pct == 50


def test_unknown_state_is_preserved_and_missing_values_are_not_zero():
    module = parse_pwr(PWR.replace("-2000", "----").replace("Low", "NewFault"))[0]
    assert module.current_a is None
    assert module.alarms[0].severity == "unknown"
    assert module.states["Temp.St"] == "NewFault"


def test_info_preserves_new_firmware_fields_and_short_date():
    info = parse_info(
        "Device name : SYNTHETIC_MODEL\r\nBarcode : TEST\r\nRelease Date : 00-01-01\r\nNew field : value"
    )
    assert info.address is None
    assert info.fields["Release Date"] == "00-01-01"
    assert info.fields["New field"] == "value"


def test_snapshot_chain_addressing_and_optional_command():
    session = ScriptedSession(
        [
            ("pwr", Response(PWR, "prompt")),
            ("getpwr 1", Response(GETPWR, "prompt")),
            (
                "pwrsys 1",
                Response(
                    "Recommend chg current : 10000\r\nRecommend dsg current : -20000", "prompt"
                ),
            ),
            ("getpwr 2", Response(GETPWR, "prompt")),
            ("pwrsys 2", UnsupportedCommand("unsupported", response="Invalid command")),
        ]
    )
    result = BatteryClient(session=session).snapshot()
    assert result.modules[0].recommended_charge_a == 10
    assert result.modules[0].recommended_discharge_a == -20
    assert result.modules[1].recommended_charge_a is None
    assert result.raw_responses["pwrsys 2"] == "Invalid command"
    assert not session.exchanges


def test_explicit_module_does_not_read_other_module():
    session = ScriptedSession(
        [
            ("pwr", Response(PWR, "prompt")),
            ("getpwr 2", Response(GETPWR, "prompt")),
            ("pwrsys 2", Response("Recommend chg current : 10000", "prompt")),
        ]
    )
    result = BatteryClient(session=session, module=2).snapshot()
    assert [module.address for module in result.modules] == [2]
    assert not session.exchanges


def test_malformed_monitoring_fails_without_fabricated_readings():
    with pytest.raises(ProtocolError):
        parse_getpwr("not measurements")
    with pytest.raises(ProtocolError):
        parse_pwr("not a table")


def test_watch_count_and_interval(monkeypatch):
    client = BatteryClient(session=ScriptedSession([]))
    monkeypatch.setattr(client, "snapshot", lambda: "snapshot")
    monkeypatch.setattr("batteryview.client.time.sleep", lambda _: None)
    assert list(client.watch(count=2)) == ["snapshot", "snapshot"]
    with pytest.raises(ValueError):
        next(client.watch(interval=0))
