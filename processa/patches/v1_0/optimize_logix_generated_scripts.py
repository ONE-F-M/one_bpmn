# Copyright (c) 2026, one-fm and contributors
# For license information, please see license.txt
"""
Teach Logix to emit optimized Server Scripts with no dead code.

Two idempotent, behaviour-preserving changes:

1. **Runtime** — inject the deterministic optimizer into the live
   ``Logix - Tool Review Script`` Server Script. Right after a drafted script
   passes the security gate, ``logix_tools.optimize_script`` strips unused
   imports and unused side-effect-free variable assignments, the result is
   re-validated (so the optimizer can never bypass the gate), and both the
   stored ``modified_code`` and the reply text are updated to match. The
   equivalent wiring already lives in ``script_task_agent.py`` /
   ``stage_tools.py``; this patch brings the inlined DB row in line.

2. **Prompts** — append optimization guidance to the ``script_writer`` and
   ``script_reviewer`` sub-prompts on the Logix AI Agent Configuration so the
   model also removes dead code semantically (the deterministic pass is
   conservative and keeps, e.g., unused results of side-effecting calls).

Runs AFTER ``fix_logix_script_task_injected_vars``. Every edit is guarded so
re-running the patch — or running it against a manually edited row — is a no-op
once the change is present.
"""
import frappe

AGENT_ID = "logix_agent"
REVIEW_SCRIPT_NAME = "Logix – Tool Review Script"  # en-dash, matches the DB row

# The exact valid-branch block currently inlined in the Review Script DB row.
_REVIEW_OLD = '''    code = agent._extract_code(candidate)
    validation = logix_tools.validate_script(code)
    if validation["valid"]:
        update_turn(
            context_docname, final=candidate, modified_code=code, script_safe=True, violations=[]
        )
        result["approved"] = True
        result["valid"] = True'''

_REVIEW_NEW = '''    code = agent._extract_code(candidate)
    validation = logix_tools.validate_script(code)
    if validation["valid"]:
        # Strip dead code (unused imports + unused pure assignments), then
        # re-validate so the optimizer can never bypass the security gate. Keep
        # the reply text in sync with the code that will actually be applied.
        optimized = logix_tools.optimize_script(code)
        if optimized != code and logix_tools.validate_script(optimized)["valid"]:
            candidate = logix_tools.replace_code_block(candidate, optimized)
            code = optimized
        update_turn(
            context_docname, final=candidate, modified_code=code, script_safe=True, violations=[]
        )
        result["approved"] = True
        result["valid"] = True'''

# ── Prompt reinforcement (marker-guarded, appended/inserted once) ─────────────
_WRITER_MARKER = "**Optimization — keep the script lean"
_WRITER_BLOCK = """

**Optimization — keep the script lean (the system also strips dead code automatically, but write it clean to begin with):**
- Do NOT declare a variable you never read, and do NOT import a module or name you never use.
- Compute each value once; drop intermediate variables that only pass a value straight through.
- Remove any leftover scaffolding, debug assignments, or dead branches before you finish.
- Every line in the script must contribute to the outcome you described."""

_REVIEWER_MARKER = "unused variables, unused imports, or dead code"
_REVIEWER_ANCHOR = "Respond with ONLY a JSON object:"
_REVIEWER_CRITERION = """7. Optimization — flag any unused variables, unused imports, or dead code. If the script assigns a variable that is never read, or imports something it never uses, set approved=false and return a revised_script with them removed. Preserve all behaviour and keep comments that explain real logic.

"""


def _patch_review_script():
    """Inject the optimizer call into the inlined Review Script DB row."""
    if not frappe.db.exists("Server Script", REVIEW_SCRIPT_NAME):
        return
    doc = frappe.get_doc("Server Script", REVIEW_SCRIPT_NAME)
    script = doc.script or ""
    if "optimize_script" in script:
        return  # already patched
    if _REVIEW_OLD not in script:
        # Row diverged from the expected baseline — don't guess; leave it for a
        # manual edit rather than risk a bad string replacement.
        frappe.log_error(
            title="optimize_logix_generated_scripts: Review Script anchor not found",
            message="The inlined 'Logix - Tool Review Script' did not match the "
                    "expected valid-branch block; skipped auto-injection. Add the "
                    "optimize_script() call manually.",
        )
        return
    doc.script = script.replace(_REVIEW_OLD, _REVIEW_NEW, 1)
    doc.save(ignore_permissions=True)


def _patch_prompts():
    """Append optimization guidance to the writer/reviewer sub-prompts."""
    name = frappe.db.get_value("AI Agent Configuration", {"agent_id": AGENT_ID}, "name")
    if not name:
        return
    doc = frappe.get_doc("AI Agent Configuration", name)

    updated = False
    for row in doc.sub_prompts:
        text = row.prompt_text or ""
        if row.sub_agent_id == "script_writer" and _WRITER_MARKER not in text:
            row.prompt_text = text.rstrip() + _WRITER_BLOCK
            updated = True
        elif row.sub_agent_id == "script_reviewer" and _REVIEWER_MARKER not in text:
            if _REVIEWER_ANCHOR in text:
                row.prompt_text = text.replace(
                    _REVIEWER_ANCHOR, _REVIEWER_CRITERION + _REVIEWER_ANCHOR, 1
                )
            else:  # anchor moved — append rather than skip the guidance
                row.prompt_text = text.rstrip() + "\n\n" + _REVIEWER_CRITERION.strip()
            updated = True

    if updated:
        doc.save(ignore_permissions=True)  # on_update clears agent_config:logix_agent cache


def execute():
    _patch_review_script()
    _patch_prompts()
    frappe.db.commit()
