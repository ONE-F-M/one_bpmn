# Copyright (c) 2026, one-fm and contributors
# For license information, please see license.txt

from frappe.model.document import Document


class AIAgentRun(Document):
	# begin: auto-generated types
	# This code is auto-generated. Do not modify anything in this block.

	from typing import TYPE_CHECKING

	if TYPE_CHECKING:
		from frappe.types import DF

		agent_configuration: DF.Link | None
		agent_latency_ms: DF.Int
		backend: DF.Data | None
		bpmn_id: DF.Data
		bpmn_label: DF.Data | None
		checkpoint: DF.LongText | None
		completion_basis: DF.SmallText | None
		correlation_id: DF.Data | None
		duration_ms: DF.Int
		element_type: DF.Literal["task", "subprocess"]
		ended_at: DF.Datetime | None
		error_code: DF.Data | None
		error_message: DF.LongText | None
		estimated_cost: DF.Currency
		eval_case: DF.Link | None
		eval_run: DF.Link | None
		final_output: DF.LongText | None
		goal_completion: DF.Literal["Unknown", "Achieved", "Not Achieved"]
		human_wait_ms: DF.Int
		instance: DF.Link | None
		max_retries: DF.Int
		memory_injected_tokens: DF.Int
		model: DF.Data | None
		no_terminal_tool: DF.Check
		origin: DF.Literal["production", "eval"]
		parent_run: DF.Link | None
		pending_human_task: DF.Data | None
		process_model: DF.Link | None
		prompt_hash: DF.Data | None
		provider: DF.Link | None
		queue_wait_ms: DF.Int
		recall_query: DF.SmallText | None
		retry_count: DF.Int
		started_at: DF.Datetime
		status: DF.Literal["Running", "Suspended", "Success", "Error"]
		suspended_at: DF.Datetime | None
		tool_calls: DF.Code | None
		total_cache_read_cost: DF.Currency
		total_cache_read_tokens: DF.Int
		total_cache_write_cost: DF.Currency
		total_cache_write_tokens: DF.Int
		total_completion_tokens: DF.Int
		total_input_cost: DF.Currency
		total_output_cost: DF.Currency
		total_prompt_tokens: DF.Int
		total_tokens: DF.Int
	# end: auto-generated types
	pass
