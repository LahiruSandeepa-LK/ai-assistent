# ADR-011: Runtime LLM configuration & secret handling

**Status:** Accepted · **Date:** 2026-11-09 · **Deciders:** AI Lead, Security

## Context
Administrators must be able to change the active LLM (provider, models, credentials) from the
admin console at runtime, without a redeploy. Credentials (API keys) are sensitive and must
never be exposed back through the UI or API after entry.

## Decision
Introduce a runtime **LLM config store** (`libs/llm/config_store.py`) that the model provider
build consults ahead of environment variables. Properties enforced by design:

1. **Create-only.** A config is never edited after creation — there is no `update`/`edit`/
   `set_secret` method. To change settings, create a new config and activate it.
2. **Write-only secret.** The API key is accepted on create and stored in a separate in-memory
   map. The public `LLMConfig` dataclass has **no secret field**, so a secret cannot be
   serialised into any API response. The raw secret is reachable only via `secret_for()`, called
   in-process by the provider build — never by a request handler. The admin API serialises
   configs through a hand-built `_public()` dict; the UI shows only a `has_secret` flag.
3. **Live activation.** Activating a config bumps a version and resets the model gateway, which
   rebuilds against the new provider on the next call.
4. **Cross-process propagation.** The store persists to a JSON file (`LLM_CONFIG_PATH`) on a
   shared volume so api/orchestrator/model-gateway/admin converge; each process reloads on file
   mtime change.

## Consequences
* The admin console can switch Gemini ↔ Anthropic ↔ OpenAI ↔ mock at runtime, with per-config
  model slugs and an optional `base_url` (OpenAI/Anthropic-compatible gateways).
* **POC limitation:** secrets live in a gitignored, server-only file. For production, back the
  secret store with a secrets manager (HashiCorp Vault / cloud KMS) and keep only a reference in
  the config; the `secret_for()` seam is where that integration plugs in. The file is never
  served and never returned by any endpoint.
* Admin endpoints are Administrator-gated at the edge; the agent PEP still guards tools downstream.
