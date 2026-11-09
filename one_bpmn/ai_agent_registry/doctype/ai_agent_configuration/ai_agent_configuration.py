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
		from one_bpmn.ai_agent_registry.doctype.ai_agent_allowed_role.ai_agent_allowed_role import AIAgentAllowedRole
		from one_bpmn.ai_agent_registry.doctype.ai_agent_constant.ai_agent_constant import AIAgentConstant
		from one_bpmn.ai_agent_registry.doctype.ai_agent_enabled_skill.ai_agent_enabled_skill import AIAgentEnabledSkill
		from one_bpmn.ai_agent_registry.doctype.ai_agent_example.ai_agent_example import AIAgentExample
		from one_bpmn.ai_agent_registry.doctype.ai_agent_guard_rail.ai_agent_guard_rail import AIAgentGuardRail
		from one_bpmn.ai_agent_registry.doctype.ai_agent_sample_prompt.ai_agent_sample_prompt import AIAgentSamplePrompt
		from one_bpmn.ai_agent_registry.doctype.ai_agent_sub_prompt.ai_agent_sub_prompt import AIAgentSubPrompt

		a2a_exposed: DF.Check
		a2a_skill_tags: DF.SmallText | None
		agent_creation_process: DF.Link | None
		agent_framework: DF.Literal["", "Google ADK", "LangGraph", "Direct API", "Anthropic"]
		agent_id: DF.Data
		agent_name: DF.Data
		agent_roles: DF.Table[AIAgentAllowedRole]
		agent_type: DF.Literal["Chat", "Background"]
		agent_user: DF.Link | None
		ai_model: DF.Link | None
		ai_provider: DF.Link | None
		allowed_roles: DF.Table[AIAgentAllowedRole]
		artifact_type: DF.Literal["None", "Script", "Diagram", "Schema", "Record"]
		can_create_agents: DF.Check
		chat_description: DF.SmallText | None
		chat_mode_label: DF.Data | None
		collect_feedback: DF.Check
		compaction_enabled: DF.Check
		compaction_idle_minutes: DF.Int
		compaction_keep_tail: DF.Int
		compaction_model: DF.Link | None
		compaction_on_task_boundary: DF.Check
		compaction_token_threshold: DF.Int
		composer_placeholder: DF.Data | None
		concurrent_turn_policy: DF.Literal["Queue", "Refuse"]
		constants: DF.Table[AIAgentConstant]
		context_max_messages: DF.Int
		context_token_budget: DF.Int
		conversation_store: DF.Literal["", "process_variable", "document_store", "custom"]
		delegation_deadline_minutes: DF.Int
		description: DF.SmallText | None
		enabled: DF.Check
		enabled_skills: DF.Table[AIAgentEnabledSkill]
		examples: DF.Table[AIAgentExample]
		feedback_owner: DF.Link | None
		golden_dataset_minimum: DF.Int
		golden_dataset_target: DF.Int
		greeting: DF.SmallText | None
		guardrails: DF.Table[AIAgentGuardRail]
		icon: DF.Data | None
		injection_action: DF.Literal["Log", "Flag", "Block"]
		injection_screening: DF.Literal["Enabled", "Disabled"]
		langsmith_project: DF.Data | None
		lifecycle_status: DF.Literal["Draft", "Validating", "Provisioning", "Evaluating", "Live", "Needs Attention", "Retired"]
		lock_after_blocks: DF.Int
		lock_block_window_seconds: DF.Int
		long_term_memory: DF.Literal["", "Enabled", "Disabled"]
		loop_compaction_keep_turns: DF.Int
		loop_compaction_threshold: DF.Int
		max_clarification_rounds: DF.Int
		max_delegation_retries: DF.Int
		max_recursion_depth: DF.Int
		max_retries: DF.Int
		max_task_handoffs: DF.Int
		max_tokens: DF.Int
		max_tool_calls: DF.Int
		memory_distill_model: DF.Link | None
		memory_reconcile_model: DF.Link | None
		memory_scope: DF.Literal["", "Agent", "Process", "Entity", "User and Agent", "User and Process", "User and Entity"]
		memory_token_budget: DF.Int
		memory_write_mode: DF.Literal["", "off", "distilled", "raw"]
		needs_attention_reason: DF.SmallText | None
		output_screening_mode: DF.Literal["Log", "Flag", "Block"]
		parallel_tool_calls: DF.Check
		pii_screening: DF.Literal["Enabled", "Disabled"]
		process_model: DF.Link | None
		process_owner: DF.Link | None
		rate_limit_enabled: DF.Check
		rate_limit_messages: DF.Int
		rate_limit_window_seconds: DF.Int
		require_reproduction: DF.Check
		required_variables: DF.SmallText | None
		run_cost_budget: DF.Currency
		run_token_budget: DF.Int
		sample_prompts: DF.Table[AIAgentSamplePrompt]
		sandbox_retry_on_test_failure: DF.Check
		sandbox_use_job: DF.Check
		sub_prompts: DF.Table[AIAgentSubPrompt]
		surface_type: DF.Literal["Conversation", "Document", "Form"]
		system_prompt: DF.Code | None
		temperature: DF.Float
		terminal_tools: DF.Data | None
		thinking_budget_tokens: DF.Int
		timeout_seconds: DF.Int
		tool_choice: DF.Data | None
		tool_result_max_chars: DF.Int
		top_p: DF.Float
	# end: auto-generated types

	def validate(self):
		"""Validate that required runtime variables are present in the system prompt."""
		self.derive_provider_from_model()
		self.validate_required_variables()
		self.validate_unique_chat_mode_label()
		self.validate_chat_label_against_map()
		self.validate_agent_creation_grant()
		self.validate_a2a_exposure()
		self.validate_memory_config()
		self.validate_thinking_budget()
		self.validate_loop_compaction()
		self.validate_top_p()
		self.warn_unsupported_temperature()

	def validate_top_p(self):
		"""Top P is 0 (not set here) or a fraction above 0 and at most 1."""
		if self.top_p and not 0 < self.top_p <= 1:
			frappe.throw(_("Top P must be above 0 and at most 1, or 0 to leave it to the task."))

	def warn_unsupported_temperature(self):
		"""Warn, without blocking the save, when a temperature is set on a model that is never sent one."""
		from one_bpmn.processa_engine.agent_runtime.direct_api import supports_temperature

		if self.temperature and self.ai_model and not supports_temperature(self.ai_model):
			frappe.msgprint(
				_(
					"AI Model {0} does not accept a temperature, so the temperature {1} is not sent to it."
				).format(self.ai_model, self.temperature),
				title=_("Temperature not used"),
				indicator="orange",
			)

	def validate_thinking_budget(self):
		"""Anthropic needs a thinking budget of at least 1,024 tokens and below Max Tokens."""
		from one_bpmn.processa_engine.agent_runtime.executor import DEFAULT_MAX_OUTPUT_TOKENS

		budget = self.get("thinking_budget_tokens") or 0
		limit = self.max_tokens or DEFAULT_MAX_OUTPUT_TOKENS
		if budget and not 1024 <= budget < limit:
			frappe.throw(
				_("Thinking Budget Tokens must be 0, or at least 1,024 and below Max Tokens ({0}).").format(limit),
				title=_("Invalid Thinking Budget"),
			)

	def validate_loop_compaction(self):
		"""A tool loop compacted down to one or two turns loses track of what it was doing."""
		if self.get("loop_compaction_threshold") and (self.get("loop_compaction_keep_turns") or 0) < 3:
			frappe.throw(
				_("Tool Loop Keep Turns must be at least 3 when the Tool Loop Threshold is set."),
				title=_("Invalid Tool Loop Compaction"),
			)

	def validate_memory_config(self):
		"""An Enabled config with no resolvable model silently drops
		half the memory pipeline — distillation skips, or reconciliation
		degrades — with nothing on the form to say so (see model_resolution.py
		for the shared chain this checks against the dispatch path).

		Only fires when Long-Term Memory is explicitly Enabled; blank (inherit
		the diagram's value) is untouched, same as every other memory field.
		"""
		if self.long_term_memory != "Enabled":
			return

		self.warn_if_memory_has_no_map()

		if not self.memory_scope:
			frappe.throw(
				_("Memory Scope is required when Long-Term Memory is Enabled."),
				title=_("Memory Configuration"),
			)
		if not self.memory_write_mode:
			frappe.throw(
				_("Memory Write Mode is required when Long-Term Memory is Enabled."),
				title=_("Memory Configuration"),
			)
		if self.memory_write_mode != "distilled":
			return

		from one_bpmn.ai_agent_memory.model_resolution import resolve_memory_model

		distill = resolve_memory_model(
			self.memory_distill_model, "default_memory_distill_model", self.ai_model
		)
		if not distill:
			frappe.throw(
				_(
					"No Distillation Model is resolvable for this agent — set one here, "
					"a site-wide default in Processa Settings, or link an AI Model above."
				),
				title=_("Memory Configuration"),
			)

		reconcile = resolve_memory_model(
			self.memory_reconcile_model, "default_memory_reconcile_model", distill
		)
		if not reconcile:
			frappe.throw(
				_("No Reconciliation Model is resolvable for this agent."),
				title=_("Memory Configuration"),
			)

	def warn_if_memory_has_no_map(self):
		"""Say so when the memory settings cannot do anything.

		Recall and writeback live in the map dispatcher. A chat agent with no
		Process Model runs on the single-shot path instead (see ``_runner_for``
		in api/a2a.py), which never reads a memory and never writes
		one. The settings still save and the form still shows them Enabled, so
		the only visible symptom is an agent that forgets everything, which is
		what it looks like when memory is simply not working.

		A warning and not a block: linking the map afterwards is a normal order
		to do this in, and a Background config carries no map of its own.
		"""
		if self.agent_type != "Chat" or self.process_model:
			return

		frappe.msgprint(
			_(
				"Memory is Enabled, but this agent has no Process Model. "
				"Memories are read and written by the process map, so this agent will not "
				"recall anything and will not store anything until a map is linked."
			),
			title=_("Memory Configuration"),
			indicator="orange",
		)

	def validate_a2a_exposure(self):
		"""Exposure is an admin grant on an operating agent. A
		disabled agent cannot be exposed — the card and the A2A door both
		additionally require Live, so the flag may be set pre-Live harmlessly."""
		if self.a2a_exposed and not self.enabled:
			frappe.throw(
				_("This agent is disabled. Enable it before exposing it over A2A."),
				title=_("A2A Exposure"),
			)

	def validate_chat_label_against_map(self):
		"""A chat mode label promises the agent appears in chat,
		which only works when its linked map has the chat start pattern (a
		start event conditioned on Chat Conversation insert). A label on an
		agent mapped to any other process is a false promise — reject it and
		say why. Agents with no linked map keep their label: mapless Chat
		agents chat through the direct path."""
		if self.agent_type != "Chat" or not self.chat_mode_label or not self.process_model:
			return

		from one_bpmn.ai_agent_registry.provisioning.agent_provisioning import is_chat_startable_map

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

		from one_bpmn.processa_engine.triggers import parse_start_triggers

		xml = frappe.db.get_value("BPMN Process Model", self.process_model, "bpmn_xml") or ""
		triggers = parse_start_triggers(xml)
		condition = triggers["conditional_start"] or ""
		match = re.fullmatch(
			r"""\s*agent_mode\s*==\s*["']([^"']+)["']\s*""", condition
		)
		expected = match.group(1) if match else None

		# The legacy field filter (triggerFieldName/triggerFieldValue) is a
		# SECOND copy of the same gate, and the sneakier one: it is invisible
		# in the condition editor, survives cloning, and vetoes the spawn
		# silently AFTER the visible condition passes (diagnosed live
		# 2026-08-10 — a fixed condition still spawned nothing).
		field_cond = triggers["field_condition"]
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
		"""The model is the pick, the provider is derived. When an
		AI Model is linked, ai_provider follows the model's own provider — one
		choice, no model/provider mismatch possible. An agent with no model
		keeps whatever provider it has (legacy records)."""
		if not self.ai_model:
			return
		provider = frappe.db.get_value("AI Model", self.ai_model, "provider")
		if provider:
			self.ai_provider = provider
		if not self.ai_provider:
			frappe.throw(
				_("AI Model {0} has no provider. Link a provider on the model before saving this agent.").format(
					frappe.bold(self.ai_model)
				),
				title=_("No provider for model"),
			)

	def validate_unique_chat_mode_label(self):
		"""Two enabled chat agents must never claim the same conversation mode —
		the mode label is what the map's start condition and the chat registry
		key on."""
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
		# Leave a timeline trail when a save parks the agent.
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
		self.sync_linked_shapes()

		# The agent's identity is NOT provisioned here. It is a step in the Agent
		# creation process ("Provision Agent User"), because minting a User as a
		# side effect of saving a configuration hides a real action inside a
		# database write — and the process is where this system keeps behaviour.
		# The map runs it on the edited-config loop as well as the first pass, so
		# a change to the roles still reaches the agent's user.

	def sync_linked_shapes(self):
		"""Copy a changed setting the map shapes mirror onto the shapes that link this agent."""
		from one_bpmn.ai_agent_registry.provisioning.agent_config_resolver import DRIFT_CONFIG_FIELDS, sync_shapes_to_config

		if any(self.has_value_changed(f) for f in DRIFT_CONFIG_FIELDS):
			sync_shapes_to_config(self.name)

	def revalidate_credentials_on_save(self):
		"""Re-prove the agent on EVERY save — assume nothing (user ruling,
		2026-07-21): credentials that validated at creation may since have
		been rotated, disabled, or pointed at a dead model, and a Live badge
		must mean the agent works NOW.

		Runs the full validation including the live provider test call:
		  * Live agent that fails    → parked Needs Attention, with the reason
		  * Needs Attention that passes → promoted back to Live (self-healing)
		  * Needs Attention that fails with new errors → the reason is replaced
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
			from one_bpmn.ai_agent_registry.provisioning.agent_provisioning import validate_agent_config

			result = validate_agent_config(
				self.name,
				test_provider=True,
				# Provider-grant Background agents keep an empty
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
			from one_bpmn.ai_agent_registry.provisioning.agent_config_resolver import start_reprovision

			start_reprovision(self.name)
		elif not result["ok"]:
			reason = "; ".join(result["errors"])
			if self.lifecycle_status == "Live" or reason != self.needs_attention_reason:
				self._stamp_lifecycle("Needs Attention", reason)

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


@frappe.whitelist()
def get_effective_memory_models(memory_distill_model=None, memory_reconcile_model=None, ai_model=None):
	"""What the dispatch path would actually resolve, computed against
	the form's CURRENT (possibly unsaved) values so an admin can see the effect
	of a field before saving. Mirrors ``validate_memory_config`` and dispatch's
	``_memory_model`` — same shared chain, so this can never show one answer
	while the agent runs another.
	"""
	from one_bpmn.ai_agent_memory.model_resolution import resolve_memory_model

	distill = resolve_memory_model(memory_distill_model, "default_memory_distill_model", ai_model)
	reconcile = resolve_memory_model(memory_reconcile_model, "default_memory_reconcile_model", distill)
	return {"distill_model": distill, "reconcile_model": reconcile}


def get_agent_config(agent_id: str) -> dict | None:
	"""The enabled AI Agent Configuration for agent_id as a flat dict, or None.

	Built from the cached document, which Frappe clears when the record is saved."""
	name = frappe.db.get_value("AI Agent Configuration", {"agent_id": agent_id, "enabled": 1}, "name")
	if not name:
		return None
	doc = frappe.get_cached_doc("AI Agent Configuration", name)

	skill_names = [d.skill for d in doc.enabled_skills]
	active_skills = (
		{
			s.name: s
			for s in frappe.get_all(
				"AI Skill",
				filters={"name": ["in", skill_names], "status": "Active"},
				fields=["name", "skill_name", "description"],
			)
		}
		if skill_names
		else {}
	)

	return {
		"name": doc.name,
		"agent_id": doc.agent_id,
		"system_prompt": doc.system_prompt,
		"temperature": doc.temperature,
		"max_tokens": doc.max_tokens,
		"ai_provider": doc.ai_provider,
		"ai_model": doc.ai_model,
		"langsmith_project": doc.langsmith_project,
		"agent_framework": doc.agent_framework,
		"process_model": doc.process_model,
		"chat_mode_label": doc.chat_mode_label,
		"lifecycle_status": doc.lifecycle_status,
		"agent_type": doc.agent_type,
		"sub_prompts": {
			d.sub_agent_id: {"prompt": d.prompt_text, "temperature": d.temperature} for d in doc.sub_prompts
		},
		"constants": {
			d.constant_name: _cast_constant(d.constant_value, d.constant_type) for d in doc.constants
		},
		"examples": [
			frappe._dict(
				input=d.input,
				context_summary=d.context_summary,
				trajectory=d.trajectory,
				expected_output=d.expected_output,
				note=d.note,
				enabled=d.enabled,
			)
			for d in doc.examples
		],
		"guardrails": [
			frappe._dict(guardrail=d.guardrail, category=d.category, enabled=d.enabled)
			for d in doc.guardrails
		],
		"enabled_skills": [
			{
				"name": active_skills[d.skill].skill_name,
				"description": active_skills[d.skill].description,
				"status": "Active",
			}
			for d in doc.enabled_skills
			if d.skill in active_skills
		],
	}


def agent_config_name(agent_config) -> str | None:
	"""The AI Agent Configuration record name from a record name or a get_agent_config dict.

	The dict carries agent_id but not name, so the record is looked up by agent_id."""
	if not agent_config:
		return None
	if not isinstance(agent_config, dict):
		return agent_config if isinstance(agent_config, str) else None

	if agent_config.get("name"):
		return agent_config["name"]
	agent_id = agent_config.get("agent_id")
	if not agent_id:
		return None
	try:
		return frappe.db.get_value("AI Agent Configuration", {"agent_id": agent_id}, "name")
	except Exception:
		return None


def _cast_constant(value: str, const_type: str):
	"""Cast a string constant value to the appropriate Python type."""
	if const_type == "Integer":
		return int(value)
	elif const_type == "Float":
		return float(value)
	elif const_type == "Boolean":
		return value.lower() in ("1", "true", "yes")
	return value


def _load_json_constant(config: dict, key: str, default: list) -> list:
	"""Read a JSON-array constant off a resolved agent config, or *default*.

	Constants are stored as strings, so a list-valued one (keyword sets, tool
	exclusions, trigger phrases) has to be parsed. Every failure mode — no
	config, no such constant, unparseable JSON, or JSON that is not a list —
	returns *default*, because a configuration typo must degrade the agent's
	behaviour to its built-in defaults rather than break the turn.
	"""
	import json

	if not config:
		return default
	val = (config.get("constants") or {}).get(key)
	if not val:
		return default
	try:
		parsed = json.loads(val) if isinstance(val, str) else val
	except (json.JSONDecodeError, TypeError, ValueError):
		return default
	return parsed if isinstance(parsed, list) else default
