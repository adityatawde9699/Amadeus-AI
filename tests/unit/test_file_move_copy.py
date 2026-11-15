"""copy_file / move_file / create_folder against a real allowed directory."""

from __future__ import annotations

from types import SimpleNamespace

import pytest

from src.infra.tools import system_tools as st
from src.infra.tools.base import reported_failure


@pytest.fixture
def dirs(tmp_path, monkeypatch):
    allowed, outside = tmp_path / "allowed", tmp_path / "outside"
    allowed.mkdir()
    outside.mkdir()
    (allowed / "a.txt").write_text("A")
    (outside / "s.txt").write_text("secret")
    (allowed / "link").symlink_to(outside, target_is_directory=True)
    monkeypatch.setattr(
        "src.core.config.get_settings", lambda: SimpleNamespace(SEARCH_ALLOWED_DIRS=[str(allowed)])
    )
    return allowed, outside


def test_copy_and_move_inside_allowed_dir(dirs):
    allowed, _ = dirs
    assert "copied" in st.copy_file(str(allowed / "a.txt"), str(allowed / "sub" / "b.txt"))
    assert "moved" in st.move_file(str(allowed / "sub" / "b.txt"), str(allowed / "c" / "b.txt"))
    assert (allowed / "c" / "b.txt").read_text() == "A"
    assert not (allowed / "sub" / "b.txt").exists()


def test_existing_destination_is_not_overwritten_by_default(dirs):
    allowed, _ = dirs
    (allowed / "b.txt").write_text("B")
    for fn in (st.copy_file, st.move_file):
        result = fn(str(allowed / "a.txt"), str(allowed / "b.txt"))
        assert "already exists" in result and reported_failure(result)
        assert (allowed / "b.txt").read_text() == "B"
    assert "copied" in st.copy_file(str(allowed / "a.txt"), str(allowed / "b.txt"), overwrite=True)
    assert (allowed / "b.txt").read_text() == "A"


def test_escapes_are_denied(dirs):
    allowed, outside = dirs
    cases = [
        st.create_folder(str(outside / "x")),
        st.create_folder(str(allowed / ".." / "outside" / "y")),
        st.create_folder(str(allowed / "link" / "z")),
        st.copy_file(str(allowed / "a.txt"), str(outside / "leak.txt")),
        st.copy_file(str(allowed / "link" / "s.txt"), str(allowed / "s2.txt")),
        st.move_file(str(allowed / "a.txt"), str(outside / "a.txt")),
    ]
    assert all("Access denied" in r for r in cases), cases
    assert sorted(p.name for p in outside.iterdir()) == ["s.txt"]
    assert (allowed / "a.txt").exists()
