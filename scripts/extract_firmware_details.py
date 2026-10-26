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


def fault_display_entry(data: bytes, check: int, label_load: int) -> dict:
    """Decode a reviewed Thumb LSLS/BPL display bit and its literal/ADR label."""
    try:
        shift, branch = struct.unpack_from("<HH", data, check - IMAGE_BASE)
        if shift & 0xF800 or not (shift >> 6) & 31 or branch & 0xFF00 != 0xD500:
            raise ValueError("Fault display is not the reviewed LSLS/BPL test")
        first, second = struct.unpack_from("<HH", data, label_load - IMAGE_BASE)
        pc = (label_load + 4) & ~3
        if first == 0xF8DF:
            pool = pc + (second & 0xFFF)
            pointer = struct.unpack_from("<I", data, pool - IMAGE_BASE)[0]
        elif first & 0xF800 == 0xA000:
            pointer = pc + (first & 255) * 4
        else:
            raise ValueError("Fault display label is not a reviewed literal or ADR")
        label = c_string(data, pointer).strip()
    except struct.error as exc:
        raise ValueError("Truncated fault display evidence") from exc
    return {
        "mask": f"0x{1 << (31 - ((shift >> 6) & 31)):x}",
        "label": label,
        "check_address": f"0x{check:08x}",
        "label_address": f"0x{pointer:08x}",
    }


def system_fault_metadata(data: bytes, name: str) -> dict:
    if name == "US_E2_V2.5_Crc.bin":
        checks = (
            (0x080087E0, 0x080087E4),
            (0x080087EE, 0x080087F2),
            (0x080087FA, 0x080087FE),
            (0x08008806, 0x0800880A),
            (0x0800881E, 0x08008822),
            (0x0800882A, 0x0800882E),
            (0x08008842, 0x08008846),
            (0x0800884E, 0x08008852),
            (0x0800885A, 0x0800885E),
            (0x08008866, 0x0800886A),
            (0x08008872, 0x08008876),
            (0x0800887E, 0x08008882),
            (0x0800888A, 0x0800888E),
        )
        copy, mask_set, mask_clear, presence = 0x08007490, 0x080145AC, 0x080145B8, 0x0801716A
    else:
        checks = (
            (0x08008792, 0x08008796),
            (0x080087A0, 0x080087A4),
            (0x080087AC, 0x080087B0),
            (0x080087B8, 0x080087BC),
            (0x080087C4, 0x080087C8),
            (0x080087D0, 0x080087D4),
            (0x080087E6, 0x080087EA),
            (0x080087F2, 0x080087F6),
            (0x0800880A, 0x0800880E),
            (0x08008816, 0x0800881A),
            (0x0800882E, 0x08008832),
            (0x0800883A, 0x0800883E),
            (0x08008852, 0x08008856),
        )
        copy, mask_set, mask_clear, presence = 0x080074A8, 0x080143AC, 0x080143B8, 0x08016F88
    return {
        "module_word_offset": "0x40",
        "record_word_offset": "0x3c",
        "record_copy_address": f"0x{copy:08x}",
        "display_flags": sorted(
            (fault_display_entry(data, a, b) for a, b in checks),
            key=lambda row: int(row["mask"], 16),
        ),
        "peer_presence_0x200": {
            "set_address": f"0x{mask_set:08x}",
            "clear_address": f"0x{mask_clear:08x}",
            "presence_check_address": f"0x{presence:08x}",
            "consecutive_absent_checks": 5,
        },
    }


def details(data: bytes) -> dict:
    catalog = extract(data)  # Enforces reviewed SHA-256, size and table structure.
    ram = initialized_data(data, catalog["name"])
    result = {
        "name": catalog["name"],
        "sha256": catalog["sha256"],
        "initialized_ram_size": len(ram),
        "initialized_ram_sha256": hashlib.sha256(ram).hexdigest(),
        "system_fault": system_fault_metadata(data, catalog["name"]),
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
