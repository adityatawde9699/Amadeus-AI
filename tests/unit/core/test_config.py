"""
Unit tests for the configuration module.

Tests the Settings class, validators, and configuration loading.
"""

import os
from unittest import mock

import pytest
from pydantic import ValidationError

from src.core.config import Settings, get_settings, validate_settings


class TestSettings:
    """Tests for the Settings configuration class."""
    
    def test_default_values(self):
        """Test that Settings has sensible defaults."""
        settings = Settings()
        
        assert settings.ASSISTANT_NAME == "Amadeus"
        assert settings.ENV == "development"
        assert settings.DEBUG is True
        assert settings.VOICE_ENABLED is True
        assert settings.WHISPER_MODEL == "tiny"
    
    def test_env_override(self):
        """Test that environment variables override defaults."""
        with mock.patch.dict(os.environ, {
            "ENV": "production",
            "DEBUG": "false",
            "API_PORT": "9000",
        }):
            settings = Settings()
            
            assert settings.ENV == "production"
            assert settings.DEBUG is False
            assert settings.API_PORT == 9000
    
    def test_is_production_property(self):
        """Test the is_production computed property."""
        with mock.patch.dict(os.environ, {"ENV": "production"}):
            settings = Settings()
            assert settings.is_production is True
            assert settings.is_development is False
        
        with mock.patch.dict(os.environ, {"ENV": "development"}):
            settings = Settings()
            assert settings.is_production is False
            assert settings.is_development is True
    
    def test_allowed_origins_list(self):
        """Test parsing of ALLOWED_ORIGINS to list."""
        with mock.patch.dict(os.environ, {
            "ALLOWED_ORIGINS": "http://localhost:3000, http://example.com"
        }):
            settings = Settings()
            origins = settings.allowed_origins_list
            
            assert len(origins) == 2
            assert "http://localhost:3000" in origins
            assert "http://example.com" in origins
    
    def test_database_url_async_conversion(self):
        """Test conversion of database URL to async format."""
        # SQLite
        with mock.patch.dict(os.environ, {
            "DATABASE_URL": "sqlite:///./test.db"
        }):
            settings = Settings()
            assert "sqlite+aiosqlite" in settings.get_async_database_url()
        
        # PostgreSQL
        with mock.patch.dict(os.environ, {
            "DATABASE_URL": "postgresql://user:pass@localhost/db"
        }):
            settings = Settings()
            assert "postgresql+asyncpg" in settings.get_async_database_url()
    
    def test_database_is_sqlite(self):
        """Test SQLite detection."""
        with mock.patch.dict(os.environ, {
            "DATABASE_URL": "sqlite:///./test.db"
        }):
            settings = Settings()
            assert settings.database_is_sqlite is True
        
        with mock.patch.dict(os.environ, {
            "DATABASE_URL": "postgresql://localhost/db"
        }):
            settings = Settings()
            assert settings.database_is_sqlite is False
    
    def test_system_thresholds(self):
        """Test system threshold configuration."""
        settings = Settings()
        thresholds = settings.get_system_thresholds()
        
        assert "cpu" in thresholds
        assert "memory" in thresholds
        assert "disk" in thresholds
        assert "battery" in thresholds
        
        assert thresholds["cpu"]["warning"] < thresholds["cpu"]["critical"]
    
    def test_field_validation(self):
        """Test that field validators catch invalid values."""
        # API port out of range
        with pytest.raises(ValidationError):
            Settings(API_PORT=70000)
        
        # Invalid CPU threshold
        with pytest.raises(ValidationError):
            Settings(CPU_WARNING_THRESHOLD=150)


class TestValidateSettings:
    """Tests for the validate_settings function."""
    
    def test_valid_development_settings(self):
        """Test validation passes for valid development settings."""
        settings = Settings(
            ENV="development",
            GEMINI_API_KEY="test_key",
        )
        result = validate_settings(settings)
        
        assert result["valid"] is True
        assert len(result["errors"]) == 0
    
    def test_missing_api_key_production(self):
        """Test that missing API key fails validation in production."""
        settings = Settings(
            ENV="production",
            GEMINI_API_KEY=None,
        )
        result = validate_settings(settings)
        
        assert result["valid"] is False
        assert any("GEMINI_API_KEY" in err for err in result["errors"])
    
    def test_missing_api_key_development_warning(self):
        """Test that missing API key is a warning in development."""
        settings = Settings(
            ENV="development",
            GEMINI_API_KEY=None,
        )
        result = validate_settings(settings)
        
        assert result["valid"] is True
        assert any("GEMINI_API_KEY" in warn for warn in result["warnings"])
    
    def test_sqlite_production_warning(self):
        """Test that SQLite in production triggers a warning."""
        settings = Settings(
            ENV="production",
            DATABASE_URL="sqlite:///./prod.db",
            GEMINI_API_KEY="key",
        )
        result = validate_settings(settings)
        
        assert any("SQLite" in warn for warn in result["warnings"])


class TestGetSettings:
    """Tests for the get_settings singleton."""
    
    def test_returns_settings_instance(self):
        """Test that get_settings returns a Settings instance."""
        settings = get_settings()
        assert isinstance(settings, Settings)
    
    def test_singleton_behavior(self):
        """Test that get_settings returns the same instance (cached)."""
        # Note: This relies on lru_cache behavior
        settings1 = get_settings()
        settings2 = get_settings()
        
        # They should be the same object (cached)
        assert settings1 is settings2
