"""Extract registered console commands from the two reviewed Pylontech images.

Reads .bin images or nested ZIP archives and writes deterministic JSON to stdout.
No firmware is executed. Unknown images fail rather than inheriting an assumed
memory map. Run from the repository root; only Python's standard library is used.
"""

from __future__ import annotations

import argparse
import hashlib
import io
import json
import re
import struct
import sys
import zipfile
from dataclasses import dataclass
from pathlib import Path

IMAGE_BASE = 0x08003800
RECORD = struct.Struct("<7I")


@dataclass(frozen=True)
class Image:
    name: str
    size: int
    remote_offset: int
    remote_count: int
    local_offset: int
    local_count: int
    selectors: tuple[tuple[str, int, int], ...]


IMAGES = {
    "897c3326ab8905df75a7297905112958a07c0a2cbb0592e0ecc274b886b0c82e": Image(
        "US_E2_V2.5_Crc.bin",
        217088,
        0x32BB0,
        12,
        0x32D1C,
        79,
        (
            ("config", 0x08035164, 67),
            ("prot", 0x08035270, 35),
            ("ctrl", 0x08029BF4, 12),
            ("datalist", 0x0803514C, 6),
        ),
    ),
    "5450e3bd884ae63549fc3b278ecccc0126227234f7148c7961542755cbad2d7d": Image(
        "US_C_V3.1_Crc.bin",
        242688,
        0x37444,
        12,
        0x375B0,
        90,
        (
            ("config", 0x08039884, 67),
            ("prot", 0x08039990, 35),
            ("ctrl", 0x0802D248, 12),
            ("datalist", 0x0803986C, 6),
        ),
    ),
}


def c_string(data: bytes, pointer: int) -> str:
    offset = pointer - IMAGE_BASE
    if not 0 <= offset < len(data):
        raise ValueError(f"String pointer outside image: {pointer:#x}")
    end = data.find(b"\0", offset, min(offset + 2048, len(data)))
    if end == -1:
        raise ValueError(f"Unterminated string at {pointer:#x}")
    raw = data[offset:end]
    if any(byte not in (9, 10, 13) and not 32 <= byte < 127 for byte in raw):
        raise ValueError(f"Non-ASCII command string at {pointer:#x}")
    return raw.decode("ascii")


def command_record(data: bytes, offset: int) -> dict:
    name, max_tokens, handler, help_pointer, reserved_a, reserved_b, mask = RECORD.unpack_from(
        data, offset
    )
    name_text = c_string(data, name)
    if not re.fullmatch(r"[A-Za-z_?][A-Za-z0-9_?-]{0,30}", name_text):
        raise ValueError(f"Invalid command name at {offset:#x}")
    if not 1 <= max_tokens <= 32 or mask not in (1, 3, 5, 15):
        raise ValueError(f"Invalid command metadata at {offset:#x}")
    if not handler & 1 or not IMAGE_BASE <= handler & ~1 < IMAGE_BASE + len(data):
        raise ValueError(f"Invalid Thumb handler at {offset:#x}")
    if reserved_a or reserved_b:
        raise ValueError(f"Unexpected reserved command fields at {offset:#x}")
    return {
        "name": name_text,
        "max_tokens": max_tokens,
        "required_mask": f"0x{mask:02x}",
        "handler_address": f"0x{handler & ~1:08x}",
        "record_offset": f"0x{offset:05x}",
        "help": c_string(data, help_pointer),
    }


def extract(data: bytes) -> dict:
    digest = hashlib.sha256(data).hexdigest()
    if digest not in IMAGES:
        raise ValueError(f"Unreviewed firmware SHA-256: {digest}")
    image = IMAGES[digest]
    if len(data) != image.size:
        raise ValueError("Unexpected firmware size")
    commands = []
    tables = {}
    expected_offsets = set()
    for scope, start, count in (
        ("remote", image.remote_offset, image.remote_count),
        ("local", image.local_offset, image.local_count),
    ):
        tables[scope] = {
            "file_offset": f"0x{start:05x}",
            "address": f"0x{IMAGE_BASE + start:08x}",
            "count": count,
        }
        for index in range(count):
            offset = start + RECORD.size * index
            expected_offsets.add(offset)
            commands.append({"scope": scope, **command_record(data, offset)})
        # The firmware walks each table until its command-name pointer is null.
        if struct.unpack_from("<I", data, start + count * RECORD.size)[0]:
            raise ValueError(f"Missing {scope} table sentinel")
    # Independent scan catches overlooked table entries outside the reviewed ranges.
    found_offsets = set()
    for offset in range(0, len(data) - RECORD.size + 1, 4):
        try:
            command_record(data, offset)
        except (ValueError, struct.error):
            continue
        found_offsets.add(offset)
    if found_offsets != expected_offsets:
        raise ValueError("Table ranges disagree with independent command-record scan")
    selector_tables = {}
    for name, address, count in image.selectors:
        pointers = struct.unpack_from(f"<{count}I", data, address - IMAGE_BASE)
        if pointers[-1] != 0 or any(pointer == 0 for pointer in pointers[:-1]):
            raise ValueError(f"Unexpected {name} selector-table sentinel")
        selector_tables[name] = {
            "address": f"0x{address:08x}",
            "selectors": [c_string(data, pointer) for pointer in pointers[:-1]],
        }
    return {
        "name": image.name,
        "sha256": digest,
        "size": len(data),
        "board_tag": c_string(data, IMAGE_BASE + 0x418),
        "tables": tables,
        "commands": commands,
        "selector_tables": selector_tables,
    }


def binary_images(name: str, data: bytes, depth: int = 0):
    if depth > 4:
        raise ValueError("Nested archive depth exceeded")
    if name.lower().endswith(".bin"):
        yield data
    elif name.lower().endswith(".zip"):
        with zipfile.ZipFile(io.BytesIO(data)) as archive:
            for entry in archive.infolist():
                # Never read updater executables, logs, or unrelated archive content.
                if not entry.is_dir() and entry.filename.lower().endswith((".bin", ".zip")):
                    yield from binary_images(entry.filename, archive.read(entry), depth + 1)
    else:
        raise ValueError("Expected a .bin image or .zip archive")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("inputs", nargs="+", type=Path)
    args = parser.parse_args(argv)
    try:
        images = {}
        for path in args.inputs:
            for data in binary_images(path.name, path.read_bytes()):
                image = extract(data)
                images[image["name"]] = image
        if not images:
            raise ValueError("No firmware images found")
        result = {
            "schema_version": 1,
            "image_base": f"0x{IMAGE_BASE:08x}",
            "command_record_size": RECORD.size,
            "images": [images[name] for name in sorted(images)],
        }
        print(json.dumps(result, ensure_ascii=False, indent=2))
        return 0
    except (OSError, ValueError, zipfile.BadZipFile) as exc:
        print(f"Firmware extraction failed: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
