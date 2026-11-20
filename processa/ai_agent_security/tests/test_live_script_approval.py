# Copyright (c) 2026, one-fm and contributors
"""Live script tasks are approved for what they use, and the old Server Script approval is gone."""

from contextlib import redirect_stdout
from io import StringIO
from itertools import pairwise
from unittest.mock import patch

import frappe
from frappe.tests.utils import FrappeTestCase

from processa.ai_agent_security.code_checks.script_categories import clear_category_cache
from processa.api.deploy import compile_process_model
from processa.api.server_scripts import create_server_script, update_server_script
from processa.patches.v1_0 import (
	approve_live_script_tasks,
	rename_stored_one_bpmn_paths,
	repath_eval_module_imports,
	repath_observability_module_imports,
	repath_skill_tool_imports,
	repath_stored_imports_to_processa_modules,
	seed_script_import_categories,
)
from processa.processa_engine.engine import check_server_script

FLAGGED = "Live Approval Flagged"
CLEAN = "Live Approval Clean"
FLAGGED_BODY = (
	"frappe.db.set_value('ToDo', 'x', 'status', 'Open')\n"
	"frappe.sendmail(recipients=['a@example.com'], subject='s', message='m')\n"
)
APPROVAL_FIELDS = (
	"processa_approval_section",
	"processa_allowed_modules",
	"processa_approved",
	"processa_approved_by",
	"processa_approved_on",
	"processa_pending_review",
	"processa_approved_hash",
)


class TestApproveLiveScriptTasks(FrappeTestCase):
	def setUp(self):
		super().setUp()
		clear_category_cache()
		seed_script_import_categories.execute()
		self._script(FLAGGED, FLAGGED_BODY)
		self._script(CLEAN, "result['x'] = 1")
		self.first = self._map("Live Approval Process A", "live_approval_a", FLAGGED, CLEAN)
		self.second = self._map("Live Approval Process B", "live_approval_b", FLAGGED)

	def tearDown(self):
		frappe.db.rollback()
		clear_category_cache()
		super().tearDown()

	def _script(self, name, body):
		if frappe.db.exists("Server Script", name):
			frappe.delete_doc("Server Script", name, force=True)
		frappe.get_doc(
			{
				"doctype": "Server Script",
				"name": name,
				"script_type": "API",
				"api_method": frappe.scrub(name),
				"script": body,
			}
		).insert()

	def _map(self, process, process_id, *scripts):
		if not frappe.db.exists("Process", process):
			frappe.get_doc(
				{
					"doctype": "Process",
					"process_name": process,
					"description": process,
					"process_owner": "Administrator",
				}
			).insert()
		if frappe.db.exists("BPMN Process Model", process):
			frappe.delete_doc("BPMN Process Model", process, force=1)
		model = frappe.new_doc("BPMN Process Model")
		model.update({"name": process, "title": process, "process_id": process_id, "version": 1})
		model.bpmn_xml = _deployable_map(process_id, scripts)
		model.insert()
		frappe.db.set_value("BPMN Process Model", model.name, {"process_name": process, "is_active": 1})
		return process

	def _requests(self, process, script_task, server_script):
		return frappe.get_all(
			"Script Approval Request",
			filters={"process_name": process, "script_task": script_task, "server_script": server_script},
			fields=["name", "status", "source"],
		)

	def test_a_flagged_script_task_gets_one_approved_request_and_no_instance_starts(self):
		instances = frappe.db.count("BPMN Process Instance")
		frappe.flags.in_patch = True
		self.addCleanup(setattr, frappe.flags, "in_patch", False)
		approve_live_script_tasks.execute()
		requests = self._requests(self.first, "t0", FLAGGED)
		self.assertEqual([(r.status, r.source) for r in requests], [("Approved", "Shipped by patch")])
		items = frappe.get_all(
			"Script Approval Request Item", filters={"parent": requests[0].name}, pluck="item_name"
		)
		self.assertEqual(sorted(items), ["frappe.db.set_value", "frappe.sendmail"])
		self.assertEqual(frappe.db.count("BPMN Process Instance"), instances)

	def test_a_script_task_using_only_default_categories_gets_no_request(self):
		approve_live_script_tasks.execute()
		self.assertEqual(self._requests(self.first, "t1", CLEAN), [])

	def test_one_script_on_two_maps_gets_a_request_per_script_task(self):
		approve_live_script_tasks.execute()
		self.assertEqual(len(self._requests(self.first, "t0", FLAGGED)), 1)
		self.assertEqual(len(self._requests(self.second, "t0", FLAGGED)), 1)

	def test_running_the_patch_again_adds_nothing(self):
		approve_live_script_tasks.execute()
		approve_live_script_tasks.execute()
		self.assertEqual(len(self._requests(self.first, "t0", FLAGGED)), 1)

	def test_after_the_patch_a_redeploy_and_a_run_are_not_refused(self):
		approve_live_script_tasks.execute()
		result = compile_process_model(self.first)
		self.assertFalse([w for w in result.get("warnings", []) if w["label"] == "Script awaits review"])
		check_server_script(frappe.get_doc("Server Script", FLAGGED), self.first, "t0")

	def test_a_script_awaiting_review_stays_disabled_and_is_named(self):
		frappe.db.set_value("Server Script", FLAGGED, "disabled", 1)
		output = StringIO()
		with (
			patch.object(approve_live_script_tasks, "awaiting_review", return_value=[FLAGGED]),
			redirect_stdout(output),
		):
			approve_live_script_tasks.execute()
		self.assertIn(FLAGGED, output.getvalue())
		self.assertEqual(frappe.db.get_value("Server Script", FLAGGED, "disabled"), 1)


class TestOldApprovalIsGone(FrappeTestCase):
	def tearDown(self):
		frappe.db.rollback()
		super().tearDown()

	def test_server_script_has_no_processa_approval_fields(self):
		meta = frappe.get_meta("Server Script")
		for fieldname in APPROVAL_FIELDS:
			with self.subTest(fieldname=fieldname):
				self.assertFalse(meta.has_field(fieldname))

	def test_logix_create_and_update_leave_the_script_enabled(self):
		name = "Live Approval Logix Script"
		create_server_script(name, "API", "result['x'] = 1")
		self.assertEqual(frappe.db.get_value("Server Script", name, "disabled"), 0)
		update_server_script(name, "result['x'] = 2")
		self.assertEqual(frappe.db.get_value("Server Script", name, "disabled"), 0)

	def test_the_older_repath_patches_run_without_the_approval_fields(self):
		name = "Live Approval Old Paths"
		old_paths = (
			"# one_bpmn processa.agents.eval_alerts processa.agents.observability "
			"processa.agents.shape_tools processa.agents.adversarial_gate\nx = 1\n"
		)
		frappe.get_doc(
			{
				"doctype": "Server Script",
				"name": name,
				"script_type": "API",
				"api_method": "live_old_paths",
				"script": old_paths,
			}
		).insert()
		real_get_value = frappe.db.get_value

		def get_value(doctype, filters=None, fieldname="name", *args, **kwargs):
			if doctype == "Server Script" and "processa_" in str(fieldname):
				raise frappe.db.OperationalError(1054, "Unknown column")
			return real_get_value(doctype, filters, fieldname, *args, **kwargs)

		with patch.object(frappe.db, "get_value", side_effect=get_value):
			rename_stored_one_bpmn_paths._rename_script(name)
			for repath_patch in (
				repath_skill_tool_imports,
				repath_eval_module_imports,
				repath_observability_module_imports,
				repath_stored_imports_to_processa_modules,
			):
				repath_patch._repath_script(name)
		script = frappe.db.get_value("Server Script", name, "script")
		for moved in ("one_bpmn", "processa.agents."):
			self.assertNotIn(moved, script)


def _deployable_map(process_id: str, scripts: tuple) -> str:
	ids = ["s", *(f"t{i}" for i in range(len(scripts))), "e"]
	flows = "".join(
		f'<bpmn:sequenceFlow id="f{i}" sourceRef="{a}" targetRef="{b}" />'
		for i, (a, b) in enumerate(pairwise(ids))
	)
	tasks = "".join(
		f'<bpmn:scriptTask id="t{i}" name="Step {i}" spiffworkflow:serverScript="{name}">'
		f"<bpmn:incoming>f{i}</bpmn:incoming><bpmn:outgoing>f{i + 1}</bpmn:outgoing></bpmn:scriptTask>"
		for i, name in enumerate(scripts)
	)
	return f"""<?xml version="1.0" encoding="UTF-8"?>
<bpmn:definitions xmlns:bpmn="http://www.omg.org/spec/BPMN/20100524/MODEL"
 xmlns:spiffworkflow="http://spiffworkflow.org/bpmn/schema/1.0/core"
 id="Defs_{process_id}" targetNamespace="http://bpmn.io/schema/bpmn">
  <bpmn:process id="{process_id}" isExecutable="true">
    <bpmn:startEvent id="s"><bpmn:outgoing>f0</bpmn:outgoing></bpmn:startEvent>
    {tasks}
    <bpmn:endEvent id="e"><bpmn:incoming>f{len(scripts)}</bpmn:incoming></bpmn:endEvent>
    {flows}
  </bpmn:process>
</bpmn:definitions>"""
