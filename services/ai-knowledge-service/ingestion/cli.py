"""Batch ingestion CLI — loads the mock corpus into the index. docs/11 Phase 1.

    PYTHONPATH=../../../libs python cli.py --path sample_docs
"""
from __future__ import annotations

import argparse

from rag.ingest import ingest_folder


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--path", default="sample_docs", help="folder of .md documents")
    args = ap.parse_args()
    stats = ingest_folder(args.path)
    print(f"Ingested {sum(stats.values())} chunks from {len(stats)} documents:")
    for k, v in stats.items():
        print(f"  {k}: {v} chunks")


if __name__ == "__main__":
    main()
