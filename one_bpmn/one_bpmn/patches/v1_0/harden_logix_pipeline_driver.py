import frappe

MODEL_NAME = "Logix – Script Task Agent"
SAVE_SCRIPT_NAME = "Logix – Save Response"

# The reply the user sees exists ONLY if the model calls finalize: Save
# Response reads the per-turn store finalize writes, and everything the model
# says outside tool calls is discarded. The map's driving prompt never said
# so — one line ("Begin with classify_intent") against a persona prompt with
# no tool rules, and haiku answered turns in helpful prose, which surfaced as
# "I couldn't generate a response. Please try again." three turns in a row
# (runs qhlj1r0e1d / qosurcnkn1 / r3ri0sncuq, 2026-08-09). The rules live on
# the MAP, not the agent configuration: the same logix_agent also serves the
# generic chat map, whose contract is the opposite (a JSON text reply, no
# pipeline tools), so a config-level "never reply in prose" would break it.
# Anchors, oldest first: the original one-liner, then the first hardening
# round (which fixed the prose-instead-of-finalize failure but left the model
# free to ask the user to "provide their message" — it cannot see the
# conversation, only its tools can, and haiku balked at processing a message
# it never received).
OLD_USER_PROMPTS = [
	"Process the latest user message now. Begin with classify_intent.",
	(
		"Process the latest user message now. HARD PIPELINE RULES: "
		"(1) Call classify_intent first and follow its next field: write_script "
		"for CREATE or MODIFY, review_script after every write, clarify for "
		"DISAMBIGUATE. "
		"(2) Every turn MUST end by calling finalize — what finalize produces is "
		"the ONLY thing the user ever sees. "
		"(3) Never answer in plain text: text outside tool calls is discarded and "
		"the user sees an error instead of your words. When you need details from "
		"the user, ask through clarify and then call finalize."
	),
]
NEW_USER_PROMPT = (
	"Process the latest user message now. You cannot see the conversation "
	"yourself — your tools read it server-side — so NEVER ask the user to "
	"repeat or provide their message. HARD PIPELINE RULES: "
	"(1) ALWAYS call classify_intent first; it reads the user's message "
	"server-side and returns the intent plus a next field. "
	"(2) Follow next: write_script for CREATE or MODIFY, review_script after "
	"every write, clarify for DISAMBIGUATE. "
	"(3) Every turn MUST end by calling finalize — what finalize produces is "
	"the ONLY thing the user ever sees. "
	"(4) Never answer in plain text: text outside tool calls is discarded and "
	"the user sees an error instead of your words."
)

# Belt for contract-breaking turns: rather than the canned error, show the
# model's own final text (the ai_agent task's output variable). Degraded — no
# card, no intent — but the user reads words instead of a dead end.
OLD_FALLBACK = (
	'    response_text = task_data.get("response_text") or '
	'"I couldn\'t generate a response. Please try again."'
)
NEW_FALLBACK = (
	'    _prose = task_data.get("ai_result")\n'
	'    if not isinstance(_prose, str):\n'
	'        _prose = ""\n'
	'    response_text = task_data.get("response_text") or _prose.strip() or '
	'"I couldn\'t generate a response. Please try again."'
)


def execute():
	"""Make the Logix pipeline map's agent actually drive its pipeline (WI-001997 follow-up).

	Two halves: the run_logix_agent user prompt now states the tool pipeline
	as hard rules (always end with finalize, never prose), and Save Response
	falls back to the agent's own text when a turn still breaks the contract.
	"""
	_harden_driver_prompt()
	_soften_save_response_fallback()


def _harden_driver_prompt():
	if not frappe.db.exists("BPMN Process Model", MODEL_NAME):
		return
	xml = frappe.db.get_value("BPMN Process Model", MODEL_NAME, "bpmn_xml") or ""
	if "You cannot see the conversation" in xml:
		return
	old_attr = next(
		(
			'aiUserPrompt="%s"' % p
			for p in OLD_USER_PROMPTS
			if 'aiUserPrompt="%s"' % p in xml
		),
		None,
	)
	if not old_attr:
		frappe.log_error(
			title="harden_logix_pipeline_driver: prompt anchor not found",
			message=f"'{MODEL_NAME}' bpmn_xml no longer carries the expected "
			"aiUserPrompt; update the driving prompt manually.",
		)
		return
	xml = xml.replace(old_attr, 'aiUserPrompt="%s"' % NEW_USER_PROMPT, 1)

	# db_set avoids the editability gate — trusted content migration, same
	# rationale as compile_process_model's skip_editability_check.
	frappe.db.set_value("BPMN Process Model", MODEL_NAME, "bpmn_xml", xml)

	# Recompile so serialized_spec carries the new prompt. New conversations
	# pick it up; running instances keep their old spec.
	from one_bpmn.api.compilation import compile_process_model

	try:
		compile_process_model(MODEL_NAME)
	except Exception:
		frappe.log_error(
			title="harden_logix_pipeline_driver: recompile failed",
			message=frappe.get_traceback(),
		)


def _soften_save_response_fallback():
	if not frappe.db.exists("Server Script", SAVE_SCRIPT_NAME):
		return
	doc = frappe.get_doc("Server Script", SAVE_SCRIPT_NAME)
	script = doc.script or ""
	if 'task_data.get("ai_result")' in script:
		return
	if OLD_FALLBACK not in script:
		frappe.log_error(
			title="harden_logix_pipeline_driver: fallback anchor not found",
			message=f"'{SAVE_SCRIPT_NAME}' diverged from the expected body; "
			"add the ai_result fallback manually.",
		)
		return
	doc.script = script.replace(OLD_FALLBACK, NEW_FALLBACK, 1)
	doc.save(ignore_permissions=True)
