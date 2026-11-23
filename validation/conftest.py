import sys
from pathlib import Path

import pytest_asyncio

sys.path.insert(0, str(Path(__file__).parent))

from newcad_engine.config import Config  # noqa: E402
from newcad_engine.core import Engine  # noqa: E402


@pytest_asyncio.fixture(scope="session", loop_scope="session")
async def engine(tmp_path_factory):
    eng = Engine(Config(home=tmp_path_factory.mktemp("validation"), token="validation", workers=2))
    await eng.start()
    yield eng
    await eng.stop()
