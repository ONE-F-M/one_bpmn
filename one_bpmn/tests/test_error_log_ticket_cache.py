# Copyright (c) 2026, one-fm and contributors
# For license information, please see license.txt
"""The Error Log Ticket Agent's tickets from before today reach the model in its cached system prompt."""

from __future__ import annotations

import json
from unittest.mock import patch

import frappe
from frappe.tests.utils import FrappeTestCase
from frappe.utils import add_days, now_datetime

from one_bpmn.one_bpmn.patches.v1_0 import error_log_ticket_agent_caches_older_tickets as fix

COMPILE = "one_bpmn.api.compilation.compile_process_model"

# The Triage script as it runs on business-analyst.one-fm.com before the patch.
TRIAGE_BODY = """# Script Task: Triage: Kill Switch + Exact Dedup (error_log_ticket_triage_process)
#
# doc is the Error Log that started this instance. Writes:
#   outcome = "disabled" | "linked_duplicate" | "needs_ai"
#   on needs_ai: error_title, error_details, existing_tickets_json \u2014 the
#   fields the AI Agent Task's prompt renders.
import json

enabled = frappe.db.get_value("AI Agent Configuration", {"agent_id": "error_log_ticket_agent"}, "enabled")

if not enabled:
    result["outcome"] = "disabled"
else:
    title = (doc.method or "").strip()
    match_name = frappe.db.get_value(
        "HD Ticket",
        {"subject": title, "status": ["not in", ["Resolved", "Closed"]]},
        "name",
    )

    if match_name:
        frappe.db.set_value("Error Log", doc.name, "hd_ticket", match_name)
        result["outcome"] = "linked_duplicate"
        result["ticket_name"] = match_name
    else:
        # Cap what reaches the LLM. Confirmed live: this site has 424 open HD
        # Tickets, and serializing all of them blew the prompt to ~628k tokens
        # (Claude's limit is 200k) - the AI Agent Task failed on every single
        # run with FAILED_MODEL_CALL, and Apply AI Result's fail-open default
        # (no_match) silently created a fresh ticket every time instead of
        # ever actually finding a similarity match. Recent tickets are the
        # most likely duplicates anyway; descriptions are truncated too, since
        # a handful carry full stack traces.
        open_tickets = frappe.get_all(
            "HD Ticket",
            filters={"status": ["not in", ["Resolved", "Closed"]]},
            fields=["name", "subject", "description"],
            order_by="creation desc",
            limit_page_length=50,
        )
        result["outcome"] = "needs_ai"
        result["error_title"] = title
        result["error_details"] = (doc.error or "")[:2000]
        result["existing_tickets_json"] = json.dumps([
            {"name": t.name, "subject": t.subject, "description": (t.description or "")[:500]}
            for t in open_tickets
        ])
"""

MAP_XML = (
	'<?xml version="1.0" encoding="UTF-8"?>'
	'<bpmn:definitions xmlns:bpmn="http://www.omg.org/spec/BPMN/20100524/MODEL" '
	'xmlns:spiffworkflow="http://spiffworkflow.org/bpmn/schema/1.0/core" id="d" targetNamespace="http://bpmn.io/schema/bpmn">'
	'<bpmn:process id="error_log_ticket_triage_process" isExecutable="true">'
	'<bpmn:serviceTask id="ai_similarity_check" name="AI Agent Task: Similarity Check" spiffworkflow:serviceType="ai_agent" '
	f'spiffworkflow:aiUserPrompt="{fix.USER_PROMPT}" spiffworkflow:aiAgentConfig="Error Log Ticket Agent" />'
	"</bpmn:process></bpmn:definitions>"
)


def _fixtures():
	if frappe.db.exists("Server Script", fix.TRIAGE):
		frappe.db.set_value("Server Script", fix.TRIAGE, "script", TRIAGE_BODY)
	else:
		frappe.get_doc(
			{
				"doctype": "Server Script",
				"name": fix.TRIAGE,
				"script_type": "API",
				"api_method": "error_log_triage_test",
				"script": TRIAGE_BODY,
			}
		).insert(ignore_permissions=True)
	if not frappe.db.exists("AI Agent Configuration", fix.AGENT):
		frappe.get_doc(
			{
				"doctype": "AI Agent Configuration",
				"agent_name": fix.AGENT,
				"agent_id": fix.AGENT_ID,
				"agent_type": "Background",
				"agent_framework": "Direct API",
			}
		).insert(ignore_permissions=True)
	frappe.db.set_value(
		"AI Agent Configuration",
		fix.AGENT,
		"system_prompt",
		"Decide match or no_match. " + fix.PROMPT_LAST_LINE,
	)
	if not frappe.db.exists("Process", fix.MAP):
		frappe.get_doc(
			{
				"doctype": "Process",
				"process_name": fix.MAP,
				"description": "Fixture.",
				"process_owner": "Administrator",
			}
		).insert(ignore_permissions=True)
	if frappe.db.exists("BPMN Process Model", fix.MAP):
		frappe.db.set_value("BPMN Process Model", fix.MAP, "bpmn_xml", MAP_XML)
	else:
		model = frappe.new_doc("BPMN Process Model")
		model.update(
			{
				"name": fix.MAP,
				"title": fix.MAP,
				"process_id": "error_log_ticket_triage_process",
				"process_name": fix.MAP,
				"version": 1,
				"bpmn_xml": MAP_XML,
			}
		)
		model.flags.ignore_validate = True
		model.db_insert()


def _ticket(subject: str, creation) -> str:
	name = frappe.generate_hash(length=10)
	frappe.db.bulk_insert(
		"HD Ticket",
		fields=["name", "subject", "description", "status", "creation", "modified", "owner", "modified_by"],
		values=[[name, subject, "details", "Open", creation, creation, "Administrator", "Administrator"]],
	)
	return name


def _run_triage(title: str) -> dict:
	result = {}
	namespace = {
		"frappe": frappe,
		"__builtins__": __builtins__,
		"result": result,
		"doc": frappe._dict(name="error-log-test", method=title, error="Traceback ..."),
	}
	exec(frappe.db.get_value("Server Script", fix.TRIAGE, "script"), namespace)
	return result


class TestTheOlderTicketsMoveToTheSystemPrompt(FrappeTestCase):
	def setUp(self):
		frappe.set_user("Administrator")
		_fixtures()

	def _patch(self):
		with patch(COMPILE) as compile_map:
			fix.execute()
		return compile_map

	def test_the_patch_edits_the_script_the_prompt_and_the_map_and_recompiles(self):
		compile_map = self._patch()
		script = frappe.db.get_value("Server Script", fix.TRIAGE, "script")
		self.assertIn("older_tickets_json", script)
		self.assertNotIn("existing_tickets_json", script)
		prompt = frappe.db.get_value("AI Agent Configuration", fix.AGENT, "system_prompt")
		self.assertTrue(prompt.endswith("treat the two lists as one:\n{{ older_tickets_json }}"))
		xml = frappe.db.get_value("BPMN Process Model", fix.MAP, "bpmn_xml")
		self.assertIn("{{ todays_tickets_json }}", xml)
		self.assertNotIn("existing_tickets_json", xml)
		compile_map.assert_called_once_with(fix.MAP)

	def test_older_tickets_come_oldest_first_and_todays_apart(self):
		self._patch()
		yesterday = _ticket("Older ticket for the cache test", add_days(now_datetime(), -1))
		today = _ticket("Today's ticket for the cache test", now_datetime())
		result = _run_triage(f"Unique title {frappe.generate_hash(length=8)}")
		older = json.loads(result["older_tickets_json"])
		todays = [t["name"] for t in json.loads(result["todays_tickets_json"])]
		self.assertEqual(older[-1]["name"], yesterday)
		self.assertNotIn(today, [t["name"] for t in older])
		self.assertIn(today, todays)
		self.assertLessEqual(len(older), 40)
		rendered = frappe.render_template(
			frappe.db.get_value("AI Agent Configuration", fix.AGENT, "system_prompt"), result
		)
		self.assertIn(yesterday, rendered)
		self.assertNotIn(today, rendered)

	def test_running_it_again_changes_nothing(self):
		self._patch()
		before = [
			frappe.db.get_value("Server Script", fix.TRIAGE, "script"),
			frappe.db.get_value("AI Agent Configuration", fix.AGENT, "system_prompt"),
			frappe.db.get_value("BPMN Process Model", fix.MAP, "bpmn_xml"),
		]
		compile_map = self._patch()
		after = [
			frappe.db.get_value("Server Script", fix.TRIAGE, "script"),
			frappe.db.get_value("AI Agent Configuration", fix.AGENT, "system_prompt"),
			frappe.db.get_value("BPMN Process Model", fix.MAP, "bpmn_xml"),
		]
		self.assertEqual(after, before)
		compile_map.assert_not_called()

	def test_a_site_whose_script_no_longer_matches_is_left_entirely_unchanged(self):
		frappe.db.set_value(
			"Server Script",
			fix.TRIAGE,
			"script",
			TRIAGE_BODY.replace("limit_page_length=50", "limit_page_length=60"),
		)
		prompt = frappe.db.get_value("AI Agent Configuration", fix.AGENT, "system_prompt")
		self._patch()
		self.assertEqual(frappe.db.get_value("AI Agent Configuration", fix.AGENT, "system_prompt"), prompt)
		self.assertIn("existing_tickets_json", frappe.db.get_value("BPMN Process Model", fix.MAP, "bpmn_xml"))
