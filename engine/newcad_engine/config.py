"""Engine configuration: where data lives and how the engine is reached.

Everything is driven by environment variables so the Tauri shell, the dev
scripts and tests can point the engine somewhere else without code changes.
"""
from __future__ import annotations

import json
import os
import secrets
from dataclasses import dataclass, field
from pathlib import Path


def _home() -> Path:
    return Path(os.environ.get("NEWCAD_HOME", Path.home() / ".newcad")).expanduser()


@dataclass
class Config:
    home: Path = field(default_factory=_home)
    host: str = "127.0.0.1"
    port: int = 0  # 0 = pick a free port
    token: str = ""
    # Origins allowed to call the API from a browser. Local dev servers and the Tauri webview.
    allowed_origins: tuple[str, ...] = (
        "http://localhost", "http://127.0.0.1", "tauri://localhost", "http://tauri.localhost", "https://tauri.localhost",
    )
    workers: int = int(os.environ.get("NEWCAD_WORKERS", "3"))
    build_timeout_s: float = float(os.environ.get("NEWCAD_BUILD_TIMEOUT", "60"))
    build_memory_mb: int = int(os.environ.get("NEWCAD_BUILD_MEMORY_MB", "4096"))
    sim_timeout_s: float = float(os.environ.get("NEWCAD_SIM_TIMEOUT", "3600"))

    @property
    def projects_dir(self) -> Path:
        return self.home / "projects"

    @property
    def cache_dir(self) -> Path:
        return self.home / "cache"

    @property
    def staging_dir(self) -> Path:
        return self.home / "staging"

    @property
    def exports_dir(self) -> Path:
        return self.home / "exports"

    @property
    def settings_file(self) -> Path:
        return self.home / "settings.json"

    @property
    def runtime_file(self) -> Path:
        """Written on start so the dev proxy and desktop agents can find the running engine."""
        return self.home / "engine.json"

    def ensure(self) -> "Config":
        for d in (self.projects_dir, self.cache_dir, self.staging_dir, self.exports_dir):
            d.mkdir(parents=True, exist_ok=True)
        if not self.token:
            self.token = os.environ.get("NEWCAD_TOKEN") or secrets.token_urlsafe(24)
        return self

    def write_runtime(self, port: int) -> None:
        self.runtime_file.write_text(json.dumps({"url": f"http://{self.host}:{port}", "port": port, "token": self.token, "pid": os.getpid()}))
        try:
            self.runtime_file.chmod(0o600)
        except OSError:
            pass


# Densities in kg/mm³, keyed by lower-case material name.
DENSITY_KG_MM3: dict[str, float] = {
    "steel": 7.85e-6,
    "stainless": 8.0e-6,
    "stainless steel": 8.0e-6,
    "aluminium": 2.70e-6,
    "aluminum": 2.70e-6,
    "brass": 8.5e-6,
    "copper": 8.96e-6,
    "titanium": 4.43e-6,
    "pla": 1.24e-6,
    "petg": 1.27e-6,
    "abs": 1.04e-6,
    "nylon": 1.15e-6,
    "wood": 0.7e-6,
}


def density_of(material: str | None) -> float:
    if not material:
        return DENSITY_KG_MM3["steel"]
    return DENSITY_KG_MM3.get(material.strip().lower(), DENSITY_KG_MM3["steel"])
