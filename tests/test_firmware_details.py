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
