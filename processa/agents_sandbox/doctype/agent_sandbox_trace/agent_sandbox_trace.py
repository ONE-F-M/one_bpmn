# Copyright (c) 2026, one-fm and contributors
# For license information, please see license.txt

from frappe.model.document import Document


class AgentSandboxTrace(Document):
	# begin: auto-generated types
	# This code is auto-generated. Do not modify anything in this block.

	from typing import TYPE_CHECKING

	if TYPE_CHECKING:
		from frappe.types import DF
		from processa.agents_sandbox.doctype.agent_sandbox_trace_call.agent_sandbox_trace_call import AgentSandboxTraceCall

		agent_name: DF.Data | None
		call_count: DF.Int
		caller_instance: DF.Link | None
		calls: DF.Table[AgentSandboxTraceCall]
		edit_count: DF.Int
		ended_at: DF.Datetime | None
		failed_calls: DF.Int
		git_branch: DF.Data | None
		git_ms: DF.Int
		http_ms: DF.Int
		last_commit_sha: DF.Data | None
		last_error: DF.SmallText | None
		pr_ms: DF.Int
		pr_url: DF.Data | None
		repeat_edits: DF.Int
		sandbox_ms: DF.Int
		started_at: DF.Datetime | None
		state: DF.Literal["running", "finished"]
		target_app: DF.Data | None
		test_ms: DF.Int
		test_runs: DF.Int
		tool_ms: DF.Int
		work_item: DF.Data | None
	# end: auto-generated types
	pass
