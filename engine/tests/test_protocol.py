import importlib.util
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def test_protocol_schemas_are_current():
    spec = importlib.util.spec_from_file_location("export_schemas", ROOT / "scripts" / "export_schemas.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    for name, s in mod.schemas().items():
        f = mod.OUT / name
        assert f.exists() and f.read_text() == mod.render(s), f"{name} is out of date: run `uv run python scripts/export_schemas.py`"
