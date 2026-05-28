"""
Dynamic Application Registry for Amadeus AI.

Discovers and caches installed applications across Windows, Mac, and Linux.
Utilizes rapidfuzz for fast string matching against the cache.
"""

import json
import logging
import platform
from pathlib import Path
from typing import Any


from rapidfuzz import fuzz, process


logger = logging.getLogger(__name__)


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

        # In-memory dictionary mapped as { "lowercase friendly name": "absolute execution path" }
        self.apps: dict[str, str] = self._load_cache()

    def _load_cache(self) -> dict[str, str]:
        """Load from JSON cache if it exists, otherwise trigger a scan."""
        if self.cache_file.exists():
            try:
                with self.cache_file.open(encoding="utf-8") as f:
                    apps: dict[str, str] = json.load(f)
                    logger.debug("Loaded %d applications from cache.", len(apps))
                    return apps
            except Exception as e:
                logger.exception("Failed to load app cache: %s. Rebuilding...", e)
        return self.scan_and_cache()

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
                logger.info(
                    f"Successfully cached {len(discovered)} applications to {self.cache_file}"
                )
            except Exception as e:
                logger.exception("Failed to write cache file: %s", e)

        self.apps = discovered
        return discovered

    def _scan_windows(self) -> dict[str, str]:
        """Use the standard library winreg to find registered App Paths."""
        import winreg as _winreg  # type: ignore[import]  # Windows-only
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

    def _scan_linux(self) -> dict[str, str]:
        """Parse .desktop files in standard Linux directories to find executables."""
        import re as _re
        apps = {}
        dirs = [Path("/usr/share/applications"), Path.home() / ".local/share/applications"]
        for d in dirs:
            if d.exists():
                for desktop_file in d.glob("*.desktop"):
                    name = desktop_file.stem.lower()
                    try:
                        content = desktop_file.read_text(encoding="utf-8", errors="ignore")
                        # Extract Exec= line and strip field codes (%u, %f, etc.)
                        exec_match = _re.search(r"^Exec=(.+)$", content, _re.MULTILINE)
                        if exec_match:
                            exec_val = exec_match.group(1).strip()
                            # Remove field codes like %u %U %f %F %i %c %k
                            exec_cmd = _re.sub(r"%[uUfFicdDnNk]", "", exec_val).strip()
                            # Take only the first token (the binary)
                            binary = exec_cmd.split()[0] if exec_cmd else ""
                            if binary:
                                apps[name] = binary
                                continue
                    except Exception:
                        pass
                    # Fallback: store the stem so we can attempt a $PATH lookup
                    apps[name] = desktop_file.stem
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

        # 3. Fuzzy Matching (Substrings, slight misspellings)
        # Use WRatio which handles different lengths, string cases, and token sorting well
        match = process.extractOne(
            requested_name, self.apps.keys(), scorer=fuzz.WRatio, score_cutoff=score_cutoff
        )

        if match:
            best_match_key = match[0]  # The string matched from the keys
            score = match[1]
            logger.debug(
                f"Fuzzy matched '{requested_name}' to '{best_match_key}' with score {score}"
            )
            return self.apps[best_match_key]

        return None
