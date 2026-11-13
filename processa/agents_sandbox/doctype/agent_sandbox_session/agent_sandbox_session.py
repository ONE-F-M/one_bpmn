# Copyright (c) 2026, one-fm and contributors
# For license information, please see license.txt

from frappe.model.document import Document


class AgentSandboxSession(Document):
	# begin: auto-generated types
	# This code is auto-generated. Do not modify anything in this block.

	from typing import TYPE_CHECKING

	if TYPE_CHECKING:
		from frappe.types import DF

		agent_name: DF.Data | None
		attempt: DF.Int
		caller_instance: DF.Link | None
		closed_at: DF.Datetime | None
		error_message: DF.SmallText | None
		execution_name: DF.Data | None
		git_branch: DF.Data | None
		idle_timeout_seconds: DF.Int
		last_heartbeat: DF.Datetime | None
		last_seq: DF.Int
		register_token_hash: DF.Data | None
		registered_at: DF.Datetime | None
		session_key: DF.Password | None
		started_at: DF.Datetime | None
		state: DF.Literal["queued", "starting", "registered", "active", "closing", "closed", "lost", "cancelled"]
		target_app: DF.Data | None
		work_item: DF.Data | None
	# end: auto-generated types
	pass
