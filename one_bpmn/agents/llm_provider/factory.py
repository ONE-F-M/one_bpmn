"""
LLM adapter factory.

Provider resolution order (highest priority first):
  1. agent_config["llm_provider_override"]            (AI Agent Configuration — developer override)
  2. AI Chat Settings → processa_agent_configs row    (per-agent row keyed by agent_id)
  3. AI Chat Settings → processa_llm_provider         (global default for all BPMN agents)
  4. AI Chat Settings → llm_provider                  (chatbot field, last resort)
  5. "gemini"                                         (hard fallback)

Model resolution order:
  1. agent_config["model_override"]                   (AI Agent Configuration)
  2. Per-agent row → model                            (if set)
  3. Provider-specific model field in AI Chat Settings
  4. Hard-coded default per provider

API key resolution order:
  1. Per-agent row → api_key                          (if set)
  2. Global key for the resolved provider in AI Chat Settings

Adding a new provider requires only:
  - A new adapter class in its own module
  - One new branch in get_llm_adapter()
  - New credential fields in AI Chat Settings

Adding a new agent requires only:
  - A new row in AI Chat Settings → Per-Agent LLM Settings table
"""

import frappe

from .base import BaseLLMAdapter

_PROVIDER_DEFAULTS = {
    "gemini":    "gemini-2.0-flash",
    "anthropic": "claude-sonnet-4-5",
    "openai":    "gpt-4o",
}


def get_llm_adapter(provider: str, model: str, api_key: str) -> BaseLLMAdapter:
    """Instantiate the correct adapter for *provider*."""
    p = provider.lower()
    if p == "gemini":
        from .gemini import GeminiAdapter
        return GeminiAdapter(api_key=api_key, model=model)
    if p in ("anthropic", "claude"):
        from .anthropic_adapter import AnthropicAdapter
        return AnthropicAdapter(api_key=api_key, model=model)
    if p == "openai":
        from .openai_adapter import OpenAIAdapter
        return OpenAIAdapter(api_key=api_key, model=model)
    raise ValueError(f"Unknown LLM provider: {provider!r}. Supported: gemini, anthropic, openai")


def _get_global_api_key(settings, provider: str) -> str:
    """Return the global API key for *provider* from AI Chat Settings."""
    try:
        if provider == "gemini":
            return (
                settings.get_password("google_vertex_ai_api_key") or
                settings.get_password("gemini_api_key") or ""
            )
        if provider in ("anthropic", "claude"):
            return settings.get_password("anthropic_api_key") or ""
        if provider == "openai":
            return settings.get_password("openai_api_key") or ""
    except Exception:
        frappe.log_error(title="LLM Factory - API Key", message=frappe.get_traceback())
    return ""


def _get_global_model(settings, provider: str) -> str:
    """Return the global model for *provider* from AI Chat Settings."""
    if provider == "gemini":
        return getattr(settings, "gemini_model", None) or _PROVIDER_DEFAULTS["gemini"]
    if provider in ("anthropic", "claude"):
        return getattr(settings, "anthropic_model", None) or _PROVIDER_DEFAULTS["anthropic"]
    if provider == "openai":
        return getattr(settings, "openai_model", None) or _PROVIDER_DEFAULTS["openai"]
    return _PROVIDER_DEFAULTS.get(provider, "")


def _find_agent_row(settings, agent_id: str):
    """Return the matching child-table row for *agent_id*, or None."""
    if not agent_id or not settings:
        return None
    for row in (getattr(settings, "processa_agent_configs", None) or []):
        if (row.agent_id or "").strip() == agent_id.strip():
            return row
    return None


def get_llm_adapter_from_settings(agent_config: dict | None = None) -> BaseLLMAdapter:
    """
    Resolve provider/model/key from AI Chat Settings and the optional per-agent
    config dict (as returned by get_agent_config()), then return a ready adapter.
    """
    try:
        settings = frappe.get_doc("AI Chat Settings")
    except Exception:
        frappe.log_error(title="LLM Factory - AI Chat Settings", message=frappe.get_traceback())
        settings = None

    cfg        = agent_config or {}
    agent_id   = cfg.get("agent_id", "")
    agent_row  = _find_agent_row(settings, agent_id)

    # ── Provider ──────────────────────────────────────────────────────────────
    dev_override = cfg.get("llm_provider_override", "Use Global")
    if dev_override and dev_override != "Use Global":
        provider = dev_override.lower()
    elif agent_row:
        provider = (agent_row.llm_provider or "").lower()
    elif settings:
        provider = (
            getattr(settings, "processa_llm_provider", None)
            or settings.llm_provider
            or "gemini"
        ).lower()
    else:
        provider = "gemini"

    # ── Model ─────────────────────────────────────────────────────────────────
    model_override = cfg.get("model_override")
    if model_override:
        model = model_override
    elif agent_row and agent_row.model:
        model = agent_row.model
    elif settings:
        model = _get_global_model(settings, provider)
    else:
        model = _PROVIDER_DEFAULTS.get(provider, "")

    # ── API key ───────────────────────────────────────────────────────────────
    api_key = ""
    if agent_row:
        try:
            api_key = agent_row.get_password("api_key") or ""
        except Exception:
            pass

    if not api_key and settings:
        api_key = _get_global_api_key(settings, provider)

    if not api_key:
        frappe.log_error(
            title="LLM Factory - Missing API Key",
            message=(
                f"No API key found for agent '{agent_id}' provider '{provider}'. "
                f"Set a key in AI Chat Settings → Per-Agent LLM Settings or the global provider section."
            ),
        )

    return get_llm_adapter(provider=provider, model=model, api_key=api_key)
