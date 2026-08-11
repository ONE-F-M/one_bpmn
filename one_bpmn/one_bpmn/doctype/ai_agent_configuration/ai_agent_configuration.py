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

		agent_creation_process: DF.Link | None
		agent_framework: DF.Literal["", "Google ADK", "LangGraph", "Direct API", "Anthropic"]
		agent_id: DF.Data
		agent_name: DF.Data
		can_create_agents: DF.Check
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
		self.validate_chat_label_against_map()
		self.validate_agent_creation_grant()

	def validate_chat_label_against_map(self):
		"""WI-001997: a chat mode label promises the agent appears in chat,
		which only works when its linked map has the chat start pattern (a
		start event conditioned on Chat Conversation insert). A label on an
		agent mapped to any other process is a false promise — reject it and
		say why. Agents with no linked map keep their label: mapless Chat
		agents chat through the direct path."""
		if self.agent_type != "Chat" or not self.chat_mode_label or not self.process_model:
			return

		from one_bpmn.agents.agent_provisioning import is_chat_startable_map

		if is_chat_startable_map(self.process_model) is False:
			frappe.throw(
				_(
					"'{0}' is not a chat-startable map — it has no start event conditioned "
					"on Chat Conversation insert, so this agent can never appear in chat. "
					"Clear the Chat Mode Label (the agent still runs inside its process), "
					"or link a map that starts on Chat Conversation."
				).format(self.process_model),
				title=_("Map is not chat-startable"),
			)

		# A chat-startable map is not enough: its start CONDITION must match
		# THIS agent's label, or the conversation stamps one agent_mode while
		# the map waits for another and no instance ever spawns — the chat
		# answers "process not running" forever. Cloned maps keep the
		# original's condition, which is exactly how this bit live
		# (2026-08-10: Todo King 2 linked a ProsAlly clone). Only the simple
		# agent_mode == "<label>" shape is enforced; a condition too complex
		# to reason about is left to the author.
		self._validate_map_condition_matches_label()

	def _validate_map_condition_matches_label(self):
		import re

		from one_bpmn.one_bpmn.trigger import (
			_get_conditional_start_condition,
			_get_trigger_field_condition,
		)

		xml = frappe.db.get_value("BPMN Process Model", self.process_model, "bpmn_xml") or ""
		condition = _get_conditional_start_condition(xml) or ""
		match = re.fullmatch(
			r"""\s*agent_mode\s*==\s*["']([^"']+)["']\s*""", condition
		)
		expected = match.group(1) if match else None

		# The legacy field filter (triggerFieldName/triggerFieldValue) is a
		# SECOND copy of the same gate, and the sneakier one: it is invisible
		# in the condition editor, survives cloning, and vetoes the spawn
		# silently AFTER the visible condition passes (diagnosed live
		# 2026-08-10 — a fixed condition still spawned nothing).
		field_cond = _get_trigger_field_condition(xml)
		if not expected and field_cond and field_cond[0] == "agent_mode":
			expected = field_cond[1]

		if expected and expected != self.chat_mode_label:
			frappe.throw(
				_(
					"'{0}' only starts conversations whose agent mode is '{1}' "
					"(its start condition or trigger field filter), but this "
					"agent's Chat Mode Label is '{2}' — its chats would never "
					"start the process. Update the map's start condition AND "
					"its trigger field filter to '{2}' (then save the map), or "
					"link a map made for this agent."
				).format(self.process_model, expected, self.chat_mode_label),
				title=_("Map starts a different agent's chats"),
			)

		# Both gates present but DISAGREEING is broken for every label — the
		# spawn can never pass the two gates at once.
		if (
			match
			and field_cond
			and field_cond[0] == "agent_mode"
			and field_cond[1] != match.group(1)
		):
			frappe.throw(
				_(
					"'{0}' carries two start gates that disagree: its condition "
					"expects agent_mode '{1}' but its trigger field filter "
					"expects '{2}'. No conversation can pass both — align them "
					"on the map and save it."
				).format(self.process_model, match.group(1), field_cond[1]),
				title=_("Map start gates disagree"),
			)

	def validate_agent_creation_grant(self):
		"""At most one configuration may hold the agent-creation grant, and it
		must link the process that carries a new agent Draft -> Live.

		The grant replaces the hardcoded "AI Agent Creation Process" name that
		agent_config_resolver used to assume: the process is whatever THIS
		field points at. Keeping it unique means the lookup can never be
		ambiguous — there is one answer or none.
		"""
		if not self.can_create_agents:
			return

		# mandatory_depends_on covers the form; this covers every other write
		# path (endpoint, patch, bulk edit), where mandatory_depends_on is not
		# evaluated.
		if not self.agent_creation_process:
			frappe.throw(
				_("Link an Agent Creation Process before granting this agent the right to create agents."),
				title=_("Agent Creation Process required"),
			)

		clash = frappe.db.get_value(
			"AI Agent Configuration",
			{"can_create_agents": 1, "name": ("!=", self.name)},
			"name",
		)
		if clash:
			frappe.throw(
				_(
					"'{0}' already holds the agent-creation grant. Only one AI Agent "
					"Configuration may create agents — clear the checkbox on '{0}' first."
				).format(clash),
				title=_("Agent-creation grant already held"),
			)

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
		self.revalidate_credentials_on_save()

	def revalidate_credentials_on_save(self):
		"""Re-prove the agent on EVERY save — assume nothing (user ruling,
		2026-07-21): credentials that validated at creation may since have
		been rotated, disabled, or pointed at a dead model, and a Live badge
		must mean the agent works NOW.

		Runs the full validation including the live provider test call:
		  * Live agent that fails    → parked Needs Attention, with the reason
		  * Needs Attention that passes → promoted back to Live (self-healing)
		  * Draft is the creation process's to advance, Retired is a manual
		    state — neither is touched.

		Skipped during migrate/patch/install/import (seed patches save many
		configs on sites whose credentials arrive later — parking them all
		mid-migration would be noise) and in tests unless a test opts in via
		frappe.flags.test_agent_revalidation.
		"""
		if self.lifecycle_status not in ("Live", "Needs Attention"):
			return
		if (
			frappe.flags.in_migrate
			or frappe.flags.in_patch
			or frappe.flags.in_install
			or frappe.flags.in_import
			or (frappe.flags.in_test and not frappe.flags.get("test_agent_revalidation"))
		):
			return
		if frappe.flags.get("_agent_revalidation_running"):
			return  # a stamp/reprovision triggered from below must not recurse

		frappe.flags._agent_revalidation_running = True
		try:
			from one_bpmn.agents.agent_provisioning import validate_agent_config

			result = validate_agent_config(
				self.name,
				test_provider=True,
				# WI-001650 provider-grant Background agents keep an empty
				# prompt on purpose — their credentials still get live-tested.
				require_prompt=(self.agent_type != "Background"),
			)
		except Exception:
			# The revalidation must never make a record unsaveable; a broken
			# validator is its own bug and lands in the Error Log.
			frappe.log_error(
				title=f"Agent revalidation failed to run: {self.name}",
				message=frappe.get_traceback(),
			)
			return
		finally:
			frappe.flags._agent_revalidation_running = False

		if result["ok"] and self.lifecycle_status == "Needs Attention":
			# Going Live is the MAP's decision, not this controller's.
			# Credentials working again does not mean the agent has been tested
			# against injection, jailbreak, exfiltration and tool coercion — the
			# Agent Creation Process runs that gate, and promoting from here would
			# make disable/re-enable a way around it.
			#
			# An agent the map parked already has an instance waiting on the
			# Config Edited message, which this save fires; one parked from here
			# (credentials broke while Live) has no instance, so it needs an
			# explicit start or it could never return to Live at all. Starting one
			# is a no-op when the map is already waiting.
			from one_bpmn.agents.agent_config_resolver import _start_reprovision

			_start_reprovision(self.name)
		elif not result["ok"] and self.lifecycle_status == "Live":
			self._stamp_lifecycle("Needs Attention", "; ".join(result["errors"]))

	def _stamp_lifecycle(self, status: str, reason: str):
		"""Post-save lifecycle stamp: the doc row is already written, so this
		goes straight to the DB (no re-save, no hook recursion) and keeps the
		in-memory doc in sync for whoever holds the reference."""
		frappe.db.set_value(
			self.doctype,
			self.name,
			{"lifecycle_status": status, "needs_attention_reason": reason},
			update_modified=False,
		)
		self.lifecycle_status = status
		self.needs_attention_reason = reason
		if status == "Needs Attention":
			try:
				self.add_comment("Comment", _("Needs Attention: {0}").format(reason))
			except Exception:
				pass


def get_agent_config(agent_id: str) -> dict | None:
	"""
	Load agent configuration from AI Agent Configuration DocType.

	Returns a dict with: system_prompt, temperature, max_tokens,
	ai_provider_credentials, langsmith_project, sub_prompts,
	constants, and — for the frozen static context layer (WI-001639) —
	examples and guardrails. There is no per-agent override mechanism (WI-001615):
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
			"lifecycle_status", "agent_type", "pii_screening",
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

	# WI-001639: examples + guard rails are the non-Instructions half of the
	# agent's FROZEN static context. Ordered by idx so the assembled prompt is
	# byte-stable across calls; disabled rows are carried through and filtered
	# by the assembler, keeping the "what is configured" and "what is sent"
	# decisions in one place.
	examples = frappe.get_all(
		"AI Agent Example",
		filters={"parent": config.name, "parenttype": "AI Agent Configuration"},
		fields=["input", "expected_output", "note", "enabled"],
		order_by="idx asc",
	)
	guardrails = frappe.get_all(
		"AI Agent Guard Rail",
		filters={"parent": config.name, "parenttype": "AI Agent Configuration"},
		fields=["guardrail", "category", "enabled"],
		order_by="idx asc",
	)

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
		"examples": examples,
		"guardrails": guardrails,
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
