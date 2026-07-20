# Copyright (c) 2026, Kartik Sharma and contributors
# For license information, please see license.txt

import frappe
from frappe import _
from frappe.model.document import Document


class AIAgentConfiguration(Document):
	# begin: auto-generated types
	# This code is auto-generated. Do not modify anything in this block.

	from typing import TYPE_CHECKING

	if TYPE_CHECKING:
		from frappe.types import DF

		from one_bpmn.one_bpmn.doctype.ai_agent_constant.ai_agent_constant import AIAgentConstant
		from one_bpmn.one_bpmn.doctype.ai_agent_sub_prompt.ai_agent_sub_prompt import AIAgentSubPrompt

		agent_framework: DF.Literal["", "Google ADK", "LangGraph", "Direct API", "Anthropic"]
		agent_id: DF.Data
		agent_name: DF.Data
		constants: DF.Table[AIAgentConstant]
		description: DF.SmallText | None
		enabled: DF.Check
		langsmith_project: DF.Data | None
		llm_provider_override: DF.Literal["Use Global", "gemini", "anthropic", "openai"]
		max_tokens: DF.Int
		model_override: DF.Data | None
		process_owner: DF.Link | None
		sub_prompts: DF.Table[AIAgentSubPrompt]
		system_prompt: DF.Code | None
		temperature: DF.Float
		required_variables: DF.SmallText | None
	# end: auto-generated types

	def validate(self):
		"""Validate that required runtime variables are present in the system prompt."""
		self.derive_provider_from_model()
		self.validate_required_variables()
		self.validate_unique_chat_mode_label()
		self.apply_background_lifecycle()

	def derive_provider_from_model(self):
		"""WI-001655: the model is the pick, the provider is derived. When an
		AI Model is linked, ai_provider_credentials follows its credentials
		link — one choice, no model/provider mismatch possible. An agent with
		no model keeps whatever credentials it has (legacy records)."""
		if not self.ai_model:
			return
		creds = frappe.db.get_value("AI Model", self.ai_model, "ai_provider_credentials")
		if creds:
			self.ai_provider_credentials = creds

	def apply_background_lifecycle(self):
		"""WI-001652: Background agents skip the chat creation process, so they
		go Live directly on save when their essentials check out — enabled,
		with an enabled provider link. A failing check parks them in Needs
		Attention, like any agent. Retired is a deliberate manual state and is
		never overridden. Applies on every save path (form, endpoint, patch)."""
		if self.agent_type != "Background" or self.lifecycle_status == "Retired":
			return
		reason = ""
		if not self.enabled:
			reason = _("The agent is disabled.")
		elif not self.ai_provider_credentials:
			reason = (
				_("The linked AI Model '{0}' has no AI Provider Credentials link.").format(self.ai_model)
				if self.ai_model
				else _("No AI Model is linked — pick one from the catalog.")
			)
		elif not frappe.db.get_value("AI Provider Credentials", self.ai_provider_credentials, "enabled"):
			reason = _("The linked AI Provider Credentials record '{0}' is disabled.").format(
				self.ai_provider_credentials
			)
		self.lifecycle_status = "Needs Attention" if reason else "Live"
		self.needs_attention_reason = reason

	def validate_unique_chat_mode_label(self):
		"""Two enabled chat agents must never claim the same conversation mode —
		the mode label is what the map's start condition and the chat registry
		key on (WI-001538)."""
		if self.agent_type != "Chat" or not self.chat_mode_label:
			return
		clash = frappe.db.get_value(
			"AI Agent Configuration",
			{
				"chat_mode_label": self.chat_mode_label,
				"agent_type": "Chat",
				"enabled": 1,
				"name": ("!=", self.name),
			},
			"name",
		)
		if clash and self.enabled:
			frappe.throw(
				frappe._("Chat mode label {0} is already used by enabled agent {1}.").format(
					frappe.bold(self.chat_mode_label), frappe.bold(clash)
				)
			)

	def validate_required_variables(self):
		"""Check that all required variables appear as {var} placeholders in the correct prompt.

		Each variable object may contain a ``source`` field:
		- ``"system_prompt"`` (default) – variable must appear in ``self.system_prompt``
		- any other string – treated as a ``sub_agent_id``; variable must appear in
		  the matching sub-prompt's ``prompt_text``
		"""
		if not self.required_variables:
			return

		import json

		try:
			variables = json.loads(self.required_variables)
		except (json.JSONDecodeError, TypeError):
			return

		if not isinstance(variables, list):
			return

		# Build a lookup of sub-prompt texts keyed by sub_agent_id
		sub_prompt_texts = {
			sp.sub_agent_id: sp.prompt_text or ""
			for sp in (self.sub_prompts or [])
		}

		missing = []
		for v in variables:
			if not isinstance(v, dict) or not v.get("name"):
				continue
			source = v.get("source", "system_prompt")
			placeholder = f"{{{v['name']}}}"

			if source == "system_prompt":
				text = self.system_prompt or ""
			else:
				text = sub_prompt_texts.get(source, "")

			if placeholder not in text:
				label = "system prompt" if source == "system_prompt" else f"sub-prompt \"{source}\""
				missing.append(f"<code>{placeholder}</code> in {label}")

		if missing:
			formatted = ", ".join(missing)
			frappe.throw(
				msg=frappe._("The following required variables are missing: {0}. "
					"The agent may not function correctly without them.").format(formatted),
				title=frappe._("Missing Required Variables"),
			)

	def on_update(self):
		"""Clear cached config when this record is saved."""
		frappe.cache.delete_value(f"agent_config:{self.agent_id}")
		# WI-001652: leave a timeline trail when a save parks the agent.
		# (The creation process's park path writes its own comment — this
		# covers the controller-driven Background auto-lifecycle.)
		prev = getattr(self, "_doc_before_save", None)
		if (
			self.lifecycle_status == "Needs Attention"
			and self.needs_attention_reason
			# fresh insert straight into Needs Attention (prev is None), or a
			# genuine transition — but not every re-save while already parked
			and (prev is None or prev.get("lifecycle_status") != "Needs Attention")
		):
			try:
				self.add_comment("Comment", _("Needs Attention: {0}").format(self.needs_attention_reason))
			except Exception:
				pass


def get_agent_config(agent_id: str) -> dict | None:
	"""
	Load agent configuration from AI Agent Configuration DocType.

	Returns a dict with: system_prompt, temperature, max_tokens,
	ai_provider_credentials, langsmith_project, sub_prompts, and
	constants. There is no per-agent override mechanism (WI-001615):
	provider, key and model come from the linked AI Provider
	Credentials record.

	Returns None if the record is not found or disabled,
	allowing callers to fall back to hardcoded defaults.

	Cache is indefinite — only invalidated when the record is saved
	(via on_update hook in the controller above).
	"""
	cache_key = f"agent_config:{agent_id}"
	cached = frappe.cache.get_value(cache_key)
	if cached:
		return cached

	config = frappe.db.get_value(
		"AI Agent Configuration",
		{"agent_id": agent_id, "enabled": 1},
		[
			"name", "agent_id", "system_prompt", "temperature", "max_tokens",
			"ai_model", "ai_provider_credentials", "langsmith_project",
			"agent_framework", "process_model", "chat_mode_label",
			"lifecycle_status", "agent_type",
		],
		as_dict=True,
	)


	if not config:
		return None

	# Load sub-prompts keyed by sub_agent_id
	sub_prompts = {}
	for sp in frappe.get_all(
		"AI Agent Sub Prompt",
		filters={"parent": config.name},
		fields=["sub_agent_id", "prompt_text", "temperature"],
	):
		sub_prompts[sp.sub_agent_id] = {
			"prompt": sp.prompt_text,
			"temperature": sp.temperature,
		}

	# Load constants keyed by constant_name, cast to proper types
	constants = {}
	for c in frappe.get_all(
		"AI Agent Constant",
		filters={"parent": config.name},
		fields=["constant_name", "constant_value", "constant_type"],
	):
		constants[c.constant_name] = _cast_constant(c.constant_value, c.constant_type)

	result = {
		"agent_id": config.agent_id,
		"system_prompt": config.system_prompt,
		"temperature": config.temperature,
		"max_tokens": config.max_tokens,
		"ai_provider_credentials": config.ai_provider_credentials,
		"langsmith_project": config.langsmith_project,
		"agent_framework": config.agent_framework,
		"process_model": config.process_model,
		"chat_mode_label": config.chat_mode_label,
		"lifecycle_status": config.lifecycle_status,
		"agent_type": config.agent_type,
		"sub_prompts": sub_prompts,
		"constants": constants,
	}

	frappe.cache.set_value(cache_key, result)
	return result


def _cast_constant(value: str, const_type: str):
	"""Cast a string constant value to the appropriate Python type."""
	if const_type == "Integer":
		return int(value)
	elif const_type == "Float":
		return float(value)
	elif const_type == "Boolean":
		return value.lower() in ("1", "true", "yes")
	return value
