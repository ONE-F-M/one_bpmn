"""General Chat can search the DMS: creates the tool script behind the search_dms_documents shape and adds the DMS rules to the prompt."""

import frappe

AGENT_ID = "lumina_general_chat"
TOOL_SCRIPT = "Lumina - Tool DMS Search"
MARKER = "search_dms_documents"

SCRIPT = """\
# Lumina tool: search_dms_documents. The shape's arguments arrive in task_data.
from one_bpmn.agents.dms_search import search_dms_documents

result["output"] = search_dms_documents(task_data.get("query"), task_data.get("document_type"), instance=instance)
"""

DMS_PROMPT = """

COMPANY DOCUMENTS (DMS):
- For questions about company policies, procedures, manuals, guidelines or knowledge base articles, call `search_dms_documents` first. Use `search_company_wiki` only when the DMS has nothing on the topic.
- Base the answer only on the returned excerpts. When nothing is returned, say the DMS has nothing on the topic and do not answer from general knowledge.
- Name the document you relied on by its code and title, and say what type it is.
- Document types: a Policy is mandatory and sets the rules; an SOP is the required step-by-step procedure; a Manual is reference material on how a system or tool works; a Guideline is recommended practice; a Knowledge Base article is informational.
- When documents of different types disagree, the type earlier in this order governs, and you must say that you are applying it: Policy, SOP, Manual, Guideline, Knowledge Base.
- Pass `document_type` when the user asks for one type, for example "what does the policy say".
- Do not paste raw tool output or document links into the answer."""


def execute():
	_upsert_tool_script()
	append_prompt()


def _upsert_tool_script():
	if frappe.db.exists("Server Script", TOOL_SCRIPT):
		frappe.db.set_value("Server Script", TOOL_SCRIPT, "script", SCRIPT)
		return
	frappe.get_doc(
		{"doctype": "Server Script", "name": TOOL_SCRIPT, "script_type": "API", "allow_guest": 0, "disabled": 0, "script": SCRIPT}
	).insert(ignore_permissions=True)


def append_prompt():
	name = frappe.db.get_value("AI Agent Configuration", {"agent_id": AGENT_ID}, "name")
	if not name:
		return

	prompt = frappe.db.get_value("AI Agent Configuration", name, "system_prompt") or ""
	if MARKER in prompt:
		return

	frappe.db.set_value("AI Agent Configuration", name, "system_prompt", prompt.rstrip() + DMS_PROMPT)
	frappe.cache.delete_value(f"agent_config:{AGENT_ID}")
