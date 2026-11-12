# Copyright (c) 2026, one-fm and contributors
"""Preview and dry run of an AI Agent Task from the editor.

Both work on the diagram as it stands in the editor, unsaved edits included. The dry run sends one
sample message to the model with stubbed tools and writes no AI Agent Run, step or chat message.
"""

import json

import frappe
from frappe import _
from jinja2.sandbox import SandboxedEnvironment

from one_bpmn.ai_agent_registry.provisioning.agent_config_resolver import resolve_dispatch_overrides
from one_bpmn.ai_agent_registry.provisioning.context_assembler import (
	build_dynamic_preamble,
	build_static_context,
	drop_duplicated_instructions,
	load_agent_behaviour,
)
from one_bpmn.ai_agent_skills.skill_tools import get_skill_tools
from one_bpmn.ai_agent_skills.tools.shape_tools import compile_shape_tools
from one_bpmn.processa_engine.agent_runtime.executor import ExecutorContext, get_executor
from one_bpmn.processa_engine.agent_runtime.llm_types import ToolSpec, build_parameter_schema
from one_bpmn.processa_engine.compiler.agent_tools import resolve_ai_agent_tool_shapes
from one_bpmn.processa_engine.compiler.extensions import extract_service_task_config
from one_bpmn.processa_engine.compiler.prepare import sanitize_bpmn_xml

# Unsaved form values that replace the shape's and the linked configuration's own.
FORM_KEYS = (
	"aiAgentConfig",
	"aiBackend",
	"aiProvider",
	"aiModel",
	"aiSystemPrompt",
	"aiUserPrompt",
	"aiTemperature",
	"aiTopP",
	"aiMaxTokens",
	"aiTimeout",
	"aiMaxRetries",
	"aiResponseFormat",
	"aiResponseSchema",
)

# Templates here arrive with the request, so they render with no Frappe globals at all.
REQUEST_JINJA = SandboxedEnvironment()

DEFAULT_SAMPLE_RESULT = json.dumps({"dry_run": True, "note": "This tool was not executed."})


def preview_task(
	bpmn_xml: str, bpmn_id: str, form=None, sample_variables=None, sample_message: str = ""
) -> dict:
	"""The system prompt, user prompt and tools the model would receive for one sample turn."""
	task_cfg = _task_config(bpmn_xml, bpmn_id, form)
	system_prompt, user_prompt, _ctx = _prompts(task_cfg, sample_variables, sample_message)
	tools, human = _tools(task_cfg, None)
	return {
		"system_prompt": system_prompt,
		"user_prompt": user_prompt,
		"tools": [
			{
				"name": tool.name,
				"description": tool.description,
				"parameters": build_parameter_schema(tool),
				"human": tool.name in human,
			}
			for tool in tools
		],
	}


def dry_run_task(
	bpmn_xml: str,
	bpmn_id: str,
	form=None,
	sample_variables=None,
	sample_message: str = "",
	sample_results=None,
) -> dict:
	"""Run one sample turn through the executor; tools return their sample result instead of running."""
	from one_bpmn.ai_agent_guardrails.tool_policy import reset_current_agent, set_current_agent

	# Importing the executor modules registers their backends.
	from one_bpmn.processa_engine.agent_runtime import antigravity, direct_api
	from one_bpmn.processa_engine.dispatch.executor_settings import executor_config

	task_cfg = _task_config(bpmn_xml, bpmn_id, form)
	system_prompt, user_prompt, jinja_ctx = _prompts(task_cfg, sample_variables, sample_message)
	tools, _human = _tools(task_cfg, frappe.parse_json(sample_results or "{}") or {})
	config = executor_config(task_cfg, system_prompt, user_prompt, tools=tools or None)
	context = ExecutorContext(initiated_by=frappe.session.user, jinja_context=jinja_ctx)

	policy_token = set_current_agent(task_cfg.get("aiAgentConfig"))
	try:
		result = get_executor(config.backend)().run(config, context)
	finally:
		reset_current_agent(policy_token)

	return {
		"system_prompt": system_prompt,
		"user_prompt": user_prompt,
		"output": result.output,
		"error_code": result.error_code.value,
		"error_message": result.error_message,
		"turns": [_turn(record) for record in result.trace],
	}


def _task_config(bpmn_xml: str, bpmn_id: str, form) -> dict:
	"""The task's compiled config with its Tools box resolved, then the linked configuration, then the form."""
	sanitized = sanitize_bpmn_xml(bpmn_xml or "")
	extensions = extract_service_task_config(sanitized)
	resolve_ai_agent_tool_shapes(sanitized, extensions)
	task_cfg = extensions.get(bpmn_id)
	if not task_cfg or task_cfg.get("serviceType") != "ai_agent":
		frappe.throw(_("{0} is not an AI Agent Task in this diagram.").format(bpmn_id))

	form = {key: value for key, value in (frappe.parse_json(form or "{}") or {}).items() if key in FORM_KEYS}
	config_name = form.get("aiAgentConfig") or task_cfg.get("aiAgentConfig")
	if config_name:
		frappe.has_permission("AI Agent Configuration", "read", config_name, throw=True)
	return {**task_cfg, **resolve_dispatch_overrides(config_name), **form}


def _prompts(task_cfg: dict, sample_variables, sample_message: str) -> tuple:
	"""Render both prompts the way the dispatcher does, with sample variables standing in for live data."""
	sample = frappe.parse_json(sample_variables or "{}") or {}
	if not isinstance(sample, dict):
		frappe.throw(_("Sample variables must be a JSON object."))
	jinja_ctx = {"doc": frappe._dict(sample.get("doc") or {}), "instance": frappe._dict(), **sample}

	behaviour = load_agent_behaviour(task_cfg["aiAgentConfig"]) if task_cfg.get("aiAgentConfig") else {}
	system_prompt = build_static_context(
		system_prompt=_render(task_cfg.get("aiSystemPrompt"), jinja_ctx, _("System Prompt")),
		examples=behaviour.get("examples"),
		guardrails=behaviour.get("guardrails"),
		skills=behaviour.get("enabled_skills"),
	)
	user_prompt = _render(task_cfg.get("aiUserPrompt"), jinja_ctx, _("User Prompt"))
	if sample_message:
		user_prompt = build_dynamic_preamble(instructions=user_prompt, user_prompt=sample_message)
	return system_prompt, drop_duplicated_instructions(system_prompt, user_prompt), jinja_ctx


def _render(template: str | None, jinja_ctx: dict, label: str) -> str:
	if not template:
		return ""
	try:
		return REQUEST_JINJA.from_string(template).render(jinja_ctx)
	except Exception as exc:
		frappe.throw(_("The {0} does not render with these sample variables: {1}").format(label, exc))


def _tools(task_cfg: dict, sample_results) -> tuple:
	"""The tools the model would see, each answering with its sample result, and the names of the human ones."""
	built = compile_shape_tools(task_cfg.get("aiToolShapes"), None)
	if task_cfg.get("aiAgentConfig"):
		built += get_skill_tools(task_cfg["aiAgentConfig"])
	results = sample_results or {}
	tools = [
		ToolSpec(
			fn=_sample_result(results.get(tool.name)),
			name=tool.name,
			description=tool.description,
			parameters=tool.parameters,
			required=tool.required,
		)
		for tool in built
	]
	return tools, {tool.name for tool in built if tool.human}


def _sample_result(declared):
	def fn(**kwargs):
		if declared is None:
			return DEFAULT_SAMPLE_RESULT
		return declared if isinstance(declared, str) else json.dumps(declared)

	return fn


def _turn(record: dict) -> dict:
	"""One trace turn; the executor hands each TurnRecord back as a dict."""
	return {
		"content": record.get("content") or "",
		"tool_calls": [
			{"name": call.get("name"), "arguments": call.get("arguments"), "result": call.get("result")}
			for call in record.get("tool_calls") or []
		],
	}
