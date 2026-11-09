# Copyright (c) 2026, one-fm and contributors
# For license information, please see license.txt

from frappe.model.document import Document


class ChatSessionStateEntry(Document):
	# begin: auto-generated types
	# This code is auto-generated. Do not modify anything in this block.

	from typing import TYPE_CHECKING

	if TYPE_CHECKING:
		from frappe.types import DF

		key: DF.Data
		parent: DF.Data
		parentfield: DF.Data
		parenttype: DF.Data
		value: DF.LongText | None
	# end: auto-generated types
	# The index on `key` — which is what makes "find conversations holding this
	# key" a filter rather than a table scan, and therefore the whole reason
	# these are rows and not one JSON blob — comes from search_index on the
	# field itself. It is NOT added here: `key` is a MariaDB reserved word, and
	# a hand-rolled ALTER does not quote it.
	pass
