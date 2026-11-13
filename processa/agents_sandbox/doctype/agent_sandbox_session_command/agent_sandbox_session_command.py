# Copyright (c) 2026, one-fm and contributors
# For license information, please see license.txt

from frappe.model.document import Document


class AgentSandboxSessionCommand(Document):
	# begin: auto-generated types
	# This code is auto-generated. Do not modify anything in this block.

	from typing import TYPE_CHECKING

	if TYPE_CHECKING:
		from frappe.types import DF

		action: DF.Data | None
		delivered_at: DF.Datetime | None
		done_at: DF.Datetime | None
		kind: DF.Literal["tool", "run_tests", "finalize", "close"]
		payload: DF.Code | None
		result: DF.Code | None
		run: DF.Link | None
		seq: DF.Int
		session: DF.Link
		state: DF.Literal["pending", "delivered", "done", "failed"]
	# end: auto-generated types
	pass
