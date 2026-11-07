# Copyright (c) 2025, ONE FM and contributors
# For license information, please see license.txt

from frappe.utils.nestedset import NestedSet


class Process(NestedSet):
	# begin: auto-generated types
	# This code is auto-generated. Do not modify anything in this block.

	from typing import TYPE_CHECKING

	if TYPE_CHECKING:
		from frappe.types import DF
		from one_bpmn.processa_engine.doctype.process_doctype.process_doctype import ProcessDoctype
		from one_bpmn.processa_engine.doctype.process_role.process_role import ProcessRole
		from one_bpmn.processa_engine.doctype.processes.processes import Processes

		backend_code_removal_notes: DF.SmallText | None
		backend_code_removal_status: DF.Literal["Not Started", "Removed on BA", "Removed on Production", "Migrated"]
		ctc_requires_approval: DF.Check
		depends_on: DF.TableMultiSelect[Processes]
		description: DF.SmallText
		is_generic: DF.Check
		is_group: DF.Check
		is_required_for: DF.TableMultiSelect[Processes]
		lft: DF.Int
		old_parent: DF.Link | None
		parent_process: DF.Link | None
		predecessor_count: DF.Int
		process_creation_request: DF.Link | None
		process_doctypes: DF.Table[ProcessDoctype]
		process_name: DF.Data
		process_owner: DF.Link
		process_owner_name: DF.Data | None
		rgt: DF.Int
		roles: DF.Table[ProcessRole]
		successor_count: DF.Int
	# end: auto-generated types
	nsm_parent_field = "parent_process"

	def before_save(self):
		self.predecessor_count = len(self.depends_on or [])
		self.successor_count = len(self.is_required_for or [])
