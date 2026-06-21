"""
ONNX Runtime embedding backend for Amadeus AI.

Drop-in replacement for SentenceTransformer.encode() built on onnxruntime +
tokenizers only. Per the architecture mandate (CLAUDE.md §3), the runtime
daemon must NOT import torch/sentence-transformers — loading PyTorch spikes
RSS by ~500MB, while this backend stays under ~40MB.

The ONNX model is produced once, offline, by ``scripts/export_embedding_onnx.py``
from the local sentence-transformers checkpoint. Expected layout:

    Model/embed/all-MiniLM-L6-v2-onnx/
        model.onnx        (int8-quantized if quantization succeeded)
        tokenizer.json

Usage:
    from src.infra.embeddings.onnx_embedder import OnnxEmbedder

    embedder = OnnxEmbedder(Path("Model/embed/all-MiniLM-L6-v2-onnx"))
    vecs = embedder.encode(["hello world"], normalize_embeddings=True)
"""

from __future__ import annotations

import logging
from pathlib import Path
from typing import Any


logger = logging.getLogger(__name__)

_MAX_SEQ_LENGTH = 256


class OnnxEmbedder:
    """Sentence embedder backed by onnxruntime (mean-pooling + L2 norm).

    API-compatible with ``SentenceTransformer.encode`` for the call patterns
    used in this codebase: accepts a string or list of strings, supports the
    ``normalize_embeddings`` and ``show_progress_bar`` keyword arguments.
    """

    def __init__(self, model_dir: Path | str) -> None:
        import numpy as np  # noqa: F401 — fail fast if numpy is missing
        import onnxruntime as ort
        from tokenizers import Tokenizer

        model_dir = Path(model_dir)
        model_path = model_dir / "model.onnx"
        tokenizer_path = model_dir / "tokenizer.json"

        if not model_path.exists() or not tokenizer_path.exists():
            raise FileNotFoundError(
                f"ONNX embedding model not found in {model_dir}. "
                "Run `python scripts/export_embedding_onnx.py` to create it."
            )

        self._tokenizer = Tokenizer.from_file(str(tokenizer_path))
        self._tokenizer.enable_truncation(max_length=_MAX_SEQ_LENGTH)
        self._tokenizer.enable_padding()

        so = ort.SessionOptions()
        # Single-threaded keeps the daemon's CPU + RSS footprint minimal;
        # embedding batches here are small (router queries, index builds).
        so.intra_op_num_threads = 2
        so.inter_op_num_threads = 1
        so.graph_optimization_level = ort.GraphOptimizationLevel.ORT_ENABLE_ALL
        self._session = ort.InferenceSession(
            str(model_path), sess_options=so, providers=["CPUExecutionProvider"]
        )
        self._input_names = {i.name for i in self._session.get_inputs()}
        # Identity for cache invalidation: re-exporting the model must
        # invalidate any embedding index built with the old file.
        stat = model_path.stat()
        self.fingerprint = f"OnnxEmbedder:{stat.st_size}:{int(stat.st_mtime)}"
        logger.info("OnnxEmbedder loaded: %s", model_path)

    def encode(
        self,
        sentences: str | list[str],
        normalize_embeddings: bool = True,
        show_progress_bar: bool = False,  # accepted for API compat; unused
        batch_size: int = 32,
        **_: Any,
    ) -> Any:
        """Embed one or more sentences. Returns np.ndarray (1-D for a single str)."""
        import numpy as np

        single = isinstance(sentences, str)
        texts = [sentences] if single else list(sentences)
        if not texts:
            return np.zeros((0, 0), dtype=np.float32)

        chunks = []
        for start in range(0, len(texts), batch_size):
            chunks.append(self._encode_batch(texts[start : start + batch_size], np))
        matrix = np.vstack(chunks)

        if normalize_embeddings:
            norms = np.linalg.norm(matrix, axis=1, keepdims=True)
            norms[norms == 0] = 1.0
            matrix = matrix / norms

        return matrix[0] if single else matrix

    def _encode_batch(self, texts: list[str], np: Any) -> Any:
        encodings = self._tokenizer.encode_batch(texts)
        input_ids = np.array([e.ids for e in encodings], dtype=np.int64)
        attention_mask = np.array([e.attention_mask for e in encodings], dtype=np.int64)

        feed: dict[str, Any] = {
            "input_ids": input_ids,
            "attention_mask": attention_mask,
        }
        if "token_type_ids" in self._input_names:
            feed["token_type_ids"] = np.array(
                [e.type_ids for e in encodings], dtype=np.int64
            )

        # Output 0 is the token-level hidden states: (batch, seq, dim)
        hidden = self._session.run(None, feed)[0]

        # Mean pooling over non-padding tokens
        mask = attention_mask[:, :, None].astype(np.float32)
        summed = (hidden * mask).sum(axis=1)
        counts = np.clip(mask.sum(axis=1), 1e-9, None)
        return (summed / counts).astype(np.float32)
