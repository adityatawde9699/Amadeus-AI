"""
Model Manager for Amadeus AI.

Single responsibility: resolve local model paths, downloading from HuggingFace
when a model is missing and MODEL_DOWNLOAD_ENABLED=True.

All models are stored inside the project's Model/ directory so they travel
with the codebase and are never scattered across the system HF cache.

Controlled entirely via .env:

  MODEL_DIR=/absolute/path/to/Model          # default: <project>/Model/
  MODEL_DOWNLOAD_ENABLED=True                # auto-download on first run

  EMBED_MODEL_NAME=sentence-transformers/all-MiniLM-L6-v2
  EMBED_MODEL_LOCAL_DIR=                     # auto: MODEL_DIR/embed/<safe_name>

  SLM_MODEL_PATH=/abs/path/to/model.gguf    # takes full priority if given
  SLM_MODEL_REPO_ID=bartowski/Llama-3.2-1B-Instruct-GGUF
  SLM_MODEL_FILENAME=Llama-3.2-1B-Instruct-Q4_K_M.gguf
"""

from __future__ import annotations

import logging
import re
from pathlib import Path
from typing import TYPE_CHECKING


if TYPE_CHECKING:
    from src.core.config import Settings

logger = logging.getLogger(__name__)


def _safe_dir_name(model_id: str) -> str:
    """Convert 'org/model-name' to a filesystem-safe directory name."""
    return re.sub(r"[^a-zA-Z0-9_.\-]", "_", model_id)


class ModelManager:
    """
    Resolves local model paths and triggers auto-downloads when needed.

    Usage (called during service startup):
        mm = ModelManager(settings)
        embed_dir  = mm.resolve_embed_model()     # Path to local embed model dir
        gguf_path  = mm.resolve_gguf_model()      # Path to .gguf file or None
    """

    def __init__(self, settings: Settings) -> None:
        self.settings = settings
        self.model_dir: Path = Path(settings.MODEL_DIR)  # type: ignore[arg-type]
        self.model_dir.mkdir(parents=True, exist_ok=True)

    # -------------------------------------------------------------------------
    # Embedding model
    # -------------------------------------------------------------------------

    def resolve_embed_model(self) -> tuple[str, Path | None]:
        """
        Return (load_identifier, local_dir_or_None).

        load_identifier is either:
          - str path to the local directory (when already downloaded)
          - the HF model ID string (when loading from HF cache or downloading)

        If MODEL_DOWNLOAD_ENABLED and not yet downloaded, downloads into
        Model/embed/ and returns the path.
        """
        model_name = self.settings.EMBED_MODEL_NAME
        embed_root = self.model_dir / "embed"

        # Use explicit override if provided
        if self.settings.EMBED_MODEL_LOCAL_DIR:
            local_dir = Path(self.settings.EMBED_MODEL_LOCAL_DIR)
            if self._embed_model_exists(local_dir):
                logger.info("Embed model found at override path: %s", local_dir)
                return str(local_dir), local_dir
            logger.warning("EMBED_MODEL_LOCAL_DIR set but model not found: %s", local_dir)

        # Check if model already lives in Model/embed/ (standard HF cache layout)
        # SentenceTransformer caches as embed/<org>_<modelname>/ or embed/models--org--model/
        safe_name = _safe_dir_name(model_name)
        hf_cache_style = embed_root / f"models--{model_name.replace('/', '--')}"
        simple_style = embed_root / safe_name

        for candidate in [simple_style, hf_cache_style]:
            if self._embed_model_exists(candidate):
                logger.info("Embed model found locally: %s", candidate)
                return str(candidate), candidate

        if not self.settings.MODEL_DOWNLOAD_ENABLED:
            logger.info(
                "Embed model '%s' not in Model/embed/ and MODEL_DOWNLOAD_ENABLED=False. "
                "SentenceTransformer will use global HF cache.",
                model_name,
            )
            return model_name, None

        # Download into Model/embed/ using snapshot_download for clean layout
        logger.info(
            "Embed model '%s' not found locally — downloading to %s …",
            model_name, embed_root,
        )
        downloaded = self._download_embed_model_snapshot(model_name, embed_root)
        if downloaded and downloaded.exists():
            return str(downloaded), downloaded

        # Fallback: let SentenceTransformer handle it (uses global HF cache)
        logger.warning("Embed download failed — using HF model ID: %s", model_name)
        return model_name, None

    def _embed_model_exists(self, local_dir: Path) -> bool:
        """Check if the model directory contains the key config file."""
        return (local_dir / "config.json").exists()

    def _download_embed_model_snapshot(self, model_name: str, embed_root: Path) -> Path | None:
        """Download a sentence-transformers model using huggingface_hub.snapshot_download."""
        try:
            from huggingface_hub import snapshot_download

            embed_root.mkdir(parents=True, exist_ok=True)
            safe_name = _safe_dir_name(model_name)
            local_dir = embed_root / safe_name
            local_dir.mkdir(parents=True, exist_ok=True)

            logger.info("Downloading embed model '%s' …", model_name)
            snapshot_download(
                repo_id=model_name,
                local_dir=str(local_dir),
                ignore_patterns=["*.msgpack", "flax_model*", "tf_model*", "rust_model*"],
            )
            logger.info("Embed model downloaded to: %s", local_dir)
            return local_dir
        except ImportError:
            logger.exception(
                "huggingface_hub not installed — cannot download embed model. "
                "Run: pip install huggingface_hub"
            )
        except Exception as exc:
            logger.exception("Failed to download embed model '%s': %s", model_name, exc)
        return None

    # Keep old method as internal compat alias
    def _download_embed_model(self, model_name: str, local_dir: Path) -> None:
        self._download_embed_model_snapshot(model_name, local_dir.parent)

    # -------------------------------------------------------------------------
    # GGUF / LLM model
    # -------------------------------------------------------------------------

    def resolve_gguf_model(self) -> Path | None:
        """
        Return the absolute path to the GGUF model file.

        Resolution order:
          1. SLM_MODEL_PATH (explicit absolute path — always wins)
          2. Model/<filename> if SLM_MODEL_FILENAME exists there already
          3. Download from SLM_MODEL_REPO_ID / SLM_MODEL_FILENAME if both set
          4. None — LlamaCpp will not be activated
        """
        settings = self.settings

        # 1. Explicit path wins
        if settings.SLM_MODEL_PATH:
            p = Path(settings.SLM_MODEL_PATH)
            if p.exists():
                logger.info("Using configured SLM_MODEL_PATH: %s", p)
                return p
            logger.warning(
                "SLM_MODEL_PATH set to '%s' but file does not exist. "
                "Trying repo download …", p
            )

        if not settings.SLM_MODEL_FILENAME:
            logger.debug("SLM_MODEL_FILENAME not set — LlamaCpp disabled.")
            return None

        # 2. Check if file already lives in Model/
        local_gguf = self.model_dir / settings.SLM_MODEL_FILENAME
        if local_gguf.exists():
            logger.info("GGUF model found locally: %s", local_gguf)
            return local_gguf

        # 3. Download from HuggingFace
        if not settings.SLM_MODEL_REPO_ID:
            logger.warning(
                "GGUF file '%s' not found at %s and SLM_MODEL_REPO_ID not set. "
                "LlamaCpp disabled.",
                settings.SLM_MODEL_FILENAME, local_gguf,
            )
            return None

        if not settings.MODEL_DOWNLOAD_ENABLED:
            logger.warning(
                "GGUF model '%s' not found and MODEL_DOWNLOAD_ENABLED=False. "
                "LlamaCpp disabled.", local_gguf
            )
            return None

        logger.info(
            "GGUF model '%s' not found — downloading from '%s' …",
            settings.SLM_MODEL_FILENAME, settings.SLM_MODEL_REPO_ID,
        )
        return self._download_gguf(
            repo_id=settings.SLM_MODEL_REPO_ID,
            filename=settings.SLM_MODEL_FILENAME,
            dest_dir=self.model_dir,
        )

    def _download_gguf(self, repo_id: str, filename: str, dest_dir: Path) -> Path | None:
        """Download a single GGUF file from a HuggingFace repo."""
        dest_dir.mkdir(parents=True, exist_ok=True)
        dest_dir / filename

        try:
            from huggingface_hub import hf_hub_download

            logger.info(
                "Downloading %s from %s — this may take a while for large models…",
                filename, repo_id,
            )
            downloaded_path = hf_hub_download(
                repo_id=repo_id,
                filename=filename,
                local_dir=str(dest_dir),
            )
            real_path = Path(downloaded_path)
            logger.info("GGUF model downloaded: %s", real_path)
            return real_path

        except ImportError:
            logger.exception(
                "huggingface_hub not installed — cannot download GGUF model. "
                "Run: pip install huggingface_hub"
            )
        except Exception as exc:
            logger.exception(
                "Failed to download GGUF '%s' from '%s': %s", filename, repo_id, exc
            )
        return None
