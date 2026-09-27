"""
Classify Intent and Confirm ran as two separate LLM calls back to back for
every new action request: one to decide GENERATE_NEW/OVERWRITE_EXISTING/
MODIFY_EXISTING, a second, separate round-trip to write the "Shall I go
ahead?" summary. Each live call costs a few seconds on its own, so the pair
cost roughly twice what one call needs, before the process is even drawn.

The intent_classifier prompt now also writes the confirmation message in the
same response when its intent is an action intent, following the same rules
the Confirmer sub-prompt already used (plain language, 2-4 sentences, ends
with a yes/no question, mentions an unavoidable layout crossing). Classify
Intent absorbs Confirm's routing and its overwrite-warning preserver, and
sets next="finalize" directly instead of next="confirm" - the separate
Confirm tool is no longer reached from this path but is left in place
untouched.

Idempotent: each edit fires only when its anchor is present and the new text
is not.
"""

import frappe

AGENT_ID = "prosally_agent"

PROMPT_OLD = (
	"- Anything outside process modelling scope is IRRELEVANT.\n\n"
	'Respond with ONLY a JSON object — no other text:\n'
	'{"intent": "GENERATE_NEW|OVERWRITE_EXISTING|MODIFY_EXISTING|AMBIGUOUS|INCOMPLETE|IRRELEVANT", '
	'"reason": "one short sentence"}'
)
PROMPT_NEW = (
	"- Anything outside process modelling scope is IRRELEVANT.\n\n"
	"When your intent is GENERATE_NEW, OVERWRITE_EXISTING, or MODIFY_EXISTING, also write the "
	"confirmation message the person will see before you act, in the SAME response. The person is "
	"NOT technical: never use words like BPMN, XML, flow, element, gateway, node, or modelling.\n"
	"- Tell them plainly what you are about to do:\n"
	'  - GENERATE_NEW: "I\'ll draw the [process name] process for you from scratch..."\n'
	'  - OVERWRITE_EXISTING: "I\'ll redraw the [process name] process completely..."\n'
	'  - MODIFY_EXISTING: "I\'ll update [the specific part] of the [process name] process..."\n'
	"- List the main steps or decisions you understood from their description.\n"
	"- Keep it short, 2 to 4 sentences plus a brief list.\n"
	'- End with a simple yes/no question such as "Shall I go ahead?"\n'
	"- If the conversation shows the compiler reported the process as non-planar, say before asking "
	"that the change introduces one unavoidable crossing line.\n"
	'For AMBIGUOUS, INCOMPLETE, and IRRELEVANT, leave "summary" and "question" empty.\n\n'
	"Respond with ONLY a JSON object, no other text:\n"
	'{"intent": "GENERATE_NEW|OVERWRITE_EXISTING|MODIFY_EXISTING|AMBIGUOUS|INCOMPLETE|IRRELEVANT", '
	'"reason": "one short sentence", "summary": "the confirmation message described above, or empty", '
	'"question": "the yes/no question, or empty"}'
)

# Present once applied - the "already done" signal, and the anchor checked
# below for a prompt that has drifted out from under this patch.
_MARKER = "also write the"

CLASSIFY_INTENT = r'''# ProsAlly – Tool Classify Intent (self-contained, FLAT top-level code).
# Runs under the AI Agent shape-tool exec (split globals/locals) — NO def/lambda
# and no comprehension referencing a module-level import/const.
# Classify the modelling request and, in the same call, write the
# confirmation message for an action intent. Called first. If
# confirmed_action set, adopt it.
import json
import re
from one_bpmn.agents.turn_state import get_turn, run_sync, update_turn
from one_bpmn.agents.llm_provider import get_llm_adapter_from_settings
from one_bpmn.one_bpmn.doctype.ai_agent_configuration.ai_agent_configuration import get_agent_config
# Property preservation is INLINED (self-contained dispatcher) — no backend
# dependency. Helpers are NESTED inside the dispatcher so they close over its
# scope and survive the shape-tool split globals/locals exec.
def _prosally_preserver(mode, arg_a="", arg_b=None):
    # Self-contained BPMN property preserver (inlined for the ProsAlly shape-tool
    # split-namespace exec). All helpers are nested so they close over this
    # function's scope; nothing is referenced from the top-level exec locals.
    # modes: "extract" -> configured dict; "summarize" -> str; "transfer" ->
    # (merged_xml, removed); "format_removal" -> str; "overwrite_warning" -> str.
    import re
    from xml.etree import ElementTree as ET

    NS = {
        "bpmn": "http://www.omg.org/spec/BPMN/20100524/MODEL",
        "bpmndi": "http://www.omg.org/spec/BPMN/20100524/DI",
        "dc": "http://www.omg.org/spec/DD/20100524/DC",
        "di": "http://www.omg.org/spec/DD/20100524/DI",
        "spiffworkflow": "http://spiffworkflow.org/bpmn/schema/1.0/core",
        "custom": "http://custom/text-style",
        "camunda": "http://camunda.org/schema/1.0/bpmn",
    }
    _EXTENSION_NS_URIS = (
        "{http://spiffworkflow.org/bpmn/schema/1.0/core}",
        "{http://custom/text-style}",
        "{http://camunda.org/schema/1.0/bpmn}",
    )
    _ATTR_FAMILY_LABELS = {
        "serverScript": "Server Script",
        "assignmentMode": "Assignment Mode",
        "assigneeDocField": "Assignee (Doc Field)",
        "roundRobinRole": "Round Robin Role",
        "loadBalancingRole": "Load Balancing Role",
        "leaveRelieverEnabled": "Leave Reliever",
        "triggerType": "Trigger Type",
        "triggerDoctype": "Trigger DocType",
        "serviceType": "Service Type",
        "serviceTargetDoctype": "Target DocType",
        "workflowState": "Workflow State",
        "docStatus": "Doc Status",
        "emailSubject": "Email Subject",
        "emailTo": "Email To",
        "emailBody": "Email Body",
        "emailAccount": "Email Account",
        "gchatMessage": "Google Chat Message",
        "gchatSpaceId": "Google Chat Space",
        "pushTitle": "Push Notification Title",
        "pushMessage": "Push Notification Message",
        "updateFieldDoctype": "Update Field DocType",
        "updateFieldName": "Update Field Name",
        "updateFieldValue": "Update Field Value",
        "calledDecisionId": "Decision Table",
        "notificationName": "Notification",
        "fontFamily": "Font Family",
        "fontSize": "Font Size",
        "fontWeight": "Font Weight",
        "fontStyle": "Font Style",
        "textColor": "Text Color",
        "textDecoration": "Text Decoration",
        "assignee": "Assignee",
        "candidateGroups": "Candidate Groups",
        "candidateUsers": "Candidate Users",
        "formKey": "Form Key",
        "dueDate": "Due Date",
        "followUpDate": "Follow-Up Date",
        "priority": "Priority",
        "asyncBefore": "Async Before",
        "asyncAfter": "Async After",
    }

    def _register_namespaces():
        for _p, _u in NS.items():
            ET.register_namespace(_p, _u)

    def _is_extension_attr(attr_name):
        for _uri in _EXTENSION_NS_URIS:
            if attr_name.startswith(_uri):
                return True
        return False

    def _short_attr_name(attr_name):
        if "}" in attr_name:
            return attr_name.split("}", 1)[1]
        return attr_name

    def _attr_label(clark_name):
        _local = _short_attr_name(clark_name)
        return _ATTR_FAMILY_LABELS.get(_local, _local)

    def _element_type_label(tag):
        _local = tag.split("}", 1)[-1] if "}" in tag else tag
        _label = re.sub(r"([a-z])([A-Z])", r"\1 \2", _local)
        return _label.title()

    def _get_documentation_text(elem):
        _doc_el = elem.find("{" + NS["bpmn"] + "}documentation")
        if _doc_el is not None and _doc_el.text:
            return _doc_el.text.strip()
        return None

    def _set_documentation(elem, text):
        _doc_tag = "{" + NS["bpmn"] + "}documentation"
        _doc_el = elem.find(_doc_tag)
        if _doc_el is not None:
            if not (_doc_el.text or "").strip():
                _doc_el.text = text
        else:
            _doc_el = ET.Element(_doc_tag)
            _doc_el.text = text
            elem.insert(0, _doc_el)

    def extract_configured_elements(xml):
        if not xml or not xml.strip():
            return {}
        _register_namespaces()
        try:
            _root = ET.fromstring(xml)
        except ET.ParseError:
            return {}
        _configured = {}
        for _elem in _root.iter():
            _tag = _elem.tag
            _skip = False
            for _ns in (NS["bpmndi"], NS["dc"], NS["di"]):
                if _ns in _tag:
                    _skip = True
                    break
            if _skip:
                continue
            _elem_id = _elem.get("id")
            if not _elem_id:
                continue
            _ext_attrs = {}
            for _an, _av in _elem.attrib.items():
                if _is_extension_attr(_an):
                    _ext_attrs[_an] = _av
            _ext_elements_xml = None
            _ext_el = _elem.find("{" + NS["bpmn"] + "}extensionElements")
            if _ext_el is not None and len(_ext_el) > 0:
                _ext_elements_xml = ET.tostring(_ext_el, encoding="unicode")
            _documentation = _get_documentation_text(_elem)
            if _ext_attrs or _ext_elements_xml or _documentation:
                _configured[_elem_id] = {
                    "name": _elem.get("name", _elem_id),
                    "type": _element_type_label(_tag),
                    "attrs": _ext_attrs,
                    "extension_elements_xml": _ext_elements_xml,
                    "documentation": _documentation,
                }
        return _configured

    def transfer_properties(old_xml, new_xml):
        if not old_xml or not old_xml.strip() or not new_xml or not new_xml.strip():
            return new_xml, []
        _old_configured = extract_configured_elements(old_xml)
        if not _old_configured:
            return new_xml, []
        _register_namespaces()
        try:
            _new_root = ET.fromstring(new_xml)
        except ET.ParseError:
            return new_xml, []
        _new_by_id = {}
        for _elem in _new_root.iter():
            _eid = _elem.get("id")
            if _eid:
                _new_by_id[_eid] = _elem
        _removed = []
        for _elem_id, _old_data in _old_configured.items():
            if _elem_id in _new_by_id:
                _new_elem = _new_by_id[_elem_id]
                for _clark, _val in _old_data["attrs"].items():
                    _new_elem.set(_clark, _val)
                if _old_data["extension_elements_xml"]:
                    try:
                        _old_ext_el = ET.fromstring(_old_data["extension_elements_xml"])
                        _new_ext_el = _new_elem.find("{" + NS["bpmn"] + "}extensionElements")
                        if _new_ext_el is None:
                            _new_ext_el = ET.SubElement(_new_elem, "{" + NS["bpmn"] + "}extensionElements")
                        for _child in _old_ext_el:
                            _new_ext_el.append(_child)
                    except ET.ParseError:
                        pass
                if _old_data.get("documentation"):
                    _set_documentation(_new_elem, _old_data["documentation"])
            else:
                _configs = []
                for _clark, _val in _old_data["attrs"].items():
                    _configs.append(_attr_label(_clark) + ": " + _val)
                if _old_data["extension_elements_xml"]:
                    _configs.append("Extension Elements (pre/post scripts or other)")
                if _old_data.get("documentation"):
                    _doc_preview = _old_data["documentation"][:80]
                    if len(_old_data["documentation"]) > 80:
                        _doc_preview = _doc_preview + "…"
                    _configs.append("Documentation: " + _doc_preview)
                _removed.append({
                    "id": _elem_id,
                    "name": _old_data["name"],
                    "type": _old_data["type"],
                    "configs": _configs,
                })
        _merged_xml = ET.tostring(_new_root, encoding="unicode", xml_declaration=True)
        _merged_xml = re.sub(
            r"^<\?xml\s[^?]*\?>",
            '<?xml version="1.0" encoding="UTF-8"?>',
            _merged_xml,
        )
        return _merged_xml, _removed

    def format_removal_warning(removed_elements):
        if not removed_elements:
            return ""
        _lines = [
            "I've prepared the changes, but the following configured shapes "
            "will be removed and their settings will be lost:\n"
        ]
        for _elem in removed_elements:
            _name = _elem.get("name", _elem.get("id", "Unknown"))
            _etype = _elem.get("type", "Element")
            _configs = _elem.get("configs", [])
            _line = "• **" + _name + "** (" + _etype + ")"
            if _configs:
                _detail = list(_configs[:3])
                if len(_configs) > 3:
                    _detail.append("and " + str(len(_configs) - 3) + " more")
                _line = _line + " — " + ", ".join(_detail)
            _lines.append(_line)
        _lines.append(
            "\nThese configurations (scripts, assignments, triggers, documentation, etc.) "
            "cannot be recovered after applying the changes."
            "\n\nShall I apply the changes anyway?"
        )
        return "\n".join(_lines)

    def summarize_configured_elements(configured):
        if not configured:
            return ""
        _lines = [
            "This will completely replace the existing diagram. "
            "The following shapes have configurations that will be lost:\n"
        ]
        for _elem_id, _data in configured.items():
            _name = _data.get("name", _elem_id)
            _etype = _data.get("type", "Element")
            _attrs = _data.get("attrs", {})
            _config_labels = []
            for _clark in _attrs:
                _lbl = _attr_label(_clark)
                if _lbl not in _config_labels:
                    _config_labels.append(_lbl)
            if _data.get("extension_elements_xml"):
                _config_labels.append("Extension Elements")
            if _data.get("documentation"):
                _config_labels.append("Documentation")
            _line = "• **" + _name + "** (" + _etype + ")"
            if _config_labels:
                _line = _line + " — " + ", ".join(_config_labels[:4])
                if len(_config_labels) > 4:
                    _line = _line + " and " + str(len(_config_labels) - 4) + " more"
            _lines.append(_line)
        _lines.append(
            "\nAll of these configurations will be lost. "
            "Are you sure you want to proceed?"
        )
        return "\n".join(_lines)

    if mode == "extract":
        return extract_configured_elements(arg_a)
    if mode == "summarize":
        return summarize_configured_elements(arg_b)
    if mode == "transfer":
        return transfer_properties(arg_a, arg_b)
    if mode == "format_removal":
        return format_removal_warning(arg_b)
    if mode == "overwrite_warning":
        _cfg = extract_configured_elements(arg_a)
        if not _cfg:
            return ""
        return summarize_configured_elements(_cfg)
    return None

_ACTION_INTENTS = frozenset({"GENERATE_NEW", "OVERWRITE_EXISTING", "MODIFY_EXISTING"})
_GENERATE_INTENTS = frozenset({"GENERATE_NEW", "OVERWRITE_EXISTING"})
_NEEDS_CLARIFICATION = frozenset({"AMBIGUOUS", "INCOMPLETE"})

turn = get_turn(context_docname)
confirmed = (turn.get("confirmed_action") or "").strip()

if confirmed in _ACTION_INTENTS:
    update_turn(context_docname, intent=confirmed, confirmed=True)
    nxt = "generate_process" if confirmed in _GENERATE_INTENTS else "modify_process"
    result["intent"] = confirmed
    result["already_confirmed"] = True
    result["next"] = nxt
else:
    _cfg = get_agent_config("prosally_agent") or {}
    _cfg.setdefault("agent_id", "prosally_agent")
    _subs = _cfg.get("sub_prompts") or {}
    _adapter = get_llm_adapter_from_settings(_cfg)

    process_name = turn.get("process_name", "")
    message = turn.get("user_text", "")
    chat_history = turn.get("chat_history", []) or []
    current_xml = turn.get("current_xml", "")

    # ── format history (inline) ──
    _hist = ""
    if chat_history:
        _hlines = []
        for _e in chat_history[-10:]:
            _role = _e.get("role") or _e.get("type", "user")
            _content = (_e.get("content") or "").strip()
            if _content:
                _hlines.append(("User" if _role == "user" else "ProsAlly") + ": " + _content)
        _hist = "\n".join(_hlines)

    # ── build intent prompt (inline) ──
    _parts = []
    if process_name:
        _parts.append("Process being modelled: " + process_name)
    if _hist:
        _parts.append("Conversation so far:\n" + _hist)
    _parts.append("User message: " + message)
    prompt = "\n\n".join(_parts)

    _system = (_subs.get("intent_classifier") or {}).get("prompt") or ""
    raw = run_sync(_adapter.complete(system=_system, user=prompt)).text

    # ── best-effort JSON extraction (inline) ──
    data = None
    if raw:
        _cands = [raw.strip()]
        _s2 = raw.strip()
        if _s2.startswith("```"):
            _s2 = _s2.split("\n", 1)[-1]
            if _s2.rstrip().endswith("```"):
                _s2 = _s2.rstrip()[: _s2.rstrip().rfind("```")]
        _cands.append(_s2.strip())
        _fenced = re.search(r"```(?:json)?\s*\n(.*?)```", raw, re.DOTALL)
        if _fenced:
            _cands.append(_fenced.group(1).strip())
        _start = raw.find("{")
        if _start != -1:
            _depth = 0
            for _i in range(_start, len(raw)):
                if raw[_i] == "{":
                    _depth += 1
                elif raw[_i] == "}":
                    _depth -= 1
                    if _depth == 0:
                        _cands.append(raw[_start:_i + 1])
                        break
        for _c in _cands:
            try:
                _p = json.loads(_c)
                if isinstance(_p, dict):
                    data = _p
                    break
            except (json.JSONDecodeError, TypeError):
                continue

    intent = "INCOMPLETE"
    reason = ""
    summary = ""
    question = ""
    if data:
        intent = str(data.get("intent", "INCOMPLETE")).upper()
        reason = data.get("reason", "")
        summary = data.get("summary", "") or ""
        question = data.get("question", "") or ""
    if intent not in (_ACTION_INTENTS | _NEEDS_CLARIFICATION | frozenset({"IRRELEVANT"})):
        intent = "INCOMPLETE"

    update_turn(context_docname, intent=intent, intent_reason=reason, confirmed=False)
    result["intent"] = intent
    result["reason"] = reason

    if intent == "IRRELEVANT":
        result["next"] = "redirect"
    elif intent in _NEEDS_CLARIFICATION:
        result["next"] = "clarify"
    else:
        # An action intent that has not been confirmed yet. The confirmation
        # message came back in this same response, so no separate call runs.
        if not question:
            question = "Shall I go ahead?"
        response_text = (summary + "\n" + question) if summary else question

        # Warn about configuration that an OVERWRITE would discard.
        if intent == "OVERWRITE_EXISTING" and current_xml.strip():
            _overwrite_warning = _prosally_preserver("overwrite_warning", current_xml)
            if _overwrite_warning:
                response_text = response_text + "\n\n⚠️ **Warning:**\n" + _overwrite_warning

        output = {
            "intent": "CONFIRM",
            "action_intent": intent,
            "response": response_text,
            "options": ["Yes, proceed", "No, let me adjust"],
        }
        update_turn(context_docname, output=output, done=True)
        result["next"] = "finalize"
'''


def execute():
	original_user = frappe.session.user
	try:
		frappe.set_user("Administrator")

		name = frappe.db.get_value("AI Agent Configuration", {"agent_id": AGENT_ID}, "name")
		if name:
			doc = frappe.get_doc("AI Agent Configuration", name)
			updated = False
			for row in doc.sub_prompts:
				if row.sub_agent_id != "intent_classifier":
					continue
				text = row.prompt_text or ""
				if PROMPT_NEW not in text and PROMPT_OLD in text:
					row.prompt_text = text.replace(PROMPT_OLD, PROMPT_NEW, 1)
					updated = True
				elif _MARKER not in text:
					frappe.log_error(
						title="prosally_merge_classify_and_confirm: anchor not found",
						message="intent_classifier prompt_text does not contain the expected trailing block.",
					)
			if updated:
				doc.save(ignore_permissions=True)

		if frappe.db.exists("Server Script", "ProsAlly – Tool Classify Intent"):
			script_doc = frappe.get_doc("Server Script", "ProsAlly – Tool Classify Intent")
			if (script_doc.script or "").strip() != CLASSIFY_INTENT.strip():
				script_doc.script = CLASSIFY_INTENT
				script_doc.save(ignore_permissions=True)

		frappe.db.commit()
	finally:
		frappe.set_user(original_user)
