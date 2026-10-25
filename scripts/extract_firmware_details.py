"""Extract reviewed gauge descriptors and programming-script metadata, without payloads.

Accepts the same .bin/nested ZIP inputs as extract_firmware_commands.py. Rebuilds
initialized data using the firmware's literal/back-reference encoding; it never
executes the image or communicates with hardware. Only reviewed hashes are accepted.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import struct
import sys
import zipfile
from collections import Counter
from pathlib import Path

from extract_firmware_commands import IMAGE_BASE, binary_images, c_string, extract


def decompress(data: bytes, expected_size: int) -> bytes:
    """Decode the reviewed startup LZ stream with strict input/output bounds."""
    cursor = 0
    result = bytearray()

    def byte() -> int:
        nonlocal cursor
        if cursor >= len(data):
            raise ValueError("Truncated initialization stream")
        value = data[cursor]
        cursor += 1
        return value

    while cursor < len(data):
        control = byte()
        literals = control & 3
        if literals == 0:
            literals = byte() + 3
        match = control >> 4
        if match == 15:
            match = byte() + 15
        # The firmware decrements the literal counter before copying.
        if len(result) + literals - 1 > expected_size:
            raise ValueError("Initialization output exceeds reviewed size")
        for _ in range(literals - 1):
            result.append(byte())
        if match:
            low = byte()
            high = (control >> 2) & 3
            if high == 3:
                high = byte()
            distance = low + (high << 8)
            if not 0 < distance <= len(result):
                raise ValueError("Invalid initialization back-reference")
            if len(result) + match + 2 > expected_size:
                raise ValueError("Initialization output exceeds reviewed size")
            for _ in range(match + 2):
                result.append(result[-distance])
    if len(result) != expected_size:
        raise ValueError("Initialization output disagrees with reviewed size")
    return bytes(result)


def initialized_data(data: bytes, name: str) -> bytes:
    if name == "US_C_V3.1_Crc.bin":
        # Startup descriptor: relative source, encoded size/flags, RAM destination.
        entry = 0x08003BCC
        relative, size, destination = struct.unpack_from("<III", data, entry - IMAGE_BASE)
        if destination != 0x20000000 or size & 1:
            raise ValueError("Unexpected C initialization descriptor")
        start = entry + relative - IMAGE_BASE
        return decompress(data[start : start + (size >> 1)], 4479)
    if name == "US_E2_V2.5_Crc.bin":
        # Segmented decoder has one input segment and one output segment here.
        relative, length, destination, output_size = struct.unpack_from(
            "<4I", data, 0x08037F28 - IMAGE_BASE
        )
        if destination != 0x20000000 or output_size != 3471:
            raise ValueError("Unexpected E2 initialization descriptor")
        start = 0x08037F28 + relative - IMAGE_BASE
        return decompress(data[start : start + length], output_size)
    raise ValueError("Unreviewed initialization layout")


def gauge_fields(data: bytes) -> list[dict]:
    fields = []
    start = 0x08020EE4 - IMAGE_BASE
    for index in range(39):
        pointer, subclass, offset, kind, reserved, default = struct.unpack_from(
            "<IBBBBI", data, start + index * 12
        )
        if pointer == 0:
            if index != 38:
                raise ValueError("Unexpected gauge descriptor sentinel")
            return fields
        if kind > 7 or reserved:
            raise ValueError("Unexpected gauge field type")
        fields.append(
            {
                "name": c_string(data, pointer),
                "subclass_decimal": subclass,
                "offset_decimal": offset,
                "type": kind,
                "default_word": f"0x{default:08x}",
            }
        )
    raise ValueError("Missing gauge descriptor sentinel")


def script_metadata(data: bytes, ram: bytes) -> dict:
    rows = []
    for offset in range(0x744, 0xA20, 4):
        pointer = struct.unpack_from("<I", ram, offset)[0]
        if pointer == 0:
            if offset != 0xA1C:
                raise ValueError("Unexpected gauge script sentinel")
            break
        rows.append(c_string(data, pointer))
    if len(rows) != 182:
        raise ValueError("Unexpected gauge script length")
    counts = Counter()
    targets = set()
    chunks = []
    delays = []
    for row in rows:
        operation, value = row.split(": ", 1)
        counts[operation] += 1
        if operation == "X":
            delays.append(int(value, 10))
        elif operation in ("W", "C"):
            raw = bytes.fromhex(value)
            if len(raw) < 2:
                raise ValueError("Invalid gauge script transaction")
            targets.add(raw[0] >> 1)
            if operation == "W" and raw[:3] == bytes((0x16, 0, 0x0A)):
                chunks.append(raw[3])
        else:
            raise ValueError("Unknown gauge script operation")
    if counts != {"W": 91, "C": 47, "X": 44} or chunks != list(range(32)):
        raise ValueError("Unexpected gauge programming-script structure")
    return {
        "ram_pointer_table": "0x20000744",
        "ram_sentinel": "0x20000a1c",
        "steps": len(rows),
        "operation_counts": dict(sorted(counts.items())),
        "bus_addresses": [f"0x{target:02x}" for target in sorted(targets)],
        "indexed_programming_chunks": chunks,
        "delay_arguments": delays,
        "script_lines_sha256": hashlib.sha256(("\n".join(rows) + "\n").encode()).hexdigest(),
        "payloads_included": False,
    }


def details(data: bytes) -> dict:
    catalog = extract(data)  # Enforces reviewed SHA-256, size and table structure.
    ram = initialized_data(data, catalog["name"])
    result = {
        "name": catalog["name"],
        "sha256": catalog["sha256"],
        "initialized_ram_size": len(ram),
        "initialized_ram_sha256": hashlib.sha256(ram).hexdigest(),
    }
    if catalog["name"] == "US_C_V3.1_Crc.bin":
        result["gauge_fields"] = gauge_fields(data)
        result["socclr_script"] = script_metadata(data, ram)
    else:
        result["weekdays"] = [
            c_string(data, struct.unpack_from("<I", ram, 0x814 + day * 4)[0]) for day in range(1, 8)
        ]
    return result


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("inputs", nargs="+", type=Path)
    args = parser.parse_args(argv)
    try:
        images = {}
        for path in args.inputs:
            for data in binary_images(path.name, path.read_bytes()):
                result = details(data)
                images[result["name"]] = result
        if not images:
            raise ValueError("No firmware images found")
        print(
            json.dumps(
                {"schema_version": 1, "images": [images[n] for n in sorted(images)]}, indent=2
            )
        )
        return 0
    except (OSError, ValueError, struct.error, zipfile.BadZipFile) as exc:
        print(f"Firmware detail extraction failed: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
