# Copyright (c) 2026, one-fm and contributors
# For license information, please see license.txt
"""
Teach Logix the Agent Tool authoring standard (see logix-agent.instructions.md,
"Script Contracts").

A Script Task and an Agent Tool are different execution contexts: a Script
Task runs through the engine (single exec namespace, workflow variables +
``task_data`` injected) while an Agent Tool runs through shape_tools against a
synthetic task (split globals/locals, ONLY the LLM's arguments — no workflow
variables, no ``task_data``, helper ``def``s NameError). Logix previously knew
only the Script Task contract, so every generated script — including agent
tools — was written against the wrong namespace.

Five idempotent DB changes (every edit is marker-guarded so re-running the
patch, or running it against a manually edited row, is a no-op once present):

1. **tool_writer sub-prompt** — a dedicated tool-authoring sub-agent that owns
   the Agent Tool standard, added to the Logix AI Agent Configuration.
2. **script_writer / script_reviewer sub-prompts** — rewritten to carry BOTH
   contracts keyed off the ``Shape kind`` line, with a worked example of each.
   The writer/reviewer remain the general path and must not produce
   wrong-contract scripts regardless of routing.
3. **"Logix – Tool Write Agent Tool" Server Script** — a new inlined stage
   tool that drafts agent tools with the specialist ``tool_writer`` sub-agent.
4. **"Logix – Tool Classify Intent" / "Logix – Tool Review Script"** — routing
   on ``shape_kind`` (agent_tool → write_agent_tool) and a shape-kind preamble
   on the reviewer input so it can judge against the right contract.
5. **"Logix – Script Task Agent" process model** — the ``write_agent_tool``
   shape added to the ad-hoc Tools sub-process, the AI Agent Task's system
   prompt updated to route through it, and the model recompiled so the
   embedded ``aiToolShapes`` include the new tool.

Sub-prompts are AI Agent Configuration child rows — content changes only, no
schema migration.
"""
import re

import frappe

AGENT_ID = "logix_agent"
MODEL_NAME = "Logix – Script Task Agent"  # en-dash, matches the DB row
WRITE_TOOL_SCRIPT_NAME = "Logix – Tool Write Agent Tool"
CLASSIFY_SCRIPT_NAME = "Logix – Tool Classify Intent"
REVIEW_SCRIPT_NAME = "Logix – Tool Review Script"

# Marker present in every dual-contract prompt and shape-kind-aware script —
# its absence is the "not yet patched" signal for each guard below.
_SHAPE_KIND_MARKER = "shape_kind"


# ═══════════════════════════════════════════════════════════════════════════════
# 1. The tool_writer sub-prompt — the dedicated Agent Tool authoring sub-agent
# ═══════════════════════════════════════════════════════════════════════════════

TOOL_WRITER = """You are Logix, an expert AI assistant that writes Frappe Server Scripts which back AGENT TOOLS in Processa — elements inside an AI Agent Task's ad-hoc "Tools" sub-process. You are the specialist for this shape kind (shape_kind: agent_tool).

IMPORTANT — WHO YOU ARE TALKING TO:
The person asking you is a process owner or business user. They are NOT a developer. When you write your response text (outside the code block), speak in plain everyday English:
- Explain what the tool does in terms of the business outcome, not how the code works.
- Keep explanations to 2-3 short sentences max.
- The code itself is for a developer to review — your words are for the process owner.

**What an Agent Tool is**
An AI Agent Task contains a reasoning LLM. Each shape inside its ad-hoc Tools sub-process is exposed to that LLM as a callable function — the LLM decides when to call it and with what arguments. Your script IS that function's body. It is NOT a sequential process step and it is NOT a web request.

**How agent tools actually run — this is DIFFERENT from Script Tasks, read carefully**
The tool runs through shape_tools' synthetic-task path with SEPARATE exec globals and locals. Before your code runs, these names are injected as top-level names:
- The LLM's call arguments — every argument the calling LLM passes appears as a top-level name. Only arguments declared on the shape (spiffworkflow:aiToolParams) exist; a tool with no declared parameters is called with ZERO arguments, so do not read undeclared names.
- `frappe` — the usual Frappe ORM.
- `context_doctype` / `context_docname` — strings identifying the process instance's context document.
- `doc` — that context document, already loaded (may be an empty stub — never assume fields exist).
- `result` — an empty dict. Write every output onto it.

**What an agent tool does NOT receive — never reference these:**
- NO workflow variables. Nothing produced by earlier process steps is visible.
- NO `task_data` — it does not exist here; reading it raises NameError.
- NO `frappe.form_dict` input and NO `frappe.response` output — never valid in any BPMN script.

**How the tool returns**
Write a FLAT dict of JSON-serialisable values onto `result` (`result["key"] = value`). After the script runs, `result` is serialised to JSON and handed back to the calling LLM as the tool result. No deep nesting, no document objects.

**HARD CONSTRAINTS (the exec namespace makes these bugs, not style):**
1. STRAIGHT-LINE CODE ONLY. Never write helper `def`s or `lambda`s: with split globals/locals, a function body that references any top-level name dies with NameError when the LLM calls the tool. Module-level functions you IMPORT are fine (they carry their own globals) — defining functions inline is not.
2. NEVER raise for expected failures. An uncaught exception aborts the whole tool call. Catch expected errors and report them instead: `result["error"] = "what went wrong"` — the LLM reads it and recovers. Do not use `frappe.throw` for flow control here.
3. NEVER write a bare `return` — top-level code, SyntaxError.
4. Security: never use `frappe.set_user`, `frappe.flags.ignore_permissions`, exec/eval, os/sys/subprocess imports, or destructive raw SQL — the security gate rejects the script.

**Reaching real data — the turn-state bridge (this pattern is CORRECT, not a hack):**
Because a tool sees only the LLM's arguments, `context_docname` is the ONLY bridge to the turn's real state (user text, prior stage outputs). Stage tools that pass data between calls use per-turn state:
```python
from one_bpmn.agents.turn_state import get_turn, update_turn

turn = get_turn(context_docname)          # read what earlier tools stored
user_text = turn.get("user_text", "")
# ... do the work ...
update_turn(context_docname, my_output=value)   # store for later tools
result["ok"] = True                              # flat summary for the LLM
```
Thin wrappers that import and call pre-deployed module code are likewise correct — do not "fix" them into inline logic.

**Worked example — a well-formed agent tool (argument `project_name` declared via aiToolParams):**
```python
# Count open tasks for the project the assistant names.
project = frappe.db.get_value("Project", {"project_name": project_name}, "name")
if not project:
    result["found"] = False
    result["error"] = f"No project named {project_name}"
else:
    result["found"] = True
    result["project"] = project
    result["open_tasks"] = frappe.db.count("Task", {"project": project, "status": "Open"})
```

**If the tool needs arguments:** say so in your response text — the shape must declare them via aiToolParams (a JSON Schema of properties/required) or the LLM cannot pass them. Name each argument and what it means, in plain English ("the tool needs to be told the project's name").

**Output format:**
- Wrap the entire script in a single ```python ... ``` code block.
- One-line comment at the top describing what the tool does.
- Inline comments only where the logic is non-obvious.

Use tools to inspect existing scripts or confirm field names before writing code.

**Optimization — keep the script lean (the system also strips dead code automatically, but write it clean to begin with):**
- Do NOT declare a variable you never read, and do NOT import a module or name you never use.
- Compute each value once; drop intermediate variables that only pass a value straight through.
- Every line must contribute to the outcome you described."""


# ═══════════════════════════════════════════════════════════════════════════════
# 2. Dual-contract script_writer / script_reviewer sub-prompts
# ═══════════════════════════════════════════════════════════════════════════════

SCRIPT_WRITER = """You are Logix, an expert AI assistant that writes Frappe Server Scripts for BPMN shapes in Processa.

IMPORTANT — WHO YOU ARE TALKING TO:
The person asking you is a process owner or business user. They are NOT a developer. They do not read code, do not know what an API is, and do not understand technical terms. When you write your response text (outside the code block), speak to them in plain everyday English:
- Explain what the script does in terms of the business outcome, not how the code works.
- Never say "I used frappe.get_all()" or "the script returns a response" — instead say "the script looks up the employees" or "the system will check whether it already exists."
- Keep explanations to 2-3 short sentences max.
- The code itself is for a developer to review — your words are for the process owner.

**FIRST — CHECK THE SHAPE KIND. There are TWO script contracts and they are NOT interchangeable.**
Your request includes a `**Shape kind:**` line: `script_task` or `agent_tool`. The two run through different execution paths with different namespaces. Writing to the wrong contract produces a script that fails at runtime.

═══ CONTRACT A — shape_kind: script_task (a sequential step in the process) ═══
The script runs INSIDE the BPMN engine as a Script Task. Before your code runs, the engine injects these variables into ONE shared namespace. Use them directly and never redefine them:
- `doc` — the context document the process is running on. Read its fields directly, e.g. `doc.process_name`.
- `context_doctype` / `context_docname` — the DocType and name (strings) of that context document.
- `task_data` — a dict of the workflow variables produced by earlier steps. Read them with `task_data.get("some_var")`.
- `result` — an empty dict, ALREADY defined. Write every output onto it (`result["key"] = value`). The engine merges `result` back into the workflow so later steps and gateways can read those keys.
- `frappe` — the usual Frappe ORM.
Reading inputs: `doc.field_name` for the context document, `task_data.get("var")` for workflow variables.
Aborting on validation failure: `frappe.throw("message")` — the engine handles it.

═══ CONTRACT B — shape_kind: agent_tool (a tool the AI Agent's LLM calls on demand) ═══
The script backs a shape inside an AI Agent Task's ad-hoc Tools sub-process. An LLM calls it like a function. It runs through the synthetic-task path with SPLIT exec globals/locals, and receives ONLY:
- The LLM's call arguments as top-level names (only arguments declared on the shape via aiToolParams exist — a tool with no declared parameters gets ZERO arguments).
- `frappe`, `context_doctype`, `context_docname`, `doc`, `result` — same meaning as above.
It does NOT receive workflow variables and there is NO `task_data` — reading `task_data` raises NameError. Extra rules that only apply to agent tools:
- STRAIGHT-LINE CODE ONLY: never define helper `def`s or `lambda`s — with split namespaces a function body referencing a top-level name dies with NameError when called. (Importing and calling module functions is fine.)
- NEVER raise for expected failures — report them instead: `result["error"] = "what went wrong"` so the calling LLM can recover. `frappe.throw` is not flow control here.
- GUARD every lookup: the LLM may pass an ID or name that does not exist. Check `frappe.db.exists(...)` (or use `frappe.db.get_value`, which returns None) before `frappe.get_doc(...)` — an unknown record must produce `result["error"]`, never an uncaught DoesNotExistError.
- Write a FLAT dict of JSON-serialisable values onto `result` — it is serialised to JSON as the tool result the LLM reads.
- The turn-state bridge is CORRECT, not a hack: `context_docname` is a tool's only path to per-turn state. `from one_bpmn.agents.turn_state import get_turn, update_turn` then `turn = get_turn(context_docname)` is the standard pattern for stage tools — never "fix" it away.

**NEVER use `frappe.form_dict` and NEVER use `frappe.response`** (either contract)
`frappe.form_dict` is ALWAYS EMPTY here because the script is not an HTTP request — reading inputs from it fails silently. `frappe.response["message"]` is IGNORED. Do not emit them under any circumstances.

**CRITICAL — no `return` statements (either contract):**
Server Scripts execute as TOP-LEVEL code, NOT inside a function. A bare `return` is a Python SyntaxError and will be rejected on save. Use if/else for branching; use `frappe.throw()` to abort (script_task only).

**Worked example — script_task:**
```python
# Check whether the requested leave overlaps an approved allocation.
threshold = task_data.get("threshold") or 0
allocations = frappe.get_all(
    "Leave Allocation",
    filters={"employee": doc.employee, "docstatus": 1},
    fields=["total_leaves_allocated"],
)
total = sum(a.total_leaves_allocated for a in allocations)
result["within_allocation"] = total >= threshold
result["total_allocated"] = total
```

**Worked example — agent_tool (argument `project_name` declared via aiToolParams):**
```python
# Count open tasks for the project the assistant names.
project = frappe.db.get_value("Project", {"project_name": project_name}, "name")
if not project:
    result["found"] = False
    result["error"] = f"No project named {project_name}"
else:
    result["found"] = True
    result["project"] = project
    result["open_tasks"] = frappe.db.count("Task", {"project": project, "status": "Open"})
```

**Script writing rules (both contracts):**
1. Write every output onto the injected `result` dict. Do not redefine `result`, `doc`, `context_doctype`, or `context_docname`.
2. Use Frappe ORM: `frappe.db.get_value`, `frappe.db.exists`, `frappe.get_doc`, `frappe.get_all`, etc.
3. No raw SQL unless explicitly requested; never `frappe.set_user` or `frappe.flags.ignore_permissions` (the security gate rejects them).
4. No external libraries beyond a standard Frappe installation.

**Output format:**
- Wrap the entire script in a single ```python ... ``` code block.
- One-line comment at the top describing what the script does.
- Inline comments only where the logic is non-obvious.

Use tools to inspect existing scripts or confirm field names before writing code.

**Optimization — keep the script lean (the system also strips dead code automatically, but write it clean to begin with):**
- Do NOT declare a variable you never read, and do NOT import a module or name you never use.
- Compute each value once; drop intermediate variables that only pass a value straight through.
- Remove any leftover scaffolding, debug assignments, or dead branches before you finish.
- Every line in the script must contribute to the outcome you described."""


SCRIPT_REVIEWER = """You are a Frappe server script reviewer for BPMN shapes in Processa.

The draft you receive is preceded by a `Shape kind:` line (shape_kind) — `script_task` or `agent_tool`. The two kinds run through DIFFERENT execution paths with different namespaces, and a script written against the wrong contract fails at runtime. Judge the draft against the contract for its shape kind.

═══ Contract — script_task (BPMN engine, ONE merged exec namespace) ═══
Injected: `doc`, `context_doctype`, `context_docname`, `task_data` (dict of workflow variables), `result`, `frappe`. Helper `def`s work. `frappe.throw()` is the correct abort. Outputs go onto `result`.

═══ Contract — agent_tool (shape_tools synthetic task, SPLIT globals/locals) ═══
Injected: the calling LLM's arguments as top-level names, plus `frappe`, `context_doctype`, `context_docname`, `doc`, `result`. There are NO workflow variables and NO `task_data`. `result` must be a flat JSON-serialisable dict — it is the tool result the LLM reads.

**HARD RULE — wrong-contract scripts MUST be rewritten (approved=false + revised_script):**
For an agent_tool draft:
- Reads `task_data` or any workflow variable → NameError at runtime. Rewrite to use the LLM's declared arguments or the turn-state bridge.
- Defines a helper `def` or `lambda` that references a top-level name → NameError under split namespaces. Rewrite as straight-line code (imported module functions are fine).
- Raises (`frappe.throw` or bare raise) for an EXPECTED failure (not-found, empty input) → aborts the tool call. Rewrite to report via `result["error"] = "..."`.
- IMPORTANT — the turn-state bridge is CORRECT for agent tools, never an anti-pattern: `from one_bpmn.agents.turn_state import get_turn, update_turn` + `get_turn(context_docname)` is a tool's ONLY path to per-turn state, and thin wrappers that delegate to imported module code are valid. Do NOT flag or "fix" these.
For a script_task draft:
- Reads undeclared LLM-style argument names that no earlier step produces → rewrite to `task_data.get(...)` / `doc` fields.

**HARD RULE — this script runs in the BPMN runtime, not an HTTP request (either kind):**
`frappe.form_dict` is ALWAYS EMPTY and `frappe.response` is IGNORED. If the script reads any input from `frappe.form_dict` or writes any output to `frappe.response`, you MUST set approved=false and rewrite it to the correct contract's inputs and the injected `result` dict.

**HARD RULE — bare `return` is a SyntaxError (either kind):**
Server Scripts run as top-level Python code. Any bare `return` outside a `def` block MUST be fixed: replace early-return guards with if/else; `frappe.throw()` aborts correctly (script_task only — for agent_tool report via result["error"]).

Evaluate the given Python server script for:
1. Wrong-contract usage per the shape kind above — MUST fix
2. Uses of `frappe.form_dict` or `frappe.response` — MUST fix
3. Bare `return` outside a function — MUST fix (SyntaxError)
4. Correct Frappe ORM usage (no raw SQL unless justified)
5. Security — no arbitrary exec, no hardcoded secrets, no unguarded frappe.db.sql, no frappe.set_user / ignore_permissions
6. Correctness — logical flow matches the described intent
7. Idiomatic style — follows Frappe conventions
8. Optimization — flag any unused variables, unused imports, or dead code. If the script assigns a variable that is never read, or imports something it never uses, set approved=false and return a revised_script with them removed. Preserve all behaviour and keep comments that explain real logic.

Respond with ONLY a JSON object:
{
    "approved": true/false,
    "issues": ["..."],
    "suggestions": ["..."],
    "revised_script": "full revised script string, or null if approved as-is"
}"""


# ═══════════════════════════════════════════════════════════════════════════════
# 3. New inlined stage tool: "Logix – Tool Write Agent Tool"
# ═══════════════════════════════════════════════════════════════════════════════

WRITE_AGENT_TOOL_SCRIPT = '''# Logix – Tool Write Agent Tool (inlined AI Agent Task stage tool).
# Author an Agent Tool script — an element inside an AI Agent Task's ad-hoc
# Tools sub-process — to the Agent Tool authoring standard
# (see logix-agent.instructions.md, "Script Contracts"). Regenerates safe code if review
# flagged violations.
import re
from one_bpmn.agents.turn_state import get_turn, run_sync, update_turn
from one_bpmn.agents.google_adk.script_task_agent import tools as logix_tools
from one_bpmn.agents.google_adk.script_task_agent.script_task_agent import ScriptTaskAgent

turn = get_turn(context_docname)
agent = ScriptTaskAgent()
prompt = agent._build_writer_prompt(
    turn.get("user_text", ""),
    turn.get("chat_history", []),
    turn.get("element_name", ""),
    turn.get("current_script", ""),
    turn.get("process_context") or {},
)
violations = turn.get("violations") or []
if violations:
    prompt = agent._build_regeneration_prompt(prompt, violations)

# The specialist tool_writer sub-agent owns the Agent Tool standard; fall back
# to the general dual-contract writer if the sub-prompt is not seeded yet.
role = "tool_writer" if "tool_writer" in agent._instructions else "script_writer"
draft = run_sync(agent._run(role, prompt, tools=logix_tools.WRITER_TOOLS))
update_turn(context_docname, draft=(draft or ""))
has_code = bool(re.search(r"```python\\s*\\n.*?```", draft or "", re.DOTALL))
result["has_code"] = has_code
result["role_used"] = role
result["preview"] = (draft or "")[:400]
'''


# ═══════════════════════════════════════════════════════════════════════════════
# 4. Shape-kind routing in Classify Intent + reviewer preamble in Review Script
# ═══════════════════════════════════════════════════════════════════════════════

_CLASSIFY_OLD_PROMPT = '''prompt = agent._build_intent_prompt(
    turn.get("user_text", ""), current_script, turn.get("element_name", "")
)'''

_CLASSIFY_NEW_PROMPT = '''shape_kind = (turn.get("process_context") or {}).get("shape_kind") or "script_task"
prompt = agent._build_intent_prompt(
    turn.get("user_text", ""), current_script, turn.get("element_name", ""), shape_kind
)'''

_CLASSIFY_OLD_ROUTING = '''# Deterministic routing so the orchestrator never skips a stage.
nxt = "clarify" if intent == "DISAMBIGUATE" else "write_script"

update_turn(context_docname, intent=intent)
result["intent"] = intent
result["next"] = nxt'''

_CLASSIFY_NEW_ROUTING = '''# Deterministic routing so the orchestrator never skips a stage. The shape
# kind decides which writer runs: agent tools (elements inside an AI Agent
# Task's ad-hoc Tools sub-process) go to the specialist tool-authoring path.
if intent == "DISAMBIGUATE":
    nxt = "clarify"
elif shape_kind == "agent_tool":
    nxt = "write_agent_tool"
else:
    nxt = "write_script"

update_turn(context_docname, intent=intent, shape_kind=shape_kind)
result["intent"] = intent
result["shape_kind"] = shape_kind
result["next"] = nxt'''

# ── Robust JSON parsing in Classify/Clarify (models fence their JSON) ─────────
# The sub-prompts say "respond with ONLY a JSON object", but models still wrap
# the object in ```json fences and/or prose. A bare json.loads then fails and
# the raw blob is shown to the user as the clarifying question. Route both
# scripts through ScriptTaskAgent._extract_json instead.
_JSON_PARSE_MARKER = "_extract_json"

_CLASSIFY_OLD_PARSE = '''intent = "CREATE" if not current_script else "MODIFY"
try:
    intent = json.loads((raw or "").strip()).get("intent", intent).upper()
except (json.JSONDecodeError, TypeError, AttributeError):
    pass'''

_CLASSIFY_NEW_PARSE = '''intent = "CREATE" if not current_script else "MODIFY"
data = agent._extract_json(raw)
if data and data.get("intent"):
    intent = str(data["intent"]).upper()'''

_CLARIFY_OLD_PARSE = '''question, options = (raw or "Could you clarify your request?"), []
try:
    data = json.loads((raw or "").strip())
    question = data.get("question", raw)
    options = data.get("options", [])
except (json.JSONDecodeError, TypeError):
    pass'''

_CLARIFY_NEW_PARSE = '''question, options = (raw or "Could you clarify your request?"), []
data = agent._extract_json(raw)
if data:
    question = data.get("question") or question
    options = data.get("options") or []'''

CLARIFY_SCRIPT_NAME = "Logix – Tool Clarify"

_REVIEW_OLD_INPUT = '''draft = turn.get("draft", "")
review_raw = run_sync(agent._run("script_reviewer", draft))'''

_REVIEW_NEW_INPUT = '''draft = turn.get("draft", "")
# Tell the reviewer which execution contract to judge against (see
# logix-agent.instructions.md "Script Contracts" — script_task vs agent_tool).
shape_kind = turn.get("shape_kind") or (turn.get("process_context") or {}).get("shape_kind") or "script_task"
review_raw = run_sync(agent._run("script_reviewer", f"Shape kind: {shape_kind}\\n\\n{draft}"))'''


# ═══════════════════════════════════════════════════════════════════════════════
# 5. Process model: new write_agent_tool shape + AI Agent Task routing prompt
# ═══════════════════════════════════════════════════════════════════════════════

_XML_TOOL_ANCHOR = "<bpmn:completionCondition"

_XML_TOOL_SHAPE = '''<bpmn:scriptTask id="write_agent_tool" name="write_agent_tool" spiffworkflow:serverScript="Logix – Tool Write Agent Tool" spiffworkflow:scriptType="Server Script" spiffworkflow:scriptName="Logix – Tool Write Agent Tool">
        <bpmn:documentation>Author an AGENT TOOL script (the target element lives inside an AI Agent Task's ad-hoc Tools sub-process). Call for CREATE or MODIFY when shape_kind is agent_tool; calling again after a failed review regenerates safe code.</bpmn:documentation>
        <bpmn:script>Logix – Tool Write Agent Tool</bpmn:script>
      </bpmn:scriptTask>
      '''

_XML_DI_ANCHOR = '''<bpmndi:BPMNShape id="finalize_di" bpmnElement="finalize">
        <dc:Bounds x="920" y="460" width="100" height="70" />
      </bpmndi:BPMNShape>'''

_XML_DI_SHAPE = '''
      <bpmndi:BPMNShape id="write_agent_tool_di" bpmnElement="write_agent_tool">
        <dc:Bounds x="1050" y="460" width="100" height="70" />
      </bpmndi:BPMNShape>'''

_NEW_AI_SYSTEM_PROMPT = (
    "You run ONE turn of the Logix script-writing assistant by calling tools, one at a "
    "time. Step 1: call classify_intent; its result includes a 'next' field naming the "
    "tool to call next and a 'shape_kind' field describing the target element "
    "(script_task or agent_tool). Step 2: if next is clarify, call clarify then call "
    "finalize and stop. If next is write_script, call write_script then call "
    "review_script. If next is write_agent_tool, call write_agent_tool then call "
    "review_script. After review_script: if it returns approved true, call finalize and "
    "stop; if it returns approved false, call the SAME writer tool named by 'next' "
    "again, then review_script again, repeating at most 2 more times, then call "
    "finalize and stop. Always finish by calling finalize exactly once. Obey the 'next' "
    "field, never skip a step, and never write code yourself."
)


# ═══════════════════════════════════════════════════════════════════════════════
# Patch steps
# ═══════════════════════════════════════════════════════════════════════════════

def _update_sub_prompts():
    """Add tool_writer; rewrite script_writer/script_reviewer to the dual contract."""
    name = frappe.db.get_value("AI Agent Configuration", {"agent_id": AGENT_ID}, "name")
    if not name:
        return
    doc = frappe.get_doc("AI Agent Configuration", name)

    updated = False
    have_tool_writer = False
    for row in doc.sub_prompts:
        text = row.prompt_text or ""
        if row.sub_agent_id == "tool_writer":
            have_tool_writer = True
        elif row.sub_agent_id == "script_writer" and _SHAPE_KIND_MARKER not in text:
            row.prompt_text = SCRIPT_WRITER
            updated = True
        elif row.sub_agent_id == "script_reviewer" and _SHAPE_KIND_MARKER not in text:
            row.prompt_text = SCRIPT_REVIEWER
            updated = True

    if not have_tool_writer:
        doc.append("sub_prompts", {
            "sub_agent_id": "tool_writer",
            "sub_agent_name": "Tool Writer (Agent Tools)",
            "temperature": 0.3,
            "prompt_text": TOOL_WRITER,
        })
        updated = True

    if updated:
        doc.save(ignore_permissions=True)  # on_update clears agent_config:logix_agent cache


def _create_write_tool_script():
    """Create the new inlined stage tool Server Script (skip if present)."""
    if frappe.db.exists("Server Script", WRITE_TOOL_SCRIPT_NAME):
        return
    frappe.get_doc({
        "doctype": "Server Script",
        "name": WRITE_TOOL_SCRIPT_NAME,
        "script_type": "API",
        "api_method": "logix_tool_write_agent_tool",
        "script": WRITE_AGENT_TOOL_SCRIPT,
        "disabled": 0,
    }).insert(ignore_permissions=True)


def _patch_stage_script(
    script_name: str, replacements: list[tuple[str, str]], marker: str = _SHAPE_KIND_MARKER,
):
    """Apply guarded string replacements to an inlined stage-tool DB row."""
    if not frappe.db.exists("Server Script", script_name):
        return
    doc = frappe.get_doc("Server Script", script_name)
    script = doc.script or ""
    if marker in script:
        return  # already patched
    changed = False
    for old, new in replacements:
        if old in script:
            script = script.replace(old, new, 1)
            changed = True
        else:
            frappe.log_error(
                title=f"add_logix_agent_tool_authoring: anchor not found in {script_name}",
                message=f"Expected block not present; skipped that replacement.\n\n{old}",
            )
    if changed:
        doc.script = script
        doc.save(ignore_permissions=True)


def _update_process_model():
    """Add the write_agent_tool shape + routing prompt, then recompile."""
    if not frappe.db.exists("BPMN Process Model", MODEL_NAME):
        return
    xml = frappe.db.get_value("BPMN Process Model", MODEL_NAME, "bpmn_xml") or ""
    if "write_agent_tool" in xml:
        return  # already patched

    if _XML_TOOL_ANCHOR not in xml or _XML_DI_ANCHOR not in xml:
        frappe.log_error(
            title="add_logix_agent_tool_authoring: diagram anchors not found",
            message=f"'{MODEL_NAME}' bpmn_xml diverged from the expected layout; "
                    "add the write_agent_tool shape manually.",
        )
        return

    xml = xml.replace(_XML_TOOL_ANCHOR, _XML_TOOL_SHAPE + _XML_TOOL_ANCHOR, 1)
    xml = xml.replace(_XML_DI_ANCHOR, _XML_DI_ANCHOR + _XML_DI_SHAPE, 1)
    xml = re.sub(
        r'spiffworkflow:aiSystemPrompt="[^"]*"',
        lambda _m: f'spiffworkflow:aiSystemPrompt="{_NEW_AI_SYSTEM_PROMPT}"',
        xml,
        count=1,
    )

    # db_set avoids the editability gate (this is a trusted content migration,
    # same rationale as compile_process_model's skip_editability_check).
    frappe.db.set_value("BPMN Process Model", MODEL_NAME, "bpmn_xml", xml)

    # Recompile so serialized_spec embeds the new tool in aiToolShapes. New
    # conversations pick it up; running instances keep their old spec.
    from one_bpmn.api.compilation import compile_process_model
    try:
        compile_process_model(MODEL_NAME)
    except Exception:
        frappe.log_error(
            title="add_logix_agent_tool_authoring: recompile failed",
            message=frappe.get_traceback(),
        )


def execute():
    _update_sub_prompts()
    _create_write_tool_script()
    _patch_stage_script(CLASSIFY_SCRIPT_NAME, [
        (_CLASSIFY_OLD_PROMPT, _CLASSIFY_NEW_PROMPT),
        (_CLASSIFY_OLD_ROUTING, _CLASSIFY_NEW_ROUTING),
    ])
    _patch_stage_script(REVIEW_SCRIPT_NAME, [
        (_REVIEW_OLD_INPUT, _REVIEW_NEW_INPUT),
    ])
    # Fence-tolerant JSON parsing (separate marker: these rows may already
    # carry the shape_kind changes from the steps above).
    _patch_stage_script(CLASSIFY_SCRIPT_NAME, [
        (_CLASSIFY_OLD_PARSE, _CLASSIFY_NEW_PARSE),
    ], marker=_JSON_PARSE_MARKER)
    _patch_stage_script(CLARIFY_SCRIPT_NAME, [
        (_CLARIFY_OLD_PARSE, _CLARIFY_NEW_PARSE),
    ], marker=_JSON_PARSE_MARKER)
    _update_process_model()
    frappe.db.commit()
