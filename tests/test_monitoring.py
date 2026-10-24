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

# Constructed example: labels follow the protocol, values and address are invented.
PWR_LABELED = (
    "pwr\n\r@\r\r\n ----------------------------\r\r\n Power  8\r\r\n"
    " Voltage : 51000 mV\r\r\n Current : -4000 mA\r\r\n"
    " Temperature : -2000 mC\r\r\n Coulomb : 40 %\r\r\n"
    " Total Coulomb : 120000 mAH\r\r\n Basic Status : Dischg\r\r\n"
    " Volt Status : Normal\r\r\n Current Status : Normal\r\r\n"
    " Tmpr. Status : Normal\r\r\n Coul. Status : Normal\r\r\n"
    " Soh. Status : Normal\r\r\n Heater Status : OFF\r\r\n"
    " Protect ENA : BOV BUV\r\r\n Bat Events : 0x0\r\r\n"
    " Power Events : 0x0\r\r\n System Fault : 0x0\r\r\n"
    " Future field : SYNTHETIC_VALUE\r\r\n ----------------------------\r\n"
    "\rCommand completed successfully\r\n\r$$\r\n\rpylon_debug>"
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


def test_labeled_pwr_preserves_module_address_units_statuses_and_raw_fields(caplog):
    import logging

    with caplog.at_level(logging.DEBUG, logger="batteryview.parsers"):
        modules = parse_pwr(PWR_LABELED)
    assert len(modules) == 1
    module = modules[0]
    assert module.address == 8
    assert module.voltage_v == 51
    assert module.current_a == -4
    assert module.temperature_c == -2
    assert module.soc_pct == 40
    assert module.capacity_ah == 120
    assert module.states == {
        "Base.St": "Dischg",
        "Volt.St": "Normal",
        "Curr.St": "Normal",
        "Temp.St": "Normal",
        "Coul.St": "Normal",
        "Soh.St": "Normal",
        "H.St": "OFF",
    }
    assert not module.alarms
    assert module.raw["Power"] == "8"
    assert module.raw["Voltage"] == "51000 mV"
    assert module.raw["Heater Status"] == "OFF"
    assert module.raw["Protect ENA"] == "BOV BUV"
    assert module.raw["System Fault"] == "0x0"
    assert module.raw["Future field"] == "SYNTHETIC_VALUE"
    assert "Parsed pwr format=labeled module_count=1" in caplog.text
    assert "SYNTHETIC_VALUE" not in caplog.text


def test_labeled_pwr_optional_fields_remain_absent():
    module = parse_pwr("Power 8\r\r\nVoltage : 51000 mV\r\r\n")[0]
    assert module.address == 8 and module.voltage_v == 51
    assert module.current_a is None and module.temperature_c is None
    assert module.soc_pct is None and module.capacity_ah is None
    assert not module.states and not module.alarms


@pytest.mark.parametrize(
    "text",
    [
        "Voltage : 51000 mV",
        "Power other\nVoltage : 51000 mV",
        "Power 8\nCurrent : -4000 mA",
        "Power 8\nVoltage : unknown",
    ],
)
def test_malformed_labeled_pwr_is_not_a_successful_empty_module(text):
    with pytest.raises(ProtocolError) as error:
        parse_pwr(text)
    assert error.value.response == text


def test_labeled_pwr_blocks_do_not_mix_module_fields():
    modules = parse_pwr(
        "Power 8\nVoltage : 51000 mV\nCurrent : -4000 mA\nPower 9\nVoltage : 52000 mV\n"
    )
    assert [module.address for module in modules] == [8, 9]
    assert [module.voltage_v for module in modules] == [51, 52]
    assert modules[0].current_a == -4 and modules[1].current_a is None


@pytest.mark.parametrize(
    "label,value,key,severity",
    [
        ("Volt Status", "High", "Volt.St", "warning"),
        ("Current Status", "DOC", "Curr.St", "error"),
        ("Tmpr. Status", "NewFault", "Temp.St", "unknown"),
    ],
)
def test_labeled_pwr_statuses_feed_existing_alarm_mapping(label, value, key, severity):
    module = parse_pwr(PWR_LABELED.replace(f"{label} : Normal", f"{label} : {value}"))[0]
    assert module.states[key] == value
    assert any(
        a.source == f"module.{key}" and a.code == value and a.severity == severity
        for a in module.alarms
    )


@pytest.mark.parametrize("capacity,expected", [(None, 120), (0, 0), (130000, 130)])
def test_single_labeled_module_snapshot_uses_connected_console_and_capacity_fallback(
    replay, capacity, expected
):
    detailed = (
        "getpwr\n\r@\r\r\nVoltage : 52000 mV\r\r\nCurrent : -3000 mA\r\r\n"
        "Temperature : 10000 mC\r\r\n"
        + (f"Total Coulomb : {capacity} mAH\r\r\n" if capacity is not None else "")
        + "Battery Volt Curr Tempr Base State Volt. State Curr. State Temp. State Coulomb\r\r\n"
        "0 3201 -3000 15000 Dischg Normal Normal Normal 45%\r\r\n\rpylon_debug>"
    )
    unsupported = "pwrsys\n\r@\r\r\nUnknown command 'pwrsys' - try 'help'\r\n\rpylon_debug>"
    session, transport = replay(
        [
            (b"getpwr\n", detailed),
            (b"pwr\n", PWR_LABELED),
            (b"pwrsys\n", unsupported),
            (b"cmdquit\n", "cmdquit\n\r"),
        ]
    )
    with BatteryClient(session=session, profile="generic") as client:
        snapshot = client.snapshot()
    assert len(snapshot.modules) == 1
    module = snapshot.modules[0]
    assert module.address == 8
    assert module.voltage_v == 52 and module.current_a == -3
    assert module.soc_pct == 40 and module.capacity_ah == expected
    assert module.states["Base.St"] == "Dischg"
    assert module.cells[0].voltage_v == 3.201
    assert module.recommended_charge_a is None
    assert snapshot.raw_responses["pwrsys"] == unsupported
    assert snapshot.raw_responses["pwr"] == PWR_LABELED
    assert module.raw["Future field"] == "SYNTHETIC_VALUE"
    assert transport.writes == [b"getpwr\n", b"pwr\n", b"pwrsys\n", b"cmdquit\n"]
    assert transport.closed and not transport.exchanges


def test_explicit_labeled_module_selection_keeps_addressed_queries():
    session = ScriptedSession(
        [
            ("getpwr 8", Response(GETPWR, "prompt")),
            ("pwr 8", Response(PWR_LABELED, "prompt")),
            ("pwrsys 8", Response("Recommend chg current : 10000", "prompt")),
            ("pwrsys", Response("system Recommend chg current : 20000", "prompt")),
        ]
    )
    snapshot = BatteryClient(session=session, module=8, profile="generic").snapshot()
    assert [module.address for module in snapshot.modules] == [8]
    assert not session.exchanges


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
            ("getpwr", Response(GETPWR, "prompt")),
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
            ("pwrsys", Response("system Recommend chg current : 20000", "prompt")),
        ]
    )
    result = BatteryClient(session=session, profile="generic").snapshot()
    assert result.modules[0].recommended_charge_a == 10
    assert result.modules[0].recommended_discharge_a == -20
    assert result.modules[1].recommended_charge_a is None
    assert result.raw_responses["pwrsys 2"] == "Invalid command"
    assert not session.exchanges


def test_explicit_module_does_not_read_other_module():
    session = ScriptedSession(
        [
            ("getpwr 2", Response(GETPWR, "prompt")),
            (
                "pwr 2",
                Response(
                    PWR.replace("1 50000 -2000 -5000 Dischg Normal Normal Low 50% novel\r\n", ""),
                    "prompt",
                ),
            ),
            ("pwrsys 2", Response("Recommend chg current : 10000", "prompt")),
            ("pwrsys", Response("system Recommend chg current : 20000", "prompt")),
        ]
    )
    result = BatteryClient(session=session, module=2, profile="generic").snapshot()
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
