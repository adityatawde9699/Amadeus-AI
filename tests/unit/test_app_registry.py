import json
from unittest.mock import patch

import pytest

from src.infra.system.app_registry import AppRegistry


@pytest.fixture
def mock_cache_dir(tmp_path):
    return tmp_path / ".amadeus"


def test_app_registry_initialization_no_cache(mock_cache_dir):
    with patch.object(
        AppRegistry, "scan_and_cache", return_value={"chrome": "/path/to/chrome"}
    ) as mock_scan:
        registry = AppRegistry(cache_dir=mock_cache_dir)

        mock_scan.assert_called_once()
        assert registry.apps == {"chrome": "/path/to/chrome"}
        assert registry.cache_file == mock_cache_dir / "app_registry.json"


def test_app_registry_load_from_cache(mock_cache_dir):
    # Setup mock cache
    mock_cache_dir.mkdir(parents=True, exist_ok=True)
    cache_file = mock_cache_dir / "app_registry.json"
    cache_data = {"discord": "/path/to/discord", "spotify": "/path/to/spotify"}

    with open(cache_file, "w") as f:
        json.dump(cache_data, f)

    with patch.object(AppRegistry, "scan_and_cache") as mock_scan:
        registry = AppRegistry(cache_dir=mock_cache_dir)

        mock_scan.assert_not_called()
        assert registry.apps == cache_data


def test_app_registry_get_executable_exact_match():
    with patch.object(AppRegistry, "_load_cache", return_value={"calculator": "/path/to/calc.exe"}):
        registry = AppRegistry()
        result = registry.get_executable("calculator")
        assert result == "/path/to/calc.exe"


def test_app_registry_get_executable_substring_match():
    with patch.object(
        AppRegistry, "_load_cache", return_value={"visual studio code": "/path/to/code.exe"}
    ):
        registry = AppRegistry()
        result = registry.get_executable("code.exe")
        assert result == "/path/to/code.exe"


def test_app_registry_get_executable_fuzzy_match():
    with patch.object(AppRegistry, "_load_cache", return_value={"spotify": "/path/to/spotify.exe"}):
        registry = AppRegistry()
        # Misspelled "spotfy" -> should fuzzy match to "spotify"
        result = registry.get_executable("spotfy")
        assert result == "/path/to/spotify.exe"


def test_app_registry_get_executable_no_match():
    with patch.object(AppRegistry, "_load_cache", return_value={"spotify": "/path/to/spotify.exe"}):
        registry = AppRegistry()
        result = registry.get_executable("completely_random_app")
        assert result is None
