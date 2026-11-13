"""GGUF resolution: explicit path, local Model/, and where downloads land."""

from __future__ import annotations

from types import SimpleNamespace

from src.infra.model_manager import ModelManager


FILE = "tiny-Q4_K_M.gguf"


def _mm(tmp_path, **over):
    settings = SimpleNamespace(
        MODEL_DIR=tmp_path / "Model",
        SLM_MODEL_PATH=None,
        SLM_MODEL_FILENAME=FILE,
        SLM_MODEL_REPO_ID="org/tiny-GGUF",
        MODEL_DOWNLOAD_ENABLED=True,
    )
    for k, v in over.items():
        setattr(settings, k, v)
    mm = ModelManager(settings)
    calls = []

    def fake_download(repo_id, filename, dest_dir):
        calls.append((repo_id, filename, dest_dir))
        return dest_dir / filename

    mm._download_gguf = fake_download
    return mm, calls


def test_existing_explicit_path_wins(tmp_path):
    model = tmp_path / "elsewhere.gguf"
    model.write_bytes(b"x")
    mm, calls = _mm(tmp_path, SLM_MODEL_PATH=str(model))
    assert mm.resolve_gguf_model() == model and calls == []


def test_found_in_model_dir(tmp_path):
    (tmp_path / "Model").mkdir()
    (tmp_path / "Model" / FILE).write_bytes(b"x")
    mm, calls = _mm(tmp_path)
    assert mm.resolve_gguf_model() == tmp_path / "Model" / FILE and calls == []


def test_downloads_into_model_dir_by_default(tmp_path):
    mm, calls = _mm(tmp_path)
    assert mm.resolve_gguf_model() == tmp_path / "Model" / FILE
    assert calls == [("org/tiny-GGUF", FILE, tmp_path / "Model")]


def test_missing_explicit_path_downloads_beside_it(tmp_path):
    # docker-compose: SLM_MODEL_PATH points into a persistent volume.
    vol = tmp_path / "gguf"
    mm, calls = _mm(tmp_path, SLM_MODEL_PATH=str(vol / FILE))
    assert mm.resolve_gguf_model() == vol / FILE
    assert calls == [("org/tiny-GGUF", FILE, vol)]


def test_disabled_paths(tmp_path):
    assert _mm(tmp_path, SLM_MODEL_FILENAME=None)[0].resolve_gguf_model() is None
    assert _mm(tmp_path, SLM_MODEL_REPO_ID=None)[0].resolve_gguf_model() is None
    mm, calls = _mm(tmp_path, MODEL_DOWNLOAD_ENABLED=False)
    assert mm.resolve_gguf_model() is None and calls == []


def test_memory_skips_embed_download_without_sentence_transformers(monkeypatch):
    """The Docker image has no sentence-transformers: resolving (which downloads
    the full checkpoint) must not run when it could never be loaded."""
    import asyncio

    from src.infra import model_manager, turbovec_memory
    from src.infra.memory_service import QdrantMemoryService

    calls = []
    monkeypatch.setattr(model_manager, "sentence_transformers_available", lambda: False)
    monkeypatch.setattr(
        model_manager.ModelManager, "resolve_embed_model", lambda self: calls.append(1)
    )
    monkeypatch.setitem(__import__("sys").modules, "sentence_transformers", None)
    settings = SimpleNamespace(
        EMBED_MODEL_NAME="sentence-transformers/all-MiniLM-L6-v2",
        GEMINI_API_KEY=None,
        MEMORY_EMBED_MODEL="x",
    )

    svc = QdrantMemoryService.__new__(QdrantMemoryService)
    svc._settings = settings
    svc._enabled = True
    svc._setup_embedding_model()

    tv = turbovec_memory.TurbovecMemoryService.__new__(turbovec_memory.TurbovecMemoryService)
    tv._settings = settings
    tv._enabled = True
    asyncio.run(tv._setup_embedding_model())

    assert calls == []
    assert tv._enabled is False  # no local model and no Gemini key
