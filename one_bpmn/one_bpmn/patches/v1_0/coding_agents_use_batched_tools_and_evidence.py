"""The Dev, Frontend and Mobile agents are told to use the batched tools and to submit evidence, and get 40 tool calls."""

import frappe

from one_bpmn.one_bpmn.patches.v1_0.prompt_block import with_block

AGENTS = ("Dev Agent", "Frontend Agent", "Mobile App Agent")
MAX_TOOL_CALLS = 40
MODEL_RETRIES = 4

RULES = """\
Batched tools and acceptance criteria:
- To read two or more files, use read_files. To find where something is defined or used, use grep_files before reading files one by one.
- Before your first edit, list every change you already know you need, in this file and in others, and make them in one apply_edits call (up to 20 replacements, one commit). Use edit_file only when exactly one change is left. Two edit_file calls in a row means you should have used apply_edits.
- When your instruction lists acceptance criteria as AC1, AC2 and so on, your plan must name each one and say which files and tests address it. Edits are refused until every criterion appears in your latest plan.
- Before open_pull_request, call submit_evidence with one row per criterion. A "done" row must cite a file you changed or a test. Fix what it reports and call it again.
- A criterion you could not finish is "partial" or "not_done", never "done". The pull request is then opened as a draft that lists what is unmet.
- If the instruction lists no criteria, say so in your plan and do not invent any.
"""


def marker() -> str:
	return RULES.splitlines()[0]


def execute():
	for name in AGENTS:
		if not frappe.db.exists("AI Agent Configuration", name):
			continue
		doc = frappe.get_doc("AI Agent Configuration", name)
		prompt = with_block(doc.system_prompt, RULES)
		changed = prompt != doc.system_prompt
		if changed:
			doc.system_prompt = prompt
		if (doc.max_tool_calls or 0) < MAX_TOOL_CALLS:
			doc.max_tool_calls = MAX_TOOL_CALLS
			changed = True
		if (doc.max_retries or 0) < MODEL_RETRIES:
			doc.max_retries = MODEL_RETRIES
			changed = True
		if changed:
			doc.save(ignore_permissions=True)
