# Copyright (c) 2026, one-fm and contributors
# For license information, please see license.txt
"""A migration is refused on save unless its maps, state mapping and process ownership let it run.

Also the process maps, old instances and migrations the other Processa Legacy Migration tests build on.
"""

import json
from unittest.mock import patch

import frappe
from frappe.tests import IntegrationTestCase

from processa.processa_engine.compiler.compile_step import compile_model
from processa.processa_engine.doctype.processa_legacy_migration import legacy_migration
from processa.processa_engine.instances.starting import start_process
from processa.processa_engine.instances.task_actions import complete_task
from processa.processa_engine.runtime.messages import receive_message

DT = "GP Letter Request"
VAL_OPEN, VAL_HOLD, VAL_DONE = "PLM Val Open", "PLM Val Hold", "PLM Val Done"
OWNER = "_plm_val_owner@example.com"
OTHER_OWNER = "_plm_val_other@example.com"
NOBODY = "_plm_val_nobody@example.com"
OWNED_PROCESS, OTHER_PROCESS = "PLM Val Owned", "PLM Val Other"

DRAFT, APPROVED, DONE = "PLM Rep Draft", "PLM Rep Approved", "PLM Rep Done"
PR_OPENED = "github:pull_request:opened"
SPIFF = 'xmlns:spiffworkflow="http://spiffworkflow.org/bpmn/schema/1.0/core"'

OLD = [
	("state", "Task_draft", DRAFT),
	("user", "Task_review", "Review"),
	("state", "Task_approved", APPROVED),
	("catch", "Catch_pr", PR_OPENED),
	("user", "Task_merge", "Merge"),
	("state", "Task_done", DONE),
]


def node(kind, node_id, arg, incoming, outgoing):
	flows = f"<bpmn:incoming>{incoming}</bpmn:incoming><bpmn:outgoing>{outgoing}</bpmn:outgoing>"
	if kind == "state":
		return (
			f'<bpmn:serviceTask id="{node_id}" name="Set {arg}" spiffworkflow:serviceType="apply_workflow" '
			f'spiffworkflow:serviceTargetDoctype="{DT}" spiffworkflow:workflowState="{arg}" '
			f'spiffworkflow:docStatus="0">{flows}</bpmn:serviceTask>'
		)
	if kind == "user":
		return (
			f'<bpmn:userTask id="{node_id}" name="{arg}" spiffworkflow:assigneeMode="DocField" '
			f'spiffworkflow:targetDoctype="{DT}" spiffworkflow:assigneeDocfield="owner" '
			f'spiffworkflow:taskActions="[{{&#34;action&#34;:&#34;Approve&#34;}}]">{flows}</bpmn:userTask>'
		)
	if kind == "catch":
		return (
			f'<bpmn:intermediateCatchEvent id="{node_id}" name="{arg}">{flows}'
			f'<bpmn:messageEventDefinition messageRef="Message_{node_id}" /></bpmn:intermediateCatchEvent>'
		)
	if kind == "script":
		return (
			f'<bpmn:scriptTask id="{node_id}" name="Mark">{flows}'
			"<bpmn:script>script_ran = True</bpmn:script></bpmn:scriptTask>"
		)
	if kind == "email":
		return (
			f'<bpmn:serviceTask id="{node_id}" name="Email" spiffworkflow:serviceType="send_email" '
			f'spiffworkflow:emailTo="someone@example.com" spiffworkflow:emailSubject="Hi" '
			f'spiffworkflow:emailBody="Hi">{flows}</bpmn:serviceTask>'
		)
	return f'<bpmn:callActivity id="{node_id}" name="Call" calledElement="{arg}">{flows}</bpmn:callActivity>'


def straight_xml(pid, nodes):
	"""A straight line Start, nodes, End."""
	ids = ["Start_1", *(n[1] for n in nodes), "End_1"]
	flows = [f"Flow_{i}" for i in range(len(ids) - 1)]
	body = [
		f'<bpmn:startEvent id="Start_1" name="Start"><bpmn:outgoing>{flows[0]}</bpmn:outgoing>'
		"</bpmn:startEvent>"
	]
	for i, (kind, node_id, arg) in enumerate(nodes):
		body.append(node(kind, node_id, arg, flows[i], flows[i + 1]))
	body.append(
		f'<bpmn:endEvent id="End_1" name="End"><bpmn:incoming>{flows[-1]}</bpmn:incoming></bpmn:endEvent>'
	)
	body += [
		f'<bpmn:sequenceFlow id="{f}" sourceRef="{ids[i]}" targetRef="{ids[i + 1]}" />'
		for i, f in enumerate(flows)
	]
	messages = "".join(
		f'<bpmn:message id="Message_{n[1]}" name="{n[2]}" />' for n in nodes if n[0] == "catch"
	)
	return definitions(pid, "".join(body), messages)


def definitions(pid, body, messages=""):
	return (
		'<?xml version="1.0" encoding="UTF-8"?>'
		'<bpmn:definitions xmlns:bpmn="http://www.omg.org/spec/BPMN/20100524/MODEL" '
		f'{SPIFF} id="Defs_{pid}" targetNamespace="http://bpmn.io/schema/bpmn">{messages}'
		f'<bpmn:process id="{pid}" isExecutable="true">{body}</bpmn:process></bpmn:definitions>'
	)


def loop_xml(pid):
	"""Set Draft, then a gateway whose condition always sends it back, so the review is never reached."""
	draft = node("state", "Task_draft", DRAFT, "Flow_0", "Flow_1")
	return definitions(
		pid,
		'<bpmn:startEvent id="Start_1" name="Start"><bpmn:outgoing>Flow_0</bpmn:outgoing></bpmn:startEvent>'
		+ draft.replace("</bpmn:incoming>", "</bpmn:incoming><bpmn:incoming>Flow_back</bpmn:incoming>", 1)
		+ '<bpmn:exclusiveGateway id="Gateway_1" name="Again?" default="Flow_2">'
		"<bpmn:incoming>Flow_1</bpmn:incoming>"
		"<bpmn:outgoing>Flow_back</bpmn:outgoing><bpmn:outgoing>Flow_2</bpmn:outgoing>"
		"</bpmn:exclusiveGateway>"
		+ node("user", "Task_review", "Review", "Flow_2", "Flow_3")
		+ '<bpmn:endEvent id="End_1" name="End"><bpmn:incoming>Flow_3</bpmn:incoming></bpmn:endEvent>'
		'<bpmn:sequenceFlow id="Flow_0" sourceRef="Start_1" targetRef="Task_draft" />'
		'<bpmn:sequenceFlow id="Flow_1" sourceRef="Task_draft" targetRef="Gateway_1" />'
		'<bpmn:sequenceFlow id="Flow_back" sourceRef="Gateway_1" targetRef="Task_draft">'
		"<bpmn:conditionExpression>True</bpmn:conditionExpression></bpmn:sequenceFlow>"
		'<bpmn:sequenceFlow id="Flow_2" sourceRef="Gateway_1" targetRef="Task_review" />'
		'<bpmn:sequenceFlow id="Flow_3" sourceRef="Task_review" targetRef="End_1" />',
	)


def deploy(title, xml):
	pid = frappe.scrub(title)
	model = frappe.get_doc(
		{
			"doctype": "BPMN Process Model",
			"title": title,
			"process_id": pid,
			"version": 1,
			"bpmn_xml": xml(pid) if callable(xml) else straight_xml(pid, xml),
		}
	)
	model.flags.skip_editability_check = True
	model.insert()
	compile_model(model)
	return model.name


def with_changes(nodes, **changes):
	"""OLD-style nodes with labels replaced, or nodes inserted after or removed by element id."""
	out = []
	for kind, node_id, arg in nodes:
		if changes.get("drop") == node_id:
			continue
		out.append((kind, node_id, changes.get("relabel", {}).get(node_id, arg)))
		out += changes.get("after", {}).get(node_id, [])
	return out


def old_instance(model: str, *history: str) -> str:
	"""Run the real engine on a new record: complete each named user task or deliver each message, in order.

	Document events are off throughout, so no other map active on the site starts on the record."""
	with patch("processa.processa_engine.triggers.on_doc_event"):
		record = frappe.get_doc({"doctype": DT}).insert().name
		name = start_process(model, DT, record)["instance"]
		for step in history:
			instance = frappe.get_doc("BPMN Process Instance", name)
			if step == PR_OPENED:
				receive_message(instance, PR_OPENED, {"pr_url": "https://github.com/x/y/pull/1"})
			else:
				row = next(r for r in instance.active_tasks if r.status == "Waiting")
				complete_task(name, row.task_id, json.dumps({"action": "Approve"}))
	return name


def migration(from_model: str, to_model: str, mapping: list, **values) -> str:
	"""Insert a Processa Legacy Migration without starting the map active for it on the site."""
	with patch("processa.processa_engine.triggers.on_doc_event"):
		plm = frappe.get_doc(
			{
				"doctype": "Processa Legacy Migration",
				"from_model": from_model,
				"to_model": to_model,
				"target_doctype": DT,
				"state_map": [{"old_state": o, "new_state": n} for o, n in mapping],
				**values,
			}
		).insert()
	return plm.name


def run_start(migration_name: str, run_jobs: bool = True) -> tuple[list, list]:
	"""Run start, then its queued jobs in order; returns the jobs and the exceptions they raised."""
	jobs = []
	with patch("frappe.enqueue", side_effect=lambda method, **kw: jobs.append((method, kw))):
		legacy_migration.start(migration_name)
	return jobs, run_batch_jobs(jobs) if run_jobs else []


def run_batch_jobs(jobs: list) -> list:
	"""Run run_batch jobs like a worker: a commit keeps the work so far, a job that raises loses the rest."""
	frappe.db.savepoint("plm_batch_test")
	rollback = frappe.db.rollback
	errors = []
	with (
		patch.object(frappe.db, "commit", side_effect=lambda: frappe.db.savepoint("plm_batch_test")),
		patch.object(
			frappe.db,
			"rollback",
			side_effect=lambda save_point=None, **kw: rollback(save_point=save_point or "plm_batch_test"),
		),
	):
		for _method, kwargs in jobs:
			try:
				legacy_migration.run_batch(
					kwargs["migration_name"], kwargs["instance_names"], kwargs["first_idx"]
				)
			except Exception as e:
				rollback(save_point="plm_batch_test")
				errors.append(e)
	return errors


XML = """<?xml version="1.0" encoding="UTF-8"?>
<bpmn:definitions xmlns:bpmn="http://www.omg.org/spec/BPMN/20100524/MODEL" id="Defs_{pid}"
  targetNamespace="http://bpmn.io/schema/bpmn">
  <bpmn:process id="{pid}" isExecutable="true">
    <bpmn:startEvent id="Start_1"><bpmn:outgoing>Flow_1</bpmn:outgoing></bpmn:startEvent>
    <bpmn:sequenceFlow id="Flow_1" sourceRef="Start_1" targetRef="End_1" />
    <bpmn:endEvent id="End_1"><bpmn:incoming>Flow_1</bpmn:incoming></bpmn:endEvent>
  </bpmn:process>
</bpmn:definitions>"""


def _user(email, roles):
	if not frappe.db.exists("User", email):
		frappe.get_doc(
			{
				"doctype": "User",
				"email": email,
				"first_name": email.split("@")[0],
				"send_welcome_email": 0,
				"roles": [{"role": r} for r in roles],
			}
		).insert()


def _model(title, process, doctype=DT, sets_states=(VAL_OPEN, VAL_DONE), deployed=True):
	pid = frappe.scrub(title)
	model = frappe.get_doc(
		{
			"doctype": "BPMN Process Model",
			"title": title,
			"process_name": process,
			"process_id": pid,
			"version": 1,
			"bpmn_xml": XML.format(pid=pid),
			"target_doctypes": [{"doctype_name": doctype}],
		}
	)
	model.flags.skip_editability_check = True
	model.insert()
	if deployed:
		spec = {"service_task_extensions": {f"t{i}": {"workflowState": s} for i, s in enumerate(sets_states)}}
		model.db_set("serialized_spec", json.dumps(spec))
	return model.name


class TestProcessaLegacyMigrationValidation(IntegrationTestCase):
	@classmethod
	def setUpClass(cls):
		super().setUpClass()
		with patch("processa.processa_engine.triggers.on_doc_event"):
			for state in (VAL_OPEN, VAL_HOLD, VAL_DONE):
				frappe.get_doc(
					{"doctype": "Workflow State", "workflow_state_name": state, "style": "Primary"}
				).insert()
			_user(OWNER, ["Process Owner"])
			_user(OTHER_OWNER, ["Process Owner"])
			_user(NOBODY, ["Blogger"])
			for process, owner in ((OWNED_PROCESS, OWNER), (OTHER_PROCESS, OTHER_OWNER)):
				frappe.get_doc(
					{
						"doctype": "Process",
						"process_name": process,
						"process_owner": owner,
						"description": "Test",
					}
				).insert()
			cls.old_map = _model("PLM Val Old", OWNED_PROCESS)
			cls.new_map = _model("PLM Val New", OWNED_PROCESS)
			cls._open_record(VAL_OPEN)
			cls._open_record(VAL_OPEN)

	def setUp(self):
		super().setUp()
		trigger = patch("processa.processa_engine.triggers.on_doc_event")
		trigger.start()
		self.addCleanup(trigger.stop)
		# IntegrationTestCase rolls back per class; the savepoint keeps each test's rows out of the next.
		frappe.db.savepoint("plm_validation_test")
		self.addCleanup(frappe.db.rollback, save_point="plm_validation_test")

	@classmethod
	def _open_record(cls, state):
		name = frappe.get_doc({"doctype": DT}).insert().name
		frappe.db.set_value(DT, name, "workflow_state", state)
		frappe.get_doc(
			{
				"doctype": "BPMN Process Instance",
				"process_model": cls.old_map,
				"status": "Active",
				"context_doctype": DT,
				"context_docname": name,
			}
		).insert()
		return name

	def _migration(self, **overrides):
		values = {
			"doctype": "Processa Legacy Migration",
			"from_model": self.old_map,
			"to_model": self.new_map,
			"target_doctype": DT,
			"state_map": [{"old_state": VAL_OPEN, "new_state": VAL_OPEN}],
		}
		values.update(overrides)
		return frappe.get_doc(values)

	def _assert_refused(self, migration, *words):
		with self.assertRaises(frappe.ValidationError) as caught:
			migration.insert()
		for word in words:
			self.assertIn(word, str(caught.exception))

	def test_a_valid_migration_saves_and_counts_records_per_old_state(self):
		name = self._migration().insert().name
		stored = frappe.get_doc("Processa Legacy Migration", name)
		self.assertEqual((stored.from_model, stored.to_model), (self.old_map, self.new_map))
		self.assertEqual([(d.old_state, d.record_count) for d in stored.state_map], [(VAL_OPEN, 2)])

	def test_a_missing_new_process_map_is_refused(self):
		with self.assertRaises(frappe.MandatoryError):
			self._migration(to_model="").insert()

	def test_the_same_map_twice_is_refused(self):
		self._assert_refused(self._migration(to_model=self.old_map), "must be different")

	def test_a_new_map_never_deployed_is_refused(self):
		undeployed = _model("PLM Val Undeployed", OWNED_PROCESS, deployed=False)
		self._assert_refused(self._migration(to_model=undeployed), undeployed, "is not currently deployed")

	def test_maps_for_different_doctypes_are_refused(self):
		note_map = _model("PLM Val Note Map", OWNED_PROCESS, doctype="Note")
		self._assert_refused(self._migration(to_model=note_map), DT, "Note")

	def test_a_duplicate_old_state_is_refused(self):
		rows = [
			{"old_state": VAL_OPEN, "new_state": VAL_OPEN},
			{"old_state": VAL_OPEN, "new_state": VAL_DONE},
		]
		self._assert_refused(self._migration(state_map=rows), VAL_OPEN, "more than once")

	def test_a_new_state_the_new_map_never_sets_is_refused(self):
		self._assert_refused(
			self._migration(state_map=[{"old_state": VAL_OPEN, "new_state": VAL_HOLD}]), VAL_HOLD
		)

	def test_open_records_in_an_unmapped_state_are_refused_with_their_count(self):
		self._open_record(VAL_HOLD)
		self._assert_refused(self._migration(), f"{VAL_HOLD} (1)")

	def test_a_target_doctype_without_a_state_field_is_refused(self):
		old_note, new_note = (
			_model(f"PLM Val Note {v}", OWNED_PROCESS, doctype="Note") for v in ("Old", "New")
		)
		migration = self._migration(from_model=old_note, to_model=new_note, target_doctype="Note")
		self._assert_refused(migration, "Note", "workflow_state")

	def test_a_target_doctype_neither_map_runs_on_is_refused(self):
		self._assert_refused(self._migration(target_doctype="ToDo"), self.old_map, DT, "ToDo")

	def test_an_engine_save_that_changes_the_setup_is_still_checked(self):
		name = self._migration().insert().name
		migration = frappe.get_doc("Processa Legacy Migration", name)
		migration.to_model = self.old_map
		with patch.dict(frappe.local.flags, {"bpmn_engine_action": True}):
			with self.assertRaises(frappe.ValidationError) as caught:
				migration.save()
		self.assertIn("must be different", str(caught.exception))

	def test_an_engine_save_that_leaves_the_setup_alone_skips_the_checks(self):
		name = self._migration().insert().name
		self._open_record(VAL_HOLD)
		migration = frappe.get_doc("Processa Legacy Migration", name)
		migration.workflow_state = VAL_DONE
		with patch.dict(frappe.local.flags, {"bpmn_engine_action": True}):
			migration.save()
		self.assertEqual(frappe.db.get_value("Processa Legacy Migration", name, "workflow_state"), VAL_DONE)

	def test_a_process_owner_of_both_maps_saves_and_sees_only_their_migrations(self):
		other = self._migration().insert().name
		with self.set_user(OWNER):
			mine = self._migration().insert().name
			visible = frappe.get_list("Processa Legacy Migration", pluck="name")
		self.assertEqual(visible, [mine])
		self.assertNotIn(other, visible)

	def test_a_process_owner_of_only_one_map_is_refused(self):
		foreign_map = _model("PLM Val Foreign", OTHER_PROCESS)
		with self.set_user(OWNER), self.assertRaises(frappe.PermissionError):
			self._migration(to_model=foreign_map).insert()
		self.assertFalse(frappe.db.exists("Processa Legacy Migration", {"to_model": foreign_map}))

	def test_a_user_without_either_role_cannot_create_a_migration(self):
		with self.set_user(NOBODY), self.assertRaises(frappe.PermissionError):
			self._migration().insert()

	def test_checks_are_skipped_once_the_migration_has_left_draft(self):
		for status in ("Queued", "Running", "Completed"):
			name = self._migration(status=status, to_model=self.old_map).insert().name
			self.assertTrue(frappe.db.exists("Processa Legacy Migration", name))
