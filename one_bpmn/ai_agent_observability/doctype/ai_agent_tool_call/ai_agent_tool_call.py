# Copyright (c) 2026, one-fm and contributors
# For license information, please see license.txt

from frappe.model.document import Document


class AIAgentToolCall(Document):
	# begin: auto-generated types
	# This code is auto-generated. Do not modify anything in this block.

	from typing import TYPE_CHECKING

	if TYPE_CHECKING:
		from frappe.types import DF

		artifact_file: DF.Link | None
		outcome: DF.LongText | None
		parent: DF.Data
		parentfield: DF.Data
		parenttype: DF.Data
		status: DF.Literal["Success", "Error", "Denied"]
		tool_args: DF.JSON | None
		tool_artifact: DF.LongText | None
		tool_name: DF.Data
		tool_result: DF.LongText | None
		tool_source: DF.Literal["diagram_task", "registry_tool"]
	# end: auto-generated types
	pass
