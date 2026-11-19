import pytest
from fastapi.testclient import TestClient

from app import main


@pytest.fixture(autouse=True)
def empty_store():
    # Each test starts with nothing stored, same as a fresh container
    for store in (main.members, main.phone_index, main.plans, main.agreements, main.runs):
        store.clear()


@pytest.fixture
def client():
    return TestClient(main.app)
