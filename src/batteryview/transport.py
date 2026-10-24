"""Serial I/O kept separate from console framing for replay and future transports."""

import logging
from typing import Protocol

from .errors import ConnectionError

logger = logging.getLogger(__name__)


class Transport(Protocol):
    baudrate: int

    def read(self, size: int = 65536) -> bytes: ...
    def write(self, data: bytes) -> int: ...
    def close(self) -> None: ...


class SerialTransport:
    def __init__(self, port: str, baudrate: int = 115200, *, read_timeout: float = 0.05):
        import serial

        try:
            logger.debug(
                "Opening serial port baud=%d data_bits=8 parity=N stop_bits=1 read_timeout=%.3fs dtr=False rts=False",
                baudrate,
                read_timeout,
            )
            self._serial = serial.Serial(
                None,
                baudrate,
                bytesize=8,
                parity="N",
                stopbits=1,
                timeout=read_timeout,
                write_timeout=5,
                xonxoff=False,
                rtscts=False,
                dsrdtr=False,
            )
            # Configure while closed: pySerial otherwise opens with RTS/DTR active.
            # Disabling flow control alone does not deactivate these output lines.
            self._serial.port = port
            self._open()
        except (serial.SerialException, OSError, ValueError) as exc:
            logger.debug("Serial open failed error=%s", type(exc).__name__)
            raise ConnectionError(f"Cannot open {port}: {exc}") from exc

    def _open(self) -> None:
        """Match .NET SerialPort defaults on both initial open and baud changes."""
        self._serial.dtr = False
        self._serial.rts = False
        logger.debug("Opening serial handle dtr=False rts=False")
        self._serial.open()

    @property
    def baudrate(self) -> int:
        return self._serial.baudrate

    @baudrate.setter
    def baudrate(self, value: int) -> None:
        import serial

        try:
            logger.debug("Changing serial baud rate to %d", value)
            # BatteryView closes and reopens the port when changing its baud rate.
            self._serial.close()
            self._serial.baudrate = value
            self._open()
        except (serial.SerialException, OSError, ValueError) as exc:
            logger.debug("Baud change failed error=%s", type(exc).__name__)
            raise ConnectionError(f"Cannot change console baud rate: {exc}") from exc

    def read(self, size: int = 65536) -> bytes:
        import serial

        try:
            return self._serial.read(max(1, min(size, self._serial.in_waiting or 1)))
        except (serial.SerialException, OSError) as exc:
            raise ConnectionError(f"Serial read failed: {exc}") from exc

    def write(self, data: bytes) -> int:
        import serial

        try:
            written = self._serial.write(data)
            self._serial.flush()
            return written
        except (serial.SerialException, OSError) as exc:
            raise ConnectionError(f"Serial write failed: {exc}") from exc

    def close(self) -> None:
        logger.debug("Closing serial port")
        self._serial.close()


def list_ports() -> list[dict[str, str | None]]:
    from serial.tools.list_ports import comports

    return [
        {"port": p.device, "description": p.description, "serial_number": p.serial_number}
        for p in sorted(comports())
    ]
