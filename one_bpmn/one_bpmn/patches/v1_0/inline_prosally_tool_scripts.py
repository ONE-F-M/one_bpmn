"""
Full-rip conversion (ProsAlly per-agent migration): the ProsAlly chat agent's
pipeline stage tools no longer import the ProsAlly agent package. Each tool
Server Script in the process map's ad-hoc Tools sub-process now carries its own
self-contained, FLAT logic; the one_bpmn.agents.google_adk.prosally_agent
package has been deleted.

The top-level bodies are FLAT (no def/lambda, no comprehension referencing a
module-level name) because the AI Agent shape-tool executor runs them under SPLIT
globals/locals (shape_tools._run_server_script) — a top-level nested scope there
cannot see top-level imports/consts. The one exception is the property-preserver:
it is inlined as a single SELF-CONTAINED dispatcher function (``_prosally_preserver``)
whose helpers are NESTED inside it, so they close over the function's own scope and
run correctly under the split exec (verified: passes the security gate and all 13
original preserver unit tests).

They import only shared infrastructure that cannot live in a diagram: turn_state,
the LLM adapter factory, get_agent_config, the BPMN semantic validator, and
bpmn_ir_pipeline — whose ``compile_ir`` shells out to node via ``subprocess``,
which the security gate forbids in a script body, so it is the one transform that
cannot be inlined. ElementTree property preservation IS inlined (above).

Idempotent: only updates a Server Script that exists and whose body differs.
Registered after seed_agent_prompts (which creates the config) in patches.txt.
"""

import frappe

CLASSIFY = r'''# ProsAlly – Tool Classify Intent (self-contained, FLAT top-level code).
# Runs under the AI Agent shape-tool exec (split globals/locals) — NO def/lambda
# and no comprehension referencing a module-level import/const.
# Classify the modelling request. Called first. If confirmed_action set, adopt it.
import json
import re
from one_bpmn.agents.turn_state import get_turn, run_sync, update_turn
from one_bpmn.agents.llm_provider import get_llm_adapter_from_settings
from one_bpmn.one_bpmn.doctype.ai_agent_configuration.ai_agent_configuration import get_agent_config

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
    if data:
        intent = str(data.get("intent", "INCOMPLETE")).upper()
        reason = data.get("reason", "")
    if intent not in (_ACTION_INTENTS | _NEEDS_CLARIFICATION | frozenset({"IRRELEVANT"})):
        intent = "INCOMPLETE"

    # Deterministic routing (mirrors the old ProsAllyAgent.process_message).
    if intent == "IRRELEVANT":
        nxt = "redirect"
    elif intent in _NEEDS_CLARIFICATION:
        nxt = "clarify"
    else:  # an action intent that has NOT been confirmed yet
        nxt = "confirm"

    update_turn(context_docname, intent=intent, intent_reason=reason, confirmed=False)
    result["intent"] = intent
    result["reason"] = reason
    result["next"] = nxt
'''

CLARIFY = r'''# ProsAlly – Tool Clarify (self-contained, FLAT top-level code).
# Runs under the AI Agent shape-tool exec (split globals/locals) — no def/lambda.
# Ask one focused clarifying question (use when intent is AMBIGUOUS or INCOMPLETE).
import json
import re
from one_bpmn.agents.turn_state import get_turn, run_sync, update_turn
from one_bpmn.agents.llm_provider import get_llm_adapter_from_settings
from one_bpmn.one_bpmn.doctype.ai_agent_configuration.ai_agent_configuration import get_agent_config

turn = get_turn(context_docname)
_cfg = get_agent_config("prosally_agent") or {}
_cfg.setdefault("agent_id", "prosally_agent")
_subs = _cfg.get("sub_prompts") or {}
_adapter = get_llm_adapter_from_settings(_cfg)

process_name = turn.get("process_name", "")
message = turn.get("user_text", "")
intent_reason = turn.get("intent_reason", "")
chat_history = turn.get("chat_history", []) or []

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

# ── build clarifier prompt (inline) ──
_parts = []
if process_name:
    _parts.append("Process: " + process_name)
_parts.append("Classification reason: " + (intent_reason or ""))
if _hist:
    _parts.append("Conversation so far:\n" + _hist)
_parts.append("User message: " + message)
prompt = "\n\n".join(_parts)

_system = (_subs.get("clarifier") or {}).get("prompt") or ""
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

question = "Could you tell me more about the process you'd like to model?"
options = []
if data:
    question = data.get("question") or question
    options = data.get("options") or []

output = {"intent": "CLARIFY", "action_intent": None, "response": question, "options": options}
update_turn(context_docname, output=output, done=True)
result["response"] = question
result["options"] = options
'''

CONFIRM = r'''# ProsAlly – Tool Confirm (self-contained, FLAT top-level code).
# Runs under the AI Agent shape-tool exec (split globals/locals) — no def/lambda.
# Summarise the intended action and ask the user to confirm before drawing.
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

_ACTION_LABELS = {
    "GENERATE_NEW": "GENERATE_NEW — draw a brand-new process from scratch on an empty canvas",
    "OVERWRITE_EXISTING": "OVERWRITE_EXISTING — completely replace the existing model",
    "MODIFY_EXISTING": "MODIFY_EXISTING — change a specific part of the existing model",
}

turn = get_turn(context_docname)
_cfg = get_agent_config("prosally_agent") or {}
_cfg.setdefault("agent_id", "prosally_agent")
_subs = _cfg.get("sub_prompts") or {}
_adapter = get_llm_adapter_from_settings(_cfg)

intent = turn.get("intent", "")
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

# ── build confirmer prompt (inline) ──
_parts = ["Detected action: " + _ACTION_LABELS.get(intent, intent)]
if process_name:
    _parts.append("Process: " + process_name)
if _hist:
    _parts.append("Conversation so far:\n" + _hist)
_parts.append("User message: " + message)
prompt = "\n\n".join(_parts)

_system = (_subs.get("confirmer") or {}).get("prompt") or ""
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

if data:
    summary = data.get("summary", "")
    question = data.get("question", "Shall I proceed?")
    response_text = (summary + "\n" + question) if summary else question
else:
    response_text = raw or "Shall I proceed with this?"

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
result["response"] = response_text
result["options"] = output["options"]
'''

GENERATE = r'''# ProsAlly – Tool Generate Process (self-contained, FLAT top-level code).
# Runs under the AI Agent shape-tool exec (split globals/locals) — no def/lambda;
# comprehensions reference only their own loop var.
# Generate a brand-new (or overwriting) BPMN model. GENERATE_NEW / OVERWRITE_EXISTING.
import json
import re
from one_bpmn.agents.turn_state import get_turn, run_sync, update_turn
from one_bpmn.agents.llm_provider import get_llm_adapter_from_settings
from one_bpmn.one_bpmn.doctype.ai_agent_configuration.ai_agent_configuration import get_agent_config
from one_bpmn.agents.bpmn_ir_pipeline import compile_ir, extract_process_name, translate_problems, translate_violations
from one_bpmn.security.bpmn_validator import validate_bpmn_xml

_GENERATE_INTENTS = frozenset({"GENERATE_NEW", "OVERWRITE_EXISTING"})
_MAX_FIX_PASSES = 3

turn = get_turn(context_docname)
_cfg = get_agent_config("prosally_agent") or {}
_cfg.setdefault("agent_id", "prosally_agent")
_subs = _cfg.get("sub_prompts") or {}
_adapter = get_llm_adapter_from_settings(_cfg)

action = turn.get("intent", "GENERATE_NEW")
if action not in _GENERATE_INTENTS:
    action = "GENERATE_NEW"
process_name = turn.get("process_name", "")
chat_history = turn.get("chat_history", []) or []

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

# ── build generator prompt (inline) ──
_parts = []
if action == "OVERWRITE_EXISTING":
    _parts.append("Action: OVERWRITE_EXISTING — generate a completely new IR to replace the current process.")
else:
    _parts.append("Action: GENERATE_NEW — generate an IR for a new process on an empty canvas.")
if process_name:
    _parts.append("Process name: " + process_name)
if _hist:
    _parts.append("Conversation and process description:\n" + _hist)
_parts.append("Output the IR JSON now.")
initial_prompt = "\n\n".join(_parts)

_system = (_subs.get("process_generator") or {}).get("prompt") or ""

# ── generate + validate repair loop (inline; role = process_generator) ──
best_xml = ""
problems = []
ir_dict = None
repair_hints = []
for attempt in range(_MAX_FIX_PASSES + 1):
    if attempt == 0:
        prompt = initial_prompt
    else:
        _numbered = "\n".join("  " + str(_ii + 1) + ". " + _hh for _ii, _hh in enumerate(repair_hints))
        _has_inferred = any(_n.get("inferred") for _n in (ir_dict.get("nodes") or []))
        _inferred_note = ""
        if _has_inferred:
            _inferred_note = (
                "\nNOTE: Some nodes are tagged \"inferred\": true — these were automatically "
                "inserted by the compiler to fix implicit splits/joins. Keep them in your output "
                "(or remove them and re-model the structure explicitly). Do NOT add conditions to "
                "inferred parallelGateway nodes. DO add conditions/default to any inferred "
                "exclusiveGateway node that has multiple outgoing flows.\n"
            )
        prompt = (
            "The process IR has " + str(len(repair_hints)) + " problem(s) that must be fixed.\n\n"
            "PROBLEMS:\n" + _numbered + "\n" + _inferred_note + "\n"
            "Fix every problem listed above, then output the complete corrected IR JSON.\n\n"
            "Current IR:\n" + json.dumps(ir_dict, indent=2)
        )

    raw = run_sync(_adapter.complete(system=_system, user=prompt)).text

    # ── parse IR JSON (inline) ──
    ir_dict = None
    if raw:
        _cands = [raw.strip()]
        _fenced = re.search(r"```(?:json)?\s*\n?([\s\S]*?)```", raw)
        if _fenced:
            _cands.append(_fenced.group(1).strip())
        _bm = re.search(r"\{[\s\S]*\}", raw)
        if _bm:
            _cands.append(_bm.group(0))
        for _c in _cands:
            try:
                _p = json.loads(_c)
                if isinstance(_p, dict):
                    ir_dict = _p
                    break
            except (json.JSONDecodeError, TypeError, ValueError):
                continue
    if ir_dict is None:
        repair_hints = ["Your last response was not valid JSON. Output ONLY a JSON object matching the IR schema."]
        problems = ["IR JSON parse failure"]
        frappe.log_error(title="ProsAlly IR parse (generate) — attempt " + str(attempt + 1), message=(raw or "")[:1000])
        if attempt == _MAX_FIX_PASSES:
            break
        continue

    # ── lane enforcement (generator only) ──
    _lanes = ir_dict.get("lanes") or []
    if len(_lanes) < 2:
        repair_hints = [
            "MISSING SWIMLANES — your IR has no lane structure. This is required. "
            "EVERY business process must be drawn inside a pool divided into lanes, "
            "one lane per actor role.\n"
            "Step 1: identify EVERY distinct actor in the process description "
            "(human roles such as Employee, Manager, HR, Finance; "
            "plus 'System (Automatic)' for every automated step).\n"
            "Step 2: add a 'lanes' array with one entry per actor:\n"
            "  \"lanes\": [{\"id\": \"employee\", \"name\": \"Employee\"}, "
            "{\"id\": \"manager\", \"name\": \"Manager\"}, "
            "{\"id\": \"system\", \"name\": \"System (Automatic)\"}]\n"
            "Step 3: add a \"lane\" field to EVERY node pointing to its actor's lane id.\n"
            "Output the complete corrected IR JSON now."
        ]
        problems = ["IR missing required swimlane lanes array (< 2 lanes)"]
        if attempt == _MAX_FIX_PASSES:
            break
        continue

    # ── compile IR -> XML ──
    _res = compile_ir(ir_dict)
    xml = _res.get("xml") or ""
    _pipe_probs = _res.get("problems") or []
    _norm = _res.get("normalizedIR")
    if _norm:
        ir_dict = _norm
    if xml:
        best_xml = xml

    if not _res.get("ok"):
        repair_hints = translate_problems(_pipe_probs)
        problems = []
        for _pp in _pipe_probs:
            problems.append(_pp.get("message") or str(_pp))
        frappe.log_error(title="ProsAlly pipeline fail (generate) — attempt " + str(attempt + 1), message=str(_pipe_probs)[:1000])
        if attempt == _MAX_FIX_PASSES:
            break
        continue

    # ── semantic validation ──
    _val = validate_bpmn_xml(xml)
    if _val.get("valid"):
        problems = []
        break
    _violations = _val.get("violations") or []
    repair_hints = translate_violations(_violations)
    problems = _violations
    if attempt == _MAX_FIX_PASSES:
        break

note = (" (" + str(len(problems)) + " issue(s) remain — review the canvas.)") if problems else ""
xml_name = extract_process_name(best_xml) or process_name or "process"
output = {
    "intent": "BPMN_GENERATED",
    "action_intent": action,
    "bpmn_xml": best_xml,
    "response": "I've generated the " + xml_name + " process model." + note + " Review it on the canvas.",
    "options": [],
}
update_turn(context_docname, output=output, done=True)
result["generated"] = True
result["process_name"] = xml_name
result["issues"] = len(problems)
'''

MODIFY = r'''# ProsAlly – Tool Modify Process (self-contained, FLAT top-level code).
# Runs under the AI Agent shape-tool exec (split globals/locals) — no def/lambda;
# comprehensions reference only their own loop var.
# Modify the existing BPMN model. Use only for MODIFY_EXISTING that the user confirmed.
import json
import re
from one_bpmn.agents.turn_state import get_turn, run_sync, update_turn
from one_bpmn.agents.llm_provider import get_llm_adapter_from_settings
from one_bpmn.one_bpmn.doctype.ai_agent_configuration.ai_agent_configuration import get_agent_config
from one_bpmn.agents.bpmn_ir_pipeline import compile_ir, extract_process_name, extract_element_ids, translate_problems, translate_violations
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
from one_bpmn.security.bpmn_validator import validate_bpmn_xml

_MAX_FIX_PASSES = 3

turn = get_turn(context_docname)
_cfg = get_agent_config("prosally_agent") or {}
_cfg.setdefault("agent_id", "prosally_agent")
_subs = _cfg.get("sub_prompts") or {}
_adapter = get_llm_adapter_from_settings(_cfg)

process_name = turn.get("process_name", "")
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

# ── build modifier prompt (inline) ──
_parts = ["Action: MODIFY_EXISTING — update the existing process as described, output the complete IR JSON for the result."]
if process_name:
    _parts.append("Process name: " + process_name)
if _hist:
    _parts.append("Modification request from conversation:\n" + _hist)
if current_xml.strip():
    _has_lanes = ("laneSet" in current_xml) or ("bpmn:laneSet" in current_xml)
    _parts.append("LANE STATUS: " + ("HAS_LANES" if _has_lanes else "NO_LANES"))
    if not _has_lanes:
        _parts.append(
            "IMPORTANT: This diagram has NO lanes/pools. "
            "Do NOT add lanes to the output IR. Omit the \"lanes\" key entirely. "
            "Do NOT add \"lane\" fields to any nodes. "
            "Preserve the flat process structure."
        )
    _id_table = extract_element_ids(current_xml)
    if _id_table:
        _parts.append(
            "ELEMENT ID TABLE — you MUST use these EXACT IDs for existing elements:\n"
            + _id_table
            + "\nDo NOT rename any of these IDs. Only NEW elements get new IDs."
        )
    _parts.append("Current BPMN XML to analyse and modify:\n" + current_xml.strip())
_parts.append("Output the complete IR JSON for the modified process now.")
initial_prompt = "\n\n".join(_parts)

_system = (_subs.get("modifier") or {}).get("prompt") or ""

# ── generate + validate repair loop (inline; role = modifier, NO lane enforcement) ──
best_xml = ""
problems = []
ir_dict = None
repair_hints = []
for attempt in range(_MAX_FIX_PASSES + 1):
    if attempt == 0:
        prompt = initial_prompt
    else:
        _numbered = "\n".join("  " + str(_ii + 1) + ". " + _hh for _ii, _hh in enumerate(repair_hints))
        _has_inferred = any(_n.get("inferred") for _n in (ir_dict.get("nodes") or []))
        _inferred_note = ""
        if _has_inferred:
            _inferred_note = (
                "\nNOTE: Some nodes are tagged \"inferred\": true — these were automatically "
                "inserted by the compiler to fix implicit splits/joins. Keep them in your output "
                "(or remove them and re-model the structure explicitly). Do NOT add conditions to "
                "inferred parallelGateway nodes. DO add conditions/default to any inferred "
                "exclusiveGateway node that has multiple outgoing flows.\n"
            )
        prompt = (
            "The process IR has " + str(len(repair_hints)) + " problem(s) that must be fixed.\n\n"
            "PROBLEMS:\n" + _numbered + "\n" + _inferred_note + "\n"
            "Fix every problem listed above, then output the complete corrected IR JSON.\n\n"
            "Current IR:\n" + json.dumps(ir_dict, indent=2)
        )

    raw = run_sync(_adapter.complete(system=_system, user=prompt)).text

    # ── parse IR JSON (inline) ──
    ir_dict = None
    if raw:
        _cands = [raw.strip()]
        _fenced = re.search(r"```(?:json)?\s*\n?([\s\S]*?)```", raw)
        if _fenced:
            _cands.append(_fenced.group(1).strip())
        _bm = re.search(r"\{[\s\S]*\}", raw)
        if _bm:
            _cands.append(_bm.group(0))
        for _c in _cands:
            try:
                _p = json.loads(_c)
                if isinstance(_p, dict):
                    ir_dict = _p
                    break
            except (json.JSONDecodeError, TypeError, ValueError):
                continue
    if ir_dict is None:
        repair_hints = ["Your last response was not valid JSON. Output ONLY a JSON object matching the IR schema."]
        problems = ["IR JSON parse failure"]
        frappe.log_error(title="ProsAlly IR parse (modify) — attempt " + str(attempt + 1), message=(raw or "")[:1000])
        if attempt == _MAX_FIX_PASSES:
            break
        continue

    # ── compile IR -> XML ──
    _res = compile_ir(ir_dict)
    xml = _res.get("xml") or ""
    _pipe_probs = _res.get("problems") or []
    _norm = _res.get("normalizedIR")
    if _norm:
        ir_dict = _norm
    if xml:
        best_xml = xml

    if not _res.get("ok"):
        repair_hints = translate_problems(_pipe_probs)
        problems = []
        for _pp in _pipe_probs:
            problems.append(_pp.get("message") or str(_pp))
        frappe.log_error(title="ProsAlly pipeline fail (modify) — attempt " + str(attempt + 1), message=str(_pipe_probs)[:1000])
        if attempt == _MAX_FIX_PASSES:
            break
        continue

    # ── semantic validation ──
    _val = validate_bpmn_xml(xml)
    if _val.get("valid"):
        problems = []
        break
    _violations = _val.get("violations") or []
    repair_hints = translate_violations(_violations)
    problems = _violations
    if attempt == _MAX_FIX_PASSES:
        break

note = (" (" + str(len(problems)) + " issue(s) remain — review the canvas.)") if problems else ""

# ── preserve configured properties from the old diagram onto the new one ──
merged_xml, removed_elements = _prosally_preserver("transfer", current_xml, best_xml)

if removed_elements:
    output = {
        "intent": "CONFIRM_REMOVAL",
        "action_intent": "MODIFY_EXISTING",
        "response": _prosally_preserver("format_removal", "", removed_elements),
        "options": ["Yes, apply changes", "No, keep existing"],
        "pending_xml": merged_xml,
    }
    update_turn(context_docname, output=output, done=True)
    result["modified"] = False
    result["needs_removal_confirm"] = True
else:
    xml_name = extract_process_name(merged_xml) or process_name or "process"
    output = {
        "intent": "BPMN_MODIFIED",
        "action_intent": "MODIFY_EXISTING",
        "bpmn_xml": merged_xml,
        "response": (
            "I've updated the " + xml_name + " process." + note + " All existing configurations "
            "have been preserved. Review the changes on the canvas."
        ),
        "options": [],
    }
    update_turn(context_docname, output=output, done=True)
    result["modified"] = True
    result["process_name"] = xml_name
    result["issues"] = len(problems)
'''

REDIRECT = r'''# ProsAlly – Tool Redirect (self-contained, FLAT top-level code).
# Runs under the AI Agent shape-tool exec (split globals/locals) — no def/lambda.
# Politely decline an off-topic request (use only when intent is IRRELEVANT).
from one_bpmn.agents.turn_state import get_turn, update_turn
from one_bpmn.one_bpmn.doctype.ai_agent_configuration.ai_agent_configuration import get_agent_config

turn = get_turn(context_docname)
_cfg = get_agent_config("prosally_agent") or {}
_subs = _cfg.get("sub_prompts") or {}
msg = (_subs.get("redirect") or {}).get(
    "prompt",
    "I'm here to help with process modelling. I'm not able to help with that request.",
)
output = {"intent": "IRRELEVANT", "action_intent": None, "response": msg, "options": []}
update_turn(context_docname, output=output, done=True)
result["response"] = msg
'''

FINALIZE = r'''# ProsAlly – Tool Finalize (self-contained, FLAT top-level code).
# Runs under the AI Agent shape-tool exec (split globals/locals) — no def/lambda.
# Close the turn. Always called last. Emits a safe fallback if no stage produced a reply.
from one_bpmn.agents.turn_state import get_turn, update_turn

turn = get_turn(context_docname)
if turn.get("done"):
    result["finalized"] = True
else:
    output = {
        "intent": "CLARIFY",
        "action_intent": None,
        "response": "Could you tell me more about the process you'd like to model?",
        "options": [],
    }
    update_turn(context_docname, output=output, done=True)
    result["finalized"] = True
    result["fallback"] = True
'''

SCRIPTS = {
    "ProsAlly – Tool Classify Intent": CLASSIFY,
    "ProsAlly – Tool Clarify": CLARIFY,
    "ProsAlly – Tool Confirm": CONFIRM,
    "ProsAlly – Tool Generate Process": GENERATE,
    "ProsAlly – Tool Modify Process": MODIFY,
    "ProsAlly – Tool Redirect": REDIRECT,
    "ProsAlly – Tool Finalize": FINALIZE,
}


def execute():
    original_user = frappe.session.user
    try:
        frappe.set_user("Administrator")
        for name, body in SCRIPTS.items():
            if not frappe.db.exists("Server Script", name):
                continue
            doc = frappe.get_doc("Server Script", name)
            if (doc.script or "").strip() == body.strip():
                continue
            doc.script = body
            doc.save(ignore_permissions=True)
        frappe.db.commit()
    finally:
        frappe.set_user(original_user)
