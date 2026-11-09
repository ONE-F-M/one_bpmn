# Copyright (c) 2026, one-fm and contributors
# For license information, please see license.txt

from frappe.model.document import Document


class AgentSandboxTraceCall(Document):
	# begin: auto-generated types
	# This code is auto-generated. Do not modify anything in this block.

	from typing import TYPE_CHECKING

	if TYPE_CHECKING:
		from frappe.types import DF

		action: DF.Data | None
		commit_sha: DF.Data | None
		ended_at: DF.Datetime | None
		error_message: DF.SmallText | None
		git_ms: DF.Int
		http_ms: DF.Int
		parent: DF.Data
		parentfield: DF.Data
		parenttype: DF.Data
		pr_ms: DF.Int
		pr_url: DF.Data | None
		run: DF.Link | None
		sandbox_ms: DF.Int
		sequence: DF.Int
		started_at: DF.Datetime | None
		state: DF.Data | None
		summary: DF.SmallText | None
		test_ms: DF.Int
		tool_ms: DF.Int
	# end: auto-generated types
	pass
