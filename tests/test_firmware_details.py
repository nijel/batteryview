"""Startup-codec regression tests use invented bytes, never battery recordings."""

import importlib
from pathlib import Path

import pytest


@pytest.fixture
def firmware_details(monkeypatch):
    monkeypatch.syspath_prepend(str(Path(__file__).resolve().parents[1] / "scripts"))
    return importlib.import_module("extract_firmware_details")


@pytest.mark.parametrize(
    ("encoded", "decoded"),
    [
        (b"\x02A", b"A"),
        (b"\x00\x02ABCD", b"ABCD"),
        (b"\x12A\x01", b"AAAA"),
        (b"\xf2\x00B\x01", b"B" * 18),
        (b"\x1fAB\x02\x00", b"ABABA"),
        (b"\x03AB\x11\x02", b"ABABA"),
    ],
)
def test_startup_literals_and_overlapping_back_references(firmware_details, encoded, decoded):
    assert firmware_details.decompress(encoded, len(decoded)) == decoded


@pytest.mark.parametrize(
    ("encoded", "size"),
    [
        (b"\x00", 4),
        (b"\x03A", 2),
        (b"\x12A", 4),
        (b"\x12A\x00", 4),
        (b"\x12A\x02", 4),
        (b"\x1fAB\x02", 5),
        (b"\x12A\x01", 3),
        (b"\x02A", 0),
        (b"\x02A", 2),
    ],
)
def test_startup_rejects_truncation_bad_references_and_size_mismatch(
    firmware_details, encoded, size
):
    with pytest.raises(ValueError):
        firmware_details.decompress(encoded, size)


def test_details_rejects_unreviewed_image(firmware_details):
    with pytest.raises(ValueError):
        firmware_details.details(b"synthetic image, not a firmware or device recording")


@pytest.mark.parametrize("adr", [False, True])
def test_fault_display_bit_and_string_decode_use_synthetic_instructions(firmware_details, adr):
    import struct

    base = firmware_details.IMAGE_BASE
    data = bytearray(160)
    struct.pack_into("<HH", data, 0, 22 << 6, 0xD501)  # LSLS #22 / BPL tests bit 9.
    if adr:
        struct.pack_into("<H", data, 4, 0xA000 | 22)  # ADR to offset 96.
    else:
        struct.pack_into("<HH", data, 4, 0xF8DF, 56)  # LDR literal pool at offset 64.
        struct.pack_into("<I", data, 64, base + 96)
    label = b"SYNTHETIC condition\0"
    data[96 : 96 + len(label)] = label
    result = firmware_details.fault_display_entry(bytes(data), base, base + 4)
    assert result["mask"] == "0x200" and result["label"] == "SYNTHETIC condition"
    assert result["label_address"] == f"0x{base + 96:08x}"
    struct.pack_into("<H", data, 2, 0xD101)  # BNE is not the reviewed signed bit test.
    with pytest.raises(ValueError, match="LSLS/BPL"):
        firmware_details.fault_display_entry(bytes(data), base, base + 4)
    with pytest.raises(ValueError):
        firmware_details.fault_display_entry(b"", base, base + 4)
