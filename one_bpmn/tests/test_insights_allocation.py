# Copyright (c) 2026, one-fm and contributors
"""The cost allocation report: the rollup finance charges departments from.

Every number here is one a department gets billed for, so the cases are the
ones where a wrong answer still looks plausible: a parent whose total drifts
from its children, spend that belongs to the other axis counted twice, a run
with nothing to bill it to quietly inflating a department, and eval traffic
priced as production.

Fixtures are written straight to the tables. The report only reads, and a real
insert of a BPMN Process Instance or an AI Agent Run starts an engine.
"""

from __future__ import annotations

import json
from io import BytesIO
from unittest.mock import patch

import frappe
from frappe.tests.utils import FrappeTestCase
from frappe.utils import flt

from one_bpmn.api.insights_api import export_cost_allocation, get_cost_allocation

OPS = "Alloc Ops - T"
FIN = "Alloc Fin - T"
HR = "Alloc HR - T"

OWNER_OPS = "alloc-ops-owner@example.com"
OWNER_FIN = "alloc-fin-owner@example.com"

ROSTER = "Alloc Roster T"
PAYROLL = "Alloc Payroll T"
ROSTER_MODEL = "Alloc Roster Model T"
PAYROLL_MODEL = "Alloc Payroll Model T"

PROC_INSTANCE = "ALLOC-T-INST-PROC"
SEAT_ROLE = "Chat User"
TITLE_MARK = "ALLOC T SECRET"

# One calendar month, starting on a Wednesday so the first week bucket has to
# be clipped to the range rather than reaching back to its Monday.
A_FROM, A_TO = "2015-06-03", "2015-06-21"
# The window the prior-period comparison reads: 2015-05-15 to 2015-06-02.
# Three months, for the month grain.
C_FROM, C_TO = "2015-04-01", "2015-06-30"
# A month of chat only, with enough users for one department to overflow.
B_FROM, B_TO = "2015-08-01", "2015-08-31"

NOW = "2015-01-01 00:00:00"


def _insert(doctype: str, name: str, owner: str = "Administrator", **values) -> str:
	doc = frappe.get_doc({"doctype": doctype, "name": name, **values})
	doc.creation = doc.modified = NOW
	doc.owner = doc.modified_by = owner
	doc.db_insert()
	return name


def _user(email: str) -> str:
	return _insert("User", email, email=email, first_name=email.split("@")[0],
	               enabled=1, user_type="System User")


def _employee(user: str, department: str) -> str:
	return _insert("Employee", f"ALLOC-T-EMP-{user}", employee_name=user,
	               user_id=user, department=department, status="Active")


def _run(name: str, started_at: str, cost: float, *, instance: str = PROC_INSTANCE,
         process_model: str = ROSTER_MODEL, origin: str = "production",
         tokens: int = 1000, model: str = "") -> str:
	return _insert("AI Agent Run", name, instance=instance, process_model=process_model,
	               origin=origin, status="Success", started_at=started_at,
	               total_tokens=tokens, estimated_cost=cost, model=model)


def _conversation(name: str, user: str, agent_mode: str, participants: list = None) -> str:
	_insert("Chat Conversation", name, owner=user, agent_mode=agent_mode,
	        title=f"{TITLE_MARK} {name}", status="Open")
	for idx, participant in enumerate(participants or [user], start=1):
		_insert("Chat Participant", f"{name}-P{idx}", user=participant, parent=name,
		        parenttype="Chat Conversation", parentfield="participants", idx=idx)
	_insert("BPMN Process Instance", f"{name}-INST", process_model=ROSTER_MODEL,
	        status="Completed", initiated_by=user,
	        context_doctype="Chat Conversation", context_docname=name)
	return f"{name}-INST"


def _chat_run(name: str, instance: str, started_at: str, cost: float, **kwargs) -> str:
	return _run(name, started_at, cost, instance=instance, process_model="", **kwargs)


class TestInsightsAllocation(FrappeTestCase):
	@classmethod
	def setUpClass(cls):
		super().setUpClass()
		_wipe()
		cls._build()
		frappe.db.commit()

	@classmethod
	def tearDownClass(cls):
		_wipe()
		frappe.db.commit()
		super().tearDownClass()

	def tearDown(self):
		frappe.set_user("Administrator")

	# -- fixtures ----------------------------------------------------------
	@classmethod
	def _build(cls):
		for role in (SEAT_ROLE,):
			_insert("Role", role, role_name=role, disabled=0)

		# 41 people could chat; 27 of them do, in the August window.
		cls.chat_users = [f"alloc-t-u{i}@example.com" for i in range(1, 42)]
		for user in cls.chat_users:
			_user(user)
			_insert("Has Role", f"ALLOC-T-HR-{user}", role=SEAT_ROLE, parent=user,
			        parenttype="User", parentfield="roles", idx=1)

		for user in (OWNER_OPS, OWNER_FIN):
			_user(user)
		_employee(OWNER_OPS, OPS)
		_employee(OWNER_FIN, FIN)
		_employee(cls.chat_users[0], OPS)
		_employee(cls.chat_users[1], FIN)
		for user in cls.chat_users[2:11]:
			_employee(user, HR)

		for process, owner in ((ROSTER, OWNER_OPS), (PAYROLL, OWNER_FIN)):
			_insert("Process", process, process_name=process, description=process,
			        process_owner=owner)
		for model, process in ((ROSTER_MODEL, ROSTER), (PAYROLL_MODEL, PAYROLL)):
			_insert("BPMN Process Model", model, title=model, process_id=model,
			        version=1, process_name=process, is_active=1)
		_insert("BPMN Process Instance", PROC_INSTANCE, process_model=ROSTER_MODEL,
		        status="Completed", initiated_by=OWNER_OPS)

		# Process axis, window A: Operations 16.00, Finance 4.00.
		_run("ALLOC-T-R1", "2015-06-04 09:00:00", 10.0)
		_run("ALLOC-T-R2", "2015-06-04 11:00:00", 6.0)
		_run("ALLOC-T-R3", "2015-06-10 09:00:00", 4.0, process_model=PAYROLL_MODEL)
		# Prior period, for the comparison: Operations only.
		_run("ALLOC-T-R0", "2015-05-20 09:00:00", 8.0)
		# Nothing to bill these to, or not production traffic.
		_run("ALLOC-T-RNOMODEL", "2015-06-05 09:00:00", 2.5, process_model="",
		     model="alloc-t-unpriced")
		_run("ALLOC-T-REVAL", "2015-06-06 09:00:00", 1.0, origin="eval")

		# Chat axis, window A: two users, two departments, two agents each,
		# plus a blank agent_mode and a two-participant conversation.
		c1 = _conversation("ALLOC-T-C1", cls.chat_users[0], "Logix",
		                   participants=[cls.chat_users[0], cls.chat_users[1]])
		c2 = _conversation("ALLOC-T-C2", cls.chat_users[0], "Docu")
		c3 = _conversation("ALLOC-T-C3", cls.chat_users[1], "Logix")
		c4 = _conversation("ALLOC-T-C4", cls.chat_users[1], "Docu")
		c5 = _conversation("ALLOC-T-C5", cls.chat_users[0], "")
		# Two runs in one conversation: a parent counts conversations, not runs.
		_chat_run("ALLOC-T-CR1A", c1, "2015-06-04 09:00:00", 2.0)
		_chat_run("ALLOC-T-CR1B", c1, "2015-06-11 09:00:00", 1.0)
		_chat_run("ALLOC-T-CR2", c2, "2015-06-04 10:00:00", 1.0)
		_chat_run("ALLOC-T-CR3", c3, "2015-06-05 09:00:00", 2.0)
		_chat_run("ALLOC-T-CR4", c4, "2015-06-05 10:00:00", 0.5)
		_chat_run("ALLOC-T-CR5", c5, "2015-06-09 09:00:00", 0.25)

		# Chat axis, window B: 27 active users, 9 of them in one department.
		costs = {0: 20.0, 1: 15.0}
		for i in range(2, 11):
			costs[i] = float(11 - i)  # 9.0 down to 1.0
		for i in range(11, 27):
			costs[i] = 0.5
		for i in range(27):
			user = cls.chat_users[i]
			instance = _conversation(f"ALLOC-T-B{i}", user, "Logix")
			_chat_run(f"ALLOC-T-BR{i}", instance, "2015-08-05 09:00:00", costs[i])

	# -- process axis ------------------------------------------------------
	def test_department_tree_nests_owner_then_process(self):
		tree = _tree(group_by="department")
		self.assertEqual([n["label"] for n in tree], [OPS, FIN])
		self.assertEqual([n["kind"] for n in tree], ["department", "department"])
		ops = tree[0]
		self.assertEqual([c["kind"] for c in ops["children"]], ["owner"])
		self.assertEqual(ops["children"][0]["key"], OWNER_OPS)
		self.assertEqual([g["kind"] for g in ops["children"][0]["children"]], ["process"])
		self.assertEqual(ops["children"][0]["children"][0]["label"], ROSTER)

	def test_every_level_is_sorted_by_cost_and_adds_up(self):
		tree = _tree(group_by="department")
		self.assertEqual([flt(n["cost"], 2) for n in tree], [16.0, 4.0])
		self.assertAlmostEqual(sum(n["share"] for n in tree), 100.0, delta=0.2)
		for node in tree:
			self._assert_parent_equals_children(node)

	def _assert_parent_equals_children(self, node):
		if not node["children"]:
			return
		self.assertAlmostEqual(node["cost"], sum(c["cost"] for c in node["children"]), places=6)
		self.assertEqual(node["runs"], sum(c["runs"] for c in node["children"]))
		costs = [c["cost"] for c in node["children"]]
		self.assertEqual(costs, sorted(costs, reverse=True))
		for child in node["children"]:
			self._assert_parent_equals_children(child)

	def test_group_by_owner_puts_owners_on_top_with_their_department(self):
		tree = _tree(group_by="owner")
		self.assertEqual([n["kind"] for n in tree], ["owner", "owner"])
		self.assertEqual(tree[0]["key"], OWNER_OPS)
		self.assertEqual(tree[0]["department"], OPS)
		self.assertEqual([c["kind"] for c in tree[0]["children"]], ["process"])

	def test_group_by_process_puts_processes_on_top_over_their_owner(self):
		tree = _tree(group_by="process")
		self.assertEqual([n["kind"] for n in tree], ["process", "process"])
		self.assertEqual(tree[0]["label"], ROSTER)
		self.assertEqual(tree[0]["department"], OPS)
		self.assertEqual([c["key"] for c in tree[0]["children"]], [OWNER_OPS])

	def test_prior_period_is_the_window_before_of_equal_length(self):
		report = _report()
		self.assertEqual(report["previous"]["from_date"], "2015-05-15")
		self.assertEqual(report["previous"]["to_date"], "2015-06-02")
		self.assertEqual(flt(report["previous"]["cost"], 2), 8.0)
		self.assertEqual(report["previous"]["users"], 1)
		self.assertEqual(report["previous"]["conversations"], 0)

	def test_a_node_with_no_prior_spend_has_no_percentage(self):
		ops, fin = _tree(group_by="department")
		self.assertEqual(flt(ops["previous_cost"], 2), 8.0)
		self.assertEqual(ops["delta"], 1.0)  # 16.00 against 8.00
		self.assertEqual(flt(fin["previous_cost"], 2), 0.0)
		self.assertIsNone(fin["delta"])

	def test_one_month_buckets_by_week_from_the_first_day_asked_for(self):
		report = _report()
		self.assertEqual(report["grain"], "week")
		self.assertEqual(report["buckets"], ["2015-06-03", "2015-06-08", "2015-06-15"])
		self.assertEqual(report["months"], ["2015-06"])

	def test_several_months_bucket_by_month_and_fill_the_empty_ones(self):
		report = _report(from_date=C_FROM, to_date=C_TO)
		self.assertEqual(report["grain"], "month")
		self.assertEqual(report["months"], ["2015-04", "2015-05", "2015-06"])
		by_month = report["tree"][0]["by_month"]
		self.assertEqual(sorted(by_month), ["2015-04", "2015-05", "2015-06"])
		self.assertEqual(flt(by_month["2015-04"], 2), 0.0)
		self.assertEqual(flt(by_month["2015-05"], 2), 8.0)

	def test_eval_runs_are_priced_apart_from_production(self):
		production = _report()
		self.assertEqual(flt(production["totals"]["cost"], 2), 20.0)

		every = _report(origin="all")
		self.assertEqual(flt(every["totals"]["cost"], 2), 21.0)
		self.assertEqual(flt(every["period_totals"]["cost"], 2),
		                 flt(production["period_totals"]["cost"] + 1.0, 2))

		evals = _report(origin="eval")
		self.assertEqual(flt(evals["totals"]["cost"], 2), 1.0)
		self.assertEqual(flt(evals["period_totals"]["cost"], 2), 1.0)

	def test_a_run_with_no_process_is_left_unallocated_not_hidden(self):
		report = _report()
		self.assertEqual(flt(report["totals"]["cost"], 2), 20.0)
		# 20.00 allocated + 2.50 with no process + 6.75 chat.
		self.assertEqual(flt(report["period_totals"]["cost"], 2), 29.25)
		unallocated = (report["period_totals"]["cost"] - report["totals"]["cost"]
		               - report["totals"]["other_axis_cost"])
		self.assertEqual(flt(unallocated, 2), 2.5)

	def test_chat_spend_is_named_as_the_other_axis_not_dropped(self):
		report = _report()
		self.assertEqual(flt(report["totals"]["other_axis_cost"], 2), 6.75)
		self.assertEqual(flt(_report(axis="chat_user")["totals"]["other_axis_cost"], 2), 22.5)

	# -- chat axis ---------------------------------------------------------
	def test_chat_tree_nests_user_then_agent(self):
		tree = _tree(axis="chat_user", group_by="department")
		self.assertEqual([n["label"] for n in tree], [OPS, FIN])
		ops = tree[0]
		self.assertEqual(flt(ops["cost"], 2), 4.25)
		user = ops["children"][0]
		self.assertEqual(user["kind"], "user")
		self.assertEqual([a["label"] for a in user["children"]], ["Logix", "Docu", "General Chat"])
		for key in ("conversations", "runs", "tokens", "cost",
		            "avg_cost_per_conversation", "share", "previous_cost", "delta"):
			self.assertIn(key, user)

	def test_a_parent_counts_conversations_not_its_children_runs(self):
		ops = _tree(axis="chat_user", group_by="department")[0]
		self.assertEqual(ops["conversations"], 3)
		self.assertEqual(ops["runs"], 4)
		self.assertEqual(ops["children"][0]["children"][0]["conversations"], 1)

	def test_chat_group_by_user_and_by_agent(self):
		users = _tree(axis="chat_user", group_by="user")
		self.assertEqual([n["kind"] for n in users], ["user", "user"])
		self.assertEqual(users[0]["department"], OPS)
		self.assertEqual({c["kind"] for c in users[0]["children"]}, {"agent"})

		agents = _tree(axis="chat_user", group_by="agent")
		self.assertEqual([n["label"] for n in agents], ["Logix", "Docu", "General Chat"])
		self.assertEqual([c["kind"] for c in agents[0]["children"]], ["user", "user"])

	def test_a_crowded_department_lists_the_heaviest_and_counts_the_rest(self):
		tree = _tree(axis="chat_user", group_by="department", from_date=B_FROM, to_date=B_TO)
		hr = next(n for n in tree if n["label"] == HR)
		self.assertEqual(hr["users"], 9)
		self.assertEqual([c["kind"] for c in hr["children"]],
		                 ["user"] * 5 + ["more"])
		rest = hr["children"][-1]
		self.assertEqual(rest["count"], 4)
		self.assertEqual(rest["children"], [])
		self.assertEqual(flt(rest["cost"], 2), 10.0)  # 4 + 3 + 2 + 1
		self.assertAlmostEqual(hr["cost"], sum(c["cost"] for c in hr["children"]), places=6)

	def test_chat_totals_report_seats_against_the_people_using_them(self):
		totals = _report(axis="chat_user", from_date=B_FROM, to_date=B_TO)["totals"]
		self.assertEqual(totals["active_users"], 27)
		self.assertEqual(totals["seats"], 41)
		self.assertEqual(totals["conversations"], 27)
		self.assertEqual(flt(totals["cost"], 2), 88.0)
		self.assertEqual(flt(totals["avg_cost_per_user"], 4), flt(88.0 / 27, 4))
		self.assertEqual(flt(totals["avg_cost_per_conversation"], 4), flt(88.0 / 27, 4))
		# 20 + 15 + 9 + 8 + 7 of 88.00.
		self.assertEqual(totals["top5_share"], flt(59.0 / 88.0 * 100, 2))

	def test_agents_are_listed_by_cost_for_the_donut(self):
		agents = _report(axis="chat_user")["agents"]
		self.assertEqual([a["label"] for a in agents], ["Logix", "Docu", "General Chat"])
		self.assertEqual(flt(agents[0]["cost"], 2), 5.0)
		self.assertAlmostEqual(sum(a["share"] for a in agents), 100.0, delta=0.2)

	def test_a_conversation_with_no_agent_is_the_general_assistant(self):
		agents = [a["key"] for a in _report(axis="chat_user")["agents"]]
		self.assertIn("General Chat", agents)
		self.assertNotIn("", agents)

	def test_a_shared_conversation_is_charged_to_its_owner_alone(self):
		users = _tree(axis="chat_user", group_by="user")
		owner = next(n for n in users if n["key"] == self.chat_users[0])
		other = next(n for n in users if n["key"] == self.chat_users[1])
		self.assertEqual(flt(owner["cost"], 2), 4.25)  # both runs of the shared chat
		self.assertEqual(flt(other["cost"], 2), 2.5)

	def test_conversation_titles_never_leave_the_detail_rows(self):
		report = _report(axis="chat_user")
		for key in ("tree", "agents", "totals"):
			self.assertNotIn(TITLE_MARK, json.dumps(report[key]))
		self.assertIn(TITLE_MARK, json.dumps(report["rows"]))

	# -- contract ----------------------------------------------------------
	def test_one_contract_remains(self):
		"""The flat table's totals keys are gone; rows stay for the export."""
		report = _report()
		for key in ("rows", "period_totals", "models_missing_pricing", "totals", "tree"):
			self.assertIn(key, report)
		for key in ("runs", "tokens", "cost", "avg_cost_per_run", "other_axis_cost", "processes", "top_process"):
			self.assertIn(key, report["totals"])
		for legacy in ("people", "departments"):
			self.assertNotIn(legacy, report["totals"])
		chat = _report(axis="chat_user")["totals"]
		for legacy in ("people", "departments"):
			self.assertNotIn(legacy, chat)
		self.assertIn("alloc-t-unpriced", report["models_missing_pricing"])
		self.assertEqual(sorted(report["rows"][0]),
		                 ["cost", "department", "month", "person", "runs", "subject",
		                  "subject_label", "tokens"])

	def test_only_a_system_manager_may_read_or_export_it(self):
		# frappe.only_for waves everything through while in_test is set, so the
		# gate has to be asked the way a request asks it.
		frappe.set_user("Guest")
		with patch.dict(frappe.local.flags, {"in_test": False}):
			self.assertRaises(frappe.PermissionError, get_cost_allocation, A_FROM, A_TO)
			self.assertRaises(frappe.PermissionError, export_cost_allocation, A_FROM, A_TO)

	def test_the_export_carries_the_summary_and_the_detail(self):
		import openpyxl

		export_cost_allocation(from_date=C_FROM, to_date=C_TO, fmt="xlsx")
		book = openpyxl.load_workbook(BytesIO(frappe.response["filecontent"]))
		self.assertEqual(book.sheetnames, ["Summary", "Detail"])

		summary = [[c.value for c in row] for row in book["Summary"].rows]
		self.assertEqual(summary[0][0], "Level")
		self.assertEqual(summary[0][-3:], ["2015-04", "2015-05", "2015-06"])
		self.assertEqual([r[0] for r in summary[1:4]], ["Department", "Owner", "Process"])
		self.assertEqual(summary[-1][0], "Total")
		self.assertEqual(flt(summary[-1][5], 2), 28.0)  # the window reaches into May
		self.assertEqual(book["Detail"].cell(row=1, column=1).value, "Month")


def _report(axis="process_owner", group_by=None, from_date=A_FROM, to_date=A_TO,
            origin="production") -> dict:
	return get_cost_allocation(from_date=from_date, to_date=to_date, axis=axis,
	                           group_by=group_by, origin=origin)


def _tree(**kwargs) -> list:
	return _report(**kwargs)["tree"]


def _wipe():
	"""Fixtures are written past the ORM, so they are removed the same way."""
	like = ("like", "ALLOC-T-%")
	frappe.db.delete("AI Agent Run", {"name": like})
	frappe.db.delete("Chat Participant", {"name": like})
	frappe.db.delete("Chat Conversation", {"name": like})
	frappe.db.delete("BPMN Process Instance", {"name": ("in", [PROC_INSTANCE])})
	frappe.db.delete("BPMN Process Instance", {"name": like})
	frappe.db.delete("Has Role", {"name": like})
	frappe.db.delete("Employee", {"name": like})
	frappe.db.delete("User", {"name": ("like", "alloc-t-u%@example.com")})
	frappe.db.delete("User", {"name": ("in", [OWNER_OPS, OWNER_FIN])})
	frappe.db.delete("BPMN Process Model", {"name": ("in", [ROSTER_MODEL, PAYROLL_MODEL])})
	frappe.db.delete("Process", {"name": ("in", [ROSTER, PAYROLL])})
	frappe.db.delete("Role", {"name": ("in", [SEAT_ROLE])})
