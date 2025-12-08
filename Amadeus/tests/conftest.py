import pytest
from fastapi.testclient import TestClient
from typing import Generator
import os
import sys

# Ensure the parent directory is in the path to import app modules
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from unittest.mock import MagicMock
sys.modules["faster_whisper"] = MagicMock()
sys.modules["edge_tts"] = MagicMock()
sys.modules["sounddevice"] = MagicMock()
sys.modules["pyaudio"] = MagicMock()

# Constants for testing
API_KEY_NAME = "X-API-Key"
API_KEY = "test-api-key"
# Setting this before imports to avoid validation errors during import
os.environ["API_KEY"] = API_KEY

from api import app

@pytest.fixture(scope="module")
def client() -> Generator:
    """
    Fixture for the FastAPI TestClient.
    """
    with TestClient(app) as c:
        yield c

@pytest.fixture
def auth_headers():
    """
    Fixture for valid authentication headers.
    """
    # Assuming config.API_KEY is available and set. 
    # If strictly testing, might want to mock this or ensure it's a known value.
    if not API_KEY:
        return {API_KEY_NAME: "test-api-key"}
    return {API_KEY_NAME: API_KEY}
