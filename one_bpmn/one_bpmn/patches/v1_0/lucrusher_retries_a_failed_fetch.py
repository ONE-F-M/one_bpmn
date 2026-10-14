"""LuCrusher can fetch a Lucidchart document again after a failed fetch.

A failed fetch left an error dict in the turn store, finalize passed it on as the
document, and Save Response stored it as the document summary (page_count 0).
Build Context then showed "ALREADY FETCHED - do not re-fetch", preloaded the
topology skill, and the prompt forbade re-running a tool the context reports as
done, so "retry" was refused. Now an error or a document with no pages is kept as
last_fetch_error, Build Context says "fetch failed (...) - retry allowed" without
the topology skill, the prompt allows a retry, and a 403 names the Lucid account
to share the document with.

Edits the live Server Scripts and the agent prompt by anchor. Idempotent: a target
already carrying its marker is left alone, and a target missing an anchor is
reported and not written.
"""

import frappe

DASH = "–"
BUILD_CONTEXT = f"LuCrusher {DASH} Build Context"
SAVE_RESPONSE = f"LuCrusher {DASH} Save Response"
FETCH_TOOL = f"LuCrusher {DASH} Tool Fetch Lucidchart Document"
AGENT_ID = "lucrusher"

BUILD_CONTEXT_EDITS = [
	(
		'    "topology", "migration_tasks", "prosally_prompts",\n)\n',
		'    "topology", "migration_tasks", "prosally_prompts", "last_fetch_error",\n)\n',
	),
	(
		'    doc_obj = state.get("document")\n    if doc_obj and isinstance(doc_obj, dict):\n',
		'''    doc_obj = state.get("document")
    _failed = state.get("last_fetch_error")
    if isinstance(doc_obj, dict) and not (doc_obj.get("pages") or doc_obj.get("page_count")):
        _failed = _failed or {"document_id": doc_obj.get("title")}
        doc_obj = None
    if doc_obj and isinstance(doc_obj, dict):
''',
	),
	(
		'    else:\n        lines.append("  Lucidchart document : not yet fetched")\n',
		'''    elif _failed:
        _why = (_failed.get("error") if isinstance(_failed, dict) else _failed) or "the document returned 0 pages"
        _id = _failed.get("document_id") if isinstance(_failed, dict) else None
        lines.append(
            "  Lucidchart document : fetch failed (" + str(_why) + ") - retry allowed"
            + (". Document id: " + str(_id) if _id else "")
        )
    else:
        lines.append("  Lucidchart document : not yet fetched")
''',
	),
	(
		"if _next_skill:\n    for _phase_skill in sorted(",
		'''_doc_state = context_state.get("document")
_fetched = isinstance(_doc_state, dict) and bool(_doc_state.get("pages") or _doc_state.get("page_count"))
if not _fetched and (_doc_state or context_state.get("last_fetch_error")):
    deactivate_skill("lucrusher-topology-analysis", agent_configuration, instance)
    if _next_skill == "lucrusher-topology-analysis":
        _next_skill = ""
if _next_skill:
    for _phase_skill in sorted(''',
	),
]

SAVE_RESPONSE_EDITS = [
	(
		'_doc = _pick("document")\n_doc_summary = None\n',
		'''_fetched = agent_result.get("document")
_last_fetch_error = _prev.get("last_fetch_error")
if isinstance(_fetched, dict) and _fetched:
    _fetch_failed = bool(_fetched.get("error")) or not _fetched.get("pages")
    _last_fetch_error = {
        "document_id": _fetched.get("document_id"),
        "error": _fetched.get("error") or "the document returned 0 pages",
    } if _fetch_failed else None
    _doc = _prev.get("document") if _fetch_failed else _pick("document")
else:
    _doc = _pick("document")
_doc_summary = None
''',
	),
	(
		'    "prosally_prompts": _pp,\n}\nfrom one_bpmn.agents.memory.session_state import record',
		'    "prosally_prompts": _pp,\n    "last_fetch_error": _last_fetch_error,\n}\nfrom one_bpmn.agents.memory.session_state import record',
	),
]

SHARE_HINT = '''def _lucrusher_share_hint(frappe, base_url, headers):
    email = ""
    try:
        profile = frappe.integrations.utils.make_get_request(base_url + "/v1/users/me/profile", headers=headers)
        email = (profile or {}).get("email") or ""
    except Exception:
        frappe.log_error(title="LuCrusher - Lucidchart profile lookup", message=frappe.get_traceback())
    who = ("the Lucid account " + email) if email else "the Lucid account that owns the platform API key"
    return (
        "Lucidchart API returned 403 Forbidden: the document is not shared with the account behind the "
        "platform API key. Share it with " + who + " (Share, then add that email as Viewer or higher), "
        "wait a minute, then tell me to retry."
    )


def _lucrusher_trim_document(doc):'''

FETCH_TOOL_EDITS = [
	("def _lucrusher_trim_document(doc):", SHARE_HINT),
	(
		'''            return _fail(
                document_id,
                "Lucidchart API returned 403 Forbidden. The API key is valid but does "
                "not have permission to access this document. Ensure the document is "
                "shared with the account that owns the API key, or that the API key "
                "scope includes document read access.",
            )''',
		"            return _fail(document_id, _lucrusher_share_hint(frappe, base_url, auth_headers))",
	),
	(
		'"the API key and update the \'Lucidchart\' API Integration record."',
		'"the API key. Ask the platform admin to do this; a process owner cannot change it."',
	),
]

PROMPT_ANCHOR = "Do NOT re-run a tool the migration context above already reports as done."
PROMPT_NEW = PROMPT_ANCHOR + " A tool that returned an error is not done; retry it when the user asks."

SCRIPT_TARGETS = (
	(BUILD_CONTEXT, "last_fetch_error", BUILD_CONTEXT_EDITS),
	(SAVE_RESPONSE, "last_fetch_error", SAVE_RESPONSE_EDITS),
	(FETCH_TOOL, "_lucrusher_share_hint", FETCH_TOOL_EDITS),
)


def apply_edits(code, edits):
	"""The code with every edit applied, or None when an anchor is missing."""
	for anchor, replacement in edits:
		if code.count(anchor) != 1:
			return None
		code = code.replace(anchor, replacement)
	return code


def execute():
	for name, marker, edits in SCRIPT_TARGETS:
		if not frappe.db.exists("Server Script", name):
			continue
		code = frappe.db.get_value("Server Script", name, "script") or ""
		if marker in code:
			continue
		patched = apply_edits(code, edits)
		if patched is None:
			frappe.log_error(
				title="LuCrusher retry: anchor not found",
				message=f"{name} no longer matches the text this patch edits; apply the retry change by hand.",
			)
			continue
		frappe.db.set_value("Server Script", name, "script", patched, update_modified=False)

	config = frappe.db.get_value("AI Agent Configuration", {"agent_id": AGENT_ID}, "name")
	prompt = (frappe.db.get_value("AI Agent Configuration", config, "system_prompt") or "") if config else ""
	if PROMPT_ANCHOR in prompt and PROMPT_NEW not in prompt:
		frappe.db.set_value(
			"AI Agent Configuration", config, "system_prompt", prompt.replace(PROMPT_ANCHOR, PROMPT_NEW, 1)
		)
