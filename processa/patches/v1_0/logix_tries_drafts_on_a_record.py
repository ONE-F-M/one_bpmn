"""Logix's review runs each script task draft on a sample record and sends a failure back to the writer.

The run is rolled back. A failure becomes a check the writer must fix; a success is described in the reply.
"""

import re

import frappe

from processa.ai_agent_security.code_checks.script_gate import script_task_findings
from processa.patches.v1_0.approve_live_script_tasks import approve
from processa.patches.v1_0.logix_review_passes_items_needing_approval import REVIEW_SCRIPT, edit_script

MODEL_NAME = "Logix \u2013 Script Task Agent"
SCRIPT_TASK = "review_script"
MARKER = "_trial"
TRIAL = """{0}_trial = None
{0}if _valid and _py_block and shape_kind == "script_task":
{0}    from processa.ai_agent_registry.definitions.logix.dry_run import dry_run
{0}    _trial = dry_run(code, turn)
{0}    if _trial.get("error"):
{0}        _valid = False
{0}        _checks = [{{
{0}            "category": "Trial run",
{0}            "rule": "The script failed when run on " + _trial["record"] + ". Fix it. Traceback:\\n" + _trial["error"],
{0}            "line": _trial["line"],
{0}            "code": _trial["code"],
{0}        }}]
{0}        _vres = {{"findings": _checks}}
{0}        _violations = [_checks[0]["rule"] + " (line " + str(_trial["line"]) + ": `" + _trial["code"] + "`)"]
"""
REPORT = """{0}if _trial:
{0}    candidate = candidate.rstrip() + "\\n\\n" + _trial["summary"]
"""
EDITS = (
	(
		re.compile(r"^( *)(if _valid:\n *# \u2500\u2500 optimise)", re.MULTILINE),
		lambda m: TRIAL.format(m[1]) + m[1] + m[2],
	),
	(
		re.compile(r"^( *)(if _needs_approval:\n)", re.MULTILINE),
		lambda m: REPORT.format(m[1]) + m[1] + m[2],
	),
)


def execute():
	edit_script(REVIEW_SCRIPT, MARKER, EDITS)
	process = frappe.db.get_value("BPMN Process Model", MODEL_NAME, "process_name")
	code = frappe.db.get_value("Server Script", REVIEW_SCRIPT, "script") or ""
	if process and MARKER in code and script_task_findings(code, process, SCRIPT_TASK, REVIEW_SCRIPT):
		approve(process, SCRIPT_TASK, SCRIPT_TASK, REVIEW_SCRIPT)
