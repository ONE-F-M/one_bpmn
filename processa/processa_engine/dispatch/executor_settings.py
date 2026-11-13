# Copyright (c) 2026, one-fm and contributors
"""The executor settings an AI Agent Task's config asks for, shared by the dispatcher, the task selector and the dry run."""

import frappe
import frappe.utils
from frappe.utils import cint

from processa.processa_engine.dispatch.common import cfg_truthy, split_config


def executor_config(
	task_cfg: dict,
	system_prompt: str,
	user_prompt: str,
	messages: list | None = None,
	tools: list | None = None,
	resume_state: dict | None = None,
):
	"""The executor settings an AI Agent Task's config asks for, around the prompts, history and tools given."""
	from processa.processa_engine.agent_runtime.executor import (
		DEFAULT_MAX_OUTPUT_TOKENS,
		DEFAULT_MAX_RETRIES,
		DEFAULT_TEMPERATURE,
		DEFAULT_TIMEOUT_SECONDS,
		DEFAULT_TOP_P,
		ExecutorConfig,
	)

	return ExecutorConfig(
		backend=task_cfg.get("aiBackend", "direct_api"),
		# A shape may name only the model; its provider is on the model's record.
		provider_name=task_cfg.get("aiProvider", "")
		or frappe.db.get_value("AI Model", task_cfg.get("aiModel", ""), "provider")
		or "",
		agent_config_name=task_cfg.get("aiAgentConfig", ""),
		model=task_cfg.get("aiModel", ""),
		system_prompt=system_prompt,
		user_prompt=user_prompt,
		messages=messages or [],
		temperature=float(task_cfg.get("aiTemperature") or DEFAULT_TEMPERATURE),
		top_p=float(task_cfg.get("aiTopP") or DEFAULT_TOP_P),
		# cint first: a shape attribute arrives as a string, and "0" is truthy.
		max_tokens=cint(task_cfg.get("aiMaxTokens")) or DEFAULT_MAX_OUTPUT_TOKENS,
		timeout_seconds=cint(task_cfg.get("aiTimeout")) or DEFAULT_TIMEOUT_SECONDS,
		response_format=task_cfg.get("aiResponseFormat", "text") or "text",
		response_schema=task_cfg.get("aiResponseSchema") or None,
		max_retries=int(task_cfg.get("aiMaxRetries", DEFAULT_MAX_RETRIES) or DEFAULT_MAX_RETRIES),
		tools=tools,
		max_tool_calls=int(task_cfg.get("aiMaxToolCalls", 10) or 10),
		tool_result_max_chars=cint(task_cfg.get("aiToolResultMaxChars")) or None,
		run_token_budget=cint(task_cfg.get("aiRunTokenBudget")) or None,
		run_cost_budget=frappe.utils.flt(task_cfg.get("aiRunCostBudget")) or None,
		resume_state=resume_state,
		terminal_tools=terminal_tools_for(task_cfg),
		tool_choice=(task_cfg.get("aiToolChoice") or "auto").strip(),
		parallel_tool_calls=cfg_truthy(task_cfg.get("aiParallelToolCalls", 1)),
		thinking_budget_tokens=cint(task_cfg.get("aiThinkingBudgetTokens")),
		loop_compaction_threshold=cint(task_cfg.get("aiLoopCompactionThreshold")),
		loop_compaction_keep_turns=cint(task_cfg.get("aiLoopCompactionKeepTurns")) or 8,
		compaction_model=task_cfg.get("aiCompactionModel") or "",
	)


def terminal_tools_for(task_cfg: dict) -> list:
	"""finalize plus the comma-separated tools the task or its agent names; each ends the turn when called."""
	return list({"finalize", *split_config(task_cfg.get("aiTerminalTools"))})
