"""
Train the runtime category classifier and write ``Model/category_classifier.npz``.

This is the only producer of the artifact loaded by
``src/app/services/category_classifier.py`` (numpy arrays, no pickle). It needs
scikit-learn, which is a build-time dependency only — the runtime never imports
it. Used by the Docker ``artifacts`` stage; locally:

    uv run --with scikit-learn python scripts/train_category_classifier.py [MODEL_DIR]
"""

from __future__ import annotations

import logging
import sys
from pathlib import Path


sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from src.app.services.category_classifier import CategoryClassifier


def main() -> int:
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")
    model_dir = Path(sys.argv[1]) if len(sys.argv) > 1 else Path("Model")
    clf = CategoryClassifier(model_dir=model_dir)
    clf.train()
    out = model_dir / CategoryClassifier.CACHE_FILENAME
    if not out.exists():
        print(f"error: {out} was not written", file=sys.stderr)
        return 1
    reloaded = CategoryClassifier(model_dir=model_dir)
    if not reloaded.load():
        print(f"error: {out} could not be reloaded", file=sys.stderr)
        return 1
    print(f"wrote {out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
