"""LLM provider interface + offline MockProvider + optional real adapters.
ADR-003. All calls funnel through the gateway for metering (ADR-010)."""
from __future__ import annotations

import os
import re
from dataclasses import dataclass


@dataclass
class Completion:
    text: str
    prompt_tokens: int
    completion_tokens: int

    @property
    def total_tokens(self) -> int:
        return self.prompt_tokens + self.completion_tokens


def _count_tokens(text: str) -> int:
    return max(1, int(len(text.split()) * 1.3))


class BaseProvider:
    is_mock = False
    name = "base"

    def complete(self, system: str, user: str, *, model: str = "strong") -> Completion:  # pragma: no cover
        raise NotImplementedError


class MockProvider(BaseProvider):
    """Deterministic, offline provider. Produces grounded, cited, extractive answers so
    the full pipeline is demoable with zero API keys. Branches on a `TASK:` marker in
    the system prompt."""

    is_mock = True
    name = "mock"

    def complete(self, system: str, user: str, *, model: str = "strong") -> Completion:
        if "TASK: synthesize" in system:
            text = self._synthesize(user)
        elif "TASK: summarize" in system:
            text = self._summarize(user)
        else:
            text = "I can only answer from retrieved ABC Bank documents."
        return Completion(text, _count_tokens(system + user), _count_tokens(text))

    def _synthesize(self, user: str) -> str:
        # Context blocks are formatted by the response node as:  [DOC_ID | section] body
        blocks = re.findall(r"\[([A-Z0-9\-]+) \| ([^\]]+)\]\s*(.+?)(?=\n\[|\Z)", user, re.S)
        question = ""
        mq = re.search(r"QUESTION:\s*(.+)", user)
        if mq:
            question = mq.group(1).strip()
        if not blocks:
            return "I couldn't find supporting evidence in the knowledge base, so I can't answer that confidently."
        # take the two most relevant blocks (already ranked upstream)
        top = blocks[:2]
        lead = top[0][2].strip().split("\n")
        body = " ".join(lead)[:280]
        cites = " ".join(f"[{b[0]}]" for b in top)
        return (
            f"{body} {cites}\n\n"
            f"(Answer grounded in the retrieved ABC Bank documents above.)"
        )

    def _summarize(self, user: str) -> str:
        words = user.split()
        return "Summary: " + " ".join(words[:50]) + ("…" if len(words) > 50 else "")


def build_provider(name: str) -> BaseProvider | None:
    """Construct a named real provider, or None if its SDK/key is unavailable."""
    name = (name or "").lower()
    try:  # pragma: no cover - exercised only when SDK + key are present
        if name == "gemini" and os.getenv("GEMINI_API_KEY"):
            from .provider_gemini import GeminiProvider

            return GeminiProvider()
        if name == "anthropic" and os.getenv("ANTHROPIC_API_KEY"):
            from .provider_anthropic import AnthropicProvider

            return AnthropicProvider()
        if name == "openai" and os.getenv("OPENAI_API_KEY"):
            from .provider_openai import OpenAIProvider

            return OpenAIProvider()
    except Exception:
        return None
    return None


def get_provider() -> BaseProvider:
    """Return the configured provider; MockProvider offline. Set LLM_PROVIDER to
    gemini | anthropic | openai | mock (plus the matching API key)."""
    provider = os.getenv("LLM_PROVIDER", "mock").lower()
    if provider in ("", "mock", "none"):
        return MockProvider()
    return build_provider(provider) or MockProvider()
