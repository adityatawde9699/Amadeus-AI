#!/usr/bin/env python3
"""
Build Script for Amadeus AI Desktop Application.

This script:
1. Uses PyInstaller to compile the FastAPI backend into a standalone binary
2. Copies the binary to the Tauri resources directory for bundling
3. The Tauri build then wraps this binary inside the final .exe/.dmg/.deb

Usage:
    # From the Amadeus-AI root directory:
    python scripts/build_backend_binary.py

    # Then build the Tauri app:
    cd clients/amadeus-desktop && npm run tauri build

Requirements:
    pip install pyinstaller
"""

import os
import platform
import shutil
import subprocess
import sys
from pathlib import Path

# ─── Config ──────────────────────────────────────────────────────────────────

PROJECT_ROOT = Path(__file__).parent.parent.resolve()
SRC_ENTRY    = PROJECT_ROOT / "src" / "api" / "server.py"
OUTPUT_DIR   = PROJECT_ROOT / "clients" / "amadeus-desktop" / "src-tauri" / "resources"
BUILD_DIR    = PROJECT_ROOT / "dist_backend"

BINARY_NAME = "amadeus-backend"
if platform.system() == "Windows":
    BINARY_NAME += ".exe"

# Files/folders to exclude from the bundle (reduces binary size)
EXCLUDES = [
    "pytest", "IPython", "jupyter", "notebook",
    "matplotlib", "scipy", "pandas",
    "tkinter", "_tkinter",
    "PIL", "cv2",
    "test", "tests",
    "locust",
]

# Data files the backend needs at runtime
DATAS = [
    # (source_path, dest_path_in_bundle)
    (str(PROJECT_ROOT / "Model"), "Model"),
    (str(PROJECT_ROOT / "data"), "data"),
    (str(PROJECT_ROOT / "alembic"), "alembic"),
    (str(PROJECT_ROOT / "alembic.ini"), "."),
]

# ─── Helpers ─────────────────────────────────────────────────────────────────

def run(cmd: list[str], cwd: Path = PROJECT_ROOT) -> None:
    """Run a subprocess command and raise on failure."""
    print(f"\n▸ {' '.join(cmd)}")
    result = subprocess.run(cmd, cwd=str(cwd))
    if result.returncode != 0:
        sys.exit(f"Command failed with exit code {result.returncode}")


def build_binary() -> None:
    """Use PyInstaller to compile the backend into a single file."""
    print("=" * 60)
    print("Amadeus AI — Building backend binary")
    print(f"  Platform : {platform.system()} {platform.machine()}")
    print(f"  Entry    : {SRC_ENTRY.relative_to(PROJECT_ROOT)}")
    print(f"  Output   : {BUILD_DIR.relative_to(PROJECT_ROOT)}")
    print("=" * 60)

    # Check PyInstaller is available
    try:
        import PyInstaller  # noqa: F401
    except ImportError:
        print("Installing PyInstaller...")
        run([sys.executable, "-m", "pip", "install", "pyinstaller"])

    # Build the --add-data arguments
    separator = ";" if platform.system() == "Windows" else ":"
    data_args = []
    for src, dst in DATAS:
        if Path(src).exists():
            data_args += ["--add-data", f"{src}{separator}{dst}"]
        else:
            print(f"  ⚠  Skipping missing data: {src}")

    # Build --exclude-module arguments
    exclude_args = []
    for mod in EXCLUDES:
        exclude_args += ["--exclude-module", mod]

    cmd = [
        sys.executable, "-m", "PyInstaller",
        "--onefile",                          # Single executable
        "--name", BINARY_NAME.replace(".exe", ""),
        "--distpath", str(BUILD_DIR),
        "--workpath", str(BUILD_DIR / "work"),
        "--specpath", str(BUILD_DIR),
        "--noconfirm",
        "--clean",
        # FastAPI / uvicorn need these hidden imports
        "--hidden-import", "uvicorn.lifespan.on",
        "--hidden-import", "uvicorn.lifespan.off",
        "--hidden-import", "uvicorn.protocols.http.auto",
        "--hidden-import", "uvicorn.protocols.websockets.auto",
        "--hidden-import", "uvicorn.loops.auto",
        "--hidden-import", "fastapi",
        "--hidden-import", "aiosqlite",
        "--hidden-import", "sqlalchemy.dialects.sqlite",
        "--hidden-import", "src.api.server",
        *data_args,
        *exclude_args,
        str(SRC_ENTRY),
    ]

    run(cmd)


def copy_to_tauri() -> None:
    """Copy the compiled binary to the Tauri resources directory."""
    binary_src = BUILD_DIR / BINARY_NAME
    if not binary_src.exists():
        # PyInstaller may not add .exe on Windows — try without
        binary_src = BUILD_DIR / BINARY_NAME.replace(".exe", "")

    if not binary_src.exists():
        sys.exit(f"❌ Binary not found at {binary_src}")

    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    dest = OUTPUT_DIR / BINARY_NAME
    shutil.copy2(binary_src, dest)

    # Make it executable on Unix
    if platform.system() != "Windows":
        dest.chmod(0o755)

    print(f"\n✅ Binary written to: {dest.relative_to(PROJECT_ROOT)}")
    size_mb = dest.stat().st_size / (1024 * 1024)
    print(f"   Size: {size_mb:.1f} MB")


def main() -> None:
    print("\n🔧 Amadeus AI — Backend Build Script")
    print(f"   Working directory: {PROJECT_ROOT}\n")

    build_binary()
    copy_to_tauri()

    print("\n" + "=" * 60)
    print("✅ Backend binary ready!")
    print("   Next step: cd clients/amadeus-desktop && npm run tauri build")
    print("=" * 60 + "\n")


if __name__ == "__main__":
    main()
