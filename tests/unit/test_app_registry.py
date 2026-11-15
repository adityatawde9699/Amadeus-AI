import json
from pathlib import Path
from unittest.mock import patch

import pytest

from src.infra.system.app_registry import _CACHE_VERSION, AppRegistry


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

    with Path(cache_file).open("w", encoding="utf-8") as file:
        json.dump(cache_data, file)
    (mock_cache_dir / "app_registry.version").write_text(_CACHE_VERSION, encoding="utf-8")

    with patch.object(AppRegistry, "scan_and_cache") as mock_scan:
        registry = AppRegistry(cache_dir=mock_cache_dir)

        mock_scan.assert_not_called()
        assert registry.apps == cache_data


def test_cache_from_an_older_scan_is_rebuilt(mock_cache_dir):
    mock_cache_dir.mkdir(parents=True, exist_ok=True)
    (mock_cache_dir / "app_registry.json").write_text('{"old": "/x"}', encoding="utf-8")
    with patch.object(AppRegistry, "scan_and_cache", return_value={"new": "/y"}) as mock_scan:
        registry = AppRegistry(cache_dir=mock_cache_dir)
    mock_scan.assert_called_once()
    assert registry.apps == {"new": "/y"}


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


APPS = {
    "com.microsoft.vscode": "/usr/share/code/code",
    "visual studio code": "/usr/share/code/code",
    "org.gnome.nautilus": "nautilus",
    "files": "nautilus",
    "spotify": "/snap/bin/spotify",
    "org.gnome.evolution-alarm-notify": "/usr/libexec/alarm-notify",
    "google chrome": "/usr/bin/google-chrome",
    "firefox": "/snap/bin/firefox",
}


@pytest.mark.parametrize(
    ("asked", "expected"),
    [
        ("vscode", "/usr/share/code/code"),
        ("Visual Studio Code", "/usr/share/code/code"),
        ("files", "nautilus"),
        ("chrome", "/usr/bin/google-chrome"),
        ("fire fox", "/snap/bin/firefox"),
        ("spotfy", "/snap/bin/spotify"),
    ],
)
def test_people_names_resolve_to_the_right_app(asked, expected):
    with patch.object(AppRegistry, "_load_cache", return_value=APPS):
        assert AppRegistry().get_executable(asked, score_cutoff=75) == expected


@pytest.mark.parametrize("asked", ["settings", "calculator", "zoom", "terminal"])
def test_unknown_apps_are_not_guessed(asked):
    with patch.object(AppRegistry, "_load_cache", return_value=APPS):
        assert AppRegistry().get_executable(asked, score_cutoff=75) is None


def test_linux_scan_indexes_display_names_and_skips_hidden_entries(tmp_path, monkeypatch):
    apps_dir = tmp_path / "applications"
    apps_dir.mkdir()
    (apps_dir / "org.gnome.Calculator.desktop").write_text(
        "[Desktop Entry]\nType=Application\nName=Calculator\nGenericName=Calculator\n"
        "Exec=gnome-calculator %U\n[Desktop Action new]\nName=New Window\nExec=other\n"
    )
    (apps_dir / "handler.desktop").write_text(
        "[Desktop Entry]\nType=Application\nName=URL Handler\nNoDisplay=true\nExec=h %u\n"
    )
    (apps_dir / "wrapped.desktop").write_text(
        "[Desktop Entry]\nType=Application\nName=Wrapped\nExec=env GDK_BACKEND=x11 wrapped-app %F\n"
    )
    (apps_dir / "fp.desktop").write_text(
        "[Desktop Entry]\nType=Application\nName=Flat App\n"
        "Exec=/usr/bin/flatpak run --branch=stable org.flat.App @@u %U @@\n"
    )
    monkeypatch.setattr(AppRegistry, "_linux_app_dirs", staticmethod(lambda: [apps_dir]))
    with patch.object(AppRegistry, "_load_cache", return_value={}):
        apps = AppRegistry()._scan_linux()
    assert (
        apps["calculator"] == "gnome-calculator"
        and apps["org.gnome.calculator"] == "gnome-calculator"
    )
    assert "handler" not in apps and "url handler" not in apps
    assert "new window" not in apps  # actions are not apps
    assert apps["wrapped"] == "wrapped-app"
    assert apps["flat app"].startswith("/usr/bin/flatpak run")
