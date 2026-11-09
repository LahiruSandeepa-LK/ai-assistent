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
        elif "TASK: context" in system:
            text = self._context(user)
        else:
            text = "How can I help you with ABC Bank's products and services?"
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
        # take the two most relevant blocks (already ranked upstream). The [DOC_ID] markers are
        # stripped before the customer sees the reply; they exist only for citation validation.
        top = blocks[:2]
        body = " ".join(top[0][2].strip().split("\n"))[:320].rstrip()
        cites = " ".join(f"[{b[0]}]" for b in top)
        return f"{body} {cites}"

    def _summarize(self, user: str) -> str:
        # internal memory summary (never shown to the customer)
        words = user.split()
        return " ".join(words[:50]) + ("…" if len(words) > 50 else "")

    def _context(self, user: str) -> str:
        return ("Happy to help — could you tell me a bit more about what you'd like to know "
                "regarding ABC Bank's products or services?")


def build_provider(name: str, *, api_key: str | None = None, model_strong: str | None = None,
                   model_fast: str | None = None, base_url: str | None = None) -> BaseProvider | None:
    """Construct a named real provider, or None if its SDK/key is unavailable.

    `api_key`/`model_*`/`base_url` let the runtime config store (admin console) inject
    credentials, model slugs and a custom endpoint directly; when omitted each adapter falls back
    to its env vars. `base_url` is honoured by the OpenAI/Anthropic adapters (OpenAI-compatible
    gateways); Gemini/mock ignore it."""
    name = (name or "").lower()
    kw = {"api_key": api_key, "model_strong": model_strong, "model_fast": model_fast,
          "base_url": base_url}
    try:  # pragma: no cover - exercised only when SDK + key are present
        if name == "gemini" and (api_key or os.getenv("GEMINI_API_KEY")):
            from .provider_gemini import GeminiProvider

            return GeminiProvider(**kw)
        if name == "anthropic" and (api_key or os.getenv("ANTHROPIC_API_KEY")):
            from .provider_anthropic import AnthropicProvider

            return AnthropicProvider(**kw)
        if name == "openai" and (api_key or os.getenv("OPENAI_API_KEY")):
            from .provider_openai import OpenAIProvider

            return OpenAIProvider(**kw)
    except Exception:
        return None
    return None


def _provider_from_config() -> BaseProvider | None:
    """If an admin created+activated an LLM config, build that provider from it (secret is read
    in-process via the store, never crossing the API boundary)."""
    try:
        from .config_store import get_config_store

        cfg = get_config_store().get_active()
        if not cfg or cfg.provider == "mock":
            return None if not cfg else MockProvider()
        secret = get_config_store().secret_for(cfg.id)
        return build_provider(cfg.provider, api_key=secret or None,
                              model_strong=cfg.model_strong or None,
                              model_fast=cfg.model_fast or None,
                              base_url=cfg.base_url or None)
    except Exception:
        return None


def get_provider() -> BaseProvider:
    """Return the configured provider. Precedence: active admin LLM config > LLM_PROVIDER env >
    MockProvider (offline default)."""
    from_cfg = _provider_from_config()
    if from_cfg is not None:
        return from_cfg
    provider = os.getenv("LLM_PROVIDER", "mock").lower()
    if provider in ("", "mock", "none"):
        return MockProvider()
    return build_provider(provider) or MockProvider()
