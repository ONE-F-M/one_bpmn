# Copyright (c) 2026, one-fm and contributors
"""Who hears that an overnight check went badly.

The sweeps used to leave a public Note, which is findable only by someone who
thinks to look. These tests are about the routing: the owner of the agent that
failed hears by name, a System Manager always hears so an unowned agent still
reaches somebody, and nobody hears twice.
"""

from __future__ import annotations

import frappe
from frappe.tests.utils import FrappeTestCase

from one_bpmn.agents._eval_test_factories import make_agent_configuration
from one_bpmn.agents.eval_alerts import (
	_agent_logins,
	notify,
	owners_of,
	recipients_for,
	system_managers,
)


def _user(email, roles=()):
	if frappe.db.exists("User", email):
		return email
	user = frappe.get_doc({"doctype": "User", "email": email, "first_name": email.split("@")[0],
						   "send_welcome_email": 0, "enabled": 1, "user_type": "System User"})
	user.flags.ignore_mandatory = True
	user.flags.ignore_permissions = True
	user.insert(ignore_permissions=True)
	for role in roles:
		user.append("roles", {"role": role})
	if roles:
		user.save(ignore_permissions=True)
	return user.name


class TestRecipients(FrappeTestCase):
	def setUp(self):
		frappe.set_user("Administrator")
		self.owner = _user("_test_eval_owner@one-fm.com")
		self.agent = make_agent_configuration(process_owner=self.owner).name

	def test_the_owner_of_a_failing_agent_is_told(self):
		self.assertIn(self.owner, recipients_for([self.agent]))

	def test_the_owner_comes_first(self):
		"""It is their agent — the message is addressed to them, not cc'd."""
		self.assertEqual(recipients_for([self.agent])[0], self.owner)

	def test_system_managers_are_told_as_well(self):
		managers = system_managers()
		if not managers:
			self.skipTest("no enabled System Manager on this site")
		self.assertTrue(set(managers) & set(recipients_for([self.agent])))

	def test_an_agent_with_no_owner_still_reaches_somebody(self):
		orphan = make_agent_configuration().name
		if not system_managers():
			self.skipTest("no enabled System Manager on this site")
		self.assertTrue(recipients_for([orphan]))

	def test_nobody_is_told_twice(self):
		people = recipients_for([self.agent, self.agent])
		self.assertEqual(len(people), len(set(people)))

	def test_administrator_is_not_a_person_to_notify(self):
		"""A shared login is not somebody; alerting it tells nobody."""
		agent = make_agent_configuration(process_owner="Administrator").name
		self.assertNotIn("Administrator", owners_of([agent]))

	def test_a_disabled_owner_is_skipped(self):
		leaver = _user("_test_eval_leaver@one-fm.com")
		agent = make_agent_configuration(process_owner=leaver).name
		frappe.db.set_value("User", leaver, "enabled", 0)
		frappe.clear_document_cache("User", leaver)
		self.assertNotIn(leaver, owners_of([agent]))


class TestDelivery(FrappeTestCase):
	def setUp(self):
		frappe.set_user("Administrator")
		self.owner = _user("_test_eval_owner2@one-fm.com")
		self.agent = make_agent_configuration(process_owner=self.owner).name

	def test_it_writes_an_alert_each_person_will_see(self):
		told = notify("Nightly evals — attention needed", "<p>two suites below the bar</p>", [self.agent])
		self.assertIn(self.owner, told)
		note = frappe.get_all("Notification Log", filters={"for_user": self.owner},
							  fields=["subject", "type"], order_by="creation desc", limit=1)
		self.assertTrue(note)
		self.assertIn("Nightly evals", note[0].subject)
		self.assertEqual(note[0].type, "Alert")

	def test_a_long_subject_does_not_break_the_write(self):
		told = notify("x" * 400, "<p>body</p>", [self.agent])
		self.assertIn(self.owner, told)

	def test_one_bad_recipient_does_not_lose_the_others(self):
		"""The finding matters more than the delivery: a sweep that found a
		problem must not fail because one alert could not be written."""
		original = frappe.new_doc
		calls = {"n": 0}

		def flaky(doctype, *args, **kwargs):
			if doctype == "Notification Log":
				calls["n"] += 1
				if calls["n"] == 1:
					raise Exception("mailbox exploded")
			return original(doctype, *args, **kwargs)

		frappe.new_doc = flaky
		try:
			told = notify("subject", "body", [self.agent])
		finally:
			frappe.new_doc = original
		self.assertTrue(calls["n"] > 1, "it kept going after the failure")

	def test_telling_nobody_is_not_an_error(self):
		self.assertIsInstance(notify("subject", "body", []), list)


class TestWhoIsAPerson(FrappeTestCase):
	"""A site where service logins hold System Manager turns "tell the admins"
	into a dozen alerts, several of them to robots."""

	def setUp(self):
		frappe.set_user("Administrator")
		self.owner = _user("_test_eval_owner3@one-fm.com")
		self.agent = make_agent_configuration(process_owner=self.owner).name

	def test_an_agents_own_login_is_never_alerted(self):
		logins = _agent_logins()
		if not logins:
			self.skipTest("no provisioned agent users on this site")
		self.assertFalse(set(system_managers()) & logins)

	def test_a_configured_list_replaces_the_managers(self):
		chosen = _user("_test_eval_watcher@one-fm.com")
		# The field is new; a process holding the old meta silently drops the rows.
		frappe.clear_cache(doctype="Processa Settings")
		settings = frappe.get_single("Processa Settings")
		settings.set("eval_alert_recipients", [{"user": chosen}])
		settings.flags.ignore_mandatory = True
		settings.save(ignore_permissions=True)
		try:
			self.assertEqual(system_managers(), [chosen])
		finally:
			settings.set("eval_alert_recipients", [])
			settings.save(ignore_permissions=True)

	def test_the_owner_is_told_even_when_a_list_is_configured(self):
		"""The list is who else hears, not who hears instead."""
		chosen = _user("_test_eval_watcher2@one-fm.com")
		# The field is new; a process holding the old meta silently drops the rows.
		frappe.clear_cache(doctype="Processa Settings")
		settings = frappe.get_single("Processa Settings")
		settings.set("eval_alert_recipients", [{"user": chosen}])
		settings.flags.ignore_mandatory = True
		settings.save(ignore_permissions=True)
		try:
			people = recipients_for([self.agent])
			self.assertEqual(people[0], self.owner)
			self.assertIn(chosen, people)
		finally:
			settings.set("eval_alert_recipients", [])
			settings.save(ignore_permissions=True)
