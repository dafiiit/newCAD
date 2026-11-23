"""Phase 3 gate: FEM results match analytic references (run in CI)."""
import os
import shutil

import pytest

from cases import cantilever, cantilever_frequency, conduction_bar, plate_with_hole

pytestmark = [
    pytest.mark.skipif(shutil.which(os.environ.get("NEWCAD_CCX") or "ccx") is None, reason="CalculiX (ccx) is not installed"),
    pytest.mark.asyncio(loop_scope="session"),
]


async def test_cantilever_converges_to_beam_theory_within_2_percent(engine):
    res = await cantilever(engine)
    errs = [abs(r.error) for r in res]
    assert res[-1].ok, f"finest mesh off by {res[-1].error:+.2%}"
    assert errs[-1] <= errs[0] + 1e-4, "refining the mesh should not move away from the reference"


async def test_cantilever_first_frequency(engine):
    (r,) = await cantilever_frequency(engine)
    assert r.ok, f"{r.fem:.2f} Hz vs {r.reference:.2f} Hz ({r.error:+.2%})"


async def test_plate_with_hole_stress_concentration(engine):
    (r,) = await plate_with_hole(engine)
    assert r.ok, f"{r.fem:.2f} MPa vs {r.reference:.2f} MPa ({r.error:+.2%})"


async def test_conduction_bar(engine):
    (r,) = await conduction_bar(engine)
    assert r.ok, f"{r.fem:.2f} °C vs {r.reference:.2f} °C ({r.error:+.2%})"
