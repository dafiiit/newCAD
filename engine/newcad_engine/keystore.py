"""API keys for model profiles, kept in the OS keychain (macOS Keychain, Windows Credential Manager,
Secret Service on Linux) through `keyring`. Nothing here is ever written to the engine's settings file.

If no keychain backend is available the keys live in memory for this engine run only, and
`persistent()` says so, so the UI can tell the user."""
from __future__ import annotations

import logging
import os

log = logging.getLogger(__name__)

SERVICE = "newcad-engine"


def _backend():
    if os.environ.get("NEWCAD_KEYCHAIN") == "0":  # tests and headless runs
        return None
    try:
        import keyring
        from keyring.backends import fail

        kr = keyring.get_keyring()
        if isinstance(kr, fail.Keyring):
            return None
        return keyring
    except Exception as e:  # noqa: BLE001 - no keychain is not an error, keys just stay in memory
        log.info("no OS keychain: %s", e)
        return None


class KeyStore:
    def __init__(self) -> None:
        self._kr = _backend()
        self.mem: dict[str, str] = {}

    def persistent(self) -> bool:
        return self._kr is not None

    def get(self, name: str) -> str:
        if name in self.mem:
            return self.mem[name]
        if self._kr is not None:
            try:
                v = self._kr.get_password(SERVICE, name) or ""
            except Exception as e:  # noqa: BLE001
                log.warning("keychain read failed for %s: %s", name, e)
                v = ""
            if v:
                self.mem[name] = v
            return v
        return ""

    def has(self, name: str) -> bool:
        return bool(self.get(name))

    def set(self, name: str, key: str) -> bool:
        """Store a key; returns True if it went to the keychain (False: memory only)."""
        self.mem[name] = key
        if self._kr is not None:
            try:
                self._kr.set_password(SERVICE, name, key)
                return True
            except Exception as e:  # noqa: BLE001
                log.warning("keychain write failed for %s: %s", name, e)
        return False

    def delete(self, name: str) -> None:
        self.mem.pop(name, None)
        if self._kr is not None:
            try:
                self._kr.delete_password(SERVICE, name)
            except Exception:  # noqa: BLE001 - not there
                pass
