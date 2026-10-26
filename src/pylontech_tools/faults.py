"""Source-aware fault meanings traced in the reviewed E2/C application images.

Code meanings are assumed stable across revisions. This does not make unrelated
fields interchangeable or turn a firmware condition into a component diagnosis.
See the communication manual's system-fault chapter for addresses and hashes.
"""

from __future__ import annotations

from .parsers import ERROR_BITS

SYSTEM_FIELDS = frozenset({"System Fault", "SysErrCode", "ErrCode"})
REVIEWED_MODELS = frozenset({"US2000C", "US3000C"})

# Mask: stable identifier, readable condition, kind, additional interpretation.
SYSTEM_BITS = {
    0x1: ("reversed_input", "Reversed input polarity", "fault", ""),
    0x2: ("input_overvoltage", "Input overvoltage", "fault", ""),
    0x4: ("rtc_error", "RTC error", "fault", "Firmware label: Rtc eer."),
    0x8: (
        "lock_error",
        "Lock-state error",
        "fault",
        "Firmware label: lock eer; lock mechanism is unresolved.",
    ),
    0x20: ("temperature_sensor", "Temperature-sensor error", "fault", ""),
    0x40: (
        "voltage_sensor",
        "Voltage-sensor error",
        "fault",
        "Includes the monitored auxiliary-voltage check; not proof of a failed cell.",
    ),
    0x100: ("address_allocation", "Address-allocation error", "fault", ""),
    0x200: (
        "internal_communication",
        "Internal communication/presence fault",
        "fault",
        "An expected peer was absent in five consecutive presence checks. Review rack presence, addressing, and communication state; this does not identify a failed cable or component.",
    ),
    0x400: (
        "charge_mos_monitor",
        "Charge MOS monitoring fault",
        "fault",
        "A gated current/GPIO monitoring condition; not proof that a MOSFET has physically failed.",
    ),
    0x800: (
        "discharge_mos_monitor",
        "Discharge MOS monitoring fault",
        "fault",
        "A gated current/GPIO monitoring condition; not proof that a MOSFET has physically failed.",
    ),
    0x1000: (
        "measurement_ic",
        "Current-sensor/fuel-gauge IC error",
        "fault",
        "E2 labels CurrIC err; C labels 34Z100 err. These are different measurement IC paths.",
    ),
    0x2000: ("monitor_ic", "LTC/monitor-IC error", "fault", "Firmware label: LTC err."),
    0x4000: ("eeprom_error", "EEPROM error", "fault", "Firmware label: eep eer."),
    0x8000: ("flash_error", "Flash error", "fault", "Firmware label: flash eer."),
    0x10000: (
        "battery_state_error",
        "Battery-state error",
        "fault",
        "Firmware label: bat eer; underlying cause is unresolved.",
    ),
    0x20000: (
        "afuse_status",
        "AFUSE status error",
        "fault",
        "Firmware label: afuse eer; not proof of a blown replaceable fuse.",
    ),
    0x8000000: (
        "shutdown_requested",
        "Shutdown requested",
        "status",
        "Set by the shutdown command; an operational flag, not a hardware diagnosis.",
    ),
    0x20000000: (
        "reset_in_progress",
        "Reset in progress",
        "status",
        "Set by the reset path; an operational flag, not a hardware diagnosis.",
    ),
}


def decode_faults(value: int, source: str, *, model: str | None = None) -> dict:
    """Return JSON-ready meanings without borrowing another source's bit layout."""
    if type(value) is not int or value < 0:
        raise ValueError("A fault mask must be a nonnegative integer")
    system = source in SYSTEM_FIELDS or (source == "getpwr" and model in REVIEWED_MODELS)
    if system:
        namespace, basis = "system_fault", "reviewed_firmware"
        meanings = SYSTEM_BITS
    elif source == "getpwr":
        namespace, basis = "indicator", "vendor_indicator_configuration"
        meanings = {
            1 << bit: (f"indicator_{bit}", name, "fault", "") for bit, name in enumerate(ERROR_BITS)
        }
        if model == "UP2500":
            meanings[0x1000] = (
                "fuse_indicator",
                "Fuse failure indicator",
                "fault",
                "UP2500 indicator configuration; not the reviewed firmware's measurement-IC bit.",
            )
    else:
        namespace, basis, meanings = "event_flags", "undecoded_source", {}
    known = []
    remaining = value
    for mask, (code, label, kind, explanation) in meanings.items():
        if value & mask:
            known.append(
                {
                    "mask": f"0x{mask:x}",
                    "code": code,
                    "label": label,
                    "kind": kind,
                    "explanation": explanation,
                }
            )
            remaining &= ~mask
    return {
        "source": source,
        "namespace": namespace,
        "raw_mask": f"0x{value:x}",
        "decoded_bits": known,
        "unknown_mask": f"0x{remaining:x}",
        "mapping_basis": basis,
    }


def describe_faults(decoded: dict) -> str:
    names = [bit["label"] for bit in decoded["decoded_bits"]]
    if int(decoded["unknown_mask"], 16):
        names.append(
            f"undecoded {decoded['namespace'].replace('_', ' ')} bits {decoded['unknown_mask']}"
        )
    text = f"{decoded['source']} {decoded['raw_mask']}: " + (", ".join(names) or "no flags set")
    return text + (" (vendor indicator mapping)" if decoded["namespace"] == "indicator" else "")


def fault_severity(decoded: dict) -> str:
    if decoded["namespace"] == "event_flags":
        return "info"
    if any(bit["kind"] == "fault" for bit in decoded["decoded_bits"]) or int(
        decoded["unknown_mask"], 16
    ):
        return "warning"
    return "info"
