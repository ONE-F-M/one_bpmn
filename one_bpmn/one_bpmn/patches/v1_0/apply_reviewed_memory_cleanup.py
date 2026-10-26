"""Applies the reviewed AI Memory clean-up listed in data/memory_actions.csv.

Every row was read and given one action by hand; nothing is decided here. A name that no
longer exists is skipped, so the patch is safe to re-run. Run delete_retired_memories
by hand after 30 days to remove the retired rows nobody asked back.
"""

import csv
import json
from collections import Counter
from pathlib import Path

import frappe
from frappe.utils import add_days, get_datetime, now_datetime

from one_bpmn.agents.memory.prune import _invalidate
from one_bpmn.agents.memory.tools import _json_loads
from one_bpmn.one_bpmn.patches.v1_0.prompt_block import with_block

ACTIONS_CSV = Path(__file__).parent / "data" / "memory_actions.csv"
RETIRE_REASON = "reviewed clean-up"
RETENTION_DAYS = 30
SUB_AGENT_ELEMENTS = ("write_script", "write_agent_tool", "clarify")
PARENT_ELEMENT = "run_logix_agent"

SCRIPT_CONTRACT = ("AI Skill", "bpmn-script-task-contract", "body")
SCRIPT_SAFETY = ("AI Skill", "frappe-server-script-safety", "body")
FORM_DESIGN = ("AI Skill", "doctype-form-design-rules", "body")
TOPOLOGY = ("AI Skill", "lucrusher-topology-analysis", "body")
PROSALLY_PROMPTS = ("AI Skill", "lucrusher-prosally-prompts", "body")
MODELLING = ("AI Skill", "bpmn-modelling-rules-and-ir-schema", "body")
LUCRUSHER_PROMPT = ("AI Agent Configuration", "Lucrusher", "system_prompt")
LOGIX_PROMPT = ("AI Agent Configuration", "Logix", "system_prompt")

LUCIDCHART_ERRORS = """\
Lucidchart access errors:
- 401 Unauthorized: the API key is invalid, expired or lacks permission. Generate a new key with
  read permission in Lucidchart account settings and update the Lucidchart API Integration record.
- 403 or permission denied on a document: read the account email on the Lucidchart API
  Integration record, then ask the owner to share the document with that email with View access.
"""

# name -> (target, marker already in the target or None, block to add when marker is None)
SKILL_RULES = {
	# Already in the named skill.
	"frvh4alv8f": (MODELLING, "ONE re-entry point", None),
	"fn66u2uevr": (MODELLING, "lives in the lane of the role responsible", None),
	"fjeko11b0d": (MODELLING, "EXACTLY that list", None),
	"t786v86sfd": (SCRIPT_SAFETY, "never write `frappe.response`", None),
	"d4fnvvml4a": (SCRIPT_SAFETY, "`globals`, `locals`", None),
	"jut24u5dab": (SCRIPT_SAFETY, "Imports of os, sys, subprocess", None),
	"3is0ql16lm": (SCRIPT_SAFETY, "The `ignore_permissions` keyword in ANY form", None),
	"dhfdem4t1e": (SCRIPT_CONTRACT, 'task_data.get("some_var")', None),
	"7h3mtafbas": (SCRIPT_CONTRACT, "never redefine them", None),
	# Missing from the target: added before the row is deleted.
	"3isg63qddq": (
		SCRIPT_CONTRACT,
		None,
		"""\
## Printing
`print` writes to the worker's console only; the person running the process never sees it.
Put what they need to know on `result` for a later step, or stop with `frappe.throw`.
""",
	),
	"645rhect33": (
		SCRIPT_CONTRACT,
		None,
		"""\
## Script Task or Client Script
A Script Task is Python the engine runs as one step of the process. A Client Script is
JavaScript that runs in the browser when a person uses a form. Write Python here, and do not
offer a Script Task for something that happens on a form button.
""",
	),
	"7l050jf00s": (
		SCRIPT_CONTRACT,
		None,
		"""\
## No endpoint decorators
Never add `@frappe.whitelist()`: the script is top-level engine code, not an HTTP endpoint.
""",
	),
	"3qltl3i9hd": (
		SCRIPT_SAFETY,
		None,
		"""\
## Saving a document
To change a field that has validation or notification logic, load the document and call
`.save()` so its hooks run. `frappe.db.set_value` skips them.
""",
	),
	"5njdle2su1": (
		SCRIPT_SAFETY,
		None,
		"""\
## Reading with the user's permissions
When a script reads records for the acting user, use `frappe.get_list`, which applies their
permissions. `frappe.get_all` and direct database queries do not.
""",
	),
	"9g7rf350ks": (
		SCRIPT_SAFETY,
		None,
		"""\
## Raw SQL
Raw SQL ignores the user's permissions and returns every matching row. When a script needs it,
say so in your reply so the process owner can approve it.
""",
	),
	"s31tjf52et": (
		FORM_DESIGN,
		None,
		"""\
## Mandatory and read-only
A field that is both mandatory and read-only needs a way to fill itself in: a fetch from a
linked document, a default, or a script. Without one the person cannot save the form.
""",
	),
	"ujlt4qnd50": (
		TOPOLOGY,
		None,
		"""\
## Reference pages
Legend, training and overview pages (BPMN legends, example workflows, high-level orchestrator
pages) are reference material. Keep them as Lucidchart reference and propose no process for them.
""",
	),
	"u91hi89spu": (
		TOPOLOGY,
		None,
		"""\
## Forms
A form definition (for example the Medical and PCC forms) is a Processa DocType with a form,
not a BPMN process, even when it appears in a process diagram.
""",
	),
	"mnkfe7f261": (
		TOPOLOGY,
		None,
		"""\
## Shared DocType
Independent subprocesses can share one DocType when a workflow state or a type field (for
example movement_type) tells them apart. Do not propose a DocType per subprocess.
""",
	),
	"bm639qthds": (
		PROSALLY_PROMPTS,
		None,
		"""\
## Using the prompts
Tell the developer to paste each prompt block into the AI configuration panel of its Process
record before running ProsAlly, which generates the BPMN 2.0 XML from it.
""",
	),
	"1cb8tqobce": (LUCRUSHER_PROMPT, None, LUCIDCHART_ERRORS),
	"8kps0a2mn2": (LUCRUSHER_PROMPT, None, LUCIDCHART_ERRORS),
	"37fphnmv3b": (
		LOGIX_PROMPT,
		None,
		"""\
Gateway routing errors:
- "No conditions satisfied for Gateway_X" means no earlier script set the variable the gateway
  checks. Read the gateway's conditions, name the exact variable, and find the script that
  should set it on `result`.
""",
	),
}


def execute():
	actions = _read_actions()
	counts = Counter()
	for name in _names(actions, "SKILL"):
		_apply_skill_rule(name, counts)
	for name in _names(actions, "DELETE"):
		_delete(name, counts)
	now = now_datetime()
	for name in _names(actions, "RETIRE"):
		_retire(name, now, counts)
	for name in _names(actions, "USER"):
		_keep(name, counts, user=actions[name]["set_user"])
	for name in _names(actions, "SHARED"):
		_keep(name, counts, shared=True)
	frappe.logger("one_bpmn").info(f"AI Memory reviewed clean-up: {dict(counts)}")
	return counts


def delete_retired_memories():
	"""Deletes rows retired by execute() that nobody asked back within the retention window."""
	cutoff = get_datetime(add_days(now_datetime(), -RETENTION_DAYS))
	counts = Counter()
	names = frappe.get_all(
		"AI Memory",
		filters={"expires_on": ["is", "set"], "user_directed": 0, "metadata": ["like", f"%{RETIRE_REASON}%"]},
		pluck="name",
	)
	for name in names:
		pruned = (_json_loads(frappe.db.get_value("AI Memory", name, "metadata")) or {}).get("pruned") or {}
		if pruned.get("reason") != RETIRE_REASON:
			continue
		if get_datetime(pruned.get("on")) > cutoff:
			counts["too_early"] += 1
			continue
		frappe.delete_doc("AI Memory", name, ignore_permissions=True, force=True)
		counts["deleted"] += 1
	print(f"AI Memory retired rows: {dict(counts)}")


def _read_actions() -> dict[str, dict]:
	with open(ACTIONS_CSV, newline="", encoding="utf-8") as f:
		return {row["name"]: row for row in csv.DictReader(f)}


def _names(actions: dict, action: str) -> list[str]:
	return [name for name, row in actions.items() if row["action"] == action]


def _apply_skill_rule(name: str, counts: Counter):
	if not frappe.db.exists("AI Memory", name):
		counts["SKILL missing"] += 1
		return
	(doctype, docname, field), marker, block = SKILL_RULES[name]
	if not frappe.db.exists(doctype, docname):
		counts["SKILL target missing"] += 1
		return
	doc = frappe.get_doc(doctype, docname)
	if marker is None:
		marker = block.strip().splitlines()[0]
		if marker not in (doc.get(field) or ""):
			doc.set(field, with_block(doc.get(field), block))
			doc.save(ignore_permissions=True)
	if marker not in (doc.get(field) or ""):
		counts["SKILL rule not found"] += 1
		return
	frappe.delete_doc("AI Memory", name, ignore_permissions=True, force=True)
	counts["SKILL"] += 1


def _delete(name: str, counts: Counter):
	if not frappe.db.exists("AI Memory", name):
		counts["DELETE missing"] += 1
		return
	frappe.delete_doc("AI Memory", name, ignore_permissions=True, force=True)
	counts["DELETE"] += 1


def _retire(name: str, now, counts: Counter):
	if not frappe.db.exists("AI Memory", name):
		counts["RETIRE missing"] += 1
	elif frappe.db.get_value("AI Memory", name, "expires_on"):
		counts["RETIRE already expired"] += 1
	else:
		_invalidate(name, RETIRE_REASON, now)
		counts["RETIRE"] += 1


def _keep(name: str, counts: Counter, user: str = "", shared: bool = False):
	"""A kept row becomes personal (USER) or standing (SHARED), and active if it had expired."""
	action = "SHARED" if shared else "USER"
	if not frappe.db.exists("AI Memory", name):
		counts[f"{action} missing"] += 1
		return
	doc = frappe.get_doc("AI Memory", name)
	metadata = _json_loads(doc.metadata) or {}
	if shared:
		doc.user_directed = 1
		metadata["reviewed"] = "reviewed 13 Oct"
	else:
		doc.user = user
	if doc.expires_on:
		metadata.pop("pruned", None)
		doc.expires_on = None
		counts[f"{action} reactivated"] += 1
	if doc.agent_element in SUB_AGENT_ELEMENTS:
		doc.agent_element = PARENT_ELEMENT
	doc.metadata = json.dumps(metadata) if metadata else None
	doc.save(ignore_permissions=True, ignore_version=False)
	counts[action] += 1
