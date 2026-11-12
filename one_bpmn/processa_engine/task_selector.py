# Copyright (c) 2026, one-fm and contributors
"""AI Task Selector: the LLM decision step that picks the next task of an ad-hoc subprocess.

It replaces the diagram-order decision of the dispatch loop and activates at most one task per decision.
"""

import frappe

from one_bpmn.processa_engine import engine as bpmn_engine
from one_bpmn.processa_engine.dispatch.common import cfg_truthy, template_renderer
from one_bpmn.processa_engine.dispatch.executor_settings import terminal_tools_for
from one_bpmn.processa_engine.runtime.ai_jobs import ai_parking_active, queue_parked_ai_job
from one_bpmn.processa_engine.runtime.dispatch import log_ai_task_selected


def make_adhoc_decider(instance, wf):
	"""Build the adhoc_next_task_decider installed for one run_engine() call.

	The decider returns None (diagram order), the chosen pending Task, or engine.NO_ACTIVATION.
	"""

	def decider(sp, pending):
		bpmn_id = sp.spec.name
		task_cfg = getattr(instance, "_service_task_extensions", {}).get(bpmn_id) or {}
		if task_cfg.get("serviceType") != "ai_task_selector":
			return None

		# The resume job sets the target for one inline decision; clearing it parks the next one.
		if ai_parking_active():
			if frappe.flags.bpmn_ai_resume_target == bpmn_id:
				frappe.flags.bpmn_ai_resume_target = None
			else:
				queue_parked_ai_job(instance, "adhoc_decision", bpmn_id)
				return bpmn_engine.NO_ACTIVATION

		action, chosen_name, arguments = dispatch_ai_task_selector(
			instance, sp, task_cfg, bpmn_id
		)
		if action != "activate":
			return bpmn_engine.NO_ACTIVATION

		for task in pending:
			candidate_name = getattr(task.task_spec, "bpmn_id", None) or task.task_spec.name
			if candidate_name == chosen_name:
				if arguments:
					task.data.update(arguments)
				try:
					log_ai_task_selected(instance, bpmn_id, [chosen_name], arguments)
				except Exception:
					pass
				return task

		# The chosen task is not pending, so nothing is activated.
		frappe.log_error(
			title=f"AI Task Selector: chosen task not pending ({bpmn_id})",
			message=f"Chosen '{chosen_name}'; pending: "
			f"{[t.task_spec.name for t in pending]}",
		)
		return bpmn_engine.NO_ACTIVATION

	return decider


def dispatch_ai_task_selector(instance, sp, task_cfg: dict, bpmn_id: str) -> tuple:
	"""Run one selector decision for an ad-hoc subprocess and return (action, bpmn_id, arguments).

	Action is "activate", "idle" or "error"; failures write {bpmn_id}_error_code and _error_message and never raise.
	"""
	from frappe.utils import cint

	from one_bpmn.processa_engine.agent_runtime.executor import (
		DEFAULT_MAX_OUTPUT_TOKENS,
		DEFAULT_TEMPERATURE,
		DEFAULT_TIMEOUT_SECONDS,
		DEFAULT_TOP_P,
		ErrorCode,
		ExecutorConfig,
		ExecutorContext,
		get_executor,
	)
	from one_bpmn.processa_engine.agent_runtime.direct_api import DirectApiExecutor
	from one_bpmn.processa_engine.agent_runtime.llm_types import ToolSpec
	from one_bpmn.ai_agent_skills.tools.tool_pool import DIAGRAM_TASK, resolve_tool_pool

	# A linked AI Agent Configuration overrides the shape's agent fields; tools stay the subprocess's own.
	if task_cfg.get("aiAgentConfig"):
		from one_bpmn.ai_agent_registry.provisioning.agent_config_resolver import resolve_dispatch_overrides
		task_cfg = {**task_cfg, **resolve_dispatch_overrides(task_cfg["aiAgentConfig"])}

	render, jinja_ctx = template_renderer(
		instance,
		f"BPMN AI Task Selector: prompt template render failed ({bpmn_id})",
		data={k: v for k, v in sp.data.items() if k != "doc"} if isinstance(sp.data, dict) else None,
	)

	pool = resolve_tool_pool(sp, task_cfg, instance.process_model or "", instance)

	# Only pending heads are offered as diagram tools; finished ones go into the prompt as progress.
	from one_bpmn.processa_engine.engine import TaskState

	heads = bpmn_engine.adhoc_head_tasks(sp)
	head_name = lambda t: getattr(t.task_spec, "bpmn_id", None) or t.task_spec.name  # noqa: E731
	# READY covers subprocess entry, before the gate parks heads as FUTURE.
	pending_names = {
		head_name(t) for t in heads if t.state & (TaskState.FUTURE | TaskState.READY)
	}
	finished_names = {
		head_name(t)
		for t in heads
		if t.state & (TaskState.COMPLETED | TaskState.CANCELLED)
	}

	# Diagram tools only record the first selection; the engine activates it after this decision.
	selection = {}

	def make_activation_fn(candidate_name):
		def fn(**kwargs):
			if selection:
				return (
					"A task has already been selected for this decision point. "
					"Do not select another; give your final answer."
				)
			selection["bpmn_id"] = candidate_name
			selection["arguments"] = dict(kwargs)
			return (
				f"Task '{candidate_name}' will be activated. Its result becomes "
				"available after it completes; give your final answer now."
			)

		return fn

	tools = []
	for candidate in pool:
		spec = candidate.spec
		if candidate.source == DIAGRAM_TASK:
			if spec.name not in pending_names:
				continue
			spec = ToolSpec(
				fn=make_activation_fn(spec.name),
				name=spec.name,
				description=spec.description,
				parameters=spec.parameters,
				required=spec.required,
			)
		tools.append(spec)

	# Send tasks leave no data trace, so the prompt lists finished tasks explicitly.
	user_prompt = render(task_cfg.get("aiUserPrompt", ""))
	if finished_names:
		user_prompt += (
			"\n\nProcess progress (authoritative): these tasks have ALREADY RUN "
			"and are no longer offered: " + ", ".join(sorted(finished_names)) + "."
		)
	user_prompt += (
		"\n\nIf the task your rules prescribe is not among your offered tools, "
		"activate nothing and give your final answer."
	)

	# A linked agent's examples and guard rails go into the system prompt; selector text stays in the user prompt.
	from one_bpmn.ai_agent_registry.provisioning.context_assembler import build_static_context, load_agent_behaviour

	behaviour = {}
	if task_cfg.get("aiAgentConfig"):
		try:
			behaviour = load_agent_behaviour(task_cfg["aiAgentConfig"])
		except Exception:
			frappe.log_error(
				title=f"AI Task Selector: static context load failed ({bpmn_id})",
				message=frappe.get_traceback(),
			)

	config = ExecutorConfig(
		backend="direct_api",
		# Without aiProvider, the provider comes from the AI Model record.
		provider_name=task_cfg.get("aiProvider", "")
		or frappe.db.get_value("AI Model", task_cfg.get("aiModel", ""), "provider")
		or "",
		model=task_cfg.get("aiModel", ""),
		system_prompt=build_static_context(
			system_prompt=render(task_cfg.get("aiSystemPrompt", "")),
			examples=behaviour.get("examples"),
			guardrails=behaviour.get("guardrails"),
			skills=behaviour.get("enabled_skills"),
		),
		user_prompt=user_prompt,
		# Shape attributes are strings, so cint turns "0" into the default.
		max_tokens=cint(task_cfg.get("aiMaxTokens")) or DEFAULT_MAX_OUTPUT_TOKENS,
		temperature=float(task_cfg.get("aiTemperature") or DEFAULT_TEMPERATURE),
		top_p=float(task_cfg.get("aiTopP") or DEFAULT_TOP_P),
		timeout_seconds=cint(task_cfg.get("aiTimeout")) or DEFAULT_TIMEOUT_SECONDS,
		tools=tools,
		terminal_tools=terminal_tools_for(task_cfg),
		tool_choice=(task_cfg.get("aiToolChoice") or "auto").strip(),
		parallel_tool_calls=cfg_truthy(task_cfg.get("aiParallelToolCalls", 1)),
		thinking_budget_tokens=cint(task_cfg.get("aiThinkingBudgetTokens")),
	)
	context = ExecutorContext(
		context_doctype=instance.context_doctype or "",
		context_docname=instance.context_docname or "",
		instance_name=instance.name or "",
		initiated_by=instance.initiated_by or frappe.session.user or "",
		jinja_context=jinja_ctx,
	)

	# One observability Run per subprocess, reused across decisions; its failures never block dispatch.
	run = None
	try:
		from one_bpmn.ai_agent_observability.observability import get_or_create_selector_run

		run = get_or_create_selector_run(
			instance, bpmn_id, config, process_model=instance.process_model or ""
		)
	except Exception:
		frappe.log_error(
			title=f"AI Observability: selector run setup failed ({bpmn_id})",
			message=frappe.get_traceback(),
		)

	# Publish the agent so its tool grant applies to the selector's tool calls.
	from one_bpmn.ai_agent_guardrails.tool_policy import reset_current_agent, set_current_agent

	_policy_token = set_current_agent(task_cfg.get("aiAgentConfig"))
	try:
		executor_cls = get_executor(config.backend)
		result = executor_cls().run(config, context)
	except Exception:
		frappe.log_error(
			title=f"BPMN AI Task Selector: unexpected error ({bpmn_id})",
			message=frappe.get_traceback(),
		)
		sp.data[f"{bpmn_id}_error_code"] = "UNEXPECTED_ERROR"
		sp.data[f"{bpmn_id}_error_message"] = "See Frappe Error Log for details."
		return ("error", None, None)
	finally:
		reset_current_agent(_policy_token)

	# One Step per LLM turn, one Tool Call row per call within a turn.
	try:
		from one_bpmn.ai_agent_observability.observability import record_selector_turns

		if run is not None:
			source_map = {c.spec.name: c.source for c in pool}
			record_selector_turns(run, result.trace or [], source_map)
	except Exception:
		frappe.log_error(
			title=f"AI Observability: selector step recording failed ({bpmn_id})",
			message=frappe.get_traceback(),
		)

	if result.error_code != ErrorCode.SUCCESS:
		frappe.log_error(
			title=f"BPMN AI Task Selector: executor failed ({bpmn_id})",
			message=f"{result.error_code.value}: {result.error_message}",
		)
		sp.data[f"{bpmn_id}_error_code"] = result.error_code.value
		sp.data[f"{bpmn_id}_error_message"] = result.error_message
		return ("error", None, None)

	_record_tool_outcomes(sp, bpmn_id, result)

	# An idle decision finalizes the run only when the completion condition is already met.
	if not selection:
		try:
			from one_bpmn.ai_agent_observability.observability import finalize_selector_run

			if run is not None and bpmn_engine._adhoc_completion_met(sp):
				finalize_selector_run(run)
		except Exception:
			frappe.log_error(
				title=f"AI Observability: selector finalize failed ({bpmn_id})",
				message=frappe.get_traceback(),
			)

	if selection:
		return ("activate", selection["bpmn_id"], selection["arguments"])
	return ("idle", None, None)


def _record_tool_outcomes(sp, bpmn_id: str, result) -> None:
	"""Write registry tool results to toolCallResult process variables and log unknown tool names."""
	sp.data[f"{bpmn_id}_selector_output"] = result.output or ""

	for turn in result.trace or []:
		for call in turn.get("tool_calls", []):
			call_result = call.get("result") or ""
			if call_result.startswith("Unknown tool:"):
				frappe.log_error(
					title=f"AI Task Selector: unknown tool selected ({bpmn_id})",
					message=f"Tool '{call.get('name')}' matched neither a diagram task "
					f"nor a registry entry. Arguments: {call.get('arguments')}",
				)
			elif not call_result.startswith("Task '"):
				# Combined variable keeps the last call; the per-tool variable keeps each tool's result.
				sp.data[f"{bpmn_id}_toolCallResult"] = call_result
				tool_name = call.get("name") or ""
				if tool_name:
					sp.data[f"{tool_name}_toolCallResult"] = call_result
