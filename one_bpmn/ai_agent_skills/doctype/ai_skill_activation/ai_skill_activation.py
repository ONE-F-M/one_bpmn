# Copyright (c) 2026, kartiksharma9319@gmail.com and contributors
# For license information, please see license.txt

# import frappe
from frappe.model.document import Document


class AISkillActivation(Document):
	# begin: auto-generated types
	# This code is auto-generated. Do not modify anything in this block.

	from typing import TYPE_CHECKING

	if TYPE_CHECKING:
		from frappe.types import DF

		agent_configuration: DF.Link | None
		agent_run: DF.Link | None
		conversation: DF.Link | None
		loaded_at: DF.Datetime | None
		prompt_hash: DF.Data | None
		skill: DF.Link
		turn_loaded: DF.Int
		turn_unloaded: DF.Int
		unloaded_at: DF.Datetime | None
	# end: auto-generated types
	pass
