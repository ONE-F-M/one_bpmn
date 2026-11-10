# Copyright (c) 2026, one-fm and contributors
# For license information, please see license.txt

from frappe.model.document import Document


class AIAgentStep(Document):
	# begin: auto-generated types
	# This code is auto-generated. Do not modify anything in this block.

	from typing import TYPE_CHECKING

	if TYPE_CHECKING:
		from frappe.types import DF
		from one_bpmn.ai_agent_observability.doctype.ai_agent_tool_call.ai_agent_tool_call import AIAgentToolCall

		cache_read_cost: DF.Currency
		cache_read_tokens: DF.Int
		cache_write_cost: DF.Currency
		cache_write_tokens: DF.Int
		completion_tokens: DF.Int
		content: DF.LongText | None
		cost: DF.Currency
		ended_at: DF.Datetime | None
		error_code: DF.Data | None
		error_message: DF.LongText | None
		input_cost: DF.Currency
		is_expected_error: DF.Check
		latency_ms: DF.Int
		model_latency_ms: DF.Int
		output_cost: DF.Currency
		prompt_tokens: DF.Int
		role: DF.Literal["system", "user", "assistant", "tool"]
		run: DF.Link
		started_at: DF.Datetime | None
		step_index: DF.Int
		step_kind: DF.Literal["", "prompt", "model_call", "tool_turn", "sub_call"]
		tool_calls: DF.Table[AIAgentToolCall]
	# end: auto-generated types
	pass
