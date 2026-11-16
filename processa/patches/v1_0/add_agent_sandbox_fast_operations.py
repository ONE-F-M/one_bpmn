"""The agent_sandbox connector gets the fast operations (write_spec, browser_snapshot, trigger_job, seed_docs, seed_context) a map can call."""

import frappe

from processa.processa_connectors.seed import import_operation
from processa.patches.v1_0.add_agent_sandbox_run_tests_and_pull_request_operations import (
	_SHARED_FIELDS,
	CONNECTOR,
	HANDLER,
)


def _field(name, label, kind, help_text, required=True):
	return {"name": name, "label": label, "type": kind, "required": required, "help": help_text}


_RUN_ID = _field("run_id", "Run id", "String", "The run these belong to: the same id prepare_site and checkout_pr_head used.")


def _operation(value, label, description, output, *fields):
	return {
		"value": value,
		"label": label,
		"description": description + " Answers within the fast wait; needs the Work Item's sandbox Job session.",
		"executionType": "Python Handler",
		"handlerPath": HANDLER,
		"output": output,
		"fields": [*_SHARED_FIELDS, *fields],
	}


OPERATIONS = [
	_operation(
		"write_spec", "Write a Playwright spec",
		"Write one spec into the run's own folder in the sandbox, outside the app checkout, so it is never committed.",
		{"written": "The run folder path of the file", "bytes": "Its size"},
		_RUN_ID,
		_field("file", "File", "String", "A file name ending in .spec.js."),
		_field("content", "Content", "Text", "The spec's source."),
	),
	_operation(
		"browser_snapshot", "Snapshot a page",
		"The accessibility snapshot of a page on the test site, seen as a role's test user. The screenshot is not kept in the output.",
		{"snapshot": "The page's accessibility snapshot", "url": "The page", "role": "The role seen as"},
		_RUN_ID,
		_field("url", "Page", "String", "A path on the test site, such as /app/home."),
		_field("role", "Role", "String", "One of the roles prepare_site made a test user for."),
	),
	_operation(
		"trigger_job", "Run a scheduled job",
		"Run one of the target app's own scheduled methods on the test site. A method that is not in its scheduler_events is refused.",
		{"ran": "The method that ran"},
		_field("method", "Method", "String", "A dotted path listed in the app's scheduler_events."),
	),
	_operation(
		"seed_docs", "Seed test documents",
		"Insert documents through their controllers as Administrator, in order; a document that fails does not stop the rest. "
		"An entry may name an allowed test factory instead.",
		{"results": "The name or the error for each document", "inserted": "How many were inserted", "failed": "How many failed"},
		_RUN_ID,
		_field("docs", "Documents", "Text", "A JSON list of documents (each with a doctype) or factory calls, at most 50."),
	),
	_operation(
		"seed_context", "Read what a DocType needs",
		"For the DocTypes, dependencies first: required fields, Link targets, Select options, mandatory_depends_on, the validate source "
		"and the known factories. Read only.",
		{"order": "The DocTypes, dependencies first", "doctypes": "What each one needs"},
		_RUN_ID,
		_field("doctypes", "DocTypes", "Text", "A JSON list of DocType names, at most 10."),
	),
]


def execute():
	if not frappe.db.exists("BPMN Connector", CONNECTOR):
		return
	for idx, operation in enumerate(OPERATIONS, start=8):
		import_operation(CONNECTOR, operation, idx)
