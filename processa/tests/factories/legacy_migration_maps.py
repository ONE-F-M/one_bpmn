# Copyright (c) 2026, one-fm and contributors
"""Process maps, old instances and migrations for the Processa Legacy Migration tests."""

import json
from unittest.mock import patch

import frappe

from processa.processa_engine import legacy_migration
from processa.processa_engine.compiler.compile_step import compile_model
from processa.processa_engine.instances.starting import start_process
from processa.processa_engine.instances.task_actions import complete_task
from processa.processa_engine.runtime.messages import receive_message

DT = "GP Letter Request"
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
