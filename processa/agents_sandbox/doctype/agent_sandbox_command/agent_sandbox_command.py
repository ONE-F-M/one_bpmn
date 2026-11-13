# Copyright (c) 2026, one-fm and contributors
# For license information, please see license.txt

from frappe.model.document import Document


class AgentSandboxCommand(Document):
	# begin: auto-generated types
	# This code is auto-generated. Do not modify anything in this block.

	from typing import TYPE_CHECKING

	if TYPE_CHECKING:
		from frappe.types import DF

		action: DF.Data | None
		duration_ms: DF.Int
		ended_at: DF.Datetime | None
		error_tail: DF.SmallText | None
		parent: DF.Data
		parentfield: DF.Data
		parenttype: DF.Data
		sequence: DF.Int
		started_at: DF.Datetime | None
		status: DF.Literal["ok", "error"]
		summary: DF.SmallText | None
	# end: auto-generated types
	pass
