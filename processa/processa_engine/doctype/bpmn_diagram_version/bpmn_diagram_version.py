# Copyright (c) 2026, kartiksharma9319@gmail.com and contributors
# For license information, please see license.txt

from frappe.model.document import Document


class BPMNDiagramVersion(Document):
	# begin: auto-generated types
	# This code is auto-generated. Do not modify anything in this block.

	from typing import TYPE_CHECKING

	if TYPE_CHECKING:
		from frappe.types import DF

		bpmn_xml: DF.Code | None
		group_key: DF.Data | None
		is_named: DF.Check
		model: DF.Link
		process_name: DF.Data | None
		snapshot_type: DF.Literal["auto", "named", "restored"]
		version_name: DF.Data | None
	# end: auto-generated types
	pass
