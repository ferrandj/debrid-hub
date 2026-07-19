from __future__ import annotations

import pytest

from debrid_hub.config import Settings


@pytest.fixture
def data_dir(tmp_path):
    """An isolated data dir, never the user's real ~/.config/debrid-hub."""
    return str(tmp_path / "data")


@pytest.fixture
def settings(data_dir):
    return Settings(data_dir=data_dir, enable_mock=True)
