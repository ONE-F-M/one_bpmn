"""
A real process can outgrow one completion's output ceiling before the model
finishes the IR, and the tool has no move except to fail and tell the person
to ask for less. Real run data on the BA site showed exactly this: a single
generation call ran to its 16384-token ceiling, was cut off mid-JSON, and the
whole ~146 second call was wasted.

Raising the ceiling only postpones the same failure at a larger process size,
and the model (claude-sonnet-5) already supports up to 128000 output tokens,
far more than any one phase of a process needs. So instead: when the first
attempt at a full generation truncates, the tool asks for a small outline (2
to 6 sequential phases) and then generates each phase's own nodes and flows
in its own smaller completion, well under any ceiling. bpmn_ir_pipeline's
merge_chunked_ir concatenates the phases into one IR sharing the outline's
lane set, which then compiles and validates exactly like a normal generation.
The result stays one diagram; ProsAlly draws one process on one canvas, not a
set of linked sub-processes the person has to go find.

A repair-pass retry after a chunked assembly is not itself re-chunked. If
that retry also truncates, the existing single-completion truncation path
already degrades to the same size-limit message, so no case is left uncaught.

Idempotent: only updates the Server Script if it exists and its body differs.
Registered after prosally_deterministic_lane_repair in patches.txt.
"""

import frappe

GENERATE = r'''# ProsAlly – Tool Generate Process (self-contained, FLAT top-level code).
# Runs under the AI Agent shape-tool exec (split globals/locals) — no def/lambda;
# comprehensions reference only their own loop var.
# Generate a brand-new (or overwriting) BPMN model. GENERATE_NEW / OVERWRITE_EXISTING.
import json
import re
from one_bpmn.agents.turn_state import get_turn, run_sync, update_turn
from one_bpmn.agents.llm_provider import get_llm_adapter_from_settings
from one_bpmn.one_bpmn.doctype.ai_agent_configuration.ai_agent_configuration import get_agent_config
from one_bpmn.agents.bpmn_ir_pipeline import compile_ir, extract_process_name, translate_problems, translate_violations, ensure_default_lanes, merge_chunked_ir, chunk_exit_node_id
from one_bpmn.security.bpmn_validator import validate_bpmn_xml
from one_bpmn.agents.llm_provider.base import LLMTruncatedError

_GENERATE_INTENTS = frozenset({"GENERATE_NEW", "OVERWRITE_EXISTING"})
_MAX_FIX_PASSES = 3
_MAX_PHASES = 6

turn = get_turn(context_docname)
_cfg = get_agent_config("prosally_agent") or {}
_cfg.setdefault("agent_id", "prosally_agent")
_subs = _cfg.get("sub_prompts") or {}
_adapter = get_llm_adapter_from_settings(_cfg)

# A configured max_tokens under 16384 cuts a large IR off mid-JSON, so the
# floor is 16384 and the ceiling is whatever the model itself allows.
_max_tokens = int(_cfg.get("max_tokens") or 0)
if _max_tokens < 16384:
    _max_tokens = 16384
_model_ceiling = 0
if _cfg.get("ai_model"):
    _model_ceiling = frappe.db.get_value("AI Model", _cfg.get("ai_model"), "max_output_tokens") or 0
if _model_ceiling:
    _max_tokens = min(_max_tokens, int(_model_ceiling))
_truncated_error = False

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
topology_note = ""
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

    _chunked_ir = None
    try:
        raw = run_sync(_adapter.complete(system=_system, user=prompt, max_tokens=_max_tokens)).text
    except LLMTruncatedError:
        if attempt != 0:
            # A repair pass on an already-assembled large IR truncated too.
            # Not re-chunked in this version, so the size-limit message below
            # is the honest answer rather than a silent partial result.
            _truncated_error = True
            _size_msg = (
                "This process is too large for me to generate in a single pass — the "
                "model's output was cut off before it finished, even at a " + str(_max_tokens) +
                "-token budget. Try describing a smaller piece of the process at a time "
                "(for example, one department or phase), and I can assemble it "
                "incrementally, or ask me to model just the part you need most."
            )
            output = {
                "intent": "CLARIFY",
                "action_intent": None,
                "response": _size_msg,
                "options": [],
            }
            update_turn(context_docname, output=output, done=True)
            result["generated"] = False
            result["response"] = _size_msg
            result["truncated"] = True
            break

        # Too large for one completion: outline it into phases, then generate
        # each phase's own nodes and flows separately, well under any ceiling.
        _outline_prompt = (
            initial_prompt + "\n\n"
            "This process is too large to output in full. Instead, output ONLY an outline: "
            "break it into 2 to " + str(_MAX_PHASES) + " sequential phases that together cover the "
            "whole process. Respond with ONLY this JSON object, no other text:\n"
            '{"lanes": [{"id": "...", "name": "..."}], '
            '"phases": [{"id": "snake_case_id", "name": "Display Name", '
            '"description": "what happens in this phase, specific enough to model in detail"}]}\n'
            "Use the same lane rules as before (the designer's named lanes win; otherwise User + "
            "System (Automatic))."
        )
        try:
            _outline_raw = run_sync(_adapter.complete(system=_system, user=_outline_prompt, max_tokens=4096)).text
        except LLMTruncatedError:
            _outline_raw = ""
        _outline = None
        if _outline_raw:
            _oc = [_outline_raw.strip()]
            _of = re.search(r"```(?:json)?\s*\n?([\s\S]*?)```", _outline_raw)
            if _of:
                _oc.append(_of.group(1).strip())
            _ob = re.search(r"\{[\s\S]*\}", _outline_raw)
            if _ob:
                _oc.append(_ob.group(0))
            for _c in _oc:
                try:
                    _p = json.loads(_c)
                    if isinstance(_p, dict):
                        _outline = _p
                        break
                except (json.JSONDecodeError, TypeError, ValueError):
                    continue

        _phases = ((_outline or {}).get("phases") or [])[:_MAX_PHASES]
        _chunk_lanes = (_outline or {}).get("lanes") or []
        _chunks = []
        _prev_exit = None
        _chunk_ok = bool(_phases)
        for _pi, _phase in enumerate(_phases):
            _phase_parts = [
                "Action: " + action + " (generating ONE PHASE of a larger process, not the whole thing).",
                "Overall process: " + (process_name or "the process") + ".",
                "This phase (" + str(_pi + 1) + " of " + str(len(_phases)) + "): "
                + _phase.get("name", "") + ": " + _phase.get("description", ""),
            ]
            if _prev_exit:
                _phase_parts.append(
                    "The first node's incoming flow must come from node id \"" + _prev_exit + "\" "
                    "(the previous phase's last node). Do not add a startEvent here."
                )
            else:
                _phase_parts.append("This is the FIRST phase, include the process's single startEvent.")
            if _pi == len(_phases) - 1:
                _phase_parts.append("This is the LAST phase, include at least one endEvent.")
            else:
                _phase_parts.append(
                    "This is not the last phase. End with exactly one node the next phase will "
                    "continue from; make it the LAST entry in your \"nodes\" array. Do not add an "
                    "endEvent yet."
                )
            if _chunk_lanes:
                _phase_parts.append("Use these EXACT lanes, unchanged: " + json.dumps(_chunk_lanes))
            _phase_parts.append(
                "Output ONLY this JSON object, no other text, just this phase's own nodes and flows: "
                '{"nodes": [...], "flows": [...]}'
            )
            _phase_prompt = "\n\n".join(_phase_parts)
            try:
                _phase_raw = run_sync(_adapter.complete(system=_system, user=_phase_prompt, max_tokens=8192)).text
            except LLMTruncatedError:
                _chunk_ok = False
                break
            _phase_ir = None
            if _phase_raw:
                _pc = [_phase_raw.strip()]
                _pf = re.search(r"```(?:json)?\s*\n?([\s\S]*?)```", _phase_raw)
                if _pf:
                    _pc.append(_pf.group(1).strip())
                _pb = re.search(r"\{[\s\S]*\}", _phase_raw)
                if _pb:
                    _pc.append(_pb.group(0))
                for _c in _pc:
                    try:
                        _p = json.loads(_c)
                        if isinstance(_p, dict):
                            _phase_ir = _p
                            break
                    except (json.JSONDecodeError, TypeError, ValueError):
                        continue
            if not _phase_ir or not _phase_ir.get("nodes"):
                _chunk_ok = False
                break
            _chunks.append(_phase_ir)
            _prev_exit = chunk_exit_node_id(_phase_ir)

        if not _chunk_ok or not _chunks:
            _truncated_error = True
            _size_msg = (
                "This process is too large for me to generate, even split into smaller phases. Try "
                "describing a smaller piece of the process at a time (for example, one department or "
                "phase), and I can assemble it incrementally, or ask me to model just the part you "
                "need most."
            )
            output = {
                "intent": "CLARIFY",
                "action_intent": None,
                "response": _size_msg,
                "options": [],
            }
            update_turn(context_docname, output=output, done=True)
            result["generated"] = False
            result["response"] = _size_msg
            result["truncated"] = True
            break

        _chunked_ir = merge_chunked_ir(_chunk_lanes, _chunks)
    else:
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

    if _chunked_ir is not None:
        ir_dict = _chunked_ir

    # ── lane enforcement (generator only) ──
    # Try the deterministic "User" + "System (Automatic)" fallback before
    # spending a whole repair-pass round-trip on something the prompt already
    # told the model how to do. Only re-prompt when there is nothing to
    # assign lanes to (a deeper generation problem, not a lane problem).
    if not ensure_default_lanes(ir_dict):
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
    # The compiler now says whether the graph can be drawn flat at all, and how
    # the drawing measured up. Neither is a reason to retry: a non-planar graph
    # is a fact for the user, and avoidable crossings are our compiler's fault.
    _topo = _res.get("topology") or {}
    _layout = _res.get("layout") or {}
    if _topo.get("planar") is False:
        _names = {}
        for _n in (ir_dict.get("nodes") or []):
            _names[_n.get("id")] = _n.get("name") or _n.get("id")
        _who = ", ".join([_names.get(_x, _x) for _x in (_topo.get("obstruction") or [])[:5]])
        topology_note = " One crossing line is unavoidable: the paths through " + _who + " cannot all be laid flat."
    if _res.get("ok") and _layout.get("crossings", 0) > _topo.get("min_crossings", 0):
        frappe.log_error(title="ProsAlly layout: avoidable crossings", message=json.dumps(_layout)[:2000])
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

if not _truncated_error:
    note = ((" (" + str(len(problems)) + " issue(s) remain — review the canvas.)") if problems else "") + topology_note
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

SCRIPTS = {
    "ProsAlly – Tool Generate Process": GENERATE,
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
