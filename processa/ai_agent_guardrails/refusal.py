# Copyright (c) 2026, one-fm and contributors
# For license information, please see license.txt
"""
The one exception type that means "we decided not to do this".

WHY THIS EXISTS
---------------
15.3 taught the engine that a rate-limit refusal is a *decision*, not a fault:
without that, the process instance was marked Errored and the user was handed a
reference id for a failure that never happened. The engine learned it by name —
``isinstance(in_flight, RateLimited)``.

Injection screening now needs exactly the same treatment for a Block, and so
will every control after it. Teaching the engine a second name, then a third,
puts the security module's class list inside the workflow engine and guarantees
the next control forgets to register itself and silently halts instances again.

So the engine is taught the CATEGORY instead. Anything a security control raises
to refuse a turn derives from :class:`AgentRefusal`, and the engine's single
check covers all of them — including the ones not written yet.

``RateLimited`` keeps its own name and its own module; it simply derives from
this now. Existing ``except RateLimited`` handlers are unaffected.
"""

from __future__ import annotations

import frappe


class AgentRefusal(frappe.ValidationError):
	"""A control declined this turn on purpose.

	Carries a message meant for the person who typed it, so the chat surface can
	show the reason verbatim rather than replacing it with a reference id.

	Raise it the Frappe way — ``frappe.throw(reason, AgentRefusal)`` — or via a
	subclass that names the specific control.
	"""
