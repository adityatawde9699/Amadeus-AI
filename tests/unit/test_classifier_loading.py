from unittest.mock import patch

import pytest

from src.app.services.amadeus_service import AmadeusService
from src.core.config import get_settings


@pytest.fixture
def amadeus_service():
    with (
        patch("src.app.services.amadeus_service.genai.GenerativeModel"),
        patch("src.app.services.amadeus_service.AgentOrchestrator"),
    ):  # mock agent orchestrator
        service = AmadeusService(settings=get_settings())
        return service


def test_classifier_loading_success(amadeus_service):
    with (
        patch("src.app.services.amadeus_service.os.path.exists", return_value=True),
        patch(
            "src.app.services.amadeus_service.joblib.load", side_effect=["vectorizer", "classifier"]
        ),
    ):
        amadeus_service._load_tool_classifier()
        assert amadeus_service.classifier_enabled is True
        assert amadeus_service.vectorizer == "vectorizer"
        assert amadeus_service.classifier == "classifier"


def test_classifier_loading_failure(amadeus_service):
    with patch("src.app.services.amadeus_service.os.path.exists", return_value=False):
        amadeus_service._load_tool_classifier()
        assert amadeus_service.classifier_enabled is False
