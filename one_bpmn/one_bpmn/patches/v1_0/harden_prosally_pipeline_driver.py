import frappe

# The ProsAlly-lineage pipeline maps are blind orchestrators: the model never
# sees the conversation (its tools read it server-side) and its reply reaches
# the user ONLY through finalize's payload. The shipped one-line driver prompt
# said neither, so the model answered "I notice there's no new user message"
# in prose, finalize never ran, and Save Response wrote the canned
# "I couldn't generate a response" (observed live on staging, 2026-08-11 —
# the same failure harden_logix_pipeline_driver fixed for the Logix map).
# Matched by ANCHOR, not by model name: clones carry the same prompt.
OLD_USER_PROMPT = "Handle the latest user message now. Begin with classify_intent."
NEW_USER_PROMPT = (
	"Handle the latest user message now. You cannot see the conversation "
	"yourself — your tools read it server-side — so NEVER ask the user to "
	"repeat or provide their message. HARD PIPELINE RULES: (1) ALWAYS call "
	"classify_intent first; it reads the user message server-side and "
	"returns the intent plus a next field. (2) Follow next exactly (one of "
	"redirect, clarify, confirm, generate_process, modify_process). "
	"(3) Every turn MUST end by calling finalize — what finalize produces "
	"is the ONLY thing the user ever sees. (4) Never answer in plain text: "
	"text outside tool calls is discarded and the user sees an error "
	"instead of your words."
)
MARKER = "You cannot see the conversation"


def execute():
	"""Harden every ProsAlly-lineage pipeline driver prompt (clones included).

	Also recompiles any model whose XML already carries the rules but whose
	serialized_spec does not — a site where the XML was hand-fixed without a
	recompile still runs the old prompt (staging's exact state when this
	patch was written).
	"""
	from one_bpmn.api.compilation import compile_process_model

	models = frappe.get_all(
		"BPMN Process Model",
		or_filters=[
			["bpmn_xml", "like", f"%{OLD_USER_PROMPT}%"],
			["bpmn_xml", "like", f"%{MARKER}%"],
		],
		pluck="name",
	)
	for name in models:
		xml = frappe.db.get_value("BPMN Process Model", name, "bpmn_xml") or ""
		old_attr = 'aiUserPrompt="%s"' % OLD_USER_PROMPT
		if old_attr in xml:
			# db_set avoids the editability gate — trusted content migration,
			# same rationale as compile_process_model's skip_editability_check.
			frappe.db.set_value(
				"BPMN Process Model",
				name,
				"bpmn_xml",
				xml.replace(old_attr, 'aiUserPrompt="%s"' % NEW_USER_PROMPT, 1),
			)
		elif MARKER not in xml:
			continue  # matched the like-filter some other way — leave it alone

		spec = frappe.db.get_value("BPMN Process Model", name, "serialized_spec") or ""
		if MARKER in spec:
			continue  # already compiled with the rules
		try:
			compile_process_model(name)
			print(f"harden_prosally_pipeline_driver: {name} hardened + recompiled")
		except Exception:
			frappe.log_error(
				title=f"harden_prosally_pipeline_driver: recompile failed ({name})",
				message=frappe.get_traceback(),
			)
