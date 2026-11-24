"""Phase 4 gate: a four-bar linkage matches its analytic position curve, and a peak bearing load from
MuJoCo feeds a CalculiX study without manual retyping (run in CI)."""

import pytest

from newcad_engine.sim.fem.calculix import ccx_binary

from motion_cases import bearing_handoff, four_bar, rotating_link

pytestmark = pytest.mark.asyncio(loop_scope="session")


async def test_four_bar_rocker_follows_the_analytic_position_curve(engine):
    err, swing = await four_bar(engine)
    assert err.ok, f"rocker angle off by up to {err.fem:.4f}°"
    assert swing.ok, f"swing {swing.fem:.3f}° vs {swing.reference:.3f}° ({swing.error:+.3%})"


async def test_rotating_link_bearing_load_is_centripetal(engine):
    (r,) = await rotating_link(engine)
    assert r.ok, f"{r.fem:.4f} N vs {r.reference:.4f} N ({r.error:+.2%})"


@pytest.mark.skipif(ccx_binary() is None, reason="CalculiX (ccx) is not installed")
async def test_peak_bearing_load_feeds_a_calculix_study(engine):
    (r,) = await bearing_handoff(engine)
    assert r.ok, f"support reactions {r.fem:.3f} N vs MuJoCo peak {r.reference:.3f} N ({r.error:+.2%})"
