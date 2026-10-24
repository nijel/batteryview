import codecs
import os
import select
import subprocess
import sys
import threading
from pathlib import Path

import pytest
import serial

from batteryview.errors import ConnectionError
from batteryview.transport import SerialTransport


def test_serial_settings_baud_reopen_and_io(monkeypatch):
    class FakeSerial:
        def __init__(self, port, baudrate, **kwargs):
            assert port == "COM3" and baudrate == 115200
            assert kwargs == {
                "bytesize": 8,
                "parity": "N",
                "stopbits": 1,
                "timeout": 0.05,
                "write_timeout": 5,
                "xonxoff": False,
                "rtscts": False,
                "dsrdtr": False,
            }
            self.baudrate = baudrate
            self.in_waiting = 4
            self.operations = []

        def close(self):
            self.operations.append("close")

        def open(self):
            self.operations.append("open")

        def read(self, size):
            assert size == 4
            return b"data"

        def write(self, data):
            self.operations.append(data)
            return len(data)

        def flush(self):
            self.operations.append("flush")

    monkeypatch.setattr(serial, "Serial", FakeSerial)
    transport = SerialTransport("COM3")
    transport.baudrate = 1200
    assert transport.baudrate == 1200
    assert transport.read() == b"data"
    assert transport.write(b"info\n") == 5
    assert transport._serial.operations == ["close", "open", b"info\n", "flush"]


def test_unavailable_port_is_a_connection_error(monkeypatch):
    def unavailable(*args, **kwargs):
        raise serial.SerialException("unavailable")

    monkeypatch.setattr(serial, "Serial", unavailable)
    with pytest.raises(ConnectionError, match="unavailable"):
        SerialTransport("not-a-port")


@pytest.mark.skipif(
    os.name == "nt", reason="POSIX pseudo-terminal integration; serial settings tested on all OSes"
)
def test_installed_cli_event_through_real_serial_transport(tmp_path):
    """Run the actual CLI against an OS tty emulating a battery, without hardware."""
    import pty

    master, slave = pty.openpty()
    port = os.ttyname(slave)
    identity = "info\n\r@\r\n\rDevice name : SYNTHETIC_MODEL\r\n\rBarcode : TEST\r\n\rpylon_debug>"
    stat = "stat\n\r@\r\n\rData Items : 0\r\n\rHisData Items : 0\r\n\rpylon_debug>"
    event = "data event\n\r@\r\n\rCommand completed successfully\r\n\rpylon_debug>"
    exchanges = [
        (b"\n", "\rpylon>"),
        (b"login debug\n", "\rpylon_debug>"),
        (b"info\n", identity),
        (b"stat\n", stat),
        (b"data event\n", event),
    ]
    errors = []
    stop = threading.Event()

    def battery():
        try:
            for expected, response in exchanges:
                command = bytearray()
                while not command.endswith(b"\n"):
                    if stop.is_set():
                        return
                    ready, _, _ = select.select([master], [], [], 0.1)
                    if ready:
                        command.extend(os.read(master, 1024))
                assert bytes(command) == expected
                data = response.encode("ascii")
                while data:
                    written = os.write(master, data)
                    data = data[written:]
        except BaseException as error:
            errors.append(error)

    thread = threading.Thread(target=battery, daemon=True)
    thread.start()
    path = tmp_path / "event.txt.txt"
    env = {**os.environ, "PYTHONPATH": str(Path(__file__).parents[1] / "src")}
    try:
        process = subprocess.run(
            [
                sys.executable,
                "-m",
                "batteryview",
                "event",
                "--port",
                port,
                "--no-shift",
                "--output",
                str(path),
            ],
            capture_output=True,
            text=True,
            timeout=15,
            env=env,
        )
        assert not errors, errors
        assert process.returncode == 0, process.stderr
        expected = codecs.BOM_UTF16_LE + "".join(
            text + "\r\n" for text in (identity, stat, event)
        ).encode("utf-16-le")
        assert path.read_bytes() == expected
    finally:
        stop.set()
        thread.join(timeout=2)
        os.close(master)
        os.close(slave)
