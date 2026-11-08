"""Shared data contracts for the ABC Bank AI Assistant.

Pure-stdlib dataclasses so the core engine runs with zero third-party deps.
FastAPI services may wrap these with Pydantic at their edges.
See docs/01-system-architecture.md §4.
"""
from __future__ import annotations

from dataclasses import dataclass, field, asdict
from typing import Any, Literal, Optional


# ---- identity / RBAC ----
Role = Literal["Viewer", "Analyst", "Administrator"]


@dataclass
class UserContext:
    user_id: str
    roles: list[str] = field(default_factory=list)
    session_id: str = ""

    def has_role(self, role: str) -> bool:
        return role in self.roles

    @property
    def top_role(self) -> str:
        for r in ("Administrator", "Analyst", "Viewer"):
            if r in self.roles:
                return r
        return "Viewer"


# ---- retrieval ----
@dataclass
class Source:
    doc_id: str
    title: str = ""
    section: str = ""
    url: str = ""


@dataclass
class Chunk:
    chunk_id: str
    text: str
    source: Source
    metadata: dict[str, Any] = field(default_factory=dict)
    dense_score: float = 0.0
    sparse_score: float = 0.0
    rerank_score: float = 0.0
    score: float = 0.0  # final fused/rerank score


@dataclass
class RetrievalRequest:
    query: str
    top_k: int = 6
    namespaces: list[str] = field(default_factory=list)
    filters: dict[str, Any] = field(default_factory=dict)
    rerank: bool = True
    access_level_max: str = "restricted"


@dataclass
class RetrievalResult:
    chunks: list[Chunk] = field(default_factory=list)
    degraded: bool = False
    note: str = ""


# ---- agent events (power SSE + activity panel) ----
EventType = Literal[
    "node", "tool", "retrieval", "memory", "validation", "token", "final", "error"
]


@dataclass
class AgentEvent:
    type: EventType
    data: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {"type": self.type, **self.data}


# ---- answer ----
@dataclass
class Citation:
    doc_id: str
    title: str = ""
    section: str = ""
    url: str = ""


@dataclass
class Answer:
    text: str
    citations: list[Citation] = field(default_factory=list)
    route: str = ""
    reasoning: str = ""
    degraded: bool = False
    tokens: int = 0


# ---- RLM plan ----
@dataclass
class Batch:
    key: str
    sub_question: str


@dataclass
class SearchPlan:
    objective: str
    strategy: str = "map_reduce"
    filters: dict[str, Any] = field(default_factory=dict)
    batches: list[Batch] = field(default_factory=list)
    max_depth: int = 2


# ---- usage / token budget ----
@dataclass
class Usage:
    user_id: str
    limit: int
    used: int
    reset_at: str

    @property
    def remaining(self) -> int:
        return max(0, self.limit - self.used)


def to_jsonable(obj: Any) -> Any:
    """Best-effort conversion of our dataclasses to JSON-serialisable structures."""
    if hasattr(obj, "__dataclass_fields__"):
        return {k: to_jsonable(v) for k, v in asdict(obj).items()}
    if isinstance(obj, list):
        return [to_jsonable(x) for x in obj]
    if isinstance(obj, dict):
        return {k: to_jsonable(v) for k, v in obj.items()}
    return obj
