# Copyright (c) 2026, one-fm and contributors
# WI-001352 (2-02): dispatch_ai_task_selector — the AI-driven "decide" step
# of the ad-hoc subprocess dispatch loop.
#
# WI-001350 established a deterministic decide/activate/wait/re-decide loop
# whose default decision is "next task in diagram order". This module does
# NOT add a second loop: it replaces that decision function with an LLM call
# when an AI Task Selector (WI-001351) is configured on the subprocess —
# mirroring how Camunda's AI Agent connector reuses the same job-worker
# re-entry loop with a different decision function. One-task-at-a-time
# enforcement still applies: the LLM picks which SINGLE diagram task runs
# next; it never activates several at once.

import frappe

from one_bpmn.one_bpmn import engine as bpmn_engine


def make_adhoc_decider(instance, wf):
	"""
	Build the decider installed into engine.adhoc_next_task_decider for the
	duration of one _run_engine() call.

	The returned callable receives (subworkflow, pending_tasks) from the
	gate's promotion step and returns:
	- None                       — no selector configured; gate uses diagram order
	- a Task from pending        — the LLM's choice, arguments merged into task.data
	- engine.NO_ACTIVATION       — decision made but nothing to activate
	                               (registry-only actions, invalid tool, or
	                               executor failure) — fail-safe, the gate
	                               promotes nothing and the completion
	                               condition governs
	"""

	def decider(sp, pending):
		bpmn_id = sp.spec.name
		task_cfg = getattr(instance, "_service_task_extensions", {}).get(bpmn_id) or {}
		if task_cfg.get("serviceType") != "ai_task_selector":
			return None

		# WI-001495: park the decision — ONLY the LLM turn goes to the
		# bpmn_ai_agent worker. The resume job (run_parked_ai_task) sets
		# bpmn_ai_resume_target to this subprocess so exactly one decision
		# runs inline there; the target is consumed so the NEXT decision of
		# the same loop parks again (one job per selector turn).
		_parking_active = getattr(instance, "_ai_parking_active", None)
		if _parking_active is not None and _parking_active():
			if frappe.flags.bpmn_ai_resume_target == bpmn_id:
				frappe.flags.bpmn_ai_resume_target = None
			else:
				instance._queue_parked_ai_job("adhoc_decision", bpmn_id)
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
				# WI-001359: audit the decision itself; the activation is
				# logged separately by the gate's activation hook.
				try:
					instance.log_ai_task_selected(bpmn_id, [chosen_name], arguments)
				except Exception:
					pass
				return task

		# The LLM picked a diagram task that is not pending (already ran or
		# never existed) — same fail-safe as an unknown tool name.
		frappe.log_error(
			title=f"AI Task Selector: chosen task not pending ({bpmn_id})",
			message=f"Chosen '{chosen_name}'; pending: "
			f"{[t.task_spec.name for t in pending]}",
		)
		return bpmn_engine.NO_ACTIVATION

	return decider


def dispatch_ai_task_selector(instance, sp, task_cfg: dict, bpmn_id: str) -> tuple:
	"""
	Run one selector decision for an ad-hoc subprocess.

	Builds the tool pool (WI-001353), calls the executor with tools attached
	(WI-001356), lets registry tools execute inline within the adapter's
	loop, and reports which diagram task (if any) the LLM selected.

	Follows dispatch_ai_agent's structure: Jinja-rendered prompts with the
	same {"doc": doc, "instance": instance, "frappe": frappe} context, and
	an error fallback that keeps the loop safe — failures write
	{bpmn_id}_error_code/{bpmn_id}_error_message into the subprocess data
	and never raise.

	Returns:
	    ("activate", chosen_bpmn_id, arguments) — a diagram task was selected
	    ("idle", None, None)                    — no diagram activation
	                                              (final answer or registry-only)
	    ("error", None, None)                   — executor failure
	"""
	from one_bpmn.agents.executor import ErrorCode, ExecutorConfig, ExecutorContext, get_executor
	from one_bpmn.agents.executor.direct_api import DirectApiExecutor
	from one_bpmn.agents.llm_provider.base import ToolSpec
	from one_bpmn.agents.tool_pool import DIAGRAM_TASK, resolve_tool_pool

	# WI-001637 (live link): a linked AI Agent Configuration is authoritative
	# for agent-level fields; the shape's copies are the fallback. Tools stay
	# the subprocess's own shapes — never sourced from the config.
	if task_cfg.get("aiAgentConfig"):
		from one_bpmn.agents.agent_config_resolver import resolve_dispatch_overrides
		task_cfg = {**task_cfg, **resolve_dispatch_overrides(task_cfg["aiAgentConfig"])}

	doc = frappe._dict()
	if instance.context_doctype and instance.context_docname:
		try:
			doc = frappe.get_doc(instance.context_doctype, instance.context_docname)
		except Exception:
			pass

	jinja_ctx = {"doc": doc, "instance": instance, "frappe": frappe}
	if isinstance(sp.data, dict):
		jinja_ctx.update({k: v for k, v in sp.data.items() if k != "doc"})

	def render(text):
		if not text:
			return ""
		try:
			return frappe.render_template(text, jinja_ctx)
		except Exception:
			return text

	pool = resolve_tool_pool(sp, task_cfg, instance.process_model or "")

	# Runtime availability: the pool is spec-derived (every candidate on the
	# diagram), but at a decision point only PARKED heads can actually be
	# activated. Offering completed tasks as tools invited the model to
	# re-pick them — a safe no-op that stalled the subprocess (the dominant
	# failure in UAT). Filter diagram candidates to the pending heads and
	# tell the model what already ran instead.
	from SpiffWorkflow.util.task import TaskState

	heads = bpmn_engine.adhoc_head_tasks(sp)
	head_name = lambda t: getattr(t.task_spec, "bpmn_id", None) or t.task_spec.name  # noqa: E731
	# Activatable = not yet run: parked (FUTURE, the normal decision-time
	# state) or freshly readied (READY, subprocess entry before the gate
	# parks). Finished heads are excluded and reported as progress instead.
	pending_names = {
		head_name(t) for t in heads if t.state & (TaskState.FUTURE | TaskState.READY)
	}
	finished_names = {
		head_name(t)
		for t in heads
		if t.state & (TaskState.COMPLETED | TaskState.CANCELLED)
	}

	# Diagram-task candidates cannot execute inline the way registry tools
	# do — activation happens in the engine after this decision. Their fn
	# records the FIRST selection and tells the model to stop selecting,
	# preserving one-task-at-a-time.
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
				continue  # completed/cancelled/in-flight — not activatable
			spec = ToolSpec(
				fn=make_activation_fn(spec.name),
				name=spec.name,
				description=spec.description,
				parameters=spec.parameters,
				required=spec.required,
			)
		tools.append(spec)

	# Auto-appended progress block: authoritative memory the prompt author
	# doesn't have to engineer evidence for (send tasks leave no data trace).
	user_prompt = render(task_cfg.get("aiUserPrompt", ""))
	if finished_names:
		user_prompt += (
			"\n\nProcess progress (authoritative): these tasks have ALREADY RUN "
			"and are no longer offered: " + ", ".join(sorted(finished_names)) + "."
		)
	# Engine-level guard rail for every prompt: when a procedure's prescribed
	# task is unavailable (already ran, filtered out), improvising is worse
	# than waiting — a UAT run escalated to the wrong team this way.
	user_prompt += (
		"\n\nIf the task your rules prescribe is not among your offered tools, "
		"activate nothing and give your final answer."
	)

	config = ExecutorConfig(
		backend="direct_api",
		provider_name=task_cfg.get("aiProvider", ""),
		model=task_cfg.get("aiModel", ""),
		system_prompt=render(task_cfg.get("aiSystemPrompt", "")),
		user_prompt=user_prompt,
		max_tokens=int(task_cfg.get("aiMaxTokens", 1024) or 1024),
		timeout_seconds=int(task_cfg.get("aiTimeout", 60) or 60),
		tools=tools,
	)
	context = ExecutorContext(
		context_doctype=instance.context_doctype or "",
		context_docname=instance.context_docname or "",
		instance_name=instance.name or "",
		initiated_by=instance.initiated_by or frappe.session.user or "",
		jinja_context=jinja_ctx,
	)

	# ── Observability (WI-001358): one Run per subprocess, reused across
	# decision points. Instrumentation failures never block dispatch.
	run = None
	try:
		from one_bpmn.agents.observability import get_or_create_selector_run

		run = get_or_create_selector_run(
			instance, bpmn_id, config, process_model=instance.process_model or ""
		)
	except Exception:
		frappe.log_error(
			title=f"AI Observability: selector run setup failed ({bpmn_id})",
			message=frappe.get_traceback(),
		)

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

	# One Step per LLM turn, one Tool Call row per call within a turn.
	try:
		from one_bpmn.agents.observability import record_selector_turns

		if run is not None:
			source_map = {c.spec.name: c.source for c in pool}
			record_selector_turns(run, result.trace or [], source_map)
	except Exception:
		frappe.log_error(
			title=f"AI Observability: selector step recording failed ({bpmn_id})",
			message=frappe.get_traceback(),
		)

	if result.error_code != ErrorCode.SUCCESS:
		# Same pattern as dispatch_ai_agent: log, write error variables,
		# leave the subprocess's other inner tasks unaffected.
		frappe.log_error(
			title=f"BPMN AI Task Selector: executor failed ({bpmn_id})",
			message=f"{result.error_code.value}: {result.error_message}",
		)
		sp.data[f"{bpmn_id}_error_code"] = result.error_code.value
		sp.data[f"{bpmn_id}_error_message"] = result.error_message
		return ("error", None, None)

	_record_tool_outcomes(sp, bpmn_id, result)

	# An idle decision does NOT close the run — earlier code finalized here
	# unconditionally, so a correct "wait for the agent" decision marked the
	# run Success mid-flight and the next decision opened a second run. The
	# run is finalized when the subprocess itself completes
	# (_on_engine_task_complete → finalize_open_selector_runs). Belt: if the
	# completion condition is already satisfied at an idle decision, the
	# subprocess is about to close, so finalizing here is safe and correct.
	if not selection:
		try:
			from one_bpmn.agents.observability import finalize_selector_run

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
	"""
	Post-process the executor trace (WI-001356):
	- registry tool results are written back to a toolCallResult process
	  variable ({bpmn_id}_toolCallResult, the naming borrowed from Camunda's
	  AI Agent Sub-Process connector) — the last result wins;
	- tool names the adapters flagged as unknown are logged via
	  frappe.log_error (fail-safe, not fail-stop — the completion condition
	  is simply re-evaluated without activating anything).
	"""
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
				# A registry tool actually executed inside the adapter loop.
				# Legacy combined variable (last call wins) …
				sp.data[f"{bpmn_id}_toolCallResult"] = call_result
				# … plus a per-tool variable, so one decision calling several
				# registry tools (lookup + send email) doesn't clobber the
				# evidence later decisions route on.
				tool_name = call.get("name") or ""
				if tool_name:
					sp.data[f"{tool_name}_toolCallResult"] = call_result
