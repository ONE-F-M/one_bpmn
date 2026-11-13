import frappe

CONVERSATION = "Chat Conversation"
MESSAGE = "Chat Message"


def execute():
	"""Hand each conversation back to the person who actually had it.

	Conversations opened through the front end were inserted as Administrator
	while the person who was talking was recorded only as a participant. Now
	that visibility follows the owner, those rows would be visible to System
	Manager alone — including to the person whose conversation it is.

	Only a conversation with exactly one real participant is reassigned. With
	none, or with several, there is no way to tell whose it was, and leaving it
	with Administrator keeps it private rather than guessing it into the wrong
	inbox.
	"""
	candidates = frappe.db.sql(
		"""
		select c.name, min(p.user) as person, count(distinct p.user) as people
		from `tab{conversation}` c
		join `tabChat Participant` p
		  on p.parent = c.name and p.parenttype = %(conversation)s
		 and p.user not in ('Administrator', 'Guest')
		where c.owner = 'Administrator'
		group by c.name
		having people = 1
		""".format(conversation=CONVERSATION),
		{"conversation": CONVERSATION},
		as_dict=True,
	)

	for row in candidates:
		if not frappe.db.exists("User", row.person):
			continue
		frappe.db.set_value(CONVERSATION, row.name, "owner", row.person, update_modified=False)
		# The messages travel with it. Writing a message is owner-gated, so a
		# conversation handed over without them is one the person can read but
		# not correct.
		frappe.db.sql(
			"""update `tab{message}` set owner = %(person)s
			   where conversation = %(conversation)s and owner = 'Administrator'""".format(message=MESSAGE),
			{"person": row.person, "conversation": row.name},
		)

	_narrow_customised_permissions()
	frappe.db.commit()

	# The permission rows on both doctypes changed in this release. Cached
	# DocType meta predates them, so the old wide-open permission would keep
	# being enforced until something else happened to clear it.
	for doctype in (CONVERSATION, MESSAGE):
		frappe.clear_cache(doctype=doctype)


def _narrow_customised_permissions():
	"""Match the shipped permission rows on a site that has customised them.

	A Custom DocPerm replaces the DocType's own rows outright rather than
	merging with them, so a site where anyone opened Customize Form on these
	doctypes would keep granting ``All`` delete no matter what the JSON says.
	Only the ``All`` row is touched; a site that granted another role something
	deliberately keeps it.
	"""
	for name in frappe.get_all(
		"Custom DocPerm",
		filters={"parent": ["in", (CONVERSATION, MESSAGE)], "role": "All"},
		pluck="name",
	):
		frappe.db.set_value(
			"Custom DocPerm",
			name,
			{"delete": 0, "email": 0, "export": 0, "print": 0, "share": 0, "report": 0},
			update_modified=False,
		)
