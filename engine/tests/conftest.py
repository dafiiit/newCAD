import os
from pathlib import Path

import pytest
import pytest_asyncio

os.environ["NEWCAD_ALLOW_SCRIPTED"] = "1"
os.environ["NEWCAD_KEYCHAIN"] = "0"  # never touch the real OS keychain from tests

from newcad_engine.config import Config  # noqa: E402
from newcad_engine.core import Engine  # noqa: E402


@pytest.fixture
def home(tmp_path: Path) -> Path:
    return tmp_path


@pytest_asyncio.fixture(scope="module", loop_scope="module")
async def engine(tmp_path_factory):
    eng = Engine(Config(home=tmp_path_factory.mktemp("home"), token="test-token", workers=3, build_timeout_s=20))
    await eng.start()
    eng.settings.update({"provider": "scripted"})
    yield eng
    await eng.stop()
