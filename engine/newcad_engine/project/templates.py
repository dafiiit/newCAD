"""Files a new project starts with."""
from __future__ import annotations

import copy
import json
import time
from pathlib import Path
from typing import Any

import yaml

_SPEC = json.loads((Path(__file__).with_name("spec_template.json")).read_text())

PART_HEADER = "from build123d import *\n\n"

# A small three-part bracket, used by the "demo" template and the rebuild benchmark.
DEMO_PARTS: dict[str, tuple[str, str, str, str]] = {
    "plate": ("Base plate", "#C7CCD4", "Steel", '''# Base plate with four bolt holes (mm, Z up)
PLATE_T = 10

with BuildPart() as plate:
    Box(220, 140, PLATE_T, align=(Align.CENTER, Align.CENTER, Align.MIN))
    with Locations(*[(x, y, PLATE_T) for x in (-85, 85) for y in (-55, 55)]):
        CounterBoreHole(radius=5.5, counter_bore_radius=9, counter_bore_depth=2)

result = plate.part
'''),
    "upright": ("Upright", "#B4C2D6", "Steel", '''# Upright welded to the plate, with the generator flange holes
PLATE_T, UPRIGHT_T = 10, 10

with BuildPart() as upright:
    with Locations((-110 + UPRIGHT_T / 2, 0, PLATE_T)):
        Box(UPRIGHT_T, 140, 150, align=(Align.CENTER, Align.CENTER, Align.MIN))
    with BuildSketch(Plane.YZ.offset(-110)) as holes:
        with Locations((0, PLATE_T + 85)):
            with PolarLocations(52, 4, start_angle=45):
                Circle(4.5)
    extrude(amount=UPRIGHT_T, mode=Mode.SUBTRACT)

result = upright.part
'''),
    "gusset": ("Gussets (2x)", "#A9B9D0", "Steel", '''# Two triangular gussets at the upright root
PLATE_T, UPRIGHT_T, GUSSET_T, GUSSET_H = 10, 10, 8, 90

gussets = []
for y in (-62, 62):
    with BuildPart() as g:
        with BuildSketch(Plane.XZ.offset(-y + GUSSET_T / 2)):
            Polygon((-110 + UPRIGHT_T, PLATE_T), (-110 + UPRIGHT_T + GUSSET_H, PLATE_T), (-110 + UPRIGHT_T, PLATE_T + GUSSET_H), align=None)
        extrude(amount=GUSSET_T)
    gussets.append(g.part)

result = Compound(children=gussets)
'''),
}


def blank_spec(goal: str) -> dict[str, Any]:
    spec = copy.deepcopy(_SPEC)
    for c in spec["categories"]:
        for q in c["questions"]:
            q["by"] = "template"
            q["answers"] = []
        c.pop("extra", None)
    return {"goal": goal, "overview": goal, "categories": spec["categories"]}


def template_hints() -> dict[str, Any]:
    """Follow-up and extra question ideas per question/category from the design (Bot may use them)."""
    return copy.deepcopy(_SPEC)


def dump(data: Any) -> str:
    return yaml.safe_dump(data, sort_keys=False, allow_unicode=True, width=100)


def new_project_files(name: str, goal: str, template: str = "blank") -> dict[str, str]:
    files = {
        "project.yaml": dump({"name": name, "goal": goal, "created": int(time.time()), "units": "mm", "up": "Z"}),
        "spec.yaml": dump(blank_spec(goal)),
        "notes.yaml": dump({"notes": []}),
    }
    parts: list[dict[str, Any]] = []
    if template == "demo":
        for pid, (pname, color, material, src) in DEMO_PARTS.items():
            files[f"parts/{pid}.py"] = PART_HEADER + src
            parts.append({"id": pid, "name": pname, "file": f"parts/{pid}.py", "color": color, "material": material})
    files["assembly.yaml"] = dump({"parts": parts, "mates": []})
    return files
