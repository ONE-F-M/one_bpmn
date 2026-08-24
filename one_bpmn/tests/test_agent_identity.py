# Copyright (c) 2026, one-fm and contributors
"""An agent acting as itself, and the Work Item tools that need it (WI-002054).

Two things were true before this and both were quiet. Every write an agent's
tools made was recorded against a person who had not made it — usually
Administrator — and was allowed or refused by that person's roles rather than by
anything anybody had decided about the agent. "May this agent move a work item to
Done" had no answer you could set, because there was no subject to grant it to.

The denied tests here assert that the AGENT'S user lacks the role. That
distinction is the whole story: a test that only checked ignore_permissions was
unset would have passed just as well when the tool was running as
Administrator, who is allowed everything.
"""

from __future__ import annotations

import frappe
from frappe.tests.utils import FrappeTestCase

from one_bpmn.agents import identity
from one_bpmn.agents._eval_test_factories import make_agent_configuration


def _work_item():
	"""A Work Item of this test's own, copied from whatever the site has — a real
	one because sprint is mandatory and an invented record fails validation."""
	source = frappe.db.get_value("Work Item", {}, "name")
	doc = frappe.copy_doc(frappe.get_doc("Work Item", source))
	doc.title = f"_Test agent tools {frappe.generate_hash(length=8)}"
	doc.orchestrator = 0
	doc.assignee_user = None
	doc.flags.ignore_permissions = True
	doc.insert(ignore_permissions=True)
	return doc.name


def _somebody_else():
	"""A person who is not the reporter, made here rather than borrowed from the
	site, so the test still means something on a site with one user."""
	email = f"_test_handback_{frappe.generate_hash(length=6)}@example.com"
	user = frappe.new_doc("User")
	user.update({"email": email, "first_name": "Handback", "send_welcome_email": 0})
	user.flags.ignore_permissions = True
	user.insert(ignore_permissions=True)
	return email


def _agent(*roles):
	agent = make_agent_configuration()
	agent.set("agent_roles", [])
	for role in roles:
		agent.append("agent_roles", {"role": role})
	agent.flags.ignore_permissions = True
	agent.save(ignore_permissions=True)
	agent.reload()
	return agent


class TestTheAgentHasAnIdentity(FrappeTestCase):
	def tearDown(self):
		frappe.db.rollback()
		super().tearDown()

	def test_saving_an_agent_gives_it_a_user(self):
		agent = _agent()
		self.assertTrue(agent.agent_user)
		self.assertTrue(frappe.db.exists("User", agent.agent_user))

	def test_the_identity_does_not_narrow_who_can_see_an_agent(self):
		"""A User Permission restricts a list by every Link-to-User field on the
		doctype. Adding this one silently applied any such restriction to it — and
		since no agent's user is ever a person, the agent list went EMPTY for
		anyone carrying one. The field names a machine identity, not a person
		whose access should scope who may see the record."""
		field = next(
			f
			for f in frappe.get_meta("AI Agent Configuration").fields
			if f.fieldname == "agent_user"
		)
		self.assertTrue(field.ignore_user_permissions)

	def test_an_agent_that_already_has_an_identity_keeps_it(self):
		"""The domain changed once, and the agents provisioned under the old one
		were left there rather than renamed. So deriving the address afresh on
		every save would hand those agents a second user and strand everything the
		first one had signed. An identity that exists is the identity."""
		agent = _agent()
		inherited = "_test_inherited_identity@somewhere.else"
		if not frappe.db.exists("User", inherited):
			user = frappe.new_doc("User")
			user.update({"email": inherited, "first_name": "Inherited", "send_welcome_email": 0})
			user.flags.ignore_permissions = True
			user.insert(ignore_permissions=True)
		agent.db_set("agent_user", inherited, update_modified=False)
		agent.reload()

		agent.save(ignore_permissions=True)
		agent.reload()
		self.assertEqual(agent.agent_user, inherited)
		self.assertNotEqual(agent.agent_user, identity.agent_email(agent.name))

	def test_the_user_is_obviously_not_a_person(self):
		"""A real-looking address would invite somebody to email it."""
		agent = _agent()
		self.assertTrue(agent.agent_user.endswith(identity.AGENT_EMAIL_DOMAIN))

	def test_the_user_is_enabled_because_it_has_to_be(self):
		"""frappe.set_user refuses a disabled user, and a disabled user cannot own
		a write — so an identity that cannot be switched to is not an identity.
		What keeps a person out is that no password is ever set."""
		agent = _agent()
		self.assertTrue(frappe.db.get_value("User", agent.agent_user, "enabled"))

	def test_an_agent_granted_a_desk_role_is_a_system_user(self):
		"""Roles only mean anything on a System User, and roles are the point."""
		agent = _agent("Process Owner")
		self.assertEqual(frappe.db.get_value("User", agent.agent_user, "user_type"), "System User")

	def test_an_agent_granted_nothing_is_not_a_system_user(self):
		"""Frappe's own doing, and the right outcome: a user with no desk role has
		no business on the desk. Pinned because it means the identity of an agent
		that has been granted nothing is inert rather than merely unprivileged —
		granting its first role is what promotes it."""
		agent = _agent()
		self.assertEqual(frappe.db.get_value("User", agent.agent_user, "user_type"), "Website User")

	def test_it_is_kept_out_of_mention_lists(self):
		agent = _agent()
		self.assertFalse(frappe.db.get_value("User", agent.agent_user, "allowed_in_mentions"))

	def test_the_user_holds_the_roles_the_configuration_names(self):
		agent = _agent("Process Owner")
		roles = {r.role for r in frappe.get_doc("User", agent.agent_user).roles}
		self.assertIn("Process Owner", roles)

	def test_removing_a_role_revokes_it(self):
		"""Exactly, not at least: otherwise the list stops being the answer to
		"what may this agent do" and becomes a record of what it once could."""
		agent = _agent("Process Owner")
		agent.set("agent_roles", [])
		agent.flags.ignore_permissions = True
		agent.save(ignore_permissions=True)
		roles = {r.role for r in frappe.get_doc("User", agent.agent_user).roles} - {"All", "Guest"}
		self.assertEqual(roles, set())

	def test_a_role_granted_by_hand_is_taken_back(self):
		"""The configuration is the source. Two sources disagree the moment
		either changes."""
		agent = _agent("Process Owner")
		user = frappe.get_doc("User", agent.agent_user)
		user.append("roles", {"role": "System Manager"})
		user.flags.ignore_permissions = True
		user.save(ignore_permissions=True)
		agent.flags.ignore_permissions = True
		agent.save(ignore_permissions=True)
		roles = {r.role for r in frappe.get_doc("User", agent.agent_user).roles} - {"All", "Guest"}
		self.assertEqual(roles, {"Process Owner"})

	def test_provisioning_twice_is_harmless(self):
		agent = _agent("Process Owner")
		first = agent.agent_user
		agent.flags.ignore_permissions = True
		agent.save(ignore_permissions=True)
		agent.reload()
		self.assertEqual(agent.agent_user, first)

	def test_no_agent_means_no_identity_to_run_as(self):
		"""A real answer, not a failure: a tool called outside any agent should
		run exactly as it did before rather than as somebody arbitrary."""
		self.assertIsNone(identity.user_for(None))
		self.assertIsNone(identity.user_for("Does Not Exist"))

	def test_a_refusal_is_explained_in_terms_the_model_can_act_on(self):
		"""A bare PermissionError tells an agent nothing, and then it reports the
		work as done or offers to retry a permission it will never have."""
		agent = _agent("Process Owner")
		text = identity.describe_refusal(agent.name, frappe.PermissionError("nope"))
		self.assertIn("not permitted", text)
		self.assertIn("Process Owner", text)
		self.assertIn("do not retry", text)

	def test_an_agent_with_no_roles_is_told_it_has_none(self):
		agent = _agent()
		self.assertIn("no roles at all", identity.describe_refusal(agent.name, frappe.PermissionError()))


class TestTheIdentityIsVisibleOnEveryAgent(FrappeTestCase):
	"""The fields have to be where somebody can find them.

	They went in beside allowed_roles, which lives in the Chat Surface section —
	gated on agent_type == 'Chat'. So on a Background agent they were invisible,
	and Background is exactly the kind that uses tools: the Connector Agent and
	the Orchestrator are both Background. An identity nobody can see is an
	identity nobody grants a role to, which makes the whole story inert.
	"""

	def tearDown(self):
		frappe.db.rollback()
		super().tearDown()

	@staticmethod
	def _governing_section(fieldname):
		"""The section a field sits under, the way the form resolves it."""
		meta = frappe.get_meta("AI Agent Configuration")
		section = None
		for field in meta.fields:
			if field.fieldtype in ("Section Break", "Tab Break"):
				section = field
			if field.fieldname == fieldname:
				return section
		return None

	def test_the_identity_fields_are_always_shown(self):
		for fieldname in ("agent_user", "agent_roles"):
			with self.subTest(fieldname=fieldname):
				section = self._governing_section(fieldname)
				self.assertIsNotNone(section)
				self.assertFalse(
					section.depends_on,
					f"{fieldname} is under {section.fieldname}, which only shows when "
					f"{section.depends_on!r} — a Background agent would never see it",
				)

	def test_they_are_not_under_the_chat_section(self):
		"""Where they started, and the reason this test exists."""
		for fieldname in ("agent_user", "agent_roles"):
			with self.subTest(fieldname=fieldname):
				self.assertNotEqual(self._governing_section(fieldname).fieldname, "chat_section")

	def test_they_share_one_labelled_section(self):
		"""Somebody hunting for "what can this agent do" looks for a heading that
		says so, not for two fields loose among the security settings."""
		user_section = self._governing_section("agent_user")
		roles_section = self._governing_section("agent_roles")
		self.assertEqual(user_section.fieldname, roles_section.fieldname)
		self.assertIn("Identity", user_section.label)

	def test_a_background_agent_has_an_identity_to_show(self):
		"""The case that was broken: the agents that use tools are Background."""
		background = frappe.db.get_value(
			"AI Agent Configuration",
			{"agent_type": "Background", "agent_user": ["is", "set"]},
			["name", "agent_user"],
			as_dict=True,
		)
		if not background:
			self.skipTest("no provisioned Background agent on this site")
		self.assertTrue(background.agent_user)


class TestToolsRunAsTheAgent(FrappeTestCase):
	"""The seam. It is shared by every agent in the system, so the tests that
	matter most here are the ones proving the old behaviour is gone."""

	def tearDown(self):
		frappe.db.rollback()
		super().tearDown()

	def test_the_exec_path_switches_user_and_turns_permissions_on(self):
		import inspect

		from one_bpmn.agents import shape_tools

		source = inspect.getsource(shape_tools._run_server_script)
		self.assertIn("frappe.set_user(agent_user)", source)
		self.assertIn("frappe.flags.ignore_permissions = False", source)

	def test_the_session_is_put_back(self):
		"""set_user rewrites session.sid and WIPES session.data, which guts a
		browser session when a tool runs inline inside a web request."""
		import inspect

		from one_bpmn.agents import shape_tools

		source = inspect.getsource(shape_tools._run_server_script)
		self.assertIn("frappe.session.sid = saved_sid", source)
		self.assertIn("frappe.session.data = saved_data", source)

	def test_an_agent_without_a_user_keeps_the_old_behaviour(self):
		"""Rather than being handed somebody else's permissions and told they are
		its own."""
		import inspect

		from one_bpmn.agents import shape_tools

		source = inspect.getsource(shape_tools._run_server_script)
		self.assertIn("if agent_user:", source)

	def test_a_refusal_reaches_the_model_not_the_error_log(self):
		"""An agent cannot read the Error Log, so "see Error Log for details"
		makes it invent an explanation — usually that the work is done."""
		import inspect

		from one_bpmn.agents import shape_tools

		source = inspect.getsource(shape_tools.execute_shape)
		self.assertIn("frappe.PermissionError", source)
		self.assertIn("retryable", source)

	def test_a_validation_failure_reaches_the_model_too(self):
		"""A Work Item save can fail for reasons nothing to do with the change —
		no sprint, a completed sprint, an Epic."""
		import inspect

		from one_bpmn.agents import shape_tools

		self.assertIn("frappe.ValidationError", inspect.getsource(shape_tools.execute_shape))


class TestTheWorkItemTools(FrappeTestCase):
	"""The four tools, run the way the agent runs them."""

	def tearDown(self):
		frappe.db.rollback()
		super().tearDown()

	@staticmethod
	def _run(script_name, item, args=None, shape_config=None):
		"""Execute a tool body the way _run_server_script does, so the test
		exercises the real script rather than a paraphrase of it."""
		body = frappe.db.get_value("Server Script", script_name, "script")
		result = {}
		local_vars = {
			"frappe": frappe,
			"context_doctype": "Work Item",
			"context_docname": item,
			"result": result,
			"task_data": dict(args or {}),
			"shape_config": dict(shape_config or {}),
			"bpmn_id": "test",
			"doc": frappe.get_doc("Work Item", item),
		}
		exec(body, {"frappe": frappe, "__builtins__": __builtins__}, local_vars)
		return result

	# ── what it relates to ───────────────────────────────────────────────

	def test_related_items_returns_the_neighbourhood(self):
		item = _work_item()
		out = self._run("Work Item Tool: What This Relates To", item)
		self.assertIn("sprint_siblings", out)
		self.assertIn("epic", out)
		self.assertIn("counts", out)

	def test_related_items_refuses_when_there_is_no_work_item(self):
		body = frappe.db.get_value("Server Script", "Work Item Tool: What This Relates To", "script")
		with self.assertRaises(frappe.ValidationError):
			exec(body, {"frappe": frappe, "__builtins__": __builtins__},
			     {"frappe": frappe, "context_doctype": "A2A Task", "context_docname": None,
			      "result": {}, "task_data": {}, "shape_config": {}, "bpmn_id": "t", "doc": None})

	# ── the comment ──────────────────────────────────────────────────────

	def test_a_comment_lands_on_the_item_and_survives(self):
		item = _work_item()
		before = frappe.db.count(
			"Comment", {"reference_doctype": "Work Item", "reference_name": item, "comment_type": "Comment"}
		)
		self._run("Work Item Tool: Record a Comment", item, {"comment": "checked the rate source"})
		after = frappe.db.count(
			"Comment", {"reference_doctype": "Work Item", "reference_name": item, "comment_type": "Comment"}
		)
		self.assertEqual(after, before + 1)

	def test_an_empty_comment_is_refused(self):
		item = _work_item()
		with self.assertRaises(frappe.ValidationError):
			self._run("Work Item Tool: Record a Comment", item, {"comment": "   "})

	# ── handing back ─────────────────────────────────────────────────────

	def test_handing_back_sets_the_assignee_and_clears_the_flag(self):
		"""before_save nulls assignee_user while the orchestrator flag is set, so
		assigning without clearing it discards the value just written. This is the
		failure the tool exists to avoid."""
		item = _work_item()
		frappe.db.set_value("Work Item", item, "orchestrator", 1, update_modified=False)
		self._run("Work Item Tool: Hand Back to a Person", item,
		          {"assignee": "Administrator", "reason": "needs a decision"})
		row = frappe.db.get_value("Work Item", item, ["assignee_user", "orchestrator"], as_dict=True)
		self.assertEqual(row.assignee_user, "Administrator")
		self.assertFalse(row.orchestrator)

	def test_handing_back_records_why(self):
		item = _work_item()
		self._run("Work Item Tool: Hand Back to a Person", item,
		          {"assignee": "Administrator", "reason": "outside what any specialist can do"})
		comments = frappe.get_all(
			"Comment",
			filters={"reference_doctype": "Work Item", "reference_name": item, "comment_type": "Comment"},
			fields=["content"], order_by="creation desc", limit=1,
		)
		self.assertIn("Handed back", comments[0].content)

	def test_naming_nobody_hands_it_to_the_person_who_raised_it(self):
		"""The agent has no way to discover a person: nothing in its brief names one
		and it has no tool that lists them. While naming somebody was mandatory, the
		first work item that genuinely needed a human was reasoned about correctly,
		described in prose as needing a person, and handed to nobody. So the default
		is the reporter — they asked for it, so they can say where it goes next."""
		item = _work_item()
		frappe.db.set_value("Work Item", item, "reporter_user", "Administrator", update_modified=False)
		out = self._run("Work Item Tool: Hand Back to a Person", item, {"reason": "needs a decision"})
		self.assertEqual(frappe.db.get_value("Work Item", item, "assignee_user"), "Administrator")
		self.assertTrue(out.get("chose_the_reporter"))

	def test_a_named_person_still_wins_over_the_reporter(self):
		item = _work_item()
		frappe.db.set_value("Work Item", item, "reporter_user", "Administrator", update_modified=False)
		other = _somebody_else()
		out = self._run("Work Item Tool: Hand Back to a Person", item,
		                {"assignee": other, "reason": "they own this area"})
		self.assertEqual(frappe.db.get_value("Work Item", item, "assignee_user"), other)
		self.assertFalse(out.get("chose_the_reporter"))

	def test_handing_back_with_nobody_on_the_item_at_all_is_refused(self):
		"""Falling back has to stop somewhere. An item naming nobody who exists is
		refused out loud rather than silently assigned to whoever happens to be
		running the agent."""
		item = _work_item()
		frappe.db.set_value(
			"Work Item", item,
			{"reporter_user": None, "process_owner": None, "owner": "ghost@example.com"},
			update_modified=False,
		)
		with self.assertRaises(frappe.ValidationError):
			self._run("Work Item Tool: Hand Back to a Person", item, {"reason": "x"})

	def test_handing_back_to_someone_who_does_not_exist_is_refused(self):
		item = _work_item()
		with self.assertRaises(frappe.ValidationError):
			self._run("Work Item Tool: Hand Back to a Person", item,
			          {"assignee": "ghost@example.com", "reason": "x"})

	# ── the state tool, which is the constrained one ─────────────────────

	def test_a_permitted_state_is_set(self):
		item = _work_item()
		self._run("Work Item Tool: Move the State", item, {"state": "In Progress"},
		          {"allowed_states": "Open,In Progress"})
		self.assertEqual(frappe.db.get_value("Work Item", item, "status"), "In Progress")

	def test_a_state_the_shape_does_not_permit_is_refused(self):
		"""WI-002053 established that a work item must not advance on the strength
		of an incomplete result. A tool that could set Done would reopen that."""
		item = _work_item()
		with self.assertRaises(frappe.ValidationError) as caught:
			self._run("Work Item Tool: Move the State", item, {"state": "Done"},
			          {"allowed_states": "Open,In Progress"})
		self.assertIn("may not set", str(caught.exception))

	def test_the_refusal_says_it_is_a_deliberate_limit(self):
		"""So the agent reports it rather than retrying it."""
		item = _work_item()
		with self.assertRaises(frappe.ValidationError) as caught:
			self._run("Work Item Tool: Move the State", item, {"state": "Done"},
			          {"allowed_states": "Open"})
		self.assertIn("deliberate limit", str(caught.exception))

	def test_a_shape_declaring_nothing_can_move_nothing(self):
		"""Failing closed: a shape with no list is a shape whose limits somebody
		forgot, not a shape with no limits."""
		item = _work_item()
		with self.assertRaises(frappe.ValidationError):
			self._run("Work Item Tool: Move the State", item, {"state": "Open"}, {})

	def test_the_limit_comes_from_the_shape_not_the_arguments(self):
		"""A tool whose limits came from its arguments would be a tool with no
		limits — the model would simply widen them."""
		item = _work_item()
		with self.assertRaises(frappe.ValidationError):
			self._run("Work Item Tool: Move the State", item,
			          {"state": "Done", "allowed_states": "Done"}, {"allowed_states": "Open"})


class TestEveryToolHonoursTheAgentsRoles(FrappeTestCase):
	"""The gate has to be in the TOOLS, not left to what sits underneath them.

	Found while writing the test instructions, which is late but not too late.
	Switching user and turning permissions on is not enough on its own, because
	the things a tool calls do not all check: frappe.get_doc enforces nothing,
	add_comment inserts its Comment with permissions ignored, and the workflow
	helper saves with ignore_permissions=True. So an agent granted NOTHING could
	still annotate a work item and move its state — the two most consequential of
	the four — while the hand-back tool, which happens to call doc.save(), was
	correctly refused. One of four enforcing is worse than none, because it looks
	like it works.
	"""

	def tearDown(self):
		frappe.set_user("Administrator")
		frappe.db.rollback()
		super().tearDown()

	SCRIPTS = (
		("Work Item Tool: What This Relates To", {}, {}),
		("Work Item Tool: Record a Comment", {"comment": "x"}, {}),
		("Work Item Tool: Hand Back to a Person", {"assignee": "Administrator", "reason": "x"}, {}),
		("Work Item Tool: Move the State", {"state": "Open"}, {"allowed_states": "Open"}),
	)

	@staticmethod
	def _run_as(user, script_name, item, args, shape_config):
		body = frappe.db.get_value("Server Script", script_name, "script")
		local_vars = {
			"frappe": frappe,
			"context_doctype": "Work Item",
			"context_docname": item,
			"result": {},
			"task_data": dict(args),
			"shape_config": dict(shape_config),
			"bpmn_id": "test",
			"doc": None,
		}
		original = frappe.session.user
		frappe.set_user(user)
		try:
			exec(body, {"frappe": frappe, "__builtins__": __builtins__}, local_vars)
		finally:
			frappe.set_user(original)

	def test_every_tool_checks_the_permission_itself(self):
		"""All four, not just the one whose underlying call happened to check."""
		agent = _agent()
		item = _work_item()
		frappe.clear_cache(user=agent.agent_user)
		for script, args, cfg in self.SCRIPTS:
			with self.subTest(script=script):
				with self.assertRaises(frappe.PermissionError):
					self._run_as(agent.agent_user, script, item, args, cfg)

	def test_the_role_is_what_lets_them_through(self):
		agent = _agent("Process Owner")
		item = _work_item()
		frappe.clear_cache(user=agent.agent_user)
		for script, args, cfg in self.SCRIPTS:
			with self.subTest(script=script):
				# No exception is the assertion.
				self._run_as(agent.agent_user, script, item, args, cfg)

	def test_the_lookup_needs_only_read(self):
		"""A tool that changes nothing should not demand write — but it must not
		demand nothing either, which is what it did before."""
		body = frappe.db.get_value("Server Script", "Work Item Tool: What This Relates To", "script")
		self.assertIn('"read"', body)

	def test_the_changing_tools_need_write(self):
		for script in (
			"Work Item Tool: Record a Comment",
			"Work Item Tool: Hand Back to a Person",
			"Work Item Tool: Move the State",
		):
			with self.subTest(script=script):
				self.assertIn('"write"', frappe.db.get_value("Server Script", script, "script"))


class TestWhatTheAgentMayNotDo(FrappeTestCase):
	"""The denied paths, asserted on the AGENT'S roles.

	A test that only checked ignore_permissions was unset would pass just as well
	while the tool ran as Administrator, who is allowed everything — which is
	exactly the situation this story exists to end.
	"""

	def tearDown(self):
		frappe.set_user("Administrator")
		frappe.db.rollback()
		super().tearDown()

	def test_an_agent_with_no_roles_cannot_write_a_work_item(self):
		agent = _agent()
		item = _work_item()
		frappe.set_user(agent.agent_user)
		try:
			self.assertFalse(
				frappe.has_permission("Work Item", "write", doc=item, user=agent.agent_user),
				"an agent granted nothing must not be able to change a work item",
			)
		finally:
			frappe.set_user("Administrator")

	def test_granting_the_role_grants_the_write(self):
		"""The point of the identity: what an agent may do is configuration."""
		agent = _agent("Process Owner")
		item = _work_item()
		self.assertTrue(
			frappe.has_permission("Work Item", "write", doc=item, user=agent.agent_user),
			"Process Owner has write on Work Item, so its agent does too",
		)

	def test_revoking_the_role_revokes_the_write(self):
		agent = _agent("Process Owner")
		item = _work_item()
		self.assertTrue(frappe.has_permission("Work Item", "write", doc=item, user=agent.agent_user))
		agent.set("agent_roles", [])
		agent.flags.ignore_permissions = True
		agent.save(ignore_permissions=True)
		frappe.clear_cache(user=agent.agent_user)
		self.assertFalse(
			frappe.has_permission("Work Item", "write", doc=item, user=agent.agent_user),
			"removing the role must take the permission away, with no deployment",
		)
