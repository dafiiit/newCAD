"""Motion model: mates (joints) in assembly.yaml and the motion setup of a study.

Mates belong to the assembly, because every motion study of a model uses the
same joints:

    assembly.yaml
      parts: [...]
      mates:
      - id: crank-pivot
        type: revolute            # revolute | prismatic | ball | fixed
        parts: [ground, crank]    # "ground" is the fixed world
        faces: [{part, tag, sig}] # bore / pin faces; the axis and centre come from them
        origin: [x, y, z]         # mm, optional: overrides the faces
        axis: [x, y, z]           # optional: overrides the faces

The joint coordinate of a mate is the motion of parts[1] relative to parts[0]
(degrees for revolute, mm for prismatic), zero in the modelled position.

The study holds what drives the mechanism and for how long:

    studies/<id>.yaml
      type: motion
      motion: {duration, timestep, gravity, drivers, springs, sweep, ...}

Units: mm, deg, N, N·m, s. Speeds in rpm (revolute) or mm/s (prismatic).
"""
from __future__ import annotations

import re
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

MateType = Literal["revolute", "prismatic", "ball", "fixed"]
GROUND = "ground"


class MateFace(BaseModel):
    model_config = ConfigDict(extra="ignore")
    part: str
    tag: str
    sig: dict[str, Any] | None = None


def _vec3(v: list[float] | None) -> list[float] | None:
    if v is not None and len(v) != 3:
        raise ValueError("needs three components [x, y, z]")
    return v


class Mate(BaseModel):
    model_config = ConfigDict(extra="ignore")
    id: str
    type: MateType = "revolute"
    parts: list[str] = Field(description="The two parts it connects; 'ground' is the fixed world")
    label: str = ""
    faces: list[MateFace] = Field(default_factory=list, description="Bore, pin or ball faces; axis and centre are taken from them")
    origin: list[float] | None = Field(default=None, description="Joint centre in mm (assembly coordinates); empty = from the faces")
    axis: list[float] | None = Field(default=None, description="Joint axis; empty = from the faces")
    limits: list[float] | None = Field(default=None, description="[min, max] in deg (revolute) or mm (prismatic)")

    @field_validator("origin", "axis")
    @classmethod
    def _v3(cls, v: list[float] | None) -> list[float] | None:
        return _vec3(v)

    @field_validator("id")
    @classmethod
    def _id(cls, v: str) -> str:
        if not re.fullmatch(r"[a-z0-9][a-z0-9_-]{0,40}", v):
            raise ValueError("mate id: lower-case letters, digits, - and _")
        return v

    @field_validator("parts")
    @classmethod
    def _parts(cls, v: list[str]) -> list[str]:
        if len(v) != 2 or v[0] == v[1]:
            raise ValueError("a mate connects two different parts (or a part and ground)")
        return v

    @field_validator("limits")
    @classmethod
    def _limits(cls, v: list[float] | None) -> list[float] | None:
        if v is not None and (len(v) != 2 or v[0] >= v[1]):
            raise ValueError("limits are [min, max] with min < max")
        return v


class Driver(BaseModel):
    """Drives one mate: a motor at a speed, a torque (force), or a move to a position."""
    model_config = ConfigDict(extra="ignore")
    mate: str
    kind: Literal["speed", "torque", "position"] = "speed"
    value: float = Field(description="speed: rpm or mm/s; torque: N·m or N; position: deg or mm from the modelled position")
    ramp: float = Field(default=0.2, ge=0, description="Seconds to reach the value (smooth start)")


class Spring(BaseModel):
    model_config = ConfigDict(extra="ignore")
    mate: str
    stiffness: float = Field(default=0.0, ge=0, description="N·m/rad (revolute) or N/mm (prismatic)")
    damping: float = Field(default=0.0, ge=0, description="N·m·s/rad (revolute) or N·s/mm (prismatic)")
    rest: float = Field(default=0.0, description="Unloaded position, deg or mm from the modelled position")


SWEEP_PARAM = re.compile(r"^(drivers\.[a-z0-9_-]+\.value|springs\.[a-z0-9_-]+\.(stiffness|damping)|mass\.[A-Za-z0-9_.-]+|damping)$")


class Sweep(BaseModel):
    """Runs the study once per value, as parallel worlds (MuJoCo Warp on a CUDA target, a process pool elsewhere)."""
    model_config = ConfigDict(extra="ignore")
    parameter: str = Field(description="drivers.<mate>.value, springs.<mate>.stiffness, springs.<mate>.damping, mass.<part> (kg) or damping")
    values: list[float] = Field(min_length=1, max_length=4096)

    @field_validator("parameter")
    @classmethod
    def _param(cls, v: str) -> str:
        if not SWEEP_PARAM.match(v):
            raise ValueError("sweep parameter: drivers.<mate>.value, springs.<mate>.stiffness|damping, mass.<part> or damping")
        return v


class MotionSetup(BaseModel):
    model_config = ConfigDict(extra="ignore")
    duration: float = Field(default=2.0, gt=0, le=600, description="Simulated time in s")
    timestep: float = Field(default=0.001, ge=1e-5, le=0.01, description="Integrator step in s")
    gravity: list[float] = Field(default_factory=lambda: [0.0, 0.0, -9.81], description="m/s²")
    contacts: bool = Field(default=False, description="Collide parts that no mate connects (convex decomposition with CoACD)")
    damping: float = Field(default=0.0, ge=0, description="Damping on every joint, N·m·s/rad or N·s/mm")
    drivers: list[Driver] = Field(default_factory=list)
    springs: list[Spring] = Field(default_factory=list)
    sweep: Sweep | None = None
    samples: int = Field(default=400, ge=20, le=5000, description="Points in the time series")

    @field_validator("gravity")
    @classmethod
    def _g(cls, v: list[float]) -> list[float]:
        return _vec3(v) or [0.0, 0.0, 0.0]

    @model_validator(mode="after")
    def _one_driver_per_mate(self) -> "MotionSetup":
        seen = [d.mate for d in self.drivers]
        if len(seen) != len(set(seen)):
            raise ValueError("one driver per mate")
        return self


def mates_from(assembly: dict[str, Any]) -> list[Mate]:
    out = []
    for m in assembly.get("mates") or []:
        try:
            out.append(Mate.model_validate(m))
        except Exception:  # a broken entry shouldn't hide the others
            continue
    return out


def next_mate_id(assembly: dict[str, Any], kind: str) -> str:
    used = {m.get("id") for m in assembly.get("mates") or []}
    i = 1
    while f"{kind}-{i}" in used:
        i += 1
    return f"{kind}-{i}"
