"""Run every validation case and print a Markdown table (CI appends it to the job summary)."""
import asyncio
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))

from cases import CASES  # noqa: E402
from newcad_engine.config import Config  # noqa: E402
from newcad_engine.core import Engine  # noqa: E402


async def main() -> int:
    with tempfile.TemporaryDirectory() as home:
        eng = Engine(Config(home=Path(home), token="validation", workers=2))
        await eng.start()
        try:
            rows = []
            for fn in CASES.values():
                rows += await fn(eng)
        finally:
            await eng.stop()
    print("| Case | Quantity | FEM | Reference | Error | Tolerance | |\n|---|---|---:|---:|---:|---:|---|")
    for r in rows:
        print(f"| {r.case} | {r.quantity} | {r.fem:.4g} | {r.reference:.4g} | {r.error:+.2%} | ±{r.tolerance:.0%} | {'pass' if r.ok else 'FAIL'} |")
    for r in rows:
        if r.detail:
            print(f"\n- {r.case} ({r.quantity}): {r.detail}", end="")
    print()
    return 0 if all(r.ok for r in rows) else 1


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
