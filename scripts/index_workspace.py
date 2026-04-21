"""
Omni-Workspace CLI Indexer — scripts/index_workspace.py

Run this script once (or on a schedule) to build the semantic search index
over your local files. Subsequent runs are incremental — only changed files
are re-embedded.

Usage:
    # First-time full build
    python scripts/index_workspace.py

    # Rebuild from scratch (force)
    python scripts/index_workspace.py --force

    # Index a custom root directory
    python scripts/index_workspace.py --root "C:\\Users\\ASUS\\Projects"

    # Specify a custom index output directory
    python scripts/index_workspace.py --index-dir "data/my_index"

    # Quiet mode (suppress progress bar)
    python scripts/index_workspace.py --quiet
"""

import argparse
import logging
import sys
import time
from pathlib import Path


# ---------------------------------------------------------------------------
# Bootstrap: make sure we can import from src/
# ---------------------------------------------------------------------------
_REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(_REPO_ROOT))


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Build or update the Amadeus Omni-Workspace semantic search index.",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=__doc__,
    )
    parser.add_argument(
        "--root",
        default=r"C:\Users\ASUS\Downloads",
        help="Root directory to index recursively. Default: C:\\Users\\ASUS\\Downloads",
    )
    parser.add_argument(
        "--max-chunks",
        type=int,
        default=15_000,
        help="Max chunks to index (0 = unlimited). Default 15000 keeps RAM ≤ ~70 MB.",
    )

    parser.add_argument(
        "--index-dir",
        default=str(_REPO_ROOT / "data" / "workspace_index"),
        help="Directory to store the index files. Default: data/workspace_index/",
    )
    parser.add_argument(
        "--force",
        action="store_true",
        help="Discard existing index and rebuild from scratch.",
    )
    parser.add_argument(
        "--quiet",
        action="store_true",
        help="Suppress INFO logging (show only warnings and errors).",
    )
    return parser.parse_args()


def setup_logging(quiet: bool) -> None:
    level = logging.WARNING if quiet else logging.INFO
    logging.basicConfig(
        format="%(asctime)s  %(levelname)-8s  %(name)s — %(message)s",
        datefmt="%H:%M:%S",
        level=level,
    )


def main() -> None:
    args = parse_args()
    setup_logging(args.quiet)
    logger = logging.getLogger("index_workspace")

    root = Path(args.root)
    index_dir = Path(args.index_dir)

    if not root.exists():
        logger.error("Root directory does not exist: %s", root)
        sys.exit(1)

    logger.info("=" * 60)
    logger.info("Amadeus Omni-Workspace Indexer")
    logger.info("  Root       : %s", root)
    logger.info("  Index dir  : %s", index_dir)
    logger.info("  Force rebuild: %s", args.force)
    logger.info("=" * 60)

    try:
        from src.infra.workspace_indexer import WorkspaceIndexer
    except ImportError as exc:
        logger.error("Failed to import WorkspaceIndexer: %s", exc)
        logger.error("Make sure you are running from the repo root and the venv is active.")
        sys.exit(1)

    indexer = WorkspaceIndexer(root=root, index_dir=index_dir, max_chunks=args.max_chunks)


    start = time.perf_counter()
    try:
        indexer.build(force=args.force)
    except KeyboardInterrupt:
        logger.warning("Indexing interrupted by user.")
        sys.exit(130)
    except Exception as exc:
        logger.error("Indexing failed: %s", exc, exc_info=True)
        sys.exit(1)

    elapsed = time.perf_counter() - start

    if indexer.is_ready:
        logger.info("=" * 60)
        logger.info("✓ Index complete!")
        logger.info("  Total chunks indexed : %d", indexer.chunk_count)
        logger.info("  Time elapsed         : %.1f seconds", elapsed)
        logger.info("  Index stored at      : %s", index_dir)
        logger.info("=" * 60)
        print(
            f"\n✓ Workspace indexed successfully: "
            f"{indexer.chunk_count} chunks in {elapsed:.1f}s\n"
            f"  Amadeus can now answer questions about your local files.\n"
        )
    else:
        logger.error("Indexing did not complete successfully.")
        sys.exit(1)


if __name__ == "__main__":
    main()
