import shutil
from pathlib import Path

import PyInstaller.__main__


# Root directory of the project
ROOT_DIR = Path(__file__).resolve().parent.parent
DIST_DIR = ROOT_DIR / "dist" / "amadeus"

print(f"[*] Starting build process from: {ROOT_DIR}")

# Cleanup previous builds
for dir_name in ["build", "dist"]:
    dir_path = ROOT_DIR / dir_name
    if dir_path.exists():
        print(f"[-] Removing old {dir_name} directory...")
        shutil.rmtree(dir_path)

# PyInstaller arguments
args = [
    str(ROOT_DIR / "src" / "api" / "server.py"),
    "--name=amadeus",
    "--onedir",  # Create a folder containing the exe and dependencies
    "--noconsole",  # Run as a background process (no command prompt)
    "--clean",  # Clean PyInstaller cache
    "--noconfirm",  # Overwrite output directory without asking
    # Metadata includes for common FastAPI/Pydantic/DI libraries
    "--copy-metadata=fastapi",
    "--copy-metadata=pydantic",
    "--copy-metadata=uvicorn",
    "--copy-metadata=dependency-injector",
    "--copy-metadata=alembic",
    "--copy-metadata=sqlalchemy",
    # Add data directories
    f"--add-data={ROOT_DIR / 'alembic'};alembic",
    f"--add-data={ROOT_DIR / 'Model'};Model",
    f"--add-data={ROOT_DIR / 'alembic.ini'};.",
]

print(f"[*] Running PyInstaller with args: {' '.join(args)}")
PyInstaller.__main__.run(args)

print("\n[*] Build complete!")
print(f"    Executable is located at: {DIST_DIR / 'amadeus.exe'}")
