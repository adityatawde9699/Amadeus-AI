"""Patch system_tools.py: insert sandbox helper + apply to copy/move/create."""
from pathlib import Path

FILE = Path(r"src\infra\tools\system_tools.py")
content = FILE.read_text(encoding="utf-8")

# ── 1. Insert the helper function after app_registry declaration ──────────────
HELPER = r'''

# =============================================================================
# PATH SANDBOX HELPER (CQ-01, CQ-02)
# =============================================================================


def _assert_in_allowed_dirs(path):
    """Return an error string if *path* is outside SEARCH_ALLOWED_DIRS, else None.

    CQ-01 / CQ-02: Prevents copy_file / move_file / create_folder from writing
    to arbitrary filesystem locations when the LLM is tricked via prompt injection.
    """
    from src.core.config import get_settings
    settings = get_settings()
    allowed_roots = [Path(d).expanduser().resolve() for d in settings.SEARCH_ALLOWED_DIRS]
    try:
        resolved = path.resolve()
    except Exception:
        return "Access denied: cannot resolve path '{}'.".format(path)
    for root in allowed_roots:
        try:
            resolved.relative_to(root)
            return None  # inside an allowed directory
        except ValueError:
            continue
    roots_str = ", ".join(str(r) for r in allowed_roots)
    return (
        "Access denied: '{}' is outside the allowed directories ({}).".format(resolved, roots_str)
    )

'''

MARKER = "app_registry = AppRegistry()"
idx = content.find(MARKER)
assert idx != -1, "MARKER NOT FOUND"
insert_at = idx + len(MARKER)
content = content[:insert_at] + HELPER + content[insert_at:]

# ── 2. Patch copy_file: add sandbox check after src_path / dst_path resolved ──
OLD_COPY = """\
        src_path = Path(src).resolve()
        dst_path = Path(dst).resolve()

        if not src_path.is_file():"""

NEW_COPY = """\
        src_path = Path(src).resolve()
        dst_path = Path(dst).resolve()

        # CQ-01: Sandbox both source and destination
        for label, p in (("source", src_path), ("destination", dst_path)):
            err = _assert_in_allowed_dirs(p)
            if err:
                return "copy_file {} - {}".format(label, err)

        if not src_path.is_file():"""

content = content.replace(OLD_COPY, NEW_COPY, 1)

# ── 3. Patch move_file: same guard ────────────────────────────────────────────
OLD_MOVE = """\
        src_path = Path(src).resolve()
        dst_path = Path(dst).resolve()

        if not src_path.is_file():
            return f\"Source file does not exist: {src}\"

        dst_path.parent.mkdir(parents=True, exist_ok=True)
        shutil.move(str(src_path), str(dst_path))"""

NEW_MOVE = """\
        src_path = Path(src).resolve()
        dst_path = Path(dst).resolve()

        # CQ-01: Sandbox both source and destination
        for label, p in (("source", src_path), ("destination", dst_path)):
            err = _assert_in_allowed_dirs(p)
            if err:
                return "move_file {} - {}".format(label, err)

        if not src_path.is_file():
            return f\"Source file does not exist: {src}\"

        dst_path.parent.mkdir(parents=True, exist_ok=True)
        shutil.move(str(src_path), str(dst_path))"""

content = content.replace(OLD_MOVE, NEW_MOVE, 1)

# ── 4. Patch create_folder: guard before mkdir ────────────────────────────────
OLD_CREATE = """\
        folder_path = Path(target).resolve()

        if folder_path.exists():"""

NEW_CREATE = """\
        folder_path = Path(target).resolve()

        # CQ-02: Sandbox the target directory
        err = _assert_in_allowed_dirs(folder_path)
        if err:
            return "create_folder - {}".format(err)

        if folder_path.exists():"""

content = content.replace(OLD_CREATE, NEW_CREATE, 1)

FILE.write_text(content, encoding="utf-8")
print("Done. Patched system_tools.py successfully.")
