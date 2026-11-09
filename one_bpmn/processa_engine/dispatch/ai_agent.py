# Copyright (c) 2026, one-fm and contributors
"""Service Task serviceType="ai_agent": run an AI Agent Task through the executor, with long-term memory."""

import json
import re
import time

import frappe
import frappe.utils
from frappe.utils import cint

from one_bpmn.processa_engine.dispatch.common import cfg_truthy, split_config, template_renderer

# Evals and the run inspector read this header.
MEMORY_BLOCK_HEADER = "Relevant memory:"
_MEMORY_BLOCK_PROVENANCE = "Possibly relevant notes from earlier work; use them only if they match this request."

# Per-agent default for the injected memory block; aiMemoryTokenBudget overrides it.
DEFAULT_MEMORY_TOKEN_BUDGET = 800
KEYED_PROCESS_ROWS = 5
KEYED_USER_ROWS = 3

# Captured by the stream, never relayed: this is the answer, not a UI event.
TURN_OUTPUT_EVENT = "ONEFM_TURN_OUTPUT"

# Generic on purpose: recall gating runs ahead of every agent, so no agent's domain words belong here.
_SMALL_TALK_WORDS = frozenset(
	"""
	a afternoon alright am and are back bye can cheers cool day do does evening
	excellent fine good goodbye great hallo hello help hey hi hiya how howdy i
	is it just k kk later lovely me morning much my name nice night no now ok
	okay okey perfect ping please pong really right say see so sup sure test
	testing thank thanks thanx there this thx to u up welcome well what who
	with working works yeah yep yes yo you your yours yw
	""".split()
)

_REMEMBER_PHRASES = (
	r"\bremember (?:that|this|to|for)\b",
	r"\bfrom now on\b",
	r"\bgoing forward\b",
	r"\bmake a note (?:that|to)\b",
	r"\bkeep in mind (?:that)?\b",
	r"\bfor every .+ (?:we|you) build\b",
)
_REMEMBER_RE = re.compile("|".join(_REMEMBER_PHRASES), re.IGNORECASE)

# Tools whose turn is a canned reply or a question, so there is nothing to learn from it.
_NON_ANSWER_TOOLS = frozenset({"redirect", "clarify"})

# Shape attribute to the Processa Settings field holding its site-wide default.
_MEMORY_MODEL_SETTINGS = {
	"aiMemoryDistillModel": "default_memory_distill_model",
	"aiMemoryReconcileModel": "default_memory_reconcile_model",
}


def resume_ai_agent(instance, task, task_cfg: dict, bpmn_id: str, human_result=None, run_name: str = None) -> bool:
	"""Resume a suspended AI Agent Task with the human's output; True when a resume actually ran.

	The claim flips the run out of "Suspended" atomically, so a second call does nothing.
	"""
	from one_bpmn.processa_engine.agent_runtime import checkpoint as _checkpoint

	run_name = run_name or _checkpoint.get_suspended_run(instance.name, bpmn_id)
	if not run_name:
		return False
	if human_result is not None:
		_checkpoint.store_human_result(run_name, human_result)
	before = frappe.db.get_value("AI Agent Run", run_name, "status")
	if before != "Suspended":
		return False
	dispatch_ai_agent(instance, task, task_cfg, bpmn_id, resume_run=run_name)
	return True


def dispatch_ai_agent(instance, task, task_cfg: dict, bpmn_id: str, resume_run: str = None) -> None:
	"""Render the prompts, run the executor and write the results, AI Agent Run and memory for one AI Agent Task.

	A failure sets error variables and the task still completes. A human tool suspends the run; resume_run continues it.
	"""
	from one_bpmn.processa_engine.agent_runtime import checkpoint as _checkpoint
	from one_bpmn.processa_engine.agent_runtime.executor import (
		DEFAULT_MAX_OUTPUT_TOKENS,
		DEFAULT_MAX_RETRIES,
		DEFAULT_TEMPERATURE,
		DEFAULT_TIMEOUT_SECONDS,
		DEFAULT_TOP_P,
		ErrorCode,
		ExecutorConfig,
		ExecutorContext,
		get_executor,
	)
	from one_bpmn.processa_engine.agent_runtime import antigravity, direct_api  # noqa: F401 importing registers the backends

	resume_payload = None
	if resume_run:
		resume_payload = _checkpoint.claim_for_resume(resume_run)
		if resume_payload is None:
			return

	# A linked AI Agent Configuration wins over the shape's copies; on resume the checkpoint keeps its own prompt.
	if task_cfg.get("aiAgentConfig"):
		from one_bpmn.ai_agent_registry.provisioning.agent_config_resolver import resolve_dispatch_overrides

		_overrides = resolve_dispatch_overrides(task_cfg["aiAgentConfig"])
		if resume_payload:
			_overrides = {k: v for k, v in _overrides.items() if k != "aiSystemPrompt"}
		task_cfg = {**task_cfg, **_overrides}

	render, jinja_ctx = template_renderer(
		instance,
		f"BPMN AI Agent Task: prompt template render failed ({bpmn_id})",
		data=task.data if isinstance(getattr(task, "data", None), dict) else None,
	)

	if resume_payload:
		# The checkpointed system prompt is reused verbatim so a resumed segment sees what the first one saw.
		system_prompt = resume_payload.get("system_prompt") or ""
		user_prompt = ""
	else:
		from one_bpmn.ai_agent_registry.provisioning.context_assembler import build_static_context, load_agent_behaviour

		instructions = render(task_cfg.get("aiSystemPrompt", ""))
		agent_config = {}
		if task_cfg.get("aiAgentConfig"):
			try:
				agent_config = load_agent_behaviour(task_cfg["aiAgentConfig"])
			except Exception:
				# Behaviour rows are additive, so a failure falls back to the plain prompt.
				frappe.log_error(
					title=f"BPMN AI Agent Task: static context load failed ({bpmn_id})",
					message=frappe.get_traceback(),
				)
		system_prompt = build_static_context(
			system_prompt=instructions,
			examples=agent_config.get("examples"),
			guardrails=agent_config.get("guardrails"),
			skills=agent_config.get("enabled_skills"),
		)
		user_prompt = render(task_cfg.get("aiUserPrompt", ""))

	memory_target = None
	raw_user_message = "" if resume_payload else _turn_user_message(instance, task)
	user_message = raw_user_message
	if user_message and user_message in user_prompt:
		# A map that renders the message itself keeps its own copy; the platform does not add a second.
		user_message = ""

	is_chat_turn = (
		getattr(instance, "context_doctype", "") == "Chat Conversation"
		and bool(getattr(instance, "context_docname", ""))
	)
	# A chat turn with no resolvable message must not recall with the map's constant driving prompt.
	recall_query_unresolved = is_chat_turn and not raw_user_message

	memory_block = ""
	recall_query = ""
	memory_injected_tokens = 0
	if not resume_payload and cfg_truthy(task_cfg.get("aiLongTermMemory")):
		try:
			memory_target = _resolve_memory_target(task_cfg, instance, bpmn_id, task.data)
			# raw_user_message, not user_message: the person's question, even when the map rendered its own copy.
			query = "" if recall_query_unresolved else (raw_user_message or user_prompt)
			if memory_target and query and not _is_small_talk(query):
				recall_query = query
				from one_bpmn.ai_agent_memory.tools import memory_list_top, memory_list_user_directed, memory_search

				scope, scope_key = memory_target
				limit = int(task_cfg.get("aiMemoryLimit", 5) or 5)
				# Standing conventions come first so the budget trim drops keyword matches before them.
				user_directed = memory_list_user_directed(
					scope, scope_key, limit=3, ignore_permissions=True  # recall runs for the agent, not the user
				)
				matched = memory_search(
					scope, scope_key, query, limit=limit, ignore_permissions=True  # recall runs for the agent, not the user
				)
				preference_user = _preference_user(task.data)
				standing = []
				if preference_user:
					user_key = {"user": preference_user}
					user_directed += memory_list_user_directed("User", user_key, limit=3, ignore_permissions=True)  # recall runs for the agent
					standing = memory_list_top(scope, scope_key, limit=KEYED_PROCESS_ROWS, ignore_permissions=True)  # recall runs for the agent
					standing += memory_list_top("User", user_key, limit=KEYED_USER_ROWS, ignore_permissions=True)  # recall runs for the agent
					matched += memory_search("User", user_key, query, limit=limit, ignore_permissions=True)  # recall runs for the agent
				memories = list(user_directed)
				seen_names = {m.get("name") for m in memories}
				for m in standing + matched:
					if m.get("name") not in seen_names:
						seen_names.add(m.get("name"))
						memories.append(m)
				if memories:
					token_budget = int(task_cfg.get("aiMemoryTokenBudget") or DEFAULT_MEMORY_TOKEN_BUDGET)
					memories = bound_memories_to_budget(memories, token_budget)
					memory_block = _format_memory_block(memories)
					from one_bpmn.agents.memory.conversation_store import DEFAULT_CHARS_PER_TOKEN, estimate_tokens

					memory_injected_tokens = estimate_tokens({"content": memory_block}, DEFAULT_CHARS_PER_TOKEN)
		except Exception:
			frappe.log_error(
				title=f"BPMN AI Agent Task: memory_search failed ({bpmn_id})",
				message=frappe.get_traceback(),
			)

	turn_history, turn_established = ([], "") if resume_payload else _platform_history(
		instance, task_cfg, raw_user_message
	)

	# Skills loaded earlier in the conversation reach the prompt on the next turn.
	active_skill_bodies = []
	conversation = None
	if getattr(instance, "context_doctype", "") == "Chat Conversation":
		conversation = getattr(instance, "context_docname", None)
	if conversation and task_cfg.get("aiAgentConfig"):
		from one_bpmn.api.skill_tools import _skills_cache_key, advance_turn

		active_skill_bodies = frappe.cache().get_value(
			_skills_cache_key(conversation, task_cfg["aiAgentConfig"])
		) or []
		# Only a fresh dispatch is a new conversation turn; a resume continues the current one.
		if not resume_payload:
			advance_turn(conversation)

	if memory_block or user_message or turn_established or active_skill_bodies:
		from one_bpmn.ai_agent_registry.provisioning.context_assembler import build_dynamic_preamble

		user_prompt = build_dynamic_preamble(
			memory_block=memory_block,
			instructions=user_prompt,
			user_prompt=user_message,
			established_block=turn_established,
			active_skills=active_skill_bodies,
		)

		if active_skill_bodies:
			from one_bpmn.agents.memory.conversation_store import DEFAULT_CHARS_PER_TOKEN, estimate_tokens

			memory_injected_tokens += estimate_tokens(
				{"content": "\n\n".join(active_skill_bodies)}, DEFAULT_CHARS_PER_TOKEN
			)


	# The shapes of the referenced ad-hoc sub-process are the tools; without them this is a plain LLM call.
	tool_specs = []
	tool_shapes = task_cfg.get("aiToolShapes")
	if tool_shapes:
		from one_bpmn.agents.shape_tools import compile_shape_tools

		tool_specs = compile_shape_tools(tool_shapes, instance) or []

	from one_bpmn.api.skill_tools import get_skill_tools

	agent_name = task_cfg.get("aiAgentConfig")
	if agent_name:
		skill_tool_specs = get_skill_tools(agent_name, instance)
		if skill_tool_specs:
			tool_specs.extend(skill_tool_specs)

	# Tools of skills loaded in this conversation, keyed by conversation because a resume gets a new instance.
	if instance:
		active_skill_names = []
		if conversation and agent_name:
			from one_bpmn.api.skill_tools import _skill_names_cache_key

			active_skill_names = (
				frappe.cache().get_value(_skill_names_cache_key(conversation, agent_name)) or []
			)
		if active_skill_names:
			from one_bpmn.processa_engine.agent_runtime.llm_types import ToolSpec

			def make_dynamic_tool_fn(script_name, tool_name):
				def fn(**kwargs):
					from one_bpmn.agents.shape_tools import _run_server_script, _synthetic_task

					task = _synthetic_task(tool_name, kwargs)
					try:
						_run_server_script(instance, script_name, task, tool_name)
						produced = {k: v for k, v in task.data.items() if k not in kwargs}
						return json.dumps(produced or {"ok": True}, default=str)
					except Exception as e:
						return json.dumps({"error": str(e)})
				return fn

			for skill_name in active_skill_names:
				allowed_tools = frappe.get_all("AI Skill Allowed Tool", filters={"parent": skill_name}, fields=["tool"])
				for allowed in allowed_tools:
					tool_name = allowed.tool
					if any(t.name == tool_name for t in tool_specs):
						continue

					tool_doc = frappe.db.get_value("AI Agent Tool", tool_name, ["description", "json_schema", "script"], as_dict=True)
					if tool_doc:
						try:
							schema = json.loads(tool_doc.json_schema)
							parameters = schema.get("properties", {})
							required = schema.get("required", [])
						except Exception:
							parameters = {}
							required = []

						tool_specs.append(ToolSpec(
							fn=make_dynamic_tool_fn(tool_doc.script, tool_name),
							name=tool_name,
							description=tool_doc.description or tool_name,
							parameters=parameters,
							required=required
						))

			# A skill with Allowed Tools rows narrows the pool; one without rows changes nothing.
			restrictive_allowed_names = set()
			has_restrictive_skill = False
			for skill_name in active_skill_names:
				skill_allowed = frappe.get_all("AI Skill Allowed Tool", filters={"parent": skill_name}, pluck="tool")
				if skill_allowed:
					has_restrictive_skill = True
					restrictive_allowed_names.update(skill_allowed)

			def make_blocked_fn(tool_name):
				def blocked_fn(**kwargs):
					return "Error: Tool not allowed by active skill."
				return blocked_fn

			if has_restrictive_skill:
				allowed_tool_names = restrictive_allowed_names | {"load_skill", "load_skill_resource"}
				for t in tool_specs:
					if t.name not in allowed_tool_names:
						t.fn = make_blocked_fn(t.name)

	if not tool_specs:
		tool_specs = None

	# An instruction block the system prompt already carries is dropped from the user prompt.
	if user_prompt and system_prompt:
		from one_bpmn.ai_agent_registry.provisioning.context_assembler import drop_duplicated_instructions

		user_prompt = drop_duplicated_instructions(system_prompt, user_prompt)

	config = ExecutorConfig(
		backend          = task_cfg.get("aiBackend", "direct_api"),
		# A shape may name only the model; its provider is on the model's record.
		provider_name    = task_cfg.get("aiProvider", "")
		                   or frappe.db.get_value("AI Model", task_cfg.get("aiModel", ""), "provider")
		                   or "",
		agent_config_name = task_cfg.get("aiAgentConfig", ""),
		model            = task_cfg.get("aiModel", ""),
		system_prompt    = system_prompt,
		user_prompt      = user_prompt,
		messages         = turn_history,
		temperature      = float(task_cfg.get("aiTemperature") or DEFAULT_TEMPERATURE),
		top_p            = float(task_cfg.get("aiTopP") or DEFAULT_TOP_P),
		# cint first: a shape attribute arrives as a string, and "0" is truthy.
		max_tokens       = cint(task_cfg.get("aiMaxTokens")) or DEFAULT_MAX_OUTPUT_TOKENS,
		timeout_seconds  = cint(task_cfg.get("aiTimeout")) or DEFAULT_TIMEOUT_SECONDS,
		response_format  = task_cfg.get("aiResponseFormat", "text") or "text",
		response_schema  = task_cfg.get("aiResponseSchema") or None,
		max_retries      = int(task_cfg.get("aiMaxRetries", DEFAULT_MAX_RETRIES) or DEFAULT_MAX_RETRIES),
		tools            = tool_specs,
		max_tool_calls   = int(task_cfg.get("aiMaxToolCalls", 10) or 10),
		tool_result_max_chars = cint(task_cfg.get("aiToolResultMaxChars")) or None,
		run_token_budget = cint(task_cfg.get("aiRunTokenBudget")) or None,
		run_cost_budget  = frappe.utils.flt(task_cfg.get("aiRunCostBudget")) or None,
		resume_state     = _checkpoint.build_resume_state(resume_payload) if resume_payload else None,
		terminal_tools   = terminal_tools_for(task_cfg),
		tool_choice      = (task_cfg.get("aiToolChoice") or "auto").strip(),
		parallel_tool_calls = cfg_truthy(task_cfg.get("aiParallelToolCalls", 1)),
		thinking_budget_tokens = cint(task_cfg.get("aiThinkingBudgetTokens")),
		loop_compaction_threshold = cint(task_cfg.get("aiLoopCompactionThreshold")),
		loop_compaction_keep_turns = cint(task_cfg.get("aiLoopCompactionKeepTurns")) or 8,
		compaction_model = task_cfg.get("aiCompactionModel") or "",
	)

	context = ExecutorContext(
		context_doctype = instance.context_doctype or "",
		context_docname = instance.context_docname or "",
		instance_name   = instance.name or "",
		initiated_by    = instance.initiated_by or frappe.session.user or "",
		jinja_context   = jinja_ctx,
	)

	# A model whose credentials are known broken gets no new run; a resume continues an existing one.
	if not resume_payload:
		from one_bpmn.ai_agent_registry import model_health

		_refusal = model_health.refuse_new_run(config.model)
		if _refusal:
			_record_ai_failure(task, task_cfg, bpmn_id, ErrorCode.PROVIDER_DISABLED.value, _refusal)
			frappe.logger("one_bpmn").warning(f"AI Agent Task {bpmn_id}: refused - {_refusal}")
			return

	run = None
	if resume_payload:
		try:
			run = frappe.get_doc("AI Agent Run", resume_run)
			from one_bpmn.agents.observability import _CURRENT_RUN_FLAG, attach_resolved_call, record_ai_step

			# The resume runs in a new job, so sub-calls such as compaction need the run named again.
			frappe.flags[_CURRENT_RUN_FLAG] = run.name
			# The answer goes on the Step that made the call; a checkpoint without pending_step gets its own step.
			pending = (resume_payload.get("suspension") or {}).get("pending_call") or {}
			human_result = _checkpoint.build_resume_state(resume_payload)["human_result"]
			attached = attach_resolved_call(
				resume_payload.get("pending_step") or "",
				run,
				pending.get("name") or "",
				pending.get("arguments") or {},
				human_result,
			)
			if not attached:
				record_ai_step(
					run,
					frappe.db.count("AI Agent Step", {"run": run.name}) + 1,
					"tool",
					human_result,
					tool_calls=[{
						"name": pending.get("name") or "",
						"tool_source": "diagram_task",
						"arguments": pending.get("arguments") or {},
						"result": human_result,
						"status": "Success",
					}],
				)
		except Exception:
			frappe.log_error(
				title=f"AI Observability: resume run load error ({bpmn_id})",
				message=frappe.get_traceback(),
			)
	else:
		try:
			from one_bpmn.agents.observability import create_ai_run
			from one_bpmn.processa_engine.engine import get_task_display_name as _get_label

			run = create_ai_run(
				instance, bpmn_id, "task", config,
				bpmn_label=_get_label(task),
				process_model=instance.process_model or "",
				recall_query=recall_query,
				memory_injected_tokens=memory_injected_tokens,
			)
		except Exception:
			frappe.log_error(
				title=f"AI Observability: create_ai_run error ({bpmn_id})",
				message=frappe.get_traceback(),
			)

	exec_start = time.time()

	# Turns seeded from earlier segments are already Steps; count them before the executor runs.
	already_recorded_turns = len((config.resume_state or {}).get("trace") or [])

	# The running agent, for the tool-policy interceptor and as the delegating agent of A2A calls from its tools.
	from one_bpmn.ai_agent_guardrails.tool_policy import reset_current_agent, set_current_agent

	_policy_token = set_current_agent(task_cfg.get("aiAgentConfig"))
	_prev_delegating_agent = getattr(instance, "_a2a_delegating_agent", None)
	instance._a2a_delegating_agent = task_cfg.get("aiAgentConfig")

	# Prompt steps first on a tool-calling run, so steps made inside tool scripts number after them.
	if run and not getattr(run, "stub", False) and tool_specs and not resume_payload:
		try:
			from one_bpmn.agents.observability import record_ai_step as _record_prompt_step

			_record_prompt_step(run, 1, "system", system_prompt)
			_record_prompt_step(run, 2, "user", user_prompt)
		except Exception:
			frappe.log_error(
				title=f"AI Observability: prompt step recording failed ({bpmn_id})",
				message=frappe.get_traceback(),
			)
	try:
		from one_bpmn.processa_engine.agent_runtime import turn_signal

		executor_cls = get_executor(config.backend)
		with turn_signal.live_text_scope(instance):
			result = executor_cls().run(config, context)
	except Exception as exc:
		frappe.log_error(
			title=f"BPMN AI Agent Task: unexpected error ({bpmn_id})",
			message=frappe.get_traceback(),
		)
		_record_ai_failure(task, task_cfg, bpmn_id, "UNEXPECTED_ERROR", "See Frappe Error Log for details.")
		try:
			from one_bpmn.agents.observability import finalize_ai_run_on_exception

			finalize_ai_run_on_exception(run, exc)
		except Exception:
			frappe.log_error(
				title=f"AI Observability: finalize on exception failed ({bpmn_id})",
				message=frappe.get_traceback(),
			)
		return
	finally:
		# Cleared on both paths so this agent's tool grant does not reach the next job in the worker.
		reset_current_agent(_policy_token)
		# Restored, not deleted: an agent nested in another agent's map hands identity back.
		instance._a2a_delegating_agent = _prev_delegating_agent
	exec_latency_ms = int((time.time() - exec_start) * 1000)

	# A stage tool that answers the turn writes the reply to the turn store; the loop's own text is narration.
	if (
		result.error_code == ErrorCode.SUCCESS
		and not isinstance(result.output, dict)
		and getattr(instance, "context_doctype", "") == "Chat Conversation"
	):
		from one_bpmn.processa_engine.agent_runtime.turn_state import get_turn

		_turn_output = get_turn(instance.context_docname).get("output")
		if isinstance(_turn_output, dict) and _turn_output.get("response"):
			result.output = _turn_output["response"]

	try:
		from one_bpmn.agents.observability import finalize_ai_run, record_ai_step

		if run and not getattr(run, "stub", False):
			if tool_specs:
				# One Step per turn; the system and user steps were written before the loop.
				from one_bpmn.agents.observability import record_selector_turns

				source_map = {t.name: "diagram_task" for t in tool_specs}
				record_selector_turns(
					run, result.trace or [], source_map,
					already_recorded=already_recorded_turns,
				)
			else:
				record_ai_step(run, 1, "system", system_prompt)

				usage = result.token_usage if result.error_code == ErrorCode.SUCCESS else None
				# Input tokens and their cache split go on the user step, output tokens on the assistant step.
				record_ai_step(
					run, 2, "user", user_prompt,
					prompt_tokens=usage.prompt_tokens if usage else 0,
					cache_read_tokens=getattr(usage, "cache_read_tokens", 0) if usage else 0,
					cache_write_tokens=getattr(usage, "cache_write_tokens", 0) if usage else 0,
				)
				if result.error_code == ErrorCode.SUCCESS:
					record_ai_step(
						run, 3, "assistant",
						str(result.output or ""),
						completion_tokens=usage.completion_tokens if usage else 0,
						# Failed attempts become their own steps in finalize_ai_run.
						latency_ms=exec_latency_ms - sum(a.latency_ms for a in result.attempts or []),
					)

		# A suspended run stays open until the final answer or a failure.
		if result.error_code != ErrorCode.SUSPENDED:
			finalize_ai_run(
				run, result,
				goal_key=(task_cfg.get("aiGoalOutputKey") or "").strip() or None,
				request_text=user_prompt,
			)

		# Observability survives an aiStopOnError rollback; never inside tests, where it would defeat the rollback.
		if not frappe.flags.in_test:
			frappe.db.commit()
	except Exception:
		frappe.log_error(
			title=f"AI Observability: instrumentation error ({bpmn_id})",
			message=frappe.get_traceback(),
		)

	# A delegated worker that ran out of turns tells its caller the answer is partial.
	if getattr(result, "hit_turn_cap", False) and instance.context_doctype == "A2A Task":
		try:
			from one_bpmn.a2a import delegation

			delegation.stopped_at_limit(
				a2a_task=instance.context_docname,
				reason="turn_cap",
				limit_value=cint(task_cfg.get("aiMaxToolCalls")),
				reached_value=cint(task_cfg.get("aiMaxToolCalls")),
				detail=(
					"The agent used every tool-calling turn it was allowed and never "
					"produced a final answer, so anything it did return is partial."
				),
				instance=instance.name,
				worker_agent=task_cfg.get("aiAgentConfig"),
			)
		except Exception:
			frappe.log_error(
				title=f"AI Agent Task: turn-cap escalation failed ({bpmn_id})",
				message=frappe.get_traceback(),
			)

	if result.error_code == ErrorCode.SUSPENDED:
		# A human or delegated tool call: checkpoint the run and leave the waiting marker the engine parks on.
		from one_bpmn.agents.observability import latest_ordinary_step

		run = _checkpoint.save_checkpoint(
			run,
			instance,
			bpmn_id,
			result.suspension or {},
			system_prompt=system_prompt,
			wf_task_id=str(getattr(task, "id", "") or ""),
			human_row_id="",
			pending_step=latest_ordinary_step(run.name) if run else "",
		)
		pending = (result.suspension or {}).get("pending_call") or {}
		pending_name = pending.get("name") or ""
		label = ""
		try:
			for shape in json.loads(task_cfg.get("aiToolShapes") or "[]"):
				if isinstance(shape, dict) and shape.get("bpmn_id") == pending_name:
					label = shape.get("label") or ""
					break
		except (TypeError, ValueError):
			label = ""
		# waits_on names who owes the answer: a person (default), an A2A agent or an agent sandbox run.
		waiting_marker = {
			"run": run.name,
			"tool": pending_name,
			"label": label,
			"arguments": pending.get("arguments") or {},
		}
		deferred_wait = (result.suspension or {}).get("deferred_wait") or {}
		if deferred_wait.get("a2a_task"):
			waiting_marker["waits_on"] = "a2a"
			waiting_marker["a2a_task"] = deferred_wait["a2a_task"]
			waiting_marker["label"] = label or deferred_wait.get("label") or pending_name
		elif deferred_wait.get("run"):
			# Stored under its own key: "run" already holds this AI Agent Run's name.
			waiting_marker["waits_on"] = "agent_sandbox"
			waiting_marker["agent_sandbox_run"] = deferred_wait["run"]
			waiting_marker["label"] = label or deferred_wait.get("label") or pending_name
		task.data["_bpmn_ai_waiting_human"] = waiting_marker
		if not frappe.flags.in_test:
			frappe.db.commit()
		return

	if result.error_code == ErrorCode.SUCCESS:
		if isinstance(task.data, dict):
			task.data.pop("_bpmn_ai_waiting_human", None)
			# A failure from an earlier pass of a looping map must not mark this answer as failed.
			task.data.pop(f"{bpmn_id}_error_code", None)
			task.data.pop(f"{bpmn_id}_error_message", None)
		output_var = task_cfg.get("aiOutputVariable") or f"{bpmn_id}_output"
		task.data[output_var] = result.output
		# Downstream readers know the shape's own name, so the answer is written under it too.
		task.data[f"{bpmn_id}_output"] = result.output
		_publish_chat_turn_output(instance, result.output)
		if result.token_usage:
			task.data[f"{bpmn_id}_token_usage"] = {
				"prompt_tokens":     result.token_usage.prompt_tokens,
				"completion_tokens": result.token_usage.completion_tokens,
				"total_tokens":      result.token_usage.total_tokens,
			}

		# Each tool's result as {tool}_toolCallResult plus all of them in aiToolCallResults; a resume adds the earlier segments.
		if tool_specs and (result.trace or resume_payload):
			all_results = []
			if resume_payload:
				all_results.extend(_checkpointed_tool_results(resume_payload))
			for turn in result.trace or []:
				for call in turn.get("tool_calls") or []:
					call_result = call.get("result") or ""
					tool_name = call.get("name") or ""
					if not tool_name or str(call_result).startswith("Unknown tool:"):
						continue
					all_results.append({"tool": tool_name, "result": call_result})
			for entry in all_results:
				task.data[f"{entry['tool']}_toolCallResult"] = entry["result"]
			results_var = task_cfg.get("aiToolCallResults") or f"{bpmn_id}_toolCallResults"
			task.data[results_var] = all_results

		write_back_field = task_cfg.get("aiWriteBackField", "")
		if write_back_field and instance.context_doctype and instance.context_docname:
			try:
				frappe.db.set_value(
					instance.context_doctype,
					instance.context_docname,
					write_back_field,
					result.output,
				)
			except Exception:
				frappe.log_error(
					title=f"BPMN AI Agent Task: write-back failed ({bpmn_id})",
					message=frappe.get_traceback(),
				)

		# Memory write: "distilled" runs in a background job, "raw" stores the output, "off" writes nothing.
		write_mode = _memory_write_mode(task_cfg)
		# Eval runs never write memory; cases that need it seed it with memory_write.
		if write_mode != "off" and not frappe.flags.get("eval_origin"):
			try:
				write_target = memory_target or _resolve_memory_target(task_cfg, instance, bpmn_id, task.data)
				if write_target:
					scope, scope_key = write_target
					src = run.name if run and not getattr(run, "stub", False) else None
					# Provenance only: an Agent-scoped memory still keys on agent_element.
					memory_process_model = (
						getattr(instance, "process_model", None) if scope == "Agent" else None
					)
					if raw_user_message and _is_remember_directive(raw_user_message):
						# "remember that..." is a standing convention, stored verbatim and never distilled.
						from one_bpmn.ai_agent_memory.tools import memory_write

						memory_write(
							scope,
							scope_key,
							raw_user_message,
							source_run=src,
							ignore_permissions=True,  # the agent writes its own memory, not the user
							reconcile=True,
							reconcile_ctx={
								"provider_name": config.provider_name,
								"backend": config.backend,
								"model": config.model,
							},
							process_model=memory_process_model,
							user_directed=True,
						)
					elif write_mode == "raw":
						content = _extract_memory_content(result.output, task_cfg.get("aiMemoryContentField", ""))
						if content:
							from one_bpmn.ai_agent_memory.tools import memory_write

							memory_write(
								scope,
								scope_key,
								content,
								dedup_key=(task_cfg.get("aiMemoryDedupKey") or None),
								source_run=src,
								ignore_permissions=True,  # the agent writes its own memory, not the user
								process_model=memory_process_model,
							)
					elif not _ended_without_answer(result.trace):
						# A tool-protocol agent leaves the output empty: distill the person's words and the tool activity.
						memory_src = result.output
						if not str(memory_src or "").strip():
							trace_text = _memory_output_from_trace(result.trace)
							if trace_text:
								_user_text = _turn_user_message(instance, task)
								parts = []
								if _user_text:
									parts.append(f"[User message]\n{_user_text[:3000]}")
								parts.append(f"[Agent tool activity]\n{trace_text}")
								memory_src = "\n\n".join(parts)
						_distill_model = _memory_model(task_cfg, "aiMemoryDistillModel", config.model)
						_reconcile_model = _memory_model(task_cfg, "aiMemoryReconcileModel", config.model)
						frappe.enqueue(
							"one_bpmn.ai_agent_memory.writeback.distill_and_write",
							queue="short",
							now=frappe.flags.in_test,
							agent_output=memory_src,
							agent=(task_cfg.get("aiMemoryAgentElement") or bpmn_id),
							scope=scope,
							scope_key=scope_key,
							# The provider that serves the distill model, which may not be the agent's.
							provider_name=frappe.db.get_value("AI Model", _distill_model, "provider")
							or config.provider_name,
							backend=config.backend,
							model=_distill_model,
							reconcile_model=_reconcile_model,
							reconcile_provider=frappe.db.get_value("AI Model", _reconcile_model, "provider")
							or config.provider_name,
							source_run=src,
							process_model=memory_process_model,
							user=_preference_user(task.data),
							# What the agent was told, so the distiller rejects a fact that only restates it.
							exclude_context="\n\n".join(filter(None, [system_prompt, memory_block])),
						)
			except Exception:
				frappe.log_error(
					title=f"BPMN AI Agent Task: memory write failed ({bpmn_id})",
					message=frappe.get_traceback(),
				)

		cs_backend = task_cfg.get("aiConversationStore") or ""
		# A chat turn is already a Chat Message that the history step reads.
		if cs_backend and getattr(instance, "context_doctype", "") != "Chat Conversation":
			try:
				from one_bpmn.agents.memory.conversation_store import get_conversation_store

				store = get_conversation_store(cs_backend, task=task)
				store.append(instance.name, bpmn_id, {"role": "user", "content": user_prompt})
				store.append(instance.name, bpmn_id, {"role": "assistant", "content": str(result.output or "")})
			except Exception:
				frappe.log_error(
					title=f"BPMN AI Agent Task: conversation store append failed ({bpmn_id})",
					message=frappe.get_traceback(),
				)
	else:
		error_code_name = result.error_code.value
		# The failed run waits for nobody; a marker left from the suspension would re-spawn a dead human task.
		if isinstance(task.data, dict):
			task.data.pop("_bpmn_ai_waiting_human", None)
		frappe.log_error(
			title=f"BPMN AI Agent Task: {error_code_name} ({bpmn_id})",
			message=(
				f"bpmn_id: {bpmn_id}\n"
				f"provider: {config.provider_name}\n"
				f"model: {config.model}\n"
				f"error: {result.error_message}"
			),
		)
		# Without aiStopOnError the flow continues, so gateways still find both output names, as None.
		_record_ai_failure(task, task_cfg, bpmn_id, error_code_name, result.error_message)

		# aiStopOnError raises so the engine loop halts and the instance is marked Errored.
		if task_cfg.get("aiStopOnError"):
			raise Exception(
				f"AI Agent Task '{bpmn_id}' failed: "
				f"{error_code_name} - {result.error_message}"
			)


def terminal_tools_for(task_cfg: dict) -> list:
	"""finalize plus the comma-separated tools the task or its agent names; each ends the turn when called."""
	return list({"finalize", *split_config(task_cfg.get("aiTerminalTools"))})


def bound_memories_to_budget(memories: list, token_budget: int) -> list:
	"""Keep rank-ordered memories while the rendered block fits token_budget; drop the tail.

	A hard ceiling: when even the first memory does not fit, its content is cut to fit.
	"""
	from one_bpmn.agents.memory.conversation_store import DEFAULT_CHARS_PER_TOKEN, estimate_tokens

	if not memories or not token_budget or token_budget <= 0:
		return memories

	header_cost = estimate_tokens({"content": _format_memory_block([])}, DEFAULT_CHARS_PER_TOKEN)
	budget = max(token_budget - header_cost, 0)
	# The "\n- " each bullet adds costs about a token.
	per_item_overhead = 1

	kept = []
	spent = 0
	for m in memories:
		content = str((m or {}).get("content") or "")
		cost = estimate_tokens({"content": content}, DEFAULT_CHARS_PER_TOKEN) + per_item_overhead
		if spent + cost <= budget:
			kept.append(m)
			spent += cost
			continue
		if not kept:
			max_chars = max((budget - per_item_overhead) * DEFAULT_CHARS_PER_TOKEN, 0)
			if max_chars > 0:
				kept.append({**m, "content": content[:max_chars]})
		break
	return kept


def _is_small_talk(message: str) -> bool:
	"""True for an empty message or one whose every word is a greeting or acknowledgement word."""
	words = re.findall(r"[a-z']+", (message or "").strip().lower())
	if not words:
		return True
	return all(w in _SMALL_TALK_WORDS for w in words)


def _is_remember_directive(message: str) -> bool:
	"""True when the message asks the agent to remember a standing convention."""
	return bool(_REMEMBER_RE.search(message or ""))


def _default_memory_scope(task_cfg: dict) -> str:
	"""Blank scope: a Chat agent keeps memory per person (User and Agent), a Background agent shares it (Agent)."""
	config_name = task_cfg.get("aiAgentConfig")
	agent_type = frappe.db.get_value("AI Agent Configuration", config_name, "agent_type") if config_name else None
	return "Agent" if agent_type == "Background" else "User and Agent"


def _resolve_memory_target(task_cfg: dict, instance, bpmn_id: str, task_data: dict | None = None):
	"""(scope, scope_key) for memory from aiMemoryScope (Agent, Process or Entity), or None when no key can be built.

	A "User and X" scope adds the session user to X's key; a Guest falls back to the shared X scope.
	"""
	scope = (task_cfg.get("aiMemoryScope") or "").strip() or _default_memory_scope(task_cfg)
	user = None
	if scope.startswith("User and "):
		scope = scope[len("User and ") :]
		user = frappe.session.user if frappe.session.user != "Guest" else None

	if scope == "Agent":
		agent_element = task_cfg.get("aiMemoryAgentElement") or bpmn_id
		if not agent_element:
			return None
		key = {"agent_element": agent_element}
	elif scope == "Process":
		process_model = getattr(instance, "process_model", None)
		if not process_model:
			return None
		key = {"process": process_model}
	elif scope == "Entity":
		if task_data and "memory_reference_name" in task_data:
			reference_doctype = task_data.get("memory_reference_doctype")
			reference_name = task_data.get("memory_reference_name")
		else:
			reference_doctype = getattr(instance, "context_doctype", None)
			reference_name = getattr(instance, "context_docname", None)
		if not (reference_doctype and reference_name):
			return None
		key = {"reference_doctype": reference_doctype, "reference_name": reference_name}
	else:
		return None

	if user:
		key["user"] = user
	elif scope == "Agent":
		return (scope, key["agent_element"])
	elif scope == "Process":
		return (scope, key["process"])
	return (scope, key)


def _preference_user(task_data: dict | None) -> str | None:
	"""The session user when the task data keys memory by a business record; None for a Guest."""
	if not (task_data or {}).get("memory_reference_name"):
		return None
	user = frappe.session.user
	return user if user and user != "Guest" else None


def _format_memory_block(memories: list) -> str:
	"""Render memories as the delimited block for the dynamic prompt layer, headed by MEMORY_BLOCK_HEADER."""
	lines = [MEMORY_BLOCK_HEADER, _MEMORY_BLOCK_PROVENANCE]
	for m in memories:
		content = (m.get("content") or "").strip()
		if content:
			lines.append(f"- {content}")
	return "\n".join(lines)


def _turn_user_message(instance, task) -> str:
	"""The person's own words for a chat turn, from task data or the turn store; empty off the chat path."""
	if getattr(instance, "context_doctype", "") != "Chat Conversation":
		return ""
	if not getattr(instance, "context_docname", ""):
		return ""

	from one_bpmn.ai_agent_memory.text_clean import strip_html

	data = getattr(task, "data", None)
	if isinstance(data, dict):
		text = str(data.get("user_text") or "").strip()
		if text:
			return strip_html(text)
	try:
		from one_bpmn.processa_engine.agent_runtime.turn_state import get_turn

		return strip_html(str((get_turn(instance.context_docname) or {}).get("user_text") or ""))
	except Exception:
		frappe.log_error(title="BPMN AI Agent Task: turn store read failed", message=frappe.get_traceback())
		return ""


def _platform_history(instance, task_cfg: dict, raw_user_message: str) -> tuple[list, str]:
	"""(prior messages, facts block) for a chat turn, also written to the turn store for tool scripts."""
	from one_bpmn.agents.memory.turn_context import conversation_of, established_block, load_history
	from one_bpmn.processa_engine.agent_runtime.turn_state import update_turn

	conversation = conversation_of(instance)
	if not conversation:
		return [], ""
	history = load_history(
		conversation,
		limit=cint(task_cfg.get("aiContextMaxMessages")),
		current_message=raw_user_message,
	)
	update_turn(conversation, chat_history=history)
	return history, established_block(conversation)


def _extract_memory_content(output, content_field: str) -> str:
	"""The configured field of a dict output, else the whole output as text."""
	if content_field and isinstance(output, dict):
		return str(output.get(content_field, "") or "")
	return str(output or "")


def _ended_without_answer(trace) -> bool:
	"""True when the turn called a redirect or clarify tool."""
	return any(
		call.get("name") in _NON_ANSWER_TOOLS for turn in trace or [] for call in turn.get("tool_calls") or []
	)


def _memory_output_from_trace(trace) -> str:
	"""Distillable text from the trace's tool calls, newest turn first, for an agent whose answer lives in tools."""
	parts = []
	for turn in reversed(trace or []):
		for call in turn.get("tool_calls") or []:
			name = call.get("name") or ""
			call_result = call.get("result") or ""
			if str(call_result).startswith("Unknown tool:"):
				continue
			args = call.get("arguments")
			rendered = ""
			if args:
				try:
					rendered = json.dumps(args, default=str)
				except (TypeError, ValueError):
					rendered = str(args)
			payload = " ".join(p for p in (rendered, str(call_result)) if p).strip()
			if payload:
				parts.append(f"{name}: {payload[:2000]}")
	return "\n".join(parts)


def _memory_write_mode(task_cfg: dict) -> str:
	""""off", "raw" or "distilled": aiMemoryWriteMode, else "distilled" when the older aiMemoryAutoWrite is on."""
	mode = str(task_cfg.get("aiMemoryWriteMode") or "").strip().lower()
	if mode in ("off", "raw", "distilled"):
		return mode
	return "distilled" if cfg_truthy(task_cfg.get("aiMemoryAutoWrite")) else "off"


def _memory_model(task_cfg: dict, key: str, fallback: str | None) -> str | None:
	"""The memory model: the task's (agent config already overlaid), then Processa Settings, then fallback."""
	from one_bpmn.ai_agent_memory.model_resolution import resolve_memory_model

	return resolve_memory_model(task_cfg.get(key), _MEMORY_MODEL_SETTINGS.get(key), fallback)


def _checkpointed_tool_results(resume_payload: dict) -> list:
	"""Tool results before the final resume, in call order: completed turns, deferred results, then the human's answer."""
	from one_bpmn.processa_engine.agent_runtime.checkpoint import human_result_str

	suspension = resume_payload.get("suspension") or {}
	out = []

	def _add(name, content):
		if name and not str(content or "").startswith("Unknown tool:"):
			out.append({"tool": name, "result": content or ""})

	for entry in suspension.get("transcript") or []:
		if entry.get("role") == "tool_results":
			for r in entry.get("results") or []:
				_add(r.get("name"), r.get("content"))
	for r in suspension.get("deferred_results") or []:
		_add(r.get("name"), r.get("content"))
	pending = suspension.get("pending_call") or {}
	_add(pending.get("name"), human_result_str(resume_payload.get("pending_result")))
	return out


def _publish_chat_turn_output(instance, output) -> None:
	"""Send an AI task's output to a chat request waiting on this turn; only for a Chat Conversation."""
	if getattr(instance, "context_doctype", None) != "Chat Conversation":
		return
	name = getattr(instance, "name", None)
	if not name:
		return
	try:
		from one_bpmn.processa_engine.agent_runtime import turn_signal

		turn_signal.publish_event(name, {"type": TURN_OUTPUT_EVENT, "output": output})
	except Exception:
		# Progress is an accelerator; the reply is still on the message row.
		frappe.log_error(title="BPMN AI Agent Task: turn output publish failed", message=frappe.get_traceback())


def _record_ai_failure(task, task_cfg: dict, bpmn_id: str, error_code: str, error_message: str) -> None:
	"""Write the error code and message, and blank both output names so the previous turn's answer is gone."""
	task.data[f"{bpmn_id}_error_code"] = error_code
	task.data[f"{bpmn_id}_error_message"] = error_message
	task.data[task_cfg.get("aiOutputVariable") or f"{bpmn_id}_output"] = None
	task.data[f"{bpmn_id}_output"] = None
