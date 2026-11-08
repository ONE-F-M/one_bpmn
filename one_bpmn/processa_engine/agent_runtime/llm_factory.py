"""LLM adapter factory."""

import frappe

from one_bpmn.processa_engine.agent_runtime.llm_base import BaseLLMAdapter

_PROVIDER_DEFAULTS = {
	"gemini": "gemini-2.0-flash",
	"anthropic": "claude-sonnet-4-5",
	"openai": "gpt-4o",
}


def get_llm_adapter(
	provider: str,
	model: str,
	api_key: str,
	*,
	timeout_seconds: float | None = None,
	max_retries: int | None = None,
) -> BaseLLMAdapter:
	"""Instantiate the correct adapter for *provider*."""
	from one_bpmn.processa_engine.agent_runtime.executor import DEFAULT_TIMEOUT_SECONDS

	timeout_seconds = timeout_seconds or DEFAULT_TIMEOUT_SECONDS
	p = provider.lower()
	if p == "gemini":
		from one_bpmn.processa_engine.agent_runtime.llm_gemini import GeminiAdapter

		return GeminiAdapter(
			api_key=api_key, model=model, timeout_seconds=timeout_seconds, max_retries=max_retries
		)
	if p in ("anthropic", "claude"):
		from one_bpmn.processa_engine.agent_runtime.llm_anthropic import AnthropicAdapter

		return AnthropicAdapter(
			api_key=api_key, model=model, timeout_seconds=timeout_seconds, max_retries=max_retries
		)
	if p == "openai":
		from one_bpmn.processa_engine.agent_runtime.llm_openai import OpenAIAdapter

		return OpenAIAdapter(
			api_key=api_key, model=model, timeout_seconds=timeout_seconds, max_retries=max_retries
		)
	raise ValueError(f"Unknown LLM provider: {provider!r}. Supported: gemini, anthropic, openai")


_NAME_TO_ADAPTER = {
	"google": "gemini",
	"gemini": "gemini",
	"anthropic": "anthropic",
	"claude": "anthropic",
	"openai": "openai",
}

_ADAPTER_TO_NAME = {
	"gemini": "Google",
	"anthropic": "Anthropic",
	"openai": "OpenAI",
}


def adapter_for_provider(provider_name: str | None) -> str | None:
	"""Which adapter speaks to this AI Provider, from its name alone."""
	return _NAME_TO_ADAPTER.get((provider_name or "").strip().lower())


def model_api_key(model_name: str | None) -> str:
	"""The API key stored on a catalog model. Empty when there is none."""
	if not model_name:
		return ""
	try:
		from frappe.utils.password import get_decrypted_password

		return get_decrypted_password("AI Model", model_name, "api_key", raise_exception=False) or ""
	except Exception:
		return ""


def _get_provider_credentials(provider: str) -> tuple[str, str]:
	"""Return (api_key, model) for *provider* from AI Provider - the single catalog. The model is any enabled
	catalog model on the chosen provider, NOT a provider-level default: providers carry no default model."""
	adapter_key = _NAME_TO_ADAPTER.get((provider or "").strip().lower())
	if not adapter_key:
		return "", ""
	try:
		canonical = _ADAPTER_TO_NAME.get(adapter_key)
		names = [
			r.name
			for r in frappe.get_all("AI Provider", fields=["name"])
			if _NAME_TO_ADAPTER.get(r.name.strip().lower()) == adapter_key
		]
		names.sort(key=lambda n: n != canonical)

		for name in names:
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


def get_llm_adapter_from_settings(agent_config: dict | None = None) -> BaseLLMAdapter:
	"""Resolve provider/model/key from the optional per-agent config dict (as returned by get_agent_config()),
	falling back to Processa Settings' site-wide default provider when the config has no linked AI
	Provider."""
	cfg = agent_config or {}
	agent_id = cfg.get("agent_id", "")

	linked = cfg.get("ai_provider")
	if linked:
		try:
			rec = frappe.get_doc("AI Provider", linked)
			adapter_key = adapter_for_provider(rec.name)
			if not adapter_key:
				raise ValueError(
					f"AI Provider '{linked}' is not the name of a dialect with a "
					f"chat adapter. Name the record for what it speaks - "
					f"Anthropic, OpenAI or Google."
				)
			model = cfg.get("ai_model") or _PROVIDER_DEFAULTS.get(adapter_key, "")
			if model and not frappe.db.get_value("AI Model", model, "enable_model"):
				frappe.log_error(
					title="LLM Factory - Disabled Model",
					message=f"AI Model '{model}' is disabled.",
				)
				api_key = ""
			else:
				api_key = model_api_key(model)
			api_model = frappe.db.get_value("AI Model", model, "model_api_name") or model
			return MeteredAdapter(
				get_llm_adapter(provider=adapter_key, model=api_model, api_key=api_key or "")
			)
		except frappe.DoesNotExistError:
			frappe.log_error(
				title="LLM Factory - Missing Provider",
				message=f"AI Provider '{linked}' not found; falling back to global resolution.",
			)

	provider = (frappe.db.get_single_value("Processa Settings", "default_llm_provider") or "gemini").lower()

	cred_key, cred_model = _get_provider_credentials(provider)

	model = cred_model or _PROVIDER_DEFAULTS.get(provider, "")

	api_key = cred_key

	if not api_key:
		frappe.log_error(
			title="LLM Factory - Missing API Key",
			message=(
				f"No API key found for agent '{agent_id}' provider '{provider}'. "
				f"Link an AI Provider record on the agent's configuration."
			),
		)

	api_model = frappe.db.get_value("AI Model", model, "model_api_name") or model
	return MeteredAdapter(get_llm_adapter(provider=provider, model=api_model, api_key=api_key))


class MeteredAdapter:
	"""An adapter that records what its complete() calls cost."""

	def __init__(self, inner):
		self._inner = inner

	def __getattr__(self, name):
		return getattr(self._inner, name)

	async def complete(self, *args, **kwargs):
		import time

		from one_bpmn.agents.observability import record_sub_call

		started = time.perf_counter()
		result = await self._inner.complete(*args, **kwargs)
		latency_ms = int((time.perf_counter() - started) * 1000)
		try:
			record_sub_call(
				getattr(self._inner, "_model", "") or "",
				result,
				latency_ms=latency_ms,
			)
		except Exception:
			# Metering must never be the reason a tool fails.
			frappe.log_error(
				title="AI Observability: sub-call not recorded",
				message=frappe.get_traceback(),
			)
		return result
