# Copyright (c) 2026, one-fm and contributors
# For license information, please see license.txt
"""
classify_intent: keep the model's prose as a clarification instead of discarding it.

Symptom: Logix answered a plain "hi", or a bare fact like "Use employee ID
HR-EMP-08841", with
    "I was unable to generate a safe script after multiple attempts. Please
     rephrase your request to avoid forbidden operations ..."
— a refusal that names script-safety violations that were never the actual
problem. The turn's own internal record showed the model had already reasoned
correctly ("Let me proceed to get clarification") but that text never reached
the user.

Root cause, confirmed by reading the LIVE "Logix – Tool Classify Intent"
Server Script (not the stale copy inline_logix_tool_scripts.py installs — this
script was already rewritten, untracked, to route through execute_shape/the
real AI Agent Task dispatcher, which is what gives it memory recall; the only
trace of that rewrite is orphaned .pyc files from deleted temp scripts). Its
best-effort JSON extraction has no fallback: when the model answers in plain
prose instead of {"intent": ...} JSON, `data` stays None and the code silently
defaults to CREATE/MODIFY, throwing the prose away. write_script then has
nothing real to act on, and the turn dead-ends at the Finalize stage's
security refusal. "Logix – Tool Clarify" already handles this correctly on
its own parse failure (`question = raw or "Could you clarify your request?"`)
— classify_intent lacked the equivalent.

Fix: when no JSON is found at all but the model returned substantive prose,
treat that as DISAMBIGUATE (routing to clarify, which already knows how to use
prose) instead of guessing CREATE/MODIFY and losing the reply.

This patch also re-captures the current live script as this repo's source of
truth going forward, since the execute_shape rewrite was never committed.

Idempotent: only rewrites the Server Script when its body differs from the
text below.
"""
import frappe

CLASSIFY = r'''# Logix – Tool Classify Intent (self-contained, FLAT top-level code).
# Runs under the AI Agent shape-tool exec (split globals/locals) — so it uses NO
# def/lambda and no comprehension that references a module-level import/const.
# Classify the request as CREATE, MODIFY, or DISAMBIGUATE. Called first.
import json
import re
from one_bpmn.agents.turn_state import get_turn, update_turn
from one_bpmn.agents.shape_tools import execute_shape

turn = get_turn(context_docname)

current_script = turn.get("current_script", "")
shape_kind = (turn.get("process_context") or {}).get("shape_kind") or "script_task"
element_name = turn.get("element_name", "")
message = turn.get("user_text", "")

# ── build intent prompt (inline) ──
_label = "Agent Tool" if shape_kind == "agent_tool" else "Script Task"
_parts = []
if element_name:
    _parts.append(_label + ": " + element_name)
if current_script:
    _parts.append("Linked script: " + current_script + "  ← existing, treat as MODIFY target unless stated otherwise")
else:
    _parts.append("No script linked yet  ← default to CREATE")
_parts.append("User request: " + message)
prompt = "\n".join(_parts)

_llm_task_cfg = {
    "serviceType": "ai_agent",
    "aiAgentConfig": ai_sub_agent_config,
    "aiUserPromptRaw": prompt,
    "aiBackend": "direct_api",
    "aiResponseFormat": "text",
    "aiTimeout": 30,
    "aiMaxRetries": 2,
}
raw = json.loads(
    execute_shape(instance, "classify_intent", _llm_task_cfg, {})
).get("classify_intent_output", "") or ""

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

intent = "CREATE" if not current_script else "MODIFY"
if data and data.get("intent"):
    intent = str(data["intent"]).upper()
elif not data and raw and raw.strip():
    # No JSON was found at all, but the model answered in substantive prose —
    # discarding it defaulted the turn to CREATE/MODIFY with nothing to act
    # on, which write_script then failed with the security refusal ("I was
    # unable to generate a safe script...") even for a plain question or a
    # greeting. Clarify already treats prose as a valid answer on its own
    # parse failure (`question = raw or ...`); route there instead of
    # guessing CREATE so that fallback gets a chance to use it.
    intent = "DISAMBIGUATE"
if intent not in ("CREATE", "MODIFY", "DISAMBIGUATE"):
    intent = "CREATE" if not current_script else "MODIFY"

# Deterministic routing so the orchestrator never skips a stage.
if intent == "DISAMBIGUATE":
    nxt = "clarify"
elif shape_kind == "agent_tool":
    nxt = "write_agent_tool"
else:
    nxt = "write_script"

update_turn(context_docname, intent=intent, shape_kind=shape_kind)
result["intent"] = intent
result["shape_kind"] = shape_kind
result["next"] = nxt
# Exposed so the outer agent can relay them to clarify as arguments —
# it never receives the raw conversation itself.
result["user_request"] = message
result["element_name"] = element_name
result["current_script"] = current_script
'''


def execute():
	name = "Logix – Tool Classify Intent"
	if not frappe.db.exists("Server Script", name):
		return
	doc = frappe.get_doc("Server Script", name)
	if (doc.script or "").strip() == CLASSIFY.strip():
		return
	doc.script = CLASSIFY
	doc.save(ignore_permissions=True)
	frappe.db.commit()
