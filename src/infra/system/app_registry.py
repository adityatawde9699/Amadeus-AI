"""
Dynamic Application Registry for Amadeus AI.

Discovers and caches installed applications across Windows, Mac, and Linux.
Utilizes rapidfuzz for fast string matching against the cache.
"""

import json
import logging
import platform
import re
from pathlib import Path
from typing import Any

from rapidfuzz import fuzz, process


logger = logging.getLogger(__name__)

# Bump when the scan produces different keys, so existing caches are rebuilt once.
_CACHE_VERSION = "2"
_TOKEN_SPLIT = re.compile(r"[\s._-]+")


class AppRegistry:
    """
    Scans the operating system for installed applications and caches the paths
    in a JSON file to prevent expensive lookups on every invocation.
    Uses rapidfuzz for exact and substring matching.
    """

    def __init__(self, cache_dir: Path | None = None):
        if cache_dir is None:
            # Default to user's home directory under .amadeus
            cache_dir = Path.home() / ".amadeus"

        self.cache_file = cache_dir / "app_registry.json"
        self._version_file = cache_dir / "app_registry.version"

        # In-memory dictionary mapped as { "lowercase friendly name": "absolute execution path" }
        self.apps: dict[str, str] = self._load_cache()

    def _load_cache(self) -> dict[str, str]:
        """Load from JSON cache if it exists, otherwise trigger a scan."""
        if self.cache_file.exists() and self._cache_is_current():
            try:
                with self.cache_file.open(encoding="utf-8") as f:
                    apps: dict[str, str] = json.load(f)
                    logger.debug("Loaded %d applications from cache.", len(apps))
                    return apps
            except Exception as e:
                logger.exception("Failed to load app cache: %s. Rebuilding...", e)
        return self.scan_and_cache()

    def _cache_is_current(self) -> bool:
        try:
            return self._version_file.read_text(encoding="utf-8").strip() == _CACHE_VERSION
        except OSError:
            return False

    def scan_and_cache(self) -> dict[str, str]:
        """Scans the OS, builds the dictionary, and caches it to disk."""
        discovered = {}
        system = platform.system()

        logger.info("Starting application scan for %s...", system)

        try:
            if system == "Windows":
                discovered = self._scan_windows()
            elif system == "Darwin":
                discovered = self._scan_mac()
            elif system == "Linux":
                discovered = self._scan_linux()
        except Exception as e:
            logger.exception("Error during system scan: %s", e)

        # Ensure directory exists before writing
        self.cache_file.parent.mkdir(parents=True, exist_ok=True)

        if discovered:
            try:
                with self.cache_file.open("w", encoding="utf-8") as f:
                    json.dump(discovered, f, indent=2)
                self._version_file.write_text(_CACHE_VERSION, encoding="utf-8")
                logger.info(
                    f"Successfully cached {len(discovered)} applications to {self.cache_file}"
                )
            except Exception as e:
                logger.exception("Failed to write cache file: %s", e)

        self.apps = discovered
        return discovered

    def _scan_windows(self) -> dict[str, str]:
        """Use the standard library winreg to find registered App Paths."""
        import winreg as _winreg  # Windows-only

        winreg: Any = _winreg

        apps = {}

        key_path = r"SOFTWARE\Microsoft\Windows\CurrentVersion\App Paths"

        for root in [winreg.HKEY_LOCAL_MACHINE, winreg.HKEY_CURRENT_USER]:
            try:
                with winreg.OpenKey(root, key_path) as key:
                    num_subkeys = winreg.QueryInfoKey(key)[0]
                    for i in range(num_subkeys):
                        app_exe = winreg.EnumKey(key, i)
                        try:
                            with winreg.OpenKey(key, app_exe) as subkey:
                                # Primary value is the physical path
                                path, _ = winreg.QueryValueEx(subkey, "")
                                # Remove .exe extension for the friendly name
                                name = app_exe.lower().replace(".exe", "")
                                if path:
                                    apps[name] = str(path)
                        except OSError:
                            continue
            except OSError:
                continue

        # Manually append common Windows root directories directly if winreg missed them (optional fallback)
        # Note: Winreg is usually sufficient for program execution (os.startfile safely resolves them)
        return apps

    def _scan_mac(self) -> dict[str, str]:
        """Scan /Applications and user Applications for .app bundles."""
        apps = {}
        for app_dir in [Path("/Applications"), Path.home() / "Applications"]:
            if app_dir.exists():
                for app_path in app_dir.glob("*.app"):
                    name = app_path.stem.lower()
                    apps[name] = str(app_path)
        return apps

    @staticmethod
    def _desktop_exec(exec_line: str) -> str:
        """The command to run from a .desktop ``Exec=`` value (field codes removed)."""
        cmd = re.sub(r"%[uUfFicdDnNkvm]", "", exec_line).strip()
        tokens = cmd.split()
        # ``env FOO=bar app`` wrappers: skip to the real program.
        if tokens and tokens[0] == "env":
            tokens = [t for t in tokens[1:] if "=" not in t]
        if not tokens:
            return ""
        # flatpak/snap launchers need their arguments to name the app.
        if Path(tokens[0]).name in {"flatpak", "snap"}:
            return " ".join(tokens)
        return tokens[0]

    @staticmethod
    def _linux_app_dirs() -> list[Path]:
        return [
            Path("/usr/share/applications"),
            Path("/var/lib/snapd/desktop/applications"),
            Path("/var/lib/flatpak/exports/share/applications"),
            Path.home() / ".local/share/flatpak/exports/share/applications",
            Path.home() / ".local/share/applications",
        ]

    def _scan_linux(self) -> dict[str, str]:
        """Parse .desktop files (system, snap, flatpak, user) into name -> command.

        Each launchable app is reachable by its file stem and by the names people
        actually say: ``Name=`` and ``GenericName=`` ("Visual Studio Code",
        "Files", "Calculator"). Entries that are not applications a user would
        open (``NoDisplay``/``Hidden``: settings panels, URL handlers) are skipped.
        """
        apps: dict[str, str] = {}
        for d in self._linux_app_dirs():
            if not d.exists():
                continue
            for desktop_file in sorted(d.glob("*.desktop")):
                try:
                    content = desktop_file.read_text(encoding="utf-8", errors="ignore")
                except OSError:
                    continue
                # Only the [Desktop Entry] group (not [Desktop Action ...] blocks).
                entry = content.split("\n[Desktop Action", 1)[0]
                fields: dict[str, str] = {}
                for line in entry.splitlines():
                    key, sep, value = line.partition("=")
                    if sep and key.strip() in {
                        "Type",
                        "Exec",
                        "Name",
                        "GenericName",
                        "NoDisplay",
                        "Hidden",
                    }:
                        fields.setdefault(key.strip(), value.strip())
                if fields.get("Type", "Application") != "Application":
                    continue
                if fields.get("NoDisplay", "").lower() == "true" or (
                    fields.get("Hidden", "").lower() == "true"
                ):
                    continue
                command = self._desktop_exec(fields.get("Exec", "")) or desktop_file.stem
                stem = desktop_file.stem.lower()
                apps[stem] = command
                for label in (fields.get("Name"), fields.get("GenericName")):
                    if label and label.lower() not in apps:
                        apps[label.lower()] = command
        return apps

    def get_executable(self, requested_name: str, score_cutoff: float = 80.0) -> str | None:
        """
        Safely match the AI's requested name to an actual installed application.

        Args:
            requested_name: The application the user wants to open.
            score_cutoff: Minimum similarity score (0-100) to consider a match using RapidFuzz.

        Returns:
            Absolute path to the executable, or the desktop-file stem for Linux, or None if not found.
        """
        if not self.apps:
            return None

        requested_name = requested_name.lower().strip()

        # 1. Exact Match Check (Highest Priority)
        # Check against the keys first
        if requested_name in self.apps:
            return self.apps[requested_name]

        # 2. Substring or exact filename match (e.g. they ask for "chrome.exe" and we mapped "chrome")
        for _key_name, abs_path in self.apps.items():
            if requested_name == Path(abs_path).name.lower():
                return abs_path

        # 3. Whole-word match: every word asked for is a word of the app name
        # ("code" -> "visual studio code", "chrome" -> "google chrome").
        wanted = {t for t in _TOKEN_SPLIT.split(requested_name) if t}
        if wanted:
            hits = [
                key
                for key in self.apps
                if wanted <= {t for t in _TOKEN_SPLIT.split(key.lower()) if t}
            ]
            if hits:
                return self.apps[min(hits, key=len)]

        # 4. Typos ("spotfy", "fire fox"): whole-string similarity only. Partial
        # matching (WRatio) paired "spotify" with "evolution-alarm-notify".
        squashed = _TOKEN_SPLIT.sub("", requested_name)
        match = process.extractOne(
            squashed,
            self.apps.keys(),
            scorer=fuzz.ratio,
            processor=lambda k: _TOKEN_SPLIT.sub("", k.lower()),
            score_cutoff=max(score_cutoff, 80.0),
        )
        if match:
            logger.debug("Fuzzy matched '%s' to '%s' (%.0f)", requested_name, match[0], match[1])
            return self.apps[match[0]]

        return None
