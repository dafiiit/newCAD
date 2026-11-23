"""Write the JSON Schemas of shared engine models to packages/protocol/schemas/.

    cd engine && uv run python scripts/export_schemas.py

tests/test_protocol.py fails when a schema file is out of date.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

OUT = Path(__file__).resolve().parents[2] / "packages" / "protocol" / "schemas"


def schemas() -> dict[str, dict]:
    from newcad_engine.sim.study import Study
    s = Study.model_json_schema()
    s["$schema"] = "https://json-schema.org/draft/2020-12/schema"
    s["$id"] = "https://newcad.dev/schemas/study.schema.json"
    s["description"] = "A simulation study, stored as studies/<id>.yaml in the project repository. Units: mm, N, MPa, °C, W."
    return {"study.schema.json": s}


def render(s: dict) -> str:
    return json.dumps(s, indent=2, ensure_ascii=False) + "\n"


if __name__ == "__main__":
    OUT.mkdir(parents=True, exist_ok=True)
    for name, s in schemas().items():
        (OUT / name).write_text(render(s))
        print(f"wrote {OUT / name}", file=sys.stderr)
