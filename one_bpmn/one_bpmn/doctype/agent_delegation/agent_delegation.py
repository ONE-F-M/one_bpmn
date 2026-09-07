# Copyright (c) 2026, one-fm and contributors
# For license information, please see license.txt
"""One delegation, as a thing you can look at.

A delegation used to exist only as an A2A Task row, which knows who was asked
but not what the work was about: nothing tied the delegating instance, the
task, the worker's instance and the document being worked on together. This
record is that tie, and it is what a process owner opens to see which agent is
on which item and how far along it is.

It is written by ``agents/a2a/delegation.py`` and read-only in the UI — every
field is derived from the run, so an edited copy would only ever be wrong.
"""

from frappe.model.document import Document


class AgentDelegation(Document):
	pass
