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


# WI-001615: adapter key per AI Provider.provider_type.
_TYPE_TO_ADAPTER = {
    "Google": "gemini",
    "Anthropic": "anthropic",
    "OpenAI": "openai",
}

# WI-001614: canonical credential store. Maps the factory's lowercase provider
# keys to AI Provider.provider_type values.
_PROVIDER_TYPE_MAP = {
    "gemini": "Google",
    "anthropic": "Anthropic",
    "claude": "Anthropic",
    "openai": "OpenAI",
}


def _get_provider_credentials(provider: str) -> tuple[str, str]:
    """
    Return (api_key, model) for *provider* from AI Provider — the single
    credential store (WI-001614). The model is any enabled catalog model on the
    chosen provider, NOT a provider-level default: WI-001655 removed
    default_model. Prefers the canonical record name, else the first enabled
    provider of the matching provider_type that holds a key. Returns ("", "")
    when none qualifies so callers can fall back to the legacy AI Chat Settings
    fields.
    """
    ptype = _PROVIDER_TYPE_MAP.get(provider)
    if not ptype:
        return "", ""
    try:
        from frappe.utils.password import get_decrypted_password

        names = frappe.get_all(
            "AI Provider",
            filters={"provider_type": ptype, "enabled": 1},
            fields=["name"],
        )
        canonical = {"gemini": "Gemini", "anthropic": "Anthropic", "claude": "Anthropic", "openai": "OpenAI"}.get(provider)
        names.sort(key=lambda r: (r.name != canonical))
        for rec in names:
            key = get_decrypted_password("AI Provider", rec.name, "api_key", raise_exception=False)
            if key:
                # WI-001655: providers carry no default model — the fallback is
                # any ENABLED catalog model on this provider. Enabled matters
                # now that the catalog also holds disabled rows kept only for
                # their rate card.
                model = frappe.db.get_value(
                    "AI Model", {"provider": rec.name, "enable_model": 1}, "name"
                ) or ""
                return key, model
    except Exception:
        frappe.log_error(title="LLM Factory - AI Provider", message=frappe.get_traceback())
    return "", ""


def _get_global_api_key(settings, provider: str) -> str:
    """Return the global API key for *provider* from AI Chat Settings (legacy fallback)."""
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


# WI-001615: _find_agent_row removed — the Processa Agent LLM Config
# override table is retired; configs link an AI Provider record.


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

    cfg = agent_config or {}
    agent_id = cfg.get("agent_id", "")

    # ── WI-001615: the config's linked provider wins outright ──────────────
    # WI-001655: the MODEL is the agent's own catalog pick (cfg["ai_model"],
    # whose record name is the model id); the provider supplies the connection
    # (key, adapter routing via provider_type).
    linked = cfg.get("ai_provider")
    if linked:
        try:
            rec = frappe.get_doc("AI Provider", linked)
            adapter_key = _TYPE_TO_ADAPTER.get(rec.provider_type)
            if not adapter_key:
                raise ValueError(
                    f"AI Provider '{linked}' has provider_type "
                    f"'{rec.provider_type}', which has no chat adapter."
                )
            api_key = rec.get_password("api_key") if rec.enabled else ""
            if not rec.enabled:
                frappe.log_error(
                    title="LLM Factory - Disabled Provider",
                    message=f"AI Provider '{linked}' is disabled.",
                )
            model = cfg.get("ai_model") or _PROVIDER_DEFAULTS.get(adapter_key, "")
            return get_llm_adapter(provider=adapter_key, model=model, api_key=api_key or "")
        except frappe.DoesNotExistError:
            frappe.log_error(
                title="LLM Factory - Missing Provider",
                message=f"AI Provider '{linked}' not found; falling back to global resolution.",
            )

    # ── Global resolution (configs without a link, transitional) ────────────
    if settings:
        provider = (
            getattr(settings, "processa_llm_provider", None)
            or settings.llm_provider
            or "gemini"
        ).lower()
    else:
        provider = "gemini"

    # WI-001614: AI Provider is the credential store. Resolve it
    # once; the legacy AI Chat Settings fields remain only as a fallback until
    # every agent's migration story lands.
    cred_key, cred_model = _get_provider_credentials(provider)

    # ── Model ─────────────────────────────────────────────────────────────────
    if cred_model:
        model = cred_model
    elif settings:
        model = _get_global_model(settings, provider)
    else:
        model = _PROVIDER_DEFAULTS.get(provider, "")

    # ── API key ───────────────────────────────────────────────────────────────
    api_key = cred_key

    if not api_key and settings:
        api_key = _get_global_api_key(settings, provider)

    if not api_key:
        frappe.log_error(
            title="LLM Factory - Missing API Key",
            message=(
                f"No API key found for agent '{agent_id}' provider '{provider}'. "
                f"Link an AI Provider record on the agent's configuration."
            ),
        )

    return get_llm_adapter(provider=provider, model=model, api_key=api_key)
