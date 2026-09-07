# Copyright (c) 2026, one-fm and contributors
# WI-001363 (5-03): Create Eval Case from Run action.

from __future__ import annotations

import frappe
from frappe.tests.utils import FrappeTestCase

from one_bpmn.agents.eval_case_factory import (
	create_eval_case_from_run,
	get_run_steps_for_case_picker,
)

test_ignore = ["BPMN Process Instance", "AI Eval Suite"]


def _process_owner():
	"""A Process Owner who is deliberately NOT a System Manager."""
	email = "factory-owner@example.com"
	if not frappe.db.exists("User", email):
		user = frappe.get_doc({
			"doctype": "User",
			"email": email,
			"first_name": "Factory",
			"send_welcome_email": 0,
		})
		user.flags.ignore_permissions = True
		user.insert(ignore_permissions=True)
		user.add_roles("Process Owner")
	roles = set(frappe.get_roles(email))
	assert "System Manager" not in roles, "fixture must not be a System Manager"
	return email


def _agent_configuration():
	"""AI Eval Suite.agent_configuration is mandatory (WI-001751)."""
	suffix = frappe.generate_hash(length=6)
	doc = frappe.get_doc({
		"doctype": "AI Agent Configuration",
		"agent_name": f"_Factory Agent {suffix}",
		"agent_id": f"_factory_agent_{suffix}",
		"agent_framework": "Direct API",
		"agent_type": "Background",
		"enabled": 1,
		"lifecycle_status": "Live",
		"system_prompt": "test",
	})
	doc.flags.ignore_mandatory = True
	doc.flags.ignore_links = True
	return doc.insert(ignore_permissions=True).name


def _owned_process_model(owner):
	"""A BPMN Process Model whose Process is owned by *owner*.

	This is the chain eval_permissions walks: BPMN Process Model.process_name ->
	Process.process_owner. It is what lets a non-System-Manager reach both their
	own suites and their own runs.
	"""
	suffix = frappe.generate_hash(length=6)
	process = frappe.get_doc({
		"doctype": "Process",
		"process_name": f"_Factory Process {suffix}",
		"process_owner": owner,
	})
	process.flags.ignore_mandatory = True
	process.flags.ignore_links = True
	process.insert(ignore_permissions=True)

	model = frappe.get_doc({
		"doctype": "BPMN Process Model",
		"title": f"_Factory Model {suffix}",
		"process_id": f"_factory_model_{suffix}",
		"process_name": process.name,
	})
	model.flags.ignore_mandatory = True
	model.flags.ignore_links = True
	model.insert(ignore_permissions=True)
	return model.name


def _suite(owner=None):
	"""A process-less Direct suite. With no process_model the eval permission
	query falls back to suite.owner, so setting owner is what grants write."""
	doc = frappe.get_doc({
		"doctype": "AI Eval Suite",
		"title": "_Factory Suite " + frappe.generate_hash(length=6),
		"agent_configuration": _agent_configuration(),
		"eval_type": "Direct",
	})
	doc.flags.ignore_mandatory = True
	doc.flags.ignore_links = True
	doc.insert(ignore_permissions=True)
	if owner:
		frappe.db.set_value("AI Eval Suite", doc.name, "owner", owner, update_modified=False)
	return doc.name


def _provider():
	name = "Factory Test Provider"
	if not frappe.db.exists("AI Provider", name):
		frappe.get_doc(
			{
				"doctype": "AI Provider",
				"provider": name,
				"provider_type": "OpenAI",
				"api_key": "x",
				"enabled": 1,
			}
		).insert(ignore_permissions=True)
	return name


def _instance():
	doc = frappe.get_doc(
		{
			"doctype": "BPMN Process Instance",
			"process_id": f"fac-{frappe.generate_hash(length=6)}",
			"status": "Active",
		}
	)
	doc.flags.ignore_mandatory = True
	doc.insert(ignore_permissions=True, ignore_mandatory=True)
	return doc.name


def _run(element_type="task", status="Success", final_output="the answer", with_steps=True,
		process_model=None):
	run = frappe.get_doc(
		{
			"doctype": "AI Agent Run",
			"instance": _instance(),
			"bpmn_id": "Task_1",
			"process_model": process_model or "",
			"element_type": element_type,
			"backend": "direct_api",
			"provider": _provider(),
			"model": "m",
			"status": status,
			"started_at": frappe.utils.now_datetime(),
			"final_output": final_output,
		}
	)
	run.insert(ignore_permissions=True)
	if with_steps:
		for idx, (role, content) in enumerate(
			[("system", "sys prompt"), ("user", "usr prompt"), ("assistant", final_output)]
		):
			frappe.get_doc(
				{
					"doctype": "AI Agent Step",
					"run": run.name,
					"step_index": idx,
					"role": role,
					"content": content,
					"cost": 0,
				}
			).insert(ignore_permissions=True)
	return run


class TestEvalCaseFactory(FrappeTestCase):
	@classmethod
	def setUpClass(cls):
		super().setUpClass()
		frappe.set_user("Administrator")

	# ── Scenario 1: plain task run pre-fills prompts + expected_output ──

	def test_plain_task_run_prefills_case(self):
		run = _run()
		case_name = create_eval_case_from_run(run.name)
		case = frappe.get_doc("AI Eval Case", case_name)
		self.assertEqual(case.source_run, run.name)
		self.assertEqual(case.input_user_prompt, "usr prompt")
		self.assertEqual(case.expected_output, "the answer")
		# WI-001751 moved provider / model / system prompt off the case and onto
		# the suite's agent. Assert against the doctype's fields, not the loaded
		# document: Frappe drops the DocField but never the table column, so a
		# removed field still surfaces on the instance carrying its old value.
		fields = {df.fieldname for df in frappe.get_meta("AI Eval Case").fields}
		for gone in ("provider", "model", "backend", "input_system_prompt"):
			self.assertNotIn(gone, fields, f"{gone} should no longer be a field on AI Eval Case")

	def test_error_run_allowed(self):
		run = _run(status="Error")
		case_name = create_eval_case_from_run(run.name)
		self.assertTrue(frappe.db.exists("AI Eval Case", case_name))

	def test_case_carries_the_runs_context_document(self):
		"""A map-path eval starts the map against the document the case names, so
		capture must carry the source run's instance context onto the case —
		otherwise every captured case errors asking for an input_context."""
		todo = frappe.get_doc(
			{
				"doctype": "ToDo",
				"description": "_Test factory subject",
				"allocated_to": frappe.session.user,
			}
		).insert(ignore_permissions=True)
		run = _run()
		frappe.db.set_value(
			"BPMN Process Instance", run.instance,
			{"context_doctype": "ToDo", "context_docname": todo.name},
			update_modified=False,
		)

		case = frappe.get_doc("AI Eval Case", create_eval_case_from_run(run.name))
		self.assertEqual(
			frappe.parse_json(case.input_context),
			{"context_doctype": "ToDo", "context_docname": todo.name},
		)

	def test_case_from_a_run_with_no_instance_context_has_no_input_context(self):
		"""A standalone run (no document behind it) must not invent one."""
		run = _run()
		case = frappe.get_doc("AI Eval Case", create_eval_case_from_run(run.name))
		self.assertFalse(case.input_context)

	def test_running_run_rejected(self):
		run = _run(status="Running", with_steps=False)
		with self.assertRaises(frappe.ValidationError):
			create_eval_case_from_run(run.name)

	# ── Scenario 2: subprocess run requires a Step choice ──

	def test_subprocess_run_requires_step(self):
		run = _run(element_type="subprocess")
		with self.assertRaises(frappe.ValidationError):
			create_eval_case_from_run(run.name)

	# ── Scenario 3: expected_output pre-filled from the chosen tool call ──

	def test_subprocess_case_from_tool_call(self):
		run = _run(element_type="subprocess", final_output="")
		if not frappe.db.exists("DocType", "AI Agent Tool Call"):
			self.skipTest("AI Agent Tool Call doctype not on this branch")
		step = frappe.get_doc(
			{
				"doctype": "AI Agent Step",
				"run": run.name,
				"step_index": 3,
				"role": "tool",
				"content": "",
				"cost": 0,
			}
		)
		step.append(
			"tool_calls",
			{"tool_name": "lookup", "tool_result": "the tool result", "status": "Success"},
		)
		step.append(
			"tool_calls",
			{"tool_name": "notify", "tool_result": "sent", "status": "Success"},
		)
		step.insert(ignore_permissions=True)

		call = frappe.get_all(
			"AI Agent Tool Call",
			filters={"parent": step.name, "tool_name": "lookup"},
			pluck="name",
		)[0]
		case_name = create_eval_case_from_run(run.name, step_name=step.name, tool_call_name=call)
		case = frappe.get_doc("AI Eval Case", case_name)
		self.assertEqual(case.expected_output, "the tool result")

	def test_subprocess_step_with_multiple_calls_requires_pick(self):
		run = _run(element_type="subprocess", final_output="")
		if not frappe.db.exists("DocType", "AI Agent Tool Call"):
			self.skipTest("AI Agent Tool Call doctype not on this branch")
		step = frappe.get_doc(
			{"doctype": "AI Agent Step", "run": run.name, "step_index": 3, "role": "tool", "cost": 0}
		)
		step.append("tool_calls", {"tool_name": "a", "tool_result": "ra", "status": "Success"})
		step.append("tool_calls", {"tool_name": "b", "tool_result": "rb", "status": "Success"})
		step.insert(ignore_permissions=True)
		with self.assertRaises(frappe.ValidationError):
			create_eval_case_from_run(run.name, step_name=step.name)  # ambiguous

	# ── Scenario 4: source_run links back ──

	def test_source_run_links_back(self):
		run = _run()
		case_name = create_eval_case_from_run(run.name)
		self.assertEqual(
			frappe.db.get_value("AI Eval Case", case_name, "source_run"), run.name
		)

	# ── Permission gate ──
	# The whole action used to be only_for("System Manager") while the UI calling
	# it (the Evals "From run" dialog, and the desk buttons) was not role-gated,
	# so a Process Owner saw the button and got a PermissionError. Authoring a
	# case now costs write on the target suite — matching eval_api.create_eval_case
	# — and only falls back to System Manager when there is no suite to scope on.

	def test_case_from_own_process_run_needs_no_system_manager(self):
		user = _process_owner()
		model = _owned_process_model(user)
		run = _run(process_model=model)
		suite = _suite(owner=user)
		try:
			frappe.set_user(user)
			case_name = create_eval_case_from_run(run.name, suite=suite)
			self.assertEqual(frappe.db.get_value("AI Eval Case", case_name, "suite"), suite)
		finally:
			frappe.set_user("Administrator")

	def test_case_from_someone_elses_run_is_refused(self):
		"""AI Agent Run holds every prompt on the platform, so owning the
		destination suite must not be enough to read an unrelated run."""
		user = _process_owner()
		suite = _suite(owner=user)
		run = _run()  # no process_model -> nothing scopes it to this user
		try:
			frappe.set_user(user)
			with self.assertRaises(frappe.PermissionError):
				create_eval_case_from_run(run.name, suite=suite)
		finally:
			frappe.set_user("Administrator")

	def test_suiteless_case_from_run_still_requires_system_manager(self):
		"""A case with no suite has no permission anchor — it is invisible to the
		suite views and unscoped by the eval permission query — so it stays
		System-Manager-only rather than becoming an unscoped write."""
		user = _process_owner()
		run = _run(process_model=_owned_process_model(user))
		try:
			frappe.set_user(user)
			with self.assertRaises(frappe.PermissionError):
				create_eval_case_from_run(run.name)
		finally:
			frappe.set_user("Administrator")

	def test_step_picker_needs_no_system_manager(self):
		user = _process_owner()
		run = _run(element_type="subprocess", process_model=_owned_process_model(user))
		try:
			frappe.set_user(user)
			steps = get_run_steps_for_case_picker(run.name)
			self.assertEqual(len(steps), 3)
		finally:
			frappe.set_user("Administrator")
