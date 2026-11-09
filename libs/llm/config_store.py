"""Runtime LLM configuration store.

Admins create an LLM config (provider + model slugs + an API key) through the admin console.
Security model (hard requirements):
  * CREATE-ONLY — a config is never edited after creation (no update method exists).
  * WRITE-ONLY SECRET — the API key is accepted on create but NEVER returned by any method
    that feeds the API/UI. `LLMConfig` (the public view) carries no secret field at all, so a
    secret physically cannot be serialised into an API response. The raw secret is held in a
    separate map and reachable only via `secret_for()`, which is called in-process by the model
    provider build — never by a request handler.

Persistence: a single JSON file at $LLM_CONFIG_PATH (default ./.runtime/llm_config.json), so
every service process (api/orchestrator/model-gateway/admin) sees the same active provider.
The file is server-side only, gitignored, and never served. For production, back this with a
secrets manager (Vault/KMS) instead of a local file — see ADR-011. docs/14, ADR-003, ADR-010.
"""
from __future__ import annotations

import json
import os
import threading
import time
import uuid
from dataclasses import asdict, dataclass, field


@dataclass
class LLMConfig:
    """PUBLIC view of a config — deliberately has NO secret field."""
    id: str
    provider: str          # gemini | anthropic | openai | mock
    model_strong: str
    model_fast: str
    label: str = ""
    base_url: str = ""
    has_secret: bool = False
    active: bool = False
    created_at: float = field(default_factory=time.time)


def _default_path() -> str:
    return os.getenv("LLM_CONFIG_PATH", os.path.join(os.getcwd(), ".runtime", "llm_config.json"))


class LLMConfigStore:
    def __init__(self, path: str | None = None, persist: bool | None = None):
        # persist to disk unless explicitly disabled (tests pass persist=False)
        self._persist = (persist if persist is not None
                         else os.getenv("LLM_CONFIG_PERSIST", "true").lower() == "true")
        self._path = path or _default_path()
        self._lock = threading.RLock()
        self._configs: dict[str, LLMConfig] = {}
        self._secrets: dict[str, str] = {}   # id -> raw secret; NEVER serialised to an API response
        self._version = 0
        self._mtime = 0.0
        if self._persist:
            self._load()

    # ---- create (no update: create-only by design) ----
    def create(self, provider: str, model_strong: str, model_fast: str, *,
               secret: str = "", label: str = "", base_url: str = "",
               activate: bool = True) -> LLMConfig:
        provider = (provider or "").lower().strip()
        if provider not in ("gemini", "anthropic", "openai", "mock"):
            raise ValueError(f"unsupported provider: {provider!r}")
        cid = uuid.uuid4().hex[:12]
        cfg = LLMConfig(id=cid, provider=provider, model_strong=model_strong.strip(),
                        model_fast=model_fast.strip(), label=label.strip(),
                        base_url=base_url.strip(), has_secret=bool(secret))
        with self._lock:
            self._configs[cid] = cfg
            if secret:
                self._secrets[cid] = secret
            if activate:
                self._activate_locked(cid)
            self._version += 1
            self._save_locked()
        return cfg

    def activate(self, config_id: str) -> LLMConfig:
        with self._lock:
            if config_id not in self._configs:
                raise KeyError(config_id)
            self._activate_locked(config_id)
            self._version += 1
            self._save_locked()
            return self._configs[config_id]

    def _activate_locked(self, config_id: str) -> None:
        for c in self._configs.values():
            c.active = (c.id == config_id)

    def delete(self, config_id: str) -> bool:
        with self._lock:
            existed = self._configs.pop(config_id, None) is not None
            self._secrets.pop(config_id, None)
            self._version += 1
            self._save_locked()
            return existed

    # ---- read (public views only — never the secret) ----
    def list(self) -> list[LLMConfig]:
        with self._lock:
            self._maybe_reload()
            return sorted(self._configs.values(), key=lambda c: c.created_at)

    def get_active(self) -> LLMConfig | None:
        with self._lock:
            self._maybe_reload()
            for c in self._configs.values():
                if c.active:
                    return c
            return None

    @property
    def version(self) -> int:
        with self._lock:
            self._maybe_reload()
            return self._version

    # ---- internal-only secret access (called by provider build, never by a handler) ----
    def secret_for(self, config_id: str) -> str:
        with self._lock:
            self._maybe_reload()
            return self._secrets.get(config_id, "")

    # ---- persistence ----
    def _save_locked(self) -> None:
        if not self._persist:
            return
        os.makedirs(os.path.dirname(self._path), exist_ok=True)
        payload = {
            "configs": [asdict(c) for c in self._configs.values()],
            # secrets live in the SAME server-only file (gitignored); never exposed via API.
            "secrets": self._secrets,
        }
        tmp = self._path + ".tmp"
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump(payload, f)
        os.replace(tmp, self._path)
        try:
            self._mtime = os.path.getmtime(self._path)
        except OSError:
            pass

    def _maybe_reload(self) -> None:
        """Re-read the file if another process changed it (cross-process config propagation)."""
        if not self._persist:
            return
        try:
            mtime = os.path.getmtime(self._path)
        except OSError:
            return
        if mtime != self._mtime:
            self._configs.clear()
            self._secrets.clear()
            self._load()

    def _load(self) -> None:
        try:
            with open(self._path, encoding="utf-8") as f:
                payload = json.load(f)
            self._mtime = os.path.getmtime(self._path)
        except (FileNotFoundError, json.JSONDecodeError, OSError):
            return
        for raw in payload.get("configs", []):
            cfg = LLMConfig(**{k: raw[k] for k in raw if k in LLMConfig.__annotations__})
            self._configs[cfg.id] = cfg
        self._secrets = dict(payload.get("secrets", {}))
        self._version += 1


_STORE: LLMConfigStore | None = None


def get_config_store() -> LLMConfigStore:
    global _STORE
    if _STORE is None:
        _STORE = LLMConfigStore()
    return _STORE


def reset_config_store() -> None:
    """Test hook — drop the singleton so the next get_config_store() re-reads/re-inits."""
    global _STORE
    _STORE = None
