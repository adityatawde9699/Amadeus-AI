"""
One-time export of the all-MiniLM-L6-v2 embedding model to ONNX.

This is a BUILD-TIME script — it imports torch/transformers, which are
forbidden in the runtime daemon (CLAUDE.md §3). Run it once on setup:

    # export deps are intentionally NOT in pyproject (they conflict with the
    # numpy<2 pin on the py3.13+ resolution split) — install transiently:
    uv pip install onnxscript "ml-dtypes>=0.5.3"
    python scripts/export_embedding_onnx.py

It reads the local sentence-transformers checkpoint from
Model/embed/sentence-transformers_all-MiniLM-L6-v2 (downloading from
HuggingFace only if missing) and writes:

    Model/embed/all-MiniLM-L6-v2-onnx/model.onnx   (int8 dynamic-quantized)
    Model/embed/all-MiniLM-L6-v2-onnx/tokenizer.json

After this, the runtime uses src/infra/embeddings/onnx_embedder.py and
never touches PyTorch.
"""

from __future__ import annotations

import shutil
import sys
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parent.parent
SRC_MODEL_DIR = PROJECT_ROOT / "Model" / "embed" / "sentence-transformers_all-MiniLM-L6-v2"
OUT_DIR = PROJECT_ROOT / "Model" / "embed" / "all-MiniLM-L6-v2-onnx"
HF_MODEL_ID = "sentence-transformers/all-MiniLM-L6-v2"
MAX_SEQ_LENGTH = 256


def main() -> int:
    import torch
    from transformers import AutoModel, AutoTokenizer

    source = str(SRC_MODEL_DIR) if SRC_MODEL_DIR.exists() else HF_MODEL_ID
    print(f"Loading checkpoint from: {source}")
    model = AutoModel.from_pretrained(source)
    tokenizer = AutoTokenizer.from_pretrained(source)
    model.eval()

    OUT_DIR.mkdir(parents=True, exist_ok=True)
    fp32_path = OUT_DIR / "model_fp32.onnx"
    final_path = OUT_DIR / "model.onnx"

    # Batch of 2 with different lengths so both batch and sequence dims are
    # traced as dynamic (a batch-of-1 sample can bake batch=1 into the graph).
    sample = tokenizer(
        ["Amadeus export sample", "a second, slightly longer calibration sentence"],
        return_tensors="pt",
        padding=True,
        truncation=True,
        max_length=MAX_SEQ_LENGTH,
    )
    # Order MUST match BertModel.forward(input_ids, attention_mask, token_type_ids)
    # — tokenizer dict order is (input_ids, token_type_ids, attention_mask), and
    # passing that positionally silently swaps the mask and type ids.
    input_names = [n for n in ("input_ids", "attention_mask", "token_type_ids") if n in sample]
    dynamic_axes = {name: {0: "batch", 1: "sequence"} for name in input_names}
    dynamic_axes["last_hidden_state"] = {0: "batch", 1: "sequence"}

    print(f"Exporting to ONNX (inputs: {input_names}) ...")
    with torch.no_grad():
        torch.onnx.export(
            model,
            args=tuple(sample[name] for name in input_names),
            f=str(fp32_path),
            input_names=input_names,
            output_names=["last_hidden_state"],
            dynamic_axes=dynamic_axes,
            opset_version=14,
        )

    def _works_with_dynamic_batch(model_path: Path) -> bool:
        """Verify the model handles varying batch sizes (catches baked-in dims)."""
        import numpy as np
        import onnxruntime as ort

        sess = ort.InferenceSession(str(model_path), providers=["CPUExecutionProvider"])
        names = {i.name for i in sess.get_inputs()}
        for batch in (1, 3):
            enc = tokenizer(["test sentence"] * batch, return_tensors="np", padding=True)
            feed = {k: v.astype(np.int64) for k, v in enc.items() if k in names}
            out = sess.run(None, feed)[0]
            if out.shape[0] != batch:
                return False
        return True

    if not _works_with_dynamic_batch(fp32_path):
        print("ERROR: exported model does not support dynamic batch sizes.")
        return 1

    # Dynamic int8 quantization: ~90MB → ~23MB on disk, lower RSS, faster CPU inference.
    try:
        from onnxruntime.quantization import QuantType, quantize_dynamic

        print("Quantizing to int8 (dynamic) ...")
        quantize_dynamic(str(fp32_path), str(final_path), weight_type=QuantType.QInt8)
        if _works_with_dynamic_batch(final_path):
            fp32_path.unlink()
        else:
            print("Quantized model failed the dynamic-batch check; keeping fp32 model.")
            final_path.unlink()
            shutil.move(str(fp32_path), str(final_path))
    except Exception as exc:
        print(f"Quantization failed ({exc}); keeping fp32 model.")
        shutil.move(str(fp32_path), str(final_path))

    # The runtime tokenizer loads the fast-tokenizer JSON directly.
    src_tok = SRC_MODEL_DIR / "tokenizer.json"
    if src_tok.exists():
        shutil.copy(src_tok, OUT_DIR / "tokenizer.json")
    else:
        tokenizer.save_pretrained(OUT_DIR)

    # Smoke test with the runtime backend (no torch).
    sys.path.insert(0, str(PROJECT_ROOT))
    from src.infra.embeddings.onnx_embedder import OnnxEmbedder

    embedder = OnnxEmbedder(OUT_DIR)
    vec = embedder.encode("check my inbox", normalize_embeddings=True)
    print(f"Smoke test OK — embedding dim={vec.shape[0]}, norm={float((vec ** 2).sum()) ** 0.5:.4f}")
    print(f"Done. Model at: {final_path} ({final_path.stat().st_size / 1e6:.1f} MB)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
