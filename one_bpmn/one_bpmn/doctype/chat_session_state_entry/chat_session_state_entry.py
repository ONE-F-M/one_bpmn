# Copyright (c) 2026, one-fm and contributors
# For license information, please see license.txt

from frappe.model.document import Document


class ChatSessionStateEntry(Document):
	# The index on `key` — which is what makes "find conversations holding this
	# key" a filter rather than a table scan, and therefore the whole reason
	# these are rows and not one JSON blob — comes from search_index on the
	# field itself. It is NOT added here: `key` is a MariaDB reserved word, and
	# a hand-rolled ALTER does not quote it.
	pass
