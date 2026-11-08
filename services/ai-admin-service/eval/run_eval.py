"""Offline accuracy harness: run the golden set through retrieval + orchestrator and
score Recall@k and citation integrity. docs/15-evaluation-strategy.md.

    PYTHONPATH=../../../libs python eval/run_eval.py --docs <sample_docs> --golden golden_set.sample.jsonl
"""
from __future__ import annotations

import argparse
import asyncio
import json
import os
import re

from contracts.models import UserContext
from rag.ingest import ingest_folder
from rag.store import get_index
from orchestrator.graph import run as run_graph


async def _score(golden_path: str) -> dict:
    user = UserContext(user_id="eval", roles=["Administrator"], session_id="eval")
    rows = [json.loads(l) for l in open(golden_path, encoding="utf-8") if l.strip()]
    recall_hits = 0
    citation_ok = 0
    for r in rows:
        ans = await run_graph(user, r["question"])
        cited = {c.doc_id for c in ans.citations}
        expected = set(r.get("expected_doc_ids", []))
        if expected & cited:
            recall_hits += 1
        hallucinated = set(re.findall(r"\[([A-Z0-9\-]+)\]", ans.text)) - cited
        if not hallucinated:
            citation_ok += 1
    n = len(rows) or 1
    return {"questions": n, "recall_at_k": round(recall_hits / n, 3),
            "citation_integrity": round(citation_ok / n, 3)}


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--docs", default="sample_docs")
    ap.add_argument("--golden", default="golden_set.sample.jsonl")
    args = ap.parse_args()
    if os.path.isdir(args.docs):
        ingest_folder(args.docs)
    print(f"index: {len(get_index().chunks)} chunks")
    print("scorecard:", asyncio.run(_score(args.golden)))


if __name__ == "__main__":
    main()
