import logging

import pytest

from pylontech_tools import BatteryClient, CommandTimeout, ProtocolError
from pylontech_tools.diagnostics import (
    SERIAL_TRACE,
    command_label,
    configure_logging,
    serial_logger,
)
from pylontech_tools.protocol import ConsoleSession


@pytest.mark.parametrize(
    "command,label",
    [
        ("", "<enter>"),
        ("login debug", "login debug"),
        ("login 2 debug", "login 2 debug"),
        ("getpwr 2", "getpwr 2"),
        ("datalist history dtls 15", "datalist history dtls 15"),
        ("tbar TEST_PRIVATE", "tbar <redacted>"),
        ("login TEST_PASSWORD", "login <redacted>"),
        ("unknown TEST_PRIVATE", "<command>"),
    ],
)
def test_metadata_command_labels(command, label):
    assert command_label(command) == label


def test_debug_excludes_payload_and_identity_arguments(replay, capsys):
    text = "Barcode : TEST_PRIVATE\r\npylon_debug>"
    session, _ = replay([(b"tbar TEST_PRIVATE\n", text)])
    with configure_logging(debug=True):
        session.exchange("tbar TEST_PRIVATE")
    output = capsys.readouterr()
    assert not output.out
    assert "command=tbar <redacted>" in output.err
    assert "prompt=pylon_debug>" in output.err
    assert "tx_bytes=" in output.err and "rx_bytes=" in output.err
    assert "elapsed=" in output.err
    assert "TEST_PRIVATE" not in output.err
    assert "RX " not in output.err and "TX " not in output.err


def test_trace_includes_escaped_bytes_only_when_requested(replay, capsys):
    session, _ = replay([(b"info\r", "Barcode : TEST_PRIVATE\r\npylon_debug>")])
    with configure_logging(trace_serial=True):
        session.exchange("info", terminator=b"\r")
    output = capsys.readouterr()
    assert not output.out
    assert "TX b'info\\r'" in output.err
    assert "RX b'" in output.err and "TEST_PRIVATE" in output.err
    assert "\\r\\n" in output.err


def test_library_debug_does_not_enable_raw_serial(replay, caplog):
    session, _ = replay([(b"info\n", "Barcode : TEST_PRIVATE\rpylon_debug>")])
    with caplog.at_level(logging.DEBUG, logger="pylontech_tools"):
        session.exchange("info")
    assert "Command complete" in caplog.text
    assert "TEST_PRIVATE" not in caplog.text
    assert not any(r.name == "pylontech_tools.serial" for r in caplog.records)


def test_logging_state_is_restored_and_raw_not_enabled_by_later_debug(capsys):
    logger = logging.getLogger("pylontech_tools")
    state = logger.level, logger.propagate, logger.handlers[:], serial_logger.level
    with configure_logging(trace_serial=True):
        serial_logger.log(SERIAL_TRACE, "raw trace")
    capsys.readouterr()
    with configure_logging(debug=True):
        serial_logger.log(SERIAL_TRACE, "must not appear")
    assert "must not appear" not in capsys.readouterr().err
    assert (logger.level, logger.propagate, logger.handlers, serial_logger.level) == state


def test_timeout_metadata_retains_context_without_partial_payload(replay, capsys):
    session, _ = replay([(b"info\n", "Barcode : TEST_PRIVATE")], timeout=0.005)
    with configure_logging(debug=True), pytest.raises(CommandTimeout):
        session.exchange("info")
    output = capsys.readouterr()
    assert "Command failed command=info error=CommandTimeout" in output.err
    assert "partial_bytes=" in output.err and "elapsed=" in output.err
    assert "TEST_PRIVATE" not in output.err


@pytest.mark.parametrize("exit_debug", [False, True])
def test_info_then_snapshot_checks_mode_after_disconnect(monkeypatch, capsys, exit_debug):
    class Console:
        debug = False
        commands = []

    class Transport:
        baudrate = 115200

        def __init__(self, *args):
            self.pending = b""

        def write(self, data):
            Console.commands.append(data)
            if data == b"\n":
                response = "\rpylon_debug>" if Console.debug else "\rpylon>"
            elif data == b"login debug\n":
                if Console.debug:
                    raise AssertionError("Repeated login must not be sent")
                Console.debug = True
                response = "\rpylon_debug>"
            elif data == b"info\n":
                response = "Device name : SYNTHETIC_MODEL\rpylon_debug>"
            elif data == b"pwr\n":
                response = "Power Volt Curr Tempr Coulomb\r\n1 50000 -2000 20000 50%\rpylon_debug>"
            elif data == b"getpwr\n":
                response = (
                    "50000# -2000# 20000# 100000# Dischg# Normal# Normal# Normal#\rpylon_debug>"
                )
            elif data == b"pwrsys\n":
                response = "Invalid command\rpylon_debug>"
            elif data == b"cmdquit\n":
                # A later connection must inspect its prompt whether the firmware
                # leaves debug mode on disconnect or only acknowledges the command.
                if exit_debug:
                    Console.debug = False
                response = "cmdquit\n"
            else:
                raise AssertionError("Unexpected synthetic console command")
            self.pending = response.encode("ascii")
            return len(data)

        def read(self, size=65536):
            data, self.pending = self.pending, b""
            return data

        def close(self):
            pass

    monkeypatch.setattr("pylontech_tools.client.SerialTransport", Transport)
    monkeypatch.setattr("pylontech_tools.protocol.time.sleep", lambda _: None)
    monkeypatch.setattr(
        "pylontech_tools.client.ConsoleSession",
        lambda *args, **kwargs: ConsoleSession(*args, **kwargs, settle_time=0),
    )
    with configure_logging(debug=True):
        with BatteryClient("SYNTHETIC_PORT", shift=False) as client:
            assert client.info().name == "SYNTHETIC_MODEL"
        with BatteryClient("SYNTHETIC_PORT", shift=False) as client:
            assert client.snapshot().modules[0].voltage_v == 50
    assert Console.commands.count(b"login debug\n") == (2 if exit_debug else 1)
    assert Console.commands.count(b"cmdquit\n") == 2
    if not exit_debug:
        assert "already in debug mode; skipping login debug" in capsys.readouterr().err


def test_failed_login_logs_final_prompt_without_payload(replay, monkeypatch, capsys):
    monkeypatch.setattr("pylontech_tools.protocol.time.sleep", lambda _: None)
    session, _ = replay(
        [(b"\n", "\rpylon>"), (b"login debug\n", "Invalid command TEST_PRIVATE\rpylon>")]
    )
    session.settle_time = 0
    with configure_logging(debug=True), pytest.raises(ProtocolError):
        session.connect(shift=False)
    output = capsys.readouterr()
    assert "prompt=pylon>" in output.err and "unsupported=True" in output.err
    assert "TEST_PRIVATE" not in output.err


def test_serial_diagnostics_do_not_change_vendor_transcript(replay, tmp_path, capsys):
    import codecs

    responses = [
        (b"info\n", "Device name : SYNTHETIC_MODEL\rpylon_debug>"),
        (b"stat\n", "Data Items : 0\rpylon_debug>"),
        (b"data event\n", "data event\n\r@\rpylon_debug>"),
    ]
    session, _ = replay(responses)
    path = tmp_path / "event.txt"
    with configure_logging(trace_serial=True):
        BatteryClient(session=session).export_events(path)
    expected = codecs.BOM_UTF16_LE + "".join(text + "\r\n" for _, text in responses).encode(
        "utf-16-le"
    )
    assert path.read_bytes() == expected
    output = capsys.readouterr()
    assert not output.out and "RX " in output.err
