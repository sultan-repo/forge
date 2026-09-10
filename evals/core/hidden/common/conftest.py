import pytest
from ledger.storage import Store


@pytest.fixture
def store(tmp_path):
    return Store(tmp_path / "ledger.json")
