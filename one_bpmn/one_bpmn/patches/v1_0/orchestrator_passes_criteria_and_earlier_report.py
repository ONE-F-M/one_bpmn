"""The Orchestrator numbers the acceptance criteria and reads its own earlier report on a re-run.

The rules go on the configuration's prompt, which is the one that reaches the model. The
brief script adds the last report the orchestrator left on the Work Item.
"""

import frappe

from one_bpmn.one_bpmn.patches.v1_0.prompt_block import with_block

AGENT = "Orchestrator Agent"
SCRIPT = "Orchestrator Agent: Read the Work Item"

RULES = """\
Acceptance criteria and earlier attempts:
- In your instruction to a specialist, write the acceptance criteria from the brief as a numbered list (AC1, AC2 and so on) in the reporter's own words. If the brief gives none, say so in the instruction and do not invent any. The numbered list belongs in the instruction only; your final report stays plain sentences.
- When the brief carries an earlier report from the orchestrator, read it first. Tell the specialist what the last attempt did and what stopped it, so the same steps are not repeated.
- When a specialist's report starts with NOT REPRODUCIBLE, do not delegate again. Hand the work item back to a person with the specialist's account of what it tried and what is needed.
"""

ANCHOR = 'result["work_item_brief"] = header + brief'
MARKER = "# Earlier orchestrator report"
EARLIER = r"""# Earlier orchestrator report on this Work Item, so a re-run starts from the last attempt.
earlier = frappe.get_all(
    "Comment",
    filters={
        "reference_doctype": "Work Item",
        "reference_name": wi.name,
        "comment_type": "Comment",
        "content": ["like", "<b>Orchestrator</b>%"],
    },
    fields=["content"],
    order_by="creation desc",
    limit_page_length=1,
)
if earlier:
    last_report = frappe.utils.strip_html(earlier[0].content.split("<br>", 1)[-1]).strip()
    if last_report:
        brief += "\n\nEarlier report from the orchestrator on this work item:\n" + last_report[:2000]
"""


def execute():
	_rules()
	_brief_script()


def marker() -> str:
	return RULES.strip().splitlines()[0]


def _rules():
	if not frappe.db.exists("AI Agent Configuration", AGENT):
		return
	doc = frappe.get_doc("AI Agent Configuration", AGENT)
	prompt = with_block(doc.system_prompt, RULES)
	if prompt != doc.system_prompt:
		doc.system_prompt = prompt
		doc.save(ignore_permissions=True)


def _brief_script():
	if not frappe.db.exists("Server Script", SCRIPT):
		return
	doc = frappe.get_doc("Server Script", SCRIPT)
	script = doc.script or ""
	if MARKER in script or ANCHOR not in script:
		return
	doc.script = script.replace(ANCHOR, EARLIER + ANCHOR, 1)
	doc.save(ignore_permissions=True)
