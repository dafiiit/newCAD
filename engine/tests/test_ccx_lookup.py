import os
import stat

from newcad_engine.sim.fem import calculix


def test_ccx_found_in_pixi_env(tmp_path, monkeypatch):
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    ccx = bin_dir / "ccx"
    ccx.write_text("#!/bin/sh\necho 'This is Version 2.24'\n")
    ccx.chmod(ccx.stat().st_mode | stat.S_IXUSR)
    monkeypatch.delenv("NEWCAD_CCX", raising=False)
    monkeypatch.setenv("NEWCAD_PIXI_ENV", str(tmp_path))
    monkeypatch.setenv("PATH", "/nonexistent")
    assert calculix.ccx_binary() == str(ccx)
    assert calculix.ccx_version() == "2.24"


def test_newcad_ccx_wins(tmp_path, monkeypatch):
    other = tmp_path / "myccx"
    other.write_text("#!/bin/sh\n")
    other.chmod(0o755)
    monkeypatch.setenv("NEWCAD_CCX", str(other))
    assert calculix.ccx_binary() == str(other)
