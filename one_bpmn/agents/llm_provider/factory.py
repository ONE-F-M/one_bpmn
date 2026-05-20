"""
LLM adapter factory.

Provider resolution order (highest priority first):
  1. agent_config["llm_provider_override"]   (per-agent override in AI Agent Configuration)
  2. AI Chat Settings → llm_provider          (global default)
  3. "gemini"                                 (fallback)

Model resolution order:
  1. agent_config["model_override"]
  2. Provider-specific model field in AI Chat Settings
  3. Hard-coded sensible default per provider

Adding a new provider later requires only:
  - A new adapter class in its own module
  - One new branch in get_llm_adapter()
  - New credential fields in AI Chat Settings
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

    # ── Provider ──────────────────────────────────────────────────────────────
    override = (agent_config or {}).get("llm_provider_override", "Use Global")
    if override and override != "Use Global":
        provider = override.lower()
    elif settings:
        provider = (settings.llm_provider or "gemini").lower()
    else:
        provider = "gemini"

    # ── Model ─────────────────────────────────────────────────────────────────
    model_override = (agent_config or {}).get("model_override")
    if model_override:
        model = model_override
    elif provider == "gemini" and settings:
        model = settings.gemini_model or _PROVIDER_DEFAULTS["gemini"]
    elif provider in ("anthropic", "claude") and settings:
        model = getattr(settings, "anthropic_model", None) or _PROVIDER_DEFAULTS["anthropic"]
    elif provider == "openai" and settings:
        model = getattr(settings, "openai_model", None) or _PROVIDER_DEFAULTS["openai"]
    else:
        model = _PROVIDER_DEFAULTS.get(provider, "")

    # ── API key ───────────────────────────────────────────────────────────────
    api_key = ""
    if settings:
        try:
            if provider == "gemini":
                api_key = (
                    settings.get_password("google_vertex_ai_api_key") or
                    settings.get_password("gemini_api_key") or ""
                )
            elif provider in ("anthropic", "claude"):
                api_key = settings.get_password("anthropic_api_key") or ""
            elif provider == "openai":
                api_key = settings.get_password("openai_api_key") or ""
        except Exception:
            frappe.log_error(title="LLM Factory - API Key", message=frappe.get_traceback())

    if not api_key:
        frappe.log_error(
            title="LLM Factory - Missing API Key",
            message=f"No API key found for provider '{provider}'. Check AI Chat Settings.",
        )

    return get_llm_adapter(provider=provider, model=model, api_key=api_key)
