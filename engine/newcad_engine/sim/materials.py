"""Engineering materials for simulation.

Units follow the solver's consistent mm–N–s–tonne system: E and yield in MPa
(N/mm²), density in t/mm³, conductivity in mW/(mm·K) (numerically equal to
W/(m·K)), expansion in 1/K. Values are typical handbook values for common
grades; a study can override any of them.
"""
from __future__ import annotations

from typing import Any

# name: E [MPa], nu, density [kg/m³], yield [MPa], conductivity [W/(m·K)], expansion [1/K], specific heat [J/(kg·K)]
_TABLE: dict[str, tuple[float, float, float, float, float, float, float]] = {
    "Steel": (210_000, 0.30, 7850, 250, 50, 12e-6, 490),             # S235/S275 structural steel
    "Stainless": (193_000, 0.29, 8000, 215, 16, 17e-6, 500),         # 1.4301 / 304
    "Aluminium": (69_000, 0.33, 2700, 240, 167, 23e-6, 896),         # 6061-T6 (yield 240-275)
    "Titanium": (114_000, 0.34, 4430, 880, 7, 8.6e-6, 526),          # Ti-6Al-4V
    "Brass": (100_000, 0.34, 8500, 200, 115, 19e-6, 380),
    "Copper": (117_000, 0.34, 8960, 70, 390, 17e-6, 385),
    "PLA": (3_500, 0.36, 1240, 50, 0.13, 68e-6, 1800),
    "PETG": (2_100, 0.38, 1270, 45, 0.20, 60e-6, 1200),
    "ABS": (2_300, 0.35, 1040, 40, 0.17, 90e-6, 1400),
    "Nylon": (2_700, 0.39, 1150, 60, 0.25, 80e-6, 1700),
    "Wood": (11_000, 0.30, 700, 40, 0.15, 5e-6, 1700),               # along the grain, treated as isotropic
}

_ALIASES = {"aluminum": "Aluminium", "stainless steel": "Stainless", "pa": "Nylon", "pa12": "Nylon"}


def names() -> list[str]:
    return list(_TABLE)


def lookup(name: str | None, override: dict[str, Any] | None = None) -> dict[str, Any]:
    """Material properties by name (case-insensitive), with optional overrides. Unknown names fall back to steel."""
    key = (name or "Steel").strip()
    key = _ALIASES.get(key.lower(), next((k for k in _TABLE if k.lower() == key.lower()), "Steel"))
    E, nu, rho, sy, k, alpha, cp = _TABLE[key]
    m = {"name": key, "E": E, "nu": nu, "density": rho, "yield": sy, "conductivity": k, "expansion": alpha, "specific_heat": cp}
    for f, v in (override or {}).items():
        if f in m and v is not None:
            m[f] = v
    return m
