"""
WI-002001: stop ProsAlly re-asking "Shall I go ahead?" after the designer has
already said yes.

Reported from the editor: three consecutive turns on the Document Request map
answered a "Yes, proceed" with the same confirmation, slightly re-worded, and
never drew anything. Reproduced locally against that map — and the confirmation
was arriving correctly all along. The tool sequence on the confirmed turn should
be ``classify_intent → modify_process → finalize``; roughly two turns in five
came back ``classify_intent → modify_process → confirm → finalize``.

So the work WAS done: ``modify_process`` rebuilt the diagram and wrote it to the
per-turn store. Then the orchestrator called ``confirm`` one more time, that call
overwrote the finished output with a fresh "Shall I go ahead?", and Save Response
persisted the clobbered version. The designer confirmed again, and the loop
closed — every pass silently discarding the diagram they had asked for.

Two of the three fixes for this live outside a patch:

* the per-turn store now refuses a second terminal write, so a stray tool call
  can no longer destroy a finished turn (``agents/turn_state.py``);
* ``ProsAlly – Tool Modify Process`` no longer reports its removal-confirmation
  branch as ``{"modified": false}`` — that read as "the change did not happen",
  which is what invited the extra ``confirm`` call. Server Scripts travel by
  Processa export, not by patch, so that body is changed in the DB and exported
  from the frontend.

This patch owns the third: the orchestrator's own instructions, which live on the
prosally AI Agent Configuration and are read live at dispatch
(``resolve_dispatch_overrides``), so no recompile is needed and running
conversations pick the new prompt up on their next turn. The rules can live at
configuration level here — unlike the Logix prompt, which had to go on the map
because one configuration served two maps with opposite contracts — because the
prosally configuration is referenced by exactly one map.

Idempotent: returns early once the new prompt is in place. If the prompt has been
hand-edited to something we do not recognise, it is left alone and logged rather
than overwritten.
"""

import frappe

CONFIG_NAME = "prosally"

# Present only in the new prompt — the idempotency marker.
_MARKER = "go STRAIGHT to finalize"

OLD_SYSTEM_PROMPT = (
	"You run ONE turn of the ProsAlly process-modelling assistant by calling tools, "
	"one at a time. Step 1: call classify_intent; its result includes a 'next' field "
	"naming exactly which tool to call next (one of redirect, clarify, confirm, "
	"generate_process, modify_process). Step 2: call the tool named in 'next'. Step 3: "
	"call finalize. Always finish by calling finalize exactly once. Obey the 'next' "
	"field exactly, never skip it, never substitute another tool, and never draw BPMN "
	"yourself."
)

# The two additions over the old text: an explicit call BUDGET (three calls, in
# order), and a rule that names the specific failure — a stage tool reporting
# "nothing was modified" or "awaiting confirmation" is a COMPLETED step whose
# result is already the user's reply, not a failure to work around by asking
# again.
NEW_SYSTEM_PROMPT = (
	"You run ONE turn of the ProsAlly process-modelling assistant by calling tools, "
	"one at a time. Exactly THREE tool calls per turn, in this order. "
	"Step 1: call classify_intent; its result includes a 'next' field naming exactly "
	"which tool to call next (one of redirect, clarify, confirm, generate_process, "
	"modify_process). "
	"Step 2: call the tool named in 'next' — that tool, once. "
	"Step 3: call finalize. "
	"Obey the 'next' field exactly, never skip it, never substitute another tool, and "
	"never draw BPMN yourself. "
	"When the Step 2 tool returns, go STRAIGHT to finalize. Never call a second stage "
	"tool in the same turn, and never call confirm after generate_process or "
	"modify_process: those tools have already written the turn's reply, so confirming "
	"again re-asks a question the designer has already answered AND discards the "
	"diagram they asked for. A Step 2 result reporting that nothing was modified, that "
	"a change awaits confirmation, or that removals need approval is a COMPLETED step, "
	"not a failure — that result IS the reply. Never retry it and never follow it with "
	"another tool."
)


def execute():
	"""Tighten the ProsAlly orchestrator's tool-call rules (WI-002001)."""
	if not frappe.db.exists("AI Agent Configuration", CONFIG_NAME):
		return

	current = frappe.db.get_value("AI Agent Configuration", CONFIG_NAME, "system_prompt") or ""
	if _MARKER in current:
		return

	if current.strip() != OLD_SYSTEM_PROMPT:
		frappe.log_error(
			title="stop_prosally_reconfirm_loop: prompt anchor not found",
			message=(
				f"'{CONFIG_NAME}' system_prompt has diverged from the expected text, so it "
				"was left untouched. Add the rules manually: after the tool named in "
				"'next' returns, call finalize immediately — never a second stage tool, "
				"and never confirm after generate_process/modify_process."
			),
		)
		return

	# db_set, not doc.save: writing back to a Live agent re-runs the AI Agent
	# Creation Process (adversarial suite, real model calls) — far too much for a
	# prompt correction, and it would leave the agent mid-provisioning during a
	# migrate. The prompt is read live at dispatch either way.
	frappe.db.set_value("AI Agent Configuration", CONFIG_NAME, "system_prompt", NEW_SYSTEM_PROMPT)
