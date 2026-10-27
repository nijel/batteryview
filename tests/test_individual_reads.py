"""Invented responses for passive Python APIs; no hardware recordings."""

from dataclasses import asdict
from datetime import datetime

import pytest
from conftest import ScriptedSession
from test_monitoring import GETPWR, PWR
from test_read_commands import response
from test_reports import INFO, reply

import pylontech_tools as api
from pylontech_tools import BatteryClient, ProtocolError, UnsupportedCommand
from pylontech_tools.diagnostics import command_label
from pylontech_tools.errors import CommandCancelled, CommandTimeout
from pylontech_tools.protocol import CONTINUATION, Response
from pylontech_tools.reads import CONFIG_QUERIES, CONTROL_QUERIES

# Independent command expectations protect the passive-wire contract.
BARE = [
    ("communication_info", "ci", api.CommunicationResult),
    ("unit_baud_rate", "urates", api.CommunicationResult),
    ("inverter_protocol", "setprt", api.CommunicationResult),
    ("lg_configuration", "lg", api.CommunicationResult),
    ("nominal_capacity", "totalcoul", api.CapacityResult),
    ("cycle_statistics", "tcycle", api.CapacityResult),
    ("empty_voltage", "emptyvolt", api.CapacityResult),
    ("low_soc_configuration", "setlowcfg", api.CapacityResult),
    ("control_status", "ctrl", api.ConfigurationResult),
    ("protection_status", "prot", api.ConfigurationResult),
    ("automatic_switch_status", "autoswitch", api.ConfigurationResult),
    ("blocking_soc", "blocksoc", api.CapacityResult),
    ("lifetime_statistics", "euro", api.AccountingResult),
    ("self_discharge_state", "eurostub", api.AccountingResult),
    ("aging_voltage_history", "trdagevolt", api.AccountingResult),
    ("manufacturing_time", "cmudtesttime", api.ClockResult),
    ("soh_diagnostics", "soh", api.AccountingResult),
    ("ina_registers", "inash", api.RegisterResult),
    ("ina_calibration", "inacal", api.ConfigurationResult),
    ("current_calibration", "currcal", api.ConfigurationResult),
    ("gauge_registers", "socsh", api.RegisterResult),
    ("gauge_data", "socd", api.MeasurementResult),
    ("gauge_resistance_table", "soct", api.RegisterResult),
    ("gauge_configuration", "soccfg", api.ConfigurationResult),
    ("check_environment_temperature", "tetmp", api.CheckResult),
    ("check_pack_voltage", "tpwr", api.CheckResult),
    ("check_soh_events", "tsoh", api.CheckResult),
    ("check_system_faults", "tsto", api.CheckResult),
    ("check_aging_voltage", "tagevolt", api.CheckResult),
]
PARAMETERIZED = [
    ("command_help", (), {}, "help", api.CommunicationResult),
    ("command_help", ("eepe",), {}, "help eepe", api.CommunicationResult),
    ("communication_frame", (1,), {}, "ct 1", api.CommunicationResult),
    ("configuration", ("bsv",), {}, "config bsv", api.ConfigurationResult),
    ("configuration", ("sleep",), {}, "config sleep", api.ConfigurationResult),
    ("control_status", ("agelog",), {}, "ctrl agelog", api.ConfigurationResult),
    ("monitor_configuration", (2,), {}, "bmicrdcfg 2", api.RegisterResult),
    ("monitor_communication", (1,), {}, "bmicrdcomm 1", api.RegisterResult),
    ("ina_register", (0x1A,), {}, "inar 1a", api.RegisterResult),
    ("gauge_register", (0x7F,), {}, "socr 7f", api.RegisterResult),
    ("check_charge_current", (), {}, "tchgc", api.CheckResult),
    ("check_charge_current", (10,), {"tolerance_ma": 50}, "tchgc 10 50", api.CheckResult),
    ("check_discharge_current", (20,), {"tolerance_ma": 100}, "tdisc 20 100", api.CheckResult),
    ("check_cell_voltage", (30,), {}, "tvolt 30", api.CheckResult),
    ("check_cell_temperature", (50,), {}, "ttmp 50", api.CheckResult),
    ("check_dip_switch", (15,), {}, "tdip 15", api.CheckResult),
    ("check_input", ("rv",), {}, "tinput rv", api.CheckResult),
    ("check_input", ("dcov",), {}, "tinput dcov", api.CheckResult),
    ("check_ibc_inputs", ("nc",), {}, "tibcio nc", api.CheckResult),
    ("check_cbn_inputs", ("sc",), {}, "tcbnio sc", api.CheckResult),
    ("check_version", (0x123A,), {}, "tver 123a", api.CheckResult),
]


@pytest.mark.parametrize("method,command,cls", BARE)
def test_bare_passive_methods(replay, method, command, cls):
    text = response(command, "Counter : 7\r\nFuture : unknown\r\nVoltage : 12 mV")
    session, transport = replay([(command.encode() + b"\n", text)], chunk_size=1)
    result = getattr(BatteryClient(session=session), method)()
    assert isinstance(result, cls)
    assert isinstance(result, api.ConsoleReadResult)
    assert result.command == command
    assert result.text == text
    assert result.values["Counter"] == 7
    assert result.values["Future"] == "unknown"
    assert result.quantities["Voltage"] == api.Quantity(12, "mV")
    assert asdict(result)["fields"]["Counter"] == "7"
    assert command_label(command) == command
    assert not transport.exchanges


@pytest.mark.parametrize("method,args,kwargs,command,cls", PARAMETERIZED)
def test_parameterized_passive_forms(replay, method, args, kwargs, command, cls):
    session, transport = replay([(command.encode() + b"\n", response(command))])
    result = getattr(BatteryClient(session=session), method)(*args, **kwargs)
    assert isinstance(result, cls)
    assert result.command == command
    assert not transport.exchanges


@pytest.mark.parametrize(
    "method,command",
    [
        ("configuration", "config 4"),
        ("control_status", "ctrl 4"),
        ("protection_status", "prot 4"),
        ("empty_voltage", "emptyvolt 4"),
        ("soh_diagnostics", "soh 4"),
    ],
)
def test_verified_addressed_forms(replay, method, command):
    session, transport = replay([(command.encode() + b"\n", response(command))])
    assert getattr(BatteryClient(session=session, module=4), method)().command == command
    assert not transport.exchanges


def test_addressed_config_selector_order(replay):
    session, _ = replay([(b"config 4 bsv\n", response("config 4 bsv"))])
    BatteryClient(session=session, module=4).configuration("bsv")


@pytest.mark.parametrize(
    "method,args",
    [
        ("command_help", ("config save",)),
        ("command_help", ("pwr\ntrst",)),
        ("configuration", ("save",)),
        ("configuration", ("default",)),
        ("configuration", ("softtime",)),
        ("control_status", ("i2c",)),
        ("control_status", ("afuse",)),
        ("control_status", ("pwmp",)),
        ("communication_frame", (True,)),
        ("communication_frame", (2,)),
        ("monitor_configuration", (3,)),
        ("monitor_configuration", (0,)),
        ("monitor_communication", (256,)),
        ("ina_register", (-1,)),
        ("gauge_register", (128,)),
        ("gauge_register", (1.0,)),
        ("read_eeprom", (2, 0, 1)),
        ("read_eeprom", (0, 2047, 2)),
        ("read_eeprom", (0, -1, 1)),
        ("read_flash", (0xFFFFFFFF, 2)),
        ("read_flash", (0, 100000000)),
        ("check_input", ("present",)),
        ("check_input", ("absent",)),
        ("check_ibc_inputs", ("on",)),
        ("check_cbn_inputs", (True,)),
        ("check_version", (-1,)),
        ("check_dip_switch", (16,)),
        ("check_cell_voltage", (-1,)),
        ("check_cell_temperature", (False,)),
        ("check_discharge_current", (-1,)),
        ("read_record", ("misc",)),
        ("read_record", ("event", True)),
        ("cell_readings", (-1,)),
    ],
)
def test_invalid_arguments_send_nothing(replay, method, args):
    session, transport = replay([])
    with pytest.raises(ValueError):
        getattr(BatteryClient(session=session), method)(*args)
    assert not transport.writes


@pytest.mark.parametrize(
    "kwargs",
    [
        {"detailed": True, "field": "volt"},
        {"cell": 0},
        {"field": "save"},
        {"detailed": 1},
        {"start": -1},
        {"field": "temp", "cell": True},
    ],
)
def test_invalid_list_selection_sends_nothing(replay, kwargs):
    session, transport = replay([])
    with pytest.raises(ValueError):
        BatteryClient(session=session).list_records("event", **kwargs)
    assert not transport.writes


@pytest.mark.parametrize("kwargs", [{"tolerance_ma": 50}, {"current_ma": 10, "tolerance_ma": 49}])
def test_invalid_current_tolerance(replay, kwargs):
    session, transport = replay([])
    with pytest.raises(ValueError):
        BatteryClient(session=session).check_charge_current(**kwargs)
    assert not transport.writes


@pytest.mark.parametrize(
    "method,command,cls", [m for m in BARE if m[1] not in {"emptyvolt", "ctrl", "prot", "soh"}]
)
def test_local_bare_reads_reject_addressed_clients(replay, method, command, cls):
    session, transport = replay([])
    with pytest.raises(ValueError, match="direct module connection"):
        getattr(BatteryClient(session=session, module=4), method)()
    assert not transport.writes


def test_query_allowlists_exclude_actions_and_mutating_targets():
    assert not CONFIG_QUERIES & {"save", "default", "softtime", "cocp", "docp", "ocpd"}
    assert not CONTROL_QUERIES & {"i2c", "afuse", "pwmp"}
    assert not hasattr(BatteryClient, "read_memory")


def test_typed_settings_counters_and_clock(replay):
    replies = [
        ("stat", "CYCLE Times : 3\r\nSOH : 0\r\nPwr Percent : 8\r\nFault : 0x200"),
        ("totalcoul", "Total Coulomb : 12000 mAH"),
        ("tcycle", "Cycle : 4\r\nRealCoulomb : 21"),
        ("emptyvolt", "Coul:0% Volt : 2000"),
        ("setlowcfg", "ShutSoc : 9\r\nShutSocTime : 12"),
        ("blocksoc", "BlockSoc : 7 %"),
        ("time", "00-01-02 03:04:05"),
        ("urates", "Unit baud : 9600"),
        ("setprt", "Protocol : SMA"),
        ("autoswitch", "AutoSwitch : OFF"),
        ("cmudtesttime", "Time : 00-01-02 03:04:05"),
    ]
    session, _ = replay([(c.encode() + b"\n", response(c, b)) for c, b in replies])
    client = BatteryClient(session=session)
    stat = client.statistics()
    assert stat.cycle_count == 3 and stat.soh_pct == 0 and stat.soc_pct == 8
    assert stat.values["Fault"] == 0x200
    assert client.nominal_capacity().nominal_capacity_ah == 12
    assert client.cycle_statistics().cycle_count == 4
    assert client.empty_voltage().empty_voltage_v == 2
    low = client.low_soc_configuration()
    assert low.shutdown_soc_pct == 9 and low.shutdown_delay_s == 12
    assert client.blocking_soc().blocking_soc_pct == 7
    assert client.read_clock().timestamp == datetime(2000, 1, 2, 3, 4, 5)
    assert client.unit_baud_rate().baud_rate == 9600
    assert client.inverter_protocol().protocol == "sma"
    assert client.automatic_switch_status().enabled is False
    assert client.manufacturing_time().timestamp == datetime(2000, 1, 2, 3, 4, 5)


@pytest.mark.parametrize(
    "body,passed",
    [
        ("Test result:fail", False),
        ("Test result:pass", True),
        ("Test result:pass\r\nTest result:fail", False),
        ("Future outcome : novel", None),
    ],
)
def test_check_result_is_independent_of_success_footer(replay, body, passed):
    session, _ = replay([(b"tpwr\n", response("tpwr", body))])
    assert BatteryClient(session=session).check_pack_voltage().passed is passed


@pytest.mark.parametrize("body", ["", "Future : unknown", "Time : 00-02-31 03:04:05"])
def test_missing_and_invalid_clock_values_remain_unknown(replay, body):
    session, _ = replay([(b"time\n", response("time", body))])
    assert BatteryClient(session=session).read_clock().timestamp is None


def test_measurement_methods_reuse_normalized_parsers(replay):
    session, _ = replay([(b"pwr\n", PWR), (b"getpwr\n", GETPWR)])
    client = BatteryClient(session=session, profile="generic")
    summary = client.power_summary()
    assert len(summary.modules) == 2
    detail = client.power_details()
    assert detail.modules[0].voltage_v == 50
    assert detail.modules[0].current_a == -2
    assert detail.modules[0].cells[0].voltage_v == 3.101


def test_cell_selection_uses_address_and_validates_count(replay):
    info = INFO
    body = "Battery Volt Curr Tempr Base State Volt. State Curr. State Temp. State Coulomb\r\n0 3300 -2 20000 Idle Normal Normal Normal 50%"
    session, transport = replay([(b"info\n", info), (b"bat 1 0\n", response("bat 1 0", body))])
    result = BatteryClient(session=session).cell_readings(0)
    assert result.cells[0].index == 0 and result.cells[0].voltage_v == 3.3
    assert not transport.exchanges


def test_cell_selection_outside_reported_count_does_not_send_bat(replay):
    session, transport = replay([(b"info\n", INFO)])
    with pytest.raises(ValueError):
        BatteryClient(session=session).cell_readings(100)
    assert transport.writes == [b"info\n"]


@pytest.mark.parametrize(
    "method,args,command",
    [
        ("read_eeprom", (1, 0x20, 3), "eepr 1 20 3"),
        ("read_flash", (0x20, 3), "flar 0 20 3"),
    ],
)
def test_storage_decodes_exact_bytes(replay, method, args, command):
    session, _ = replay([(command.encode() + b"\n", response(command, "0020: 41 00 FF  |A..|"))])
    result = getattr(BatteryClient(session=session), method)(*args)
    assert result.data == b"A\x00\xff" and result.offset == 0x20


@pytest.mark.parametrize(
    "body", ["0020: 41 00", "0021: 41 00 FF", "0020: GG 00 FF", "Error reading flash"]
)
def test_storage_rejects_incomplete_or_corrupt_dump(replay, body):
    text = response("eepr 0 20 3", body)
    session, _ = replay([(b"eepr 0 20 3\n", text)])
    with pytest.raises(ProtocolError) as caught:
        BatteryClient(session=session).read_eeprom(0, 0x20, 3)
    assert caught.value.response == text
    assert caught.value.context["command"] == "eepr 0 20 3"


def test_zero_size_storage_read_and_register_widths(replay):
    session, _ = replay(
        [
            (b"eepr 0 800 0\n", response("eepr 0 800 0", "")),
            (b"inar 1a\n", response("inar 1a", "1a : abcd")),
            (b"socr 1a\n", response("socr 1a", "1a : ab")),
        ]
    )
    client = BatteryClient(session=session)
    assert client.read_eeprom(0, 0x800, 0).data == b""
    assert client.ina_register(0x1A).registers == {0x1A: 0xABCD}
    assert client.gauge_register(0x1A).registers == {0x1A: 0xAB}


def stat_reply(count):
    return response("stat", f"Data Items : {count}\r\nHisData Items : {count}")


def record_body(index=0):
    return f"Item Index : {index}\r\nTime : 00-01-02 03:04:05\r\nVoltage : 51000 mV\r\nCurrent : -1000 mA\r\nTemperature : 21000 mC\r\nPercent : 30 %"


def test_individual_record_validates_index_and_decodes_values(replay):
    session, transport = replay(
        [(b"stat\n", stat_reply(2)), (b"data event 1\n", response("data event 1", record_body(1)))]
    )
    result = BatteryClient(session=session).read_record("event", 1)
    record = result.records[0]
    assert result.indices == [1] and record.index == 1
    assert record.timestamp == datetime(2000, 1, 2, 3, 4, 5)
    assert record.voltage_v == 51 and record.current_a == -1 and record.soc_pct == 30
    assert not transport.exchanges


def test_latest_record_has_no_count_preflight(replay):
    session, transport = replay([(b"data event\n", response("data event", record_body()))])
    assert BatteryClient(session=session).read_record().indices == [0]
    assert transport.writes == [b"data event\n"]


def test_record_index_out_of_range_never_transmits_index(replay):
    session, transport = replay([(b"stat\n", stat_reply(1))])
    with pytest.raises(ValueError):
        BatteryClient(session=session).read_record("event", 1)
    assert transport.writes == [b"stat\n"]


def test_other_record_kind_reads_latest_for_bound(replay):
    session, _ = replay(
        [
            (b"data bov\n", response("data bov", record_body(2))),
            (b"data bov 1\n", response("data bov 1", record_body(1))),
        ]
    )
    assert BatteryClient(session=session).read_record("bov", 1).indices == [1]


def row(index):
    return f"{index} 00-01-02 03:04:05 50000 -1000 20000 Normal"


def test_list_records_consumes_all_pages_and_keeps_them(replay):
    header = "Item Time Vo(mV) Cu(mA) Tempr Base.St"
    first = f"datalist event 0\r\n@\r\n{header}\r\n{row(0)}\r\n{CONTINUATION}"
    last = response("", row(1))
    session, transport = replay(
        [(b"stat\n", stat_reply(2)), (b"datalist event 0\n", first), (b"\r\n", last)]
    )
    result = BatteryClient(session=session).list_records("event")
    assert result.text == first + last and result.indices == [0, 1]
    assert result.records[0].voltage_v == 50 and result.records[1].current_a == -1
    assert transport.writes[-1] == b"\r\n"
    assert session.synchronized


@pytest.mark.parametrize(
    "kwargs,command",
    [
        ({"detailed": True}, "datalist event dtls 0"),
        ({"field": "volt"}, "datalist event bat volt 0"),
        ({"field": "curr", "cell": 0}, "datalist event bat 0 curr 0"),
    ],
)
def test_list_selection_exact_syntax(replay, kwargs, command):
    preflight = [(b"info\n", INFO)] if "cell" in kwargs else []
    session, _ = replay(
        [
            *preflight,
            (b"stat\n", stat_reply(1)),
            (command.encode() + b"\n", response(command, row(0))),
        ]
    )
    result = BatteryClient(session=session).list_records("event", **kwargs)
    assert result.indices == [0]
    # Field-specific current output has differing scaling: retain it, don't guess.
    assert result.records[0].current_a is None


def test_empty_record_list_only_reads_count(replay):
    session, transport = replay([(b"stat\n", stat_reply(0))])
    assert BatteryClient(session=session).list_records("event").records == []
    assert transport.writes == [b"stat\n"]


@pytest.mark.parametrize("body", [row(1), row(0) + "\r\nError!", "unknown data"])
def test_record_list_rejects_missing_unexpected_or_corrupt_records(replay, body):
    session, _ = replay(
        [(b"stat\n", stat_reply(2)), (b"datalist event 0\n", response("datalist event 0", body))]
    )
    with pytest.raises(ProtocolError):
        BatteryClient(session=session).list_records("event")


def test_failed_page_restarts_whole_listing_after_verified_sync():
    first = Response(row(0) + "\r\n" + CONTINUATION, "page")
    complete = reply(row(0) + "\r\n" + row(1))
    session = ScriptedSession(
        [
            ("stat", reply("Data Items : 2")),
            ("datalist event 0", first),
            ("", CommandTimeout("synthetic timeout", response="fragment")),
            ("", reply()),
            ("datalist event 0", complete),
        ]
    )
    session.resynchronize = lambda **kwargs: session.exchange("", **kwargs)
    result = BatteryClient(session=session, read_retries=1).list_records("event")
    assert result.text == complete.text
    assert [c for c, _ in session.calls] == ["stat", "datalist event 0", "", "", "datalist event 0"]
    assert session.calls[2][1]["terminator"] == b"\r\n"


def test_failed_page_preserves_earlier_evidence():
    first = Response(row(0) + "\r\n" + CONTINUATION, "page")
    session = ScriptedSession(
        [
            ("stat", reply("Data Items : 2")),
            ("datalist event 0", first),
            ("", CommandTimeout("synthetic timeout", response="fragment")),
        ]
    )
    with pytest.raises(CommandTimeout) as caught:
        BatteryClient(session=session).list_records("event")
    assert caught.value.response == first.text + "fragment"


@pytest.mark.parametrize(
    "error", [UnsupportedCommand("synthetic"), CommandCancelled("synthetic"), KeyboardInterrupt()]
)
def test_individual_failures_propagate_and_context_manager_closes(error):
    session = ScriptedSession([("totalcoul", error)])
    with pytest.raises(type(error)):
        with BatteryClient(session=session) as client:
            client.nominal_capacity()
    assert session.disconnected


def test_combined_diagnostics_uses_public_methods(monkeypatch):
    session = ScriptedSession([])
    client = BatteryClient(session=session)
    methods = [
        "statistics",
        "read_clock",
        "diagnostic_log",
        "configuration",
        "nominal_capacity",
        "cycle_statistics",
        "empty_voltage",
        "low_soc_configuration",
        "control_status",
        "protection_status",
        "lifetime_statistics",
        "aging_voltage_history",
        "soh_diagnostics",
    ]
    called = []
    for method in methods:

        def read(name=method):
            called.append(name)
            return api.ConsoleReadResult(name, "synthetic", {})

        monkeypatch.setattr(client, method, read)
    assert client.diagnostics().complete
    assert called == methods


@pytest.mark.parametrize(
    "body,expected",
    [("Empty Voltage : 2 V", 2), ("Empty Voltage : 2000 mV", 2), ("Empty Voltage : 2 days", None)],
)
def test_empty_voltage_respects_explicit_units(replay, body, expected):
    session, _ = replay([(b"emptyvolt\n", response("emptyvolt", body))])
    assert BatteryClient(session=session).empty_voltage().empty_voltage_v == expected


def test_masks_keep_flag_names_and_unknown_lines(replay):
    session, _ = replay(
        [(b"euro\n", response("euro", "Fault : 0x200 SOMEFLAG\r\nFuture syntax without a colon"))]
    )
    result = BatteryClient(session=session).lifetime_statistics()
    assert result.masks["Fault"] == 0x200
    assert result.fields["Fault"] == "0x200 SOMEFLAG"
    assert "Future syntax without a colon" in result.unparsed_lines


def test_local_system_status_and_gauge_values(replay):
    session, _ = replay(
        [
            (
                b"pwrsys\n",
                response(
                    "pwrsys",
                    "System Recommend Chg Current : 2000 mA\r\nSystem Recommend Dsg Current : -3000 mA",
                ),
            ),
            (
                b"socd\n",
                response(
                    "socd",
                    "Voltage : 50000 mV\r\nCurrent : -1000 mA\r\nSOC : 20 %\r\nRemaining Capacity : 2000 mAH",
                ),
            ),
        ]
    )
    client = BatteryClient(session=session)
    system = client.system_status().system
    assert system.recommended_charge_a == 2 and system.recommended_discharge_a == -3
    gauge = client.gauge_data().modules[0]
    assert gauge.voltage_v == 50 and gauge.current_a == -1 and gauge.soc_pct == 20
    assert gauge.capacity_ah == 2


def test_help_and_frame_values_remain_typed_without_losing_source(replay):
    text = response("ct 0", "Frame : 7E 30 31 0D")
    session, _ = replay([(b"ct 0\n", text)])
    result = BatteryClient(session=session).communication_frame(0)
    assert result.frame == b"~01\r"
    assert result.text == text


def test_detailed_list_keeps_all_labeled_record_blocks(replay):
    text = response("datalist event dtls 0", record_body(0) + "\r\n" + record_body(1))
    session, _ = replay([(b"stat\n", stat_reply(2)), (b"datalist event dtls 0\n", text)])
    result = BatteryClient(session=session).list_records("event", detailed=True)
    assert result.indices == [0, 1]
    assert [r.index for r in result.records] == [0, 1]
    assert all(r.voltage_v == 51 for r in result.records)


def test_power_details_resolves_profile_from_identity(replay):
    session, transport = replay([(b"info\n", INFO), (b"getpwr\n", GETPWR)])
    assert BatteryClient(session=session).power_details().modules[0].voltage_v == 50
    assert transport.writes == [b"info\n", b"getpwr\n"]


@pytest.mark.parametrize(
    "sync", [reply("\rpylon>"), CommandTimeout("synthetic sync timeout", response="sync fragment")]
)
def test_paginated_read_does_not_restart_without_debug_prompt(sync):
    first = Response(row(0) + "\r\n" + CONTINUATION, "page")
    session = ScriptedSession(
        [
            ("stat", reply("Data Items : 2")),
            ("datalist event 0", first),
            ("", CommandTimeout("synthetic timeout", response="page fragment")),
            ("", sync),
        ]
    )
    session.resynchronize = lambda **kwargs: session.exchange("", **kwargs)
    with pytest.raises(ProtocolError) as caught:
        BatteryClient(session=session, read_retries=1).list_records("event")
    assert first.text in caught.value.response and "page fragment" in caught.value.response
    assert [c for c, _ in session.calls].count("datalist event 0") == 1


def test_repeated_page_is_rejected_and_retains_evidence():
    page = Response(row(0) + "\r\n" + CONTINUATION, "page")
    session = ScriptedSession(
        [
            ("stat", reply("Data Items : 2")),
            ("datalist event 0", page),
            ("", page),
        ]
    )
    with pytest.raises(ProtocolError, match="no progress") as caught:
        BatteryClient(session=session).list_records("event")
    assert caught.value.response == page.text * 2


def test_impossible_record_count_never_starts_a_listing(replay):
    session, transport = replay([(b"stat\n", stat_reply(1000000000))])
    with pytest.raises(ProtocolError, match="index range"):
        BatteryClient(session=session).list_records("event")
    assert transport.writes == [b"stat\n"]
