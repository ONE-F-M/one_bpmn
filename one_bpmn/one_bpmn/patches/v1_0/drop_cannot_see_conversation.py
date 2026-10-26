"""ProsAlly and Logix stop telling the model it cannot see the conversation.

The dispatcher now puts the person's message at the end of the prompt, so the
sentence that said otherwise is false — and it was load-bearing, because it is
why both prompts also forbid asking the user to repeat themselves. Left in
place, the model is handed the message and told in the same breath that it does
not have it.

Both maps carry the sentence in their driving prompt, and the engine runs the
compiled spec rather than the diagram, so each is rewritten and recompiled. A
map that already reads the new way — one that arrived by import — is left alone.
"""

import frappe

REPLACEMENT = (
	"The user&#39;s message is at the end of this prompt, and your tools read "
	"the conversation server-side, so NEVER ask them to repeat or provide it."
)

# Each map's exact sentence, oldest wording first. ProsAlly's carries one extra
# clause, so neither can be matched by a shared prefix.
OLD_SENTENCES = {
	"ProsAlly – Process Modeller (1)": (
		"Process the latest user message now. You cannot see the conversation "
		"yourself — your tools read it server-side — so NEVER ask the user to "
		"repeat or provide their message, and never say you cannot see one."
	),
	"Logix – Script Task Agent": (
		"Process the latest user message now. You cannot see the conversation "
		"yourself — your tools read it server-side — so NEVER ask the user to "
		"repeat or provide their message."
	),
}


def execute():
	for model, old in OLD_SENTENCES.items():
		_rewrite(model, old)


def _rewrite(model: str, old: str) -> None:
	if not frappe.db.exists("BPMN Process Model", model):
		return

	xml = frappe.db.get_value("BPMN Process Model", model, "bpmn_xml") or ""
	if old not in xml:
		# Already rewritten, or the prompt has moved on. Either way there is
		# nothing here to correct, and guessing at a near-match would be worse.
		return

	# db_set avoids the editability gate — trusted content migration, the same
	# rationale as compile_process_model's skip_editability_check.
	frappe.db.set_value("BPMN Process Model", model, "bpmn_xml", xml.replace(old, REPLACEMENT, 1))

	from one_bpmn.api.compilation import compile_process_model

	try:
		compile_process_model(model)
	except Exception:
		frappe.log_error(
			title=f"drop_cannot_see_conversation: recompile failed ({model})",
			message=frappe.get_traceback(),
		)
	frappe.db.commit()
