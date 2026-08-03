"""
WI-001751 follow-up: stop the assistant answering "add a user prompt" with a
system-prompt change.

Symptom: asked to write the task's User Prompt, the assistant replied "I'm
updating the 'Leave App Rev' agent with the user prompt" and rendered an
"Apply this change to Leave App Rev?" card containing a SYSTEM PROMPT. The
User Prompt field stayed empty. Nothing was miswritten — aiUserPrompt is not in
_UPDATABLE_FIELDS, so it can never reach an agent configuration — but the
designer's actual request was never answered.

Cause: the assistant's own system prompt told it to do this. Its UPDATING
EXISTING AGENTS section offered to change "(provider, prompt, sampling params)"
on the linked configuration and to "treat it as the target unless told
otherwise". "Prompt" was undifferentiated, so a request about the User Prompt
matched the update path.

The rule that separates the two — the User Prompt is a property of the TASK
SHAPE and is answered with recommendations, never proposed_update — existed only
in api/ai_assistant._creation_capability_block, injected as per-turn dialog
context. The words "user prompt" appeared nowhere in the system prompt itself.
Between a persona-level instruction and a rule buried in a long context block,
the small model the assistant runs follows the persona.

Fix: say it in the prompt that governs behaviour.

  * the update bullet is narrowed to the SYSTEM prompt, and names the model
    rather than the provider (WI-001655 made the model the pick — the provider
    is derived from it, so "change the provider" has been wrong since);
  * a WHERE EACH PROMPT LIVES section states the split once, plainly, with the
    reply shape for each.

This does not loosen any guard: aiUserPrompt still cannot be written to a
configuration. It only stops the assistant proposing the wrong change.

Prompts are data (WI-001623 — no hardcoded assistant prompts in code), so this
edits the site's own record. Idempotent: the stale sentence is matched exactly
and the new section is keyed on its heading.
"""

import frappe

AGENT_ID = "ai_agent_assistant"

# The exact bullet as shipped by the earlier prompt patches. Matched in full so
# a site whose prompt has since been hand-edited is left alone rather than
# half-rewritten.
_STALE_UPDATE_BULLET = (
	"  - You can also propose changes to an existing AI Agent Configuration "
	"(provider, prompt, sampling params) following the update-agent response "
	"contract."
)
_FIXED_UPDATE_BULLET = (
	"  - You can also propose changes to an existing AI Agent Configuration — its "
	"MODEL, its SYSTEM prompt, or its sampling params — following the update-agent "
	"response contract. Not its user prompt: agents do not have one (see WHERE EACH "
	"PROMPT LIVES)."
)

_SECTION_MARKER = "WHERE EACH PROMPT LIVES:"
_SECTION = """

WHERE EACH PROMPT LIVES:
  - SYSTEM PROMPT belongs to the AI Agent Configuration. It is the agent's standing instructions, the same on every run. Changing it is an agent change: propose it with "proposed_update".
  - USER PROMPT belongs to the TASK SHAPE on the diagram, and is stored only there. It is this task's instruction for this step, and agents have no user prompt at all. Changing it is a task-field change: answer with "recommendations": {"aiUserPrompt": "..."} and nothing else.
  - So "write the user prompt", "add a user prompt", "the user prompt should say…" is ALWAYS a recommendation, never a proposed_update and never a proposed_config — even when the task links an agent, and even when you are also proposing a system prompt. If you are doing both, the system prompt goes in proposed_update and the user prompt goes in recommendations, in the same reply.
  - Never describe writing the user prompt as "updating the agent". It does not touch the agent."""


def _apply(prompt: str) -> str:
	updated = prompt
	if _STALE_UPDATE_BULLET in updated:
		updated = updated.replace(_STALE_UPDATE_BULLET, _FIXED_UPDATE_BULLET)
	if _SECTION_MARKER not in updated:
		updated = updated.rstrip() + _SECTION
	return updated


def execute():
	name = frappe.db.get_value("AI Agent Configuration", {"agent_id": AGENT_ID}, "name")
	if not name:
		frappe.log_error(
			title="fix_assistant_prompt_routing: assistant config missing",
			message=f"No AI Agent Configuration with agent_id '{AGENT_ID}' on this site.",
		)
		return

	prompt = frappe.db.get_value("AI Agent Configuration", name, "system_prompt") or ""
	updated = _apply(prompt)
	if updated == prompt:
		return

	frappe.db.set_value(
		"AI Agent Configuration", name, "system_prompt", updated, update_modified=False
	)
	frappe.cache.delete_value(f"agent_config:{AGENT_ID}")
	frappe.db.commit()
