"""
LLM adapter factory.

Provider resolution order (highest priority first):
  1. agent_config["ai_provider"]                      (AI Agent Configuration — linked AI Provider record)
  2. Processa Settings → default_llm_provider         (site-wide fallback for a config with no linked provider)
  3. "gemini"                                         (hard fallback)

Model resolution order:
  1. agent_config["ai_model"]                         (AI Agent Configuration's own catalog pick)
  2. Any enabled AI Model on the resolved provider    (WI-001655 — providers carry no default model)
  3. Hard-coded default per provider

API key resolution order:
  1. The resolved AI Model record's own api_key       (the connection lives on the model)

AI Provider holds a name and nothing else, so the NAME is the dialect: a record
called "Anthropic" is spoken to as Anthropic. That is the only thing left to
route on, so a provider whose name is not a known dialect has no adapter, and
naming one "Test Provider" makes its models unreachable.

Adding a new provider requires only:
  - A new adapter class in its own module
  - One new branch in get_llm_adapter()
  - An AI Provider record named for the dialect, and models carrying the key

Adding a new agent requires only:
  - An AI Agent Configuration record linking an AI Provider and AI Model
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


# The AI Provider record's NAME is its dialect. Matched case-insensitively so
# "anthropic" and "Anthropic" are the same provider, and with the aliases people
# actually type — "Claude" for Anthropic, "Gemini" for Google.
_NAME_TO_ADAPTER = {
    "google": "gemini",
    "gemini": "gemini",
    "anthropic": "anthropic",
    "claude": "anthropic",
    "openai": "openai",
}

# The record name each adapter key prefers, for the reverse lookup.
_ADAPTER_TO_NAME = {
    "gemini": "Google",
    "anthropic": "Anthropic",
    "openai": "OpenAI",
}


def adapter_for_provider(provider_name: str | None) -> str | None:
    """Which adapter speaks to this AI Provider, from its name alone.

    None when the name is not a dialect we have a client for — the caller must
    treat that as an error rather than guessing, because guessing wrong means
    building an Anthropic request for an OpenAI endpoint.
    """
    return _NAME_TO_ADAPTER.get((provider_name or "").strip().lower())


def model_api_key(model_name: str | None) -> str:
    """The API key stored on a catalog model. Empty when there is none."""
    if not model_name:
        return ""
    try:
        from frappe.utils.password import get_decrypted_password

        return get_decrypted_password(
            "AI Model", model_name, "api_key", raise_exception=False
        ) or ""
    except Exception:
        return ""


def _get_provider_credentials(provider: str) -> tuple[str, str]:
    """
    Return (api_key, model) for *provider* from AI Provider — the single
    catalog. The model is any enabled catalog model on the chosen provider, NOT
    a provider-level default: providers carry no default model. Prefers the
    canonical record name, else any provider whose name speaks the same dialect,
    and within one provider the first enabled model that holds a key. Returns
    ("", "") when none qualifies, so callers fall back to the hard-coded
    per-provider default model and log a missing-API-key error.
    """
    adapter_key = _NAME_TO_ADAPTER.get((provider or "").strip().lower())
    if not adapter_key:
        return "", ""
    try:
        # Every provider whose name speaks this dialect, canonical spelling
        # first. A site may well have only "Anthropic"; it may also have
        # "anthropic" or "Claude", and all three route the same way.
        canonical = _ADAPTER_TO_NAME.get(adapter_key)
        names = [
            r.name
            for r in frappe.get_all("AI Provider", fields=["name"])
            if _NAME_TO_ADAPTER.get(r.name.strip().lower()) == adapter_key
        ]
        names.sort(key=lambda n: (n != canonical))

        for name in names:
            # The key lives on the MODEL now, so the first enabled model on this
            # provider that actually carries one decides both answers at once.
            for model in frappe.get_all(
                "AI Model",
                filters={"provider": name, "enable_model": 1},
                pluck="name",
                order_by="modified desc",
            ):
                key = model_api_key(model)
                if key:
                    return key, model
    except Exception:
        frappe.log_error(title="LLM Factory - AI Provider", message=frappe.get_traceback())
    return "", ""


# WI-001615: _find_agent_row removed — the Processa Agent LLM Config
# override table is retired; configs link an AI Provider record.


def get_llm_adapter_from_settings(agent_config: dict | None = None) -> BaseLLMAdapter:
    """
    Resolve provider/model/key from the optional per-agent config dict (as
    returned by get_agent_config()), falling back to Processa Settings'
    site-wide default provider when the config has no linked AI Provider.
    """
    cfg = agent_config or {}
    agent_id = cfg.get("agent_id", "")

    # ── The config's linked provider wins outright ─────────────────────────
    # The MODEL is the agent's own catalog pick (cfg["ai_model"], whose record
    # name is the model id) and now carries the connection too; the provider
    # contributes only its name, which is what routes the call.
    linked = cfg.get("ai_provider")
    if linked:
        try:
            rec = frappe.get_doc("AI Provider", linked)
            adapter_key = adapter_for_provider(rec.name)
            if not adapter_key:
                raise ValueError(
                    f"AI Provider '{linked}' is not the name of a dialect with a "
                    f"chat adapter. Name the record for what it speaks — "
                    f"Anthropic, OpenAI or Google."
                )
            model = cfg.get("ai_model") or _PROVIDER_DEFAULTS.get(adapter_key, "")
            # A disabled model is off for the same reason a disabled provider
            # used to be, and it is the only switch left.
            if model and not frappe.db.get_value("AI Model", model, "enable_model"):
                frappe.log_error(
                    title="LLM Factory - Disabled Model",
                    message=f"AI Model '{model}' is disabled.",
                )
                api_key = ""
            else:
                api_key = model_api_key(model)
            return get_llm_adapter(provider=adapter_key, model=model, api_key=api_key or "")
        except frappe.DoesNotExistError:
            frappe.log_error(
                title="LLM Factory - Missing Provider",
                message=f"AI Provider '{linked}' not found; falling back to global resolution.",
            )

    # ── Global resolution (configs without a link, transitional) ────────────
    provider = (
        frappe.db.get_single_value("Processa Settings", "default_llm_provider") or "gemini"
    ).lower()

    # WI-001614: AI Provider is the credential store.
    cred_key, cred_model = _get_provider_credentials(provider)

    # ── Model ─────────────────────────────────────────────────────────────────
    model = cred_model or _PROVIDER_DEFAULTS.get(provider, "")

    # ── API key ───────────────────────────────────────────────────────────────
    api_key = cred_key

    if not api_key:
        frappe.log_error(
            title="LLM Factory - Missing API Key",
            message=(
                f"No API key found for agent '{agent_id}' provider '{provider}'. "
                f"Link an AI Provider record on the agent's configuration."
            ),
        )

    return get_llm_adapter(provider=provider, model=model, api_key=api_key)
