"""Guard: the test suite must never run against the developer's real services."""

import os

from src.core.config import get_settings


def test_tests_use_isolated_database_and_no_external_services():
    settings = get_settings()
    expected = os.environ.get("AMADEUS_TEST_DATABASE_URL")
    if expected:
        assert expected == settings.DATABASE_URL
    else:
        assert settings.DATABASE_URL.startswith("sqlite:///"), settings.DATABASE_URL
        assert "amadeus-tests-" in settings.DATABASE_URL
    assert not settings.TELEGRAM_BOT_TOKEN
    assert not settings.GEMINI_API_KEY
    assert not settings.GROQ_API_KEY
    assert not settings.SENTRY_DSN
