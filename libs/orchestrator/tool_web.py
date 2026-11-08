"""Web search tool. Real provider (Tavily) when TAVILY_API_KEY is set; otherwise an offline
stub so the tool path is demoable without network. Returns results as Chunks so they flow
through the same grounded-synthesis + citation path. docs/09 §4."""
from __future__ import annotations

import os

from contracts.models import Chunk, Source


def _results(query: str, k: int = 3) -> list[dict]:
    if os.getenv("TAVILY_API_KEY"):
        try:  # pragma: no cover - needs network + key
            import httpx

            r = httpx.post(
                "https://api.tavily.com/search",
                json={"api_key": os.environ["TAVILY_API_KEY"], "query": query,
                      "max_results": k, "include_answer": False},
                timeout=15,
            )
            data = r.json()
            return [{"title": x.get("title", ""), "url": x.get("url", ""), "snippet": x.get("content", "")}
                    for x in data.get("results", [])[:k]]
        except Exception:
            pass
    # offline stub — clearly labelled, deterministic
    return [{
        "title": f"Web result for: {query}",
        "url": "https://example.com/offline-stub",
        "snippet": f"(Offline web-search stub — set TAVILY_API_KEY for live results.) Query was: {query}",
    }]


def search(query: str, k: int = 3) -> list[Chunk]:
    chunks: list[Chunk] = []
    for i, r in enumerate(_results(query, k)):
        src = Source(doc_id=f"WEB-{i+1}", title=r["title"], section="web", url=r["url"])
        chunks.append(Chunk(chunk_id=f"web-{i+1}", text=f"{r['title']} {r['snippet']}", source=src, score=1.0 - i * 0.1))
    return chunks
