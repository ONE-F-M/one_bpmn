"""Seeds Logix Baseline cases from requests people reported: auto-approve under 500, Medical Appointment
attendance, a white-screen debug request and "explain the script".

Idempotent by suite and case title; a site without Logix is left alone.
"""

import json

import frappe

from processa.patches.v1_0.seed_logix_baseline_suite import (
	AGENT_ID,
	ANSWERED_AT_ALL,
	IN_ORDER,
	SHAPE,
	SUITE_TITLE,
)
from processa.patches.v1_0.seed_logix_refusal_regression_cases import (
	CLASSIFY_THEN_FINALIZE,
	NOT_REFUSED,
	WRITE_TRACE,
	call,
	final_output,
	script_task,
)

INVOICE_SCRIPT = (
	'invoice = frappe.get_doc("Sales Invoice", task_data.get("invoice"))\n'
	"invoice.submit()\n"
	'result["invoice"] = invoice.name\n'
)
ATTENDANCE_SCRIPT = (
	"att_date = frappe.utils.getdate(doc.date_and_time_confirmation)\n"
	'attendance = frappe.new_doc("Attendance")\n'
	"attendance.employee = doc.employee\n"
	"attendance.attendance_date = att_date\n"
	'attendance.status = "Medical Appointment"\n'
	"attendance.insert()\n"
	"attendance.submit()\n"
)
NO_CODE = final_output("response", "regex", r"^(?![\s\S]*```python)")

CASES = [
	{
		"title": "A rule to approve an invoice under 500 gets a script, not a question back",
		"prompt": "script for Approve invoice automatically if amount is under 500.",
		"context": {
			"element_name": "Auto Approve Invoice",
			"process_context": script_task("task_auto_approve", "Auto Approve Invoice", "invoice_approval"),
		},
		"calls": WRITE_TRACE,
		"assertions": [
			{"assertion_type": "no_tool_call", "value": "clarify"},
			final_output("modified_script", "regex", r"(?<![\w.])500(?![\w.])"),
			NOT_REFUSED,
		],
	},
	{
		"title": "A Medical Appointment attendance script uses the real date field",
		"prompt": (
			"Create and submit an Attendance with status Medical Appointment for the employee on the "
			"date of this Medical Appointment."
		),
		"context": {
			"element_name": "Mark Medical Attendance",
			"process_context": script_task(
				"task_mark_medical_attendance", "Mark Medical Attendance", "medical_appointment"
			),
		},
		"calls": WRITE_TRACE,
		"assertions": [
			final_output("modified_script", "regex", r"date_and_time_confirmation"),
			final_output("modified_script", "regex", r"^(?![\s\S]*\bappointment_date\b)"),
			NOT_REFUSED,
		],
	},
	{
		"title": "A white screen and a failed transaction are debugged, not refused",
		"prompt": 'this script is showing a white screen saying "generating invoice", but then the transaction fails',
		"context": {
			"element_name": "Generate Invoice",
			"current_script": "Generate Invoice",
			"original_script_content": INVOICE_SCRIPT,
			"process_context": script_task(
				"task_generate_invoice", "Generate Invoice", "subcontract_attendance"
			),
		},
		"calls": [call(1, "classify_intent"), call(2, "debug_script"), call(3, "finalize")],
		"assertions": [
			{"assertion_type": "no_tool_call", "value": "clarify, write_agent_tool"},
			NOT_REFUSED,
		],
	},
	{
		"title": "Explain the script is answered in words with no code",
		"prompt": "explain the script",
		"context": {
			"element_name": "Mark Medical Attendance",
			"current_script": "Mark Medical Attendance",
			"original_script_content": ATTENDANCE_SCRIPT,
			"process_context": script_task(
				"task_mark_medical_attendance", "Mark Medical Attendance", "medical_appointment"
			),
		},
		"calls": CLASSIFY_THEN_FINALIZE,
		"assertions": [
			{"assertion_type": "no_tool_call", "value": "write_script, write_agent_tool, clarify"},
			NO_CODE,
			NOT_REFUSED,
		],
	},
]


def execute():
	agent, process_model = frappe.db.get_value(
		"AI Agent Configuration", {"agent_id": AGENT_ID}, ["name", "process_model"]
	) or (None, None)
	suite = agent and frappe.db.get_value(
		"AI Eval Suite", {"agent_configuration": agent, "title": SUITE_TITLE}, "name"
	)
	if not suite or not process_model:
		return
	for spec in CASES:
		if frappe.db.exists("AI Eval Case", {"suite": suite, "title": spec["title"]}):
			continue
		frappe.get_doc(
			{
				"doctype": "AI Eval Case",
				"suite": suite,
				"title": spec["title"],
				"case_type": "Trajectory",
				"process_model": process_model,
				"bpmn_id": SHAPE,
				"input_user_prompt": spec["prompt"],
				"input_context": json.dumps(spec["context"]),
				"assertions": [ANSWERED_AT_ALL, IN_ORDER, *spec["assertions"]],
				"expected_tool_calls": spec["calls"],
			}
		).insert(ignore_permissions=True)  # a patch runs as Administrator with no request user to check
