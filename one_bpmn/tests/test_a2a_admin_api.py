# Copyright (c) 2026, one-fm and contributors
# For license information, please see license.txt
"""WI-001934: the admin surface — both registries and the task monitor.

Every endpoint here is System Manager only: the registries decide who
may reach our agents, and the monitor shows what those agents are being
asked to do.
"""

from __future__ import annotations

import frappe
from frappe.tests.utils import FrappeTestCase

from one_bpmn.agents._eval_test_factories import make_agent_configuration
from one_bpmn.api import a2a_admin_api
from one_bpmn.tests.test_a2a_client import make_remote_for
from one_bpmn.tests.test_a2a_client_registry import approve, make_client


def make_nobody():
	return frappe.get_doc(
		{
			"doctype": "User",
			"email": f"a2a-admin-nobody-{frappe.generate_hash(length=6)}@example.com",
			"first_name": "Nobody",
			"send_welcome_email": 0,
		}
	).insert(ignore_permissions=True)


def make_task(**kwargs):
	defaults = {"doctype": "A2A Task", "direction": "Inbound", "state": "working"}
	defaults.update(kwargs)
	task = frappe.get_doc(defaults)
	task.flags.ignore_links = True
	return task.insert(ignore_permissions=True)


class TestA2AAdminPermissions(FrappeTestCase):
	def test_every_endpoint_refuses_a_non_admin(self):
		nobody = make_nobody()
		with self.set_user(nobody.name):
			self.assertFalse(a2a_admin_api.get_permissions()["administer"])
			for call, kwargs in (
				(a2a_admin_api.list_remote_agents, {}),
				(a2a_admin_api.list_clients, {}),
				(a2a_admin_api.list_tasks, {}),
				(a2a_admin_api.list_delegations, {}),
				(a2a_admin_api.delegation_detail, {"name": "x"}),
				(a2a_admin_api.delegation_filter_options, {}),
				(a2a_admin_api.cancel_delegation, {"name": "x"}),
				(a2a_admin_api.redelegate_delegation, {"name": "x"}),
				(a2a_admin_api.exposed_agents, {}),
				(a2a_admin_api.fetch_remote_card, {"name": "x"}),
				(a2a_admin_api.set_remote_approval, {"name": "x", "approval_status": "Approved"}),
				(a2a_admin_api.set_client_approval, {"name": "x", "approval_status": "Approved"}),
				(a2a_admin_api.get_client_credentials, {"name": "x"}),
			):
				with self.assertRaises(frappe.PermissionError):
					call(**kwargs)

	def test_admin_sees_administer_true(self):
		self.assertTrue(a2a_admin_api.get_permissions()["administer"])


class TestA2AAdminRegistries(FrappeTestCase):
	def test_clients_carry_their_allow_list(self):
		agent = make_agent_configuration(a2a_exposed=1)
		client = approve(make_client(agents=[agent.name]))
		row = next(c for c in a2a_admin_api.list_clients() if c["name"] == client.name)
		self.assertEqual(row["allowed_agents"], [agent.name])
		self.assertEqual(row["user"], client.user)

	def test_exposed_agents_are_the_only_candidates(self):
		exposed = make_agent_configuration(a2a_exposed=1)
		unexposed = make_agent_configuration()
		draft = make_agent_configuration(a2a_exposed=1, lifecycle_status="Draft")
		names = {a["name"] for a in a2a_admin_api.exposed_agents()}
		self.assertIn(exposed.name, names)
		self.assertNotIn(unexposed.name, names)
		self.assertNotIn(draft.name, names)

	def test_remote_approval_round_trip(self):
		remote = make_remote_for(make_agent_configuration())
		result = a2a_admin_api.set_remote_approval(remote.name, "Revoked")
		self.assertEqual(result["approval_status"], "Revoked")
		result = a2a_admin_api.set_remote_approval(remote.name, "Approved")
		self.assertEqual(result["approval_status"], "Approved")

	def test_client_approval_issues_the_user(self):
		client = make_client()
		result = a2a_admin_api.set_client_approval(client.name, "Approved")
		self.assertTrue(result["user"])
		self.assertEqual(result["approval_status"], "Approved")

	def test_unknown_approval_status_is_refused(self):
		client = make_client()
		with self.assertRaises(frappe.ValidationError):
			a2a_admin_api.set_client_approval(client.name, "Whatever")


class TestA2AAgentCatalogue(FrappeTestCase):
	"""Our own exposed agents and their cards. The cards are public; this
	catalogue is not — an outsider must not get a directory of our agents."""

	def test_lists_exposed_agents_with_their_cards(self):
		exposed = make_agent_configuration(a2a_exposed=1, a2a_skill_tags="backend, frappe")
		rows = a2a_admin_api.list_agent_cards()
		row = next(r for r in rows if r["agent_id"] == exposed.agent_id)
		self.assertEqual(row["tags"], ["backend", "frappe"])
		self.assertIn(exposed.agent_id, row["card_url"])
		self.assertEqual(row["card"]["skills"][0]["id"], exposed.agent_id)
		self.assertNotIn("system_prompt", frappe.as_json(row["card"]))

	def test_unexposed_and_draft_agents_are_absent(self):
		unexposed = make_agent_configuration()
		draft = make_agent_configuration(a2a_exposed=1, lifecycle_status="Draft")
		ids = {r["agent_id"] for r in a2a_admin_api.list_agent_cards()}
		self.assertNotIn(unexposed.agent_id, ids)
		self.assertNotIn(draft.agent_id, ids)

	def test_shows_which_approved_clients_can_reach_an_agent(self):
		agent = make_agent_configuration(a2a_exposed=1)
		lonely = make_agent_configuration(a2a_exposed=1)
		client = approve(make_client(agents=[agent.name]))

		rows = {r["agent_id"]: r for r in a2a_admin_api.list_agent_cards()}
		self.assertEqual(rows[agent.name and agent.agent_id]["reachable_by"], [client.name])
		self.assertEqual(
			rows[lonely.agent_id]["reachable_by"],
			[],
			"exposed with a public card, but no approved client lists it",
		)

	def test_a_revoked_client_no_longer_counts_as_reach(self):
		agent = make_agent_configuration(a2a_exposed=1)
		client = approve(make_client(agents=[agent.name]))
		client.approval_status = "Revoked"
		client.save(ignore_permissions=True)
		rows = {r["agent_id"]: r for r in a2a_admin_api.list_agent_cards()}
		self.assertEqual(rows[agent.agent_id]["reachable_by"], [])

	def test_catalogue_is_admin_only(self):
		nobody = make_nobody()
		with self.set_user(nobody.name):
			with self.assertRaises(frappe.PermissionError):
				a2a_admin_api.list_agent_cards()


class TestA2AAdminTaskMonitor(FrappeTestCase):
	def test_lists_both_directions_with_counters(self):
		make_task(direction="Inbound", state="working", delegation_depth=1, handoff_count=1)
		make_task(direction="Outbound", state="completed", delegation_depth=2, handoff_count=3)
		result = a2a_admin_api.list_tasks()
		self.assertGreaterEqual(result["total"], 2)
		self.assertIn("delegation_depth", result["tasks"][0])
		self.assertIn("handoff_count", result["tasks"][0])

	def test_direction_and_state_filters(self):
		make_task(direction="Outbound", state="timed-out")
		outbound = a2a_admin_api.list_tasks(direction="Outbound")
		self.assertTrue(all(t["direction"] == "Outbound" for t in outbound["tasks"]))
		timed_out = a2a_admin_api.list_tasks(state="timed-out")
		self.assertTrue(all(t["state"] == "timed-out" for t in timed_out["tasks"]))

	def test_page_length_is_capped(self):
		result = a2a_admin_api.list_tasks(page_length=5000)
		self.assertLessEqual(result["page_length"], a2a_admin_api.MAX_PAGE_LENGTH)


class TestRegisteringFromProcessa(FrappeTestCase):
	"""WI-001934 asks for 'register an endpoint' on this screen, so the whole
	lifecycle has to be reachable without opening Desk: create, edit, and
	choose which agents a caller may reach."""

	def test_a_remote_agent_can_be_registered_and_starts_in_draft(self):
		name = f"_Test New Remote {frappe.generate_hash(length=6)}"
		result = a2a_admin_api.create_remote_agent(
			agent_name=name,
			endpoint_url="https://partner.example.com/a2a",
			auth_scheme="Bearer",
			credential="s3cret",
			request_timeout=15,
		)
		self.assertEqual(result["approval_status"], "Draft", "approval must stay a deliberate step")
		doc = frappe.get_doc("A2A Remote Agent", result["name"])
		self.assertEqual(doc.endpoint_url, "https://partner.example.com/a2a")
		self.assertEqual(doc.auth_scheme, "Bearer")
		self.assertEqual(doc.get_password("credential", raise_exception=False), "s3cret")
		self.assertEqual(doc.request_timeout, 15)

	def test_a_bad_endpoint_is_refused_before_anything_is_created(self):
		name = f"_Test Bad Remote {frappe.generate_hash(length=6)}"
		with self.assertRaises(frappe.ValidationError):
			a2a_admin_api.create_remote_agent(agent_name=name, endpoint_url="partner.example.com")
		self.assertFalse(frappe.db.exists("A2A Remote Agent", name))

	def test_a_duplicate_name_is_refused(self):
		name = f"_Test Dup Remote {frappe.generate_hash(length=6)}"
		a2a_admin_api.create_remote_agent(agent_name=name, endpoint_url="https://a.example.com/a2a")
		with self.assertRaises(frappe.ValidationError):
			a2a_admin_api.create_remote_agent(agent_name=name, endpoint_url="https://b.example.com/a2a")

	def test_editing_the_endpoint_sends_an_approved_entry_back_to_draft(self):
		remote = make_remote_for(make_agent_configuration())
		self.assertEqual(remote.approval_status, "Approved")
		result = a2a_admin_api.update_remote_agent(
			remote.name, endpoint_url="https://moved.example.com/a2a"
		)
		self.assertEqual(result["approval_status"], "Draft", "a new address has not been reviewed")

	def test_a_client_can_be_registered_with_its_agents(self):
		agent = make_agent_configuration(a2a_exposed=1)
		name = f"_Test New Client {frappe.generate_hash(length=6)}"
		result = a2a_admin_api.create_client(
			client_name=name, description="A partner.", allowed_agents=frappe.as_json([agent.name])
		)
		self.assertEqual(result["approval_status"], "Draft", "approval is what issues the key")
		doc = frappe.get_doc("A2A Client", result["name"])
		self.assertEqual([r.agent_configuration for r in doc.allowed_agents], [agent.name])
		self.assertFalse(doc.user, "no key until it is approved")

	def test_only_exposed_agents_can_be_granted(self):
		exposed = make_agent_configuration(a2a_exposed=1)
		unexposed = make_agent_configuration()
		name = f"_Test Grant Client {frappe.generate_hash(length=6)}"
		result = a2a_admin_api.create_client(
			client_name=name, allowed_agents=frappe.as_json([exposed.name, unexposed.name])
		)
		doc = frappe.get_doc("A2A Client", result["name"])
		self.assertEqual(
			[r.agent_configuration for r in doc.allowed_agents],
			[exposed.name],
			"an agent that does not take part in A2A cannot be granted",
		)

	def test_a_clients_agents_can_be_replaced(self):
		first = make_agent_configuration(a2a_exposed=1)
		second = make_agent_configuration(a2a_exposed=1)
		client = make_client(agents=[first.name])
		result = a2a_admin_api.set_client_agents(client.name, frappe.as_json([second.name]))
		self.assertEqual(result["allowed_agents"], [second.name])

	def test_registering_is_admin_only(self):
		nobody = make_nobody()
		with self.set_user(nobody.name):
			for call, kwargs in (
				(a2a_admin_api.create_remote_agent, {"agent_name": "x", "endpoint_url": "https://x.example.com"}),
				(a2a_admin_api.update_remote_agent, {"name": "x"}),
				(a2a_admin_api.create_client, {"client_name": "x"}),
				(a2a_admin_api.set_client_agents, {"name": "x"}),
			):
				with self.assertRaises(frappe.PermissionError):
					call(**kwargs)


class TestDelegationMonitor(FrappeTestCase):
	"""The delegation list on the A2A screen.

	The task monitor answers "what is in flight between agents". This answers
	"who is working on this Work Item, how far along, and did anything stop it"
	— the same hop with the business document attached — so it filters by the
	work rather than by the direction of travel.
	"""

	def tearDown(self):
		frappe.db.rollback()
		super().tearDown()

	def _delegation(self, **kw):
		worker = kw.pop("worker", None) or make_agent_configuration(a2a_exposed=1)
		task = frappe.get_doc({
			"doctype": "A2A Task",
			"direction": "Internal",
			"state": kw.pop("task_state", "working"),
			"agent_configuration": worker.name,
			"delegation_depth": 1,
			"handoff_count": 1,
		})
		task.flags.ignore_links = True
		task.insert(ignore_permissions=True)

		doc = frappe.new_doc("Agent Delegation")
		doc.update({
			"worker_agent": worker.name,
			"status": "Delegated",
			"a2a_task": task.name,
			"delegation_depth": 1,
			"handoff_count": 1,
		})
		doc.update(kw)
		doc.flags.ignore_permissions = True
		doc.flags.ignore_links = True
		doc.insert(ignore_permissions=True)
		return doc

	def test_a_delegation_is_listed_with_its_work(self):
		d = self._delegation(reference_doctype="A2A Task", reference_name=self._any_task())
		row = next(r for r in a2a_admin_api.list_delegations()["delegations"] if r["name"] == d.name)
		self.assertEqual(row["reference_doctype"], "A2A Task")
		self.assertEqual(row["worker_agent"], d.worker_agent)

	@staticmethod
	def _any_task():
		return frappe.db.get_value("A2A Task", {}, "name")

	def test_filtering_by_status(self):
		wanted = self._delegation(status="Needs Review", stopped_reason="turn_cap")
		other = self._delegation(status="Completed")
		names = {r["name"] for r in a2a_admin_api.list_delegations(status="Needs Review")["delegations"]}
		self.assertIn(wanted.name, names)
		self.assertNotIn(other.name, names)

	def test_filtering_by_doctype(self):
		wanted = self._delegation(reference_doctype="A2A Task", reference_name=self._any_task())
		other = self._delegation()
		names = {
			r["name"] for r in a2a_admin_api.list_delegations(reference_doctype="A2A Task")["delegations"]
		}
		self.assertIn(wanted.name, names)
		self.assertNotIn(other.name, names)

	def test_the_document_filter_matches_a_fragment(self):
		"""Nobody types a full document id from memory — a partial is how you
		find the run you were just looking at."""
		ref = self._any_task()
		wanted = self._delegation(reference_doctype="A2A Task", reference_name=ref)
		names = {r["name"] for r in a2a_admin_api.list_delegations(reference_name=ref[:6])["delegations"]}
		self.assertIn(wanted.name, names)

	def test_the_task_filter_matches_a_fragment_too(self):
		d = self._delegation()
		names = {
			r["name"] for r in a2a_admin_api.list_delegations(a2a_task=d.a2a_task[:6])["delegations"]
		}
		self.assertIn(d.name, names)

	def test_newest_activity_first(self):
		"""Ordered by last updated, not created: a delegation moves through
		Delegated, In Progress and then Needs Review, so ordering by creation
		buries the one that just changed."""
		first = self._delegation()
		second = self._delegation()
		first.db_set("status", "Needs Review", update_modified=True)
		listed = [r["name"] for r in a2a_admin_api.list_delegations()["delegations"]]
		self.assertLess(listed.index(first.name), listed.index(second.name))

	def test_total_counts_the_filtered_set(self):
		self._delegation(status="Failed")
		result = a2a_admin_api.list_delegations(status="Failed")
		self.assertEqual(result["total"], len(result["delegations"]))

	def test_a_page_holds_what_was_asked_for(self):
		for _ in range(3):
			self._delegation(status="Delegated")
		result = a2a_admin_api.list_delegations(status="Delegated", page_length=2)
		self.assertEqual(len(result["delegations"]), 2)
		self.assertGreaterEqual(result["total"], 3)
		self.assertEqual(result["page_length"], 2)

	def test_the_next_page_is_the_next_rows_not_the_same_ones(self):
		"""The failure this guards against is a Next button that appears to work
		and shows page one again."""
		for _ in range(4):
			self._delegation(status="Delegated")
		first = a2a_admin_api.list_delegations(status="Delegated", page_length=2, start=0)
		second = a2a_admin_api.list_delegations(status="Delegated", page_length=2, start=2)
		self.assertEqual(second["start"], 2)
		self.assertFalse(
			{d["name"] for d in first["delegations"]} & {d["name"] for d in second["delegations"]}
		)

	def test_the_total_is_the_whole_filtered_set_not_the_page(self):
		"""'of N' in the footer counts every match, or paging cannot know when
		to stop."""
		for _ in range(3):
			self._delegation(status="Delegated")
		result = a2a_admin_api.list_delegations(status="Delegated", page_length=1)
		self.assertEqual(len(result["delegations"]), 1)
		self.assertGreaterEqual(result["total"], 3)

	def test_a_page_size_beyond_the_cap_is_clamped(self):
		result = a2a_admin_api.list_delegations(page_length=10_000)
		self.assertEqual(result["page_length"], a2a_admin_api.MAX_PAGE_LENGTH)

	def test_the_task_monitor_pages_the_same_way(self):
		result = a2a_admin_api.list_tasks(page_length=1, start=0)
		self.assertLessEqual(len(result["tasks"]), 1)
		self.assertEqual(result["page_length"], 1)
		self.assertEqual(result["start"], 0)

	def test_detail_carries_the_task_state_as_well(self):
		"""'Completed' on the delegation and what the worker actually said are
		different facts, and the turn-cap case is where they diverge."""
		d = self._delegation(status="Completed", task_state="completed")
		detail = a2a_admin_api.delegation_detail(d.name)
		self.assertEqual(detail["delegation"]["name"], d.name)
		self.assertEqual(detail["task"]["state"], "completed")

	def test_detail_survives_a_reference_it_cannot_resolve(self):
		d = self._delegation(reference_doctype="A2A Task", reference_name="A2A-does-not-exist")
		detail = a2a_admin_api.delegation_detail(d.name)
		self.assertEqual(detail["delegation"]["name"], d.name)
		self.assertIsNone(detail["reference_title"])

	def test_detail_of_an_unknown_delegation_is_an_error_not_an_empty_modal(self):
		with self.assertRaises(frappe.DoesNotExistError):
			a2a_admin_api.delegation_detail("AD-does-not-exist")

	def test_filter_options_come_from_the_rows_that_exist(self):
		d = self._delegation(status="Needs Review", reference_doctype="A2A Task",
			reference_name=self._any_task())
		options = a2a_admin_api.delegation_filter_options()
		self.assertIn("Needs Review", options["statuses"])
		self.assertIn("A2A Task", options["doctypes"])
		self.assertIn(d.worker_agent, options["workers"])

	def test_the_task_monitor_filters_by_agent(self):
		"""On a busy site the monitor is mostly one agent's traffic at a time."""
		mine = make_agent_configuration(a2a_exposed=1)
		task = frappe.get_doc({
			"doctype": "A2A Task",
			"direction": "Internal",
			"state": "working",
			"agent_configuration": mine.name,
		})
		task.flags.ignore_links = True
		task.insert(ignore_permissions=True)
		result = a2a_admin_api.list_tasks(agent_configuration=mine.name)
		self.assertTrue(result["tasks"])
		self.assertTrue(all(t["agent_configuration"] == mine.name for t in result["tasks"]))
		self.assertIn(mine.name, a2a_admin_api.delegation_filter_options()["task_agents"])


class TestCancellingFromTheScreen(FrappeTestCase):
	"""Cancelling is a person's action, reached through the admin screen.

	An agent able to cancel its own hand-offs could cancel its way out of a
	limit it had been given, and those limits are what stand between a loop and
	a bill — so the absence of an agent-facing door is part of the feature, and
	is pinned here rather than left to convention.
	"""

	def tearDown(self):
		frappe.db.rollback()
		super().tearDown()

	def _running(self):
		worker = make_agent_configuration(a2a_exposed=1)
		task = frappe.get_doc({
			"doctype": "A2A Task",
			"direction": "Internal",
			"state": "working",
			"agent_configuration": worker.name,
			"delegation_depth": 1,
			"handoff_count": 1,
		})
		task.flags.ignore_links = True
		task.insert(ignore_permissions=True)
		doc = frappe.new_doc("Agent Delegation")
		doc.update({
			"worker_agent": worker.name,
			"status": "In Progress",
			"a2a_task": task.name,
			"delegation_depth": 1,
			"handoff_count": 1,
		})
		doc.flags.ignore_permissions = True
		doc.flags.ignore_links = True
		doc.insert(ignore_permissions=True)
		return doc

	def test_no_connector_operation_exposes_cancellation(self):
		"""The check that matters: a map cannot draw a shape that cancels a
		delegation, because no operation handler points at it."""
		handlers = frappe.get_all("BPMN Connector Operation", pluck="handler_path")
		self.assertFalse(
			[h for h in handlers if h and "cancel_delegation" in h],
			"cancellation must not be reachable as a connector operation",
		)

	def test_cancelling_returns_what_actually_happened(self):
		"""Not a bare success: 'the worker was stopped' and 'the worker had
		nothing running, so we stopped waiting' are different outcomes, and the
		person cancelling needs to know which they got."""
		d = self._running()
		result = a2a_admin_api.cancel_delegation(d.name, reason="stuck on a dead endpoint")
		self.assertEqual(result["status"], "Cancelled")
		self.assertIn("worker_stopped", result)
		self.assertIn("pass_may_still_be_running", result)
		self.assertIn("stuck on a dead endpoint", result["detail"])

	def test_the_cancelled_delegation_is_listed_as_cancelled(self):
		d = self._running()
		a2a_admin_api.cancel_delegation(d.name)
		row = next(
			r for r in a2a_admin_api.list_delegations()["delegations"] if r["name"] == d.name
		)
		self.assertEqual(row["status"], "Cancelled")

	def test_cancelled_becomes_a_status_you_can_filter_by(self):
		d = self._running()
		a2a_admin_api.cancel_delegation(d.name)
		self.assertIn("Cancelled", a2a_admin_api.delegation_filter_options()["statuses"])
		names = {r["name"] for r in a2a_admin_api.list_delegations(status="Cancelled")["delegations"]}
		self.assertIn(d.name, names)

	def test_the_detail_modal_shows_who_stopped_it(self):
		d = self._running()
		a2a_admin_api.cancel_delegation(d.name)
		detail = a2a_admin_api.delegation_detail(d.name)["delegation"]
		self.assertEqual(detail["cancelled_by"], frappe.session.user)
		self.assertTrue(detail["cancelled_at"])


class TestHandingBackFromTheScreen(FrappeTestCase):
	"""Handing stopped work back is a person's action, like cancelling.

	An agent able to re-delegate its own stopped work could work around any
	limit it was given by simply asking again, so the absence of an agent-facing
	door is part of the feature and is pinned here.
	"""

	def tearDown(self):
		frappe.db.rollback()
		super().tearDown()

	def _stopped(self, **updates):
		worker = make_agent_configuration(a2a_exposed=1)
		task = frappe.get_doc({
			"doctype": "A2A Task", "direction": "Internal", "state": "failed",
			"agent_configuration": worker.name, "delegation_depth": 1, "handoff_count": 1,
		})
		task.flags.ignore_links = True
		task.insert(ignore_permissions=True)
		doc = frappe.new_doc("Agent Delegation")
		doc.update({
			"worker_agent": worker.name, "status": "Needs Review", "a2a_task": task.name,
			"delegation_depth": 1, "handoff_count": 1, "attempt_count": 1,
		})
		doc.update(updates)
		doc.flags.ignore_permissions = True
		doc.flags.ignore_links = True
		doc.insert(ignore_permissions=True)
		return doc

	def test_no_connector_operation_exposes_handing_work_back(self):
		"""A map must not be able to draw a shape that re-delegates."""
		handlers = frappe.get_all("BPMN Connector Operation", pluck="handler_path")
		self.assertFalse([h for h in handlers if h and "redelegate" in h])

	def test_handing_back_returns_what_happened(self):
		d = self._stopped()
		result = a2a_admin_api.redelegate_delegation(d.name)
		self.assertIn(result["state"], ("started", "failed"))
		self.assertEqual(result["attempt"], 2)
		self.assertEqual(result["by_a_person"], 1)
		self.assertIn("deadline_minutes", result)

	def test_the_screen_shows_it_live_again(self):
		d = self._stopped()
		a2a_admin_api.redelegate_delegation(d.name)
		row = next(r for r in a2a_admin_api.list_delegations()["delegations"] if r["name"] == d.name)
		self.assertEqual(row["status"], "In Progress")
		self.assertFalse(row["stopped_reason"])

	def test_the_modal_shows_who_handed_it_back(self):
		d = self._stopped()
		a2a_admin_api.redelegate_delegation(d.name)
		detail = a2a_admin_api.delegation_detail(d.name)["delegation"]
		self.assertEqual(detail["redelegated_by"], frappe.session.user)
		self.assertEqual(detail["manual_attempt_count"], 1)
		self.assertTrue(detail["deadline_restarted"])

	def test_the_confirm_step_changes_nothing(self):
		"""Called on a delegation whose limit has not moved, it must report and
		stop — the person decides."""
		agent = make_agent_configuration()
		agent.db_set("max_task_handoffs", 10, update_modified=False)
		d = self._stopped(
			delegating_agent=agent.name, stopped_reason="max_task_handoffs", limit_value=10
		)
		result = a2a_admin_api.redelegate_delegation(d.name)
		self.assertEqual(result["state"], "confirm")
		self.assertEqual(frappe.db.get_value("Agent Delegation", d.name, "status"), "Needs Review")

	def test_acknowledging_the_warning_goes_ahead(self):
		agent = make_agent_configuration()
		agent.db_set("max_task_handoffs", 10, update_modified=False)
		d = self._stopped(
			delegating_agent=agent.name, stopped_reason="max_task_handoffs", limit_value=10
		)
		a2a_admin_api.redelegate_delegation(d.name, acknowledged=1)
		self.assertEqual(frappe.db.get_value("Agent Delegation", d.name, "status"), "In Progress")
