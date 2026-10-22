import os
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))


@pytest.fixture()
def store(tmp_path):
    from taxrag.store import Store
    return Store(tmp_path / "t.sqlite")
