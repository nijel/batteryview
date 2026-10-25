"""Reviewed native equivalents of BatteryView's bundled monitoring profiles.

The bundled getpwr layouts share eight scalar fields and four fields per cell.
GeneralRegout overrides control extension commands, not arbitrary scripts/regexes.
"""

from dataclasses import dataclass


@dataclass(frozen=True)
class MonitoringProfile:
    name: str
    pwr_extension: bool = True
    addressed_pwrsys: bool = True
    system_pwrsys: bool = True
    trailer_from_end: bool = False


PROFILES = {name: MonitoringProfile(name) for name in ("generic", "US3000C", "Forcel_C")}
PROFILES["US2K"] = MonitoringProfile("US2K", trailer_from_end=True)
for _name in ("UP2500", "2500LFP2"):
    PROFILES[_name] = MonitoringProfile(
        _name, pwr_extension=False, addressed_pwrsys=False, system_pwrsys=False
    )


def monitoring_profile(name: str | None, *, explicit: bool = False) -> MonitoringProfile:
    if name in PROFILES:
        return PROFILES[name]
    if explicit:
        raise ValueError(f"Unknown monitoring profile: {name}; choose from {', '.join(PROFILES)}")
    return PROFILES["generic"]
