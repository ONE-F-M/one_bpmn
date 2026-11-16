"""Eval case authoring, conversation lookup and consistency for the Evals console."""

import json

import frappe
from frappe import _
from frappe.utils import add_days, cint, flt, now_datetime

_ASSERTION_FIELDS = ("assertion_type", "value", "judge_provider", "judge_model", "pass_threshold")


_EXPECTED_CALL_FIELDS = ("call_order", "tool_name", "argument", "matcher", "expected_value")


_ASSERTION_VALUE_LABEL = {
	"llm_judge": _("a rubric describing what a correct answer must contain"),
	"contains": _("the substring the output must contain"),
	"regex": _("the pattern the output must match"),
	"equals": _("the exact text the output must equal"),
	"schema_valid": _("the JSON Schema the output must validate against"),
}


def _set_expected_tool_calls(case, expected) -> None:
	"""Replace a case's expected tool calls from a list of dicts.

	A row with no tool names no call, so it is dropped rather than saved as an
	empty constraint that quietly passes.
	"""
	if isinstance(expected, str):
		expected = frappe.parse_json(expected) or []
	case.set("expected_tool_calls", [])
	for row in expected or []:
		if not str(row.get("tool_name") or "").strip():
			continue
		case.append(
			"expected_tool_calls",
			{k: row.get(k) for k in _EXPECTED_CALL_FIELDS if row.get(k) not in (None, "")},
		)


def _set_assertions(case, assertions) -> None:
	"""Replace a case's assertions from a list of dicts.

	``value`` is mandatory on AI Eval Assertion and carries the whole meaning of
	the check - the rubric for llm_judge, the substring for contains, and so on.
	An empty one used to be dropped from the row and then surfaced from
	doc.save() as a bare "MandatoryError: value", which named neither the
	assertion nor the field the author had actually left blank. Reject it here
	instead, saying which assertion and what belongs in it.
	"""
	if isinstance(assertions, str):
		assertions = frappe.parse_json(assertions) or []
	case.set("assertions", [])
	for idx, a in enumerate(assertions or [], start=1):
		if not a.get("assertion_type"):
			continue
		kind = a["assertion_type"]
		if not str(a.get("value") or "").strip():
			frappe.throw(
				_("Assertion {0} ({1}) needs a value - {2}.").format(
					idx, kind, _ASSERTION_VALUE_LABEL.get(kind, _("what the output is checked against"))
				)
			)
		row = {"assertion_type": kind}
		for k in _ASSERTION_FIELDS[1:]:
			if a.get(k) not in (None, ""):
				row[k] = a[k]
		# : judge_model is now a Link -> AI Model. Make sure the model
		# record exists so the link validates.
		if row.get("judge_model"):
			row["judge_model"] = ensure_ai_model(row["judge_model"], row.get("judge_provider"))
		case.append("assertions", row)


def ensure_ai_model(model_name: str, judge_provider: str = None) -> str:
	"""Return an AI Model name, creating the record if it doesn't exist yet
	(AI Model is autonamed by model_name, so name == model_name)."""
	if not model_name or frappe.db.exists("AI Model", model_name):
		return model_name
	# provider is a Link, so it has to be a real AI Provider record name. The
	# judge's own provider if it has one, otherwise whichever Anthropic record
	# the site actually has - writing a lowercase dialect string here produced a
	# dangling link that nothing could resolve.
	provider = (
		judge_provider
		if judge_provider and frappe.db.exists("AI Provider", judge_provider)
		else frappe.db.get_value("AI Provider", {"provider": ["like", "Anthropic"]}, "name")
	)
	frappe.get_doc(
		{
			"doctype": "AI Model",
			"model_name": model_name,
			"provider": provider or None,
		}
	).insert(ignore_permissions=True)  # perms: authors may lack create on AI Model
	return model_name


def create_eval_case(
	suite: str,
	title: str,
	input_user_prompt: str,
	expected_output: str = "",
	assertions=None,
	expected_tool_calls=None,
	case_type: str = None,
	target_skill: str = None,
	input_context=None,
) -> str:
	"""Create a manual AI Eval Case in ``suite`` with optional assertions. Provider/model/system prompt come from the suite's agent. The current user must be able to write the suite (owner / SM).

	``case_type`` says what the case measures and ``target_skill`` which skill it
	belongs to, so a golden dataset can be authored here rather than in the desk
	form. Provenance (source run, feedback, security event) is not settable: it
	is written by whatever promoted the case, and a hand-authored case has none.
	"""
	suite_doc = frappe.get_doc("AI Eval Suite", suite)
	suite_doc.check_permission("write")

	case = frappe.get_doc(
		{
			"doctype": "AI Eval Case",
			"suite": suite,
			"title": title,
			"process_model": suite_doc.process_model or None,
			"input_user_prompt": input_user_prompt,
			"expected_output": expected_output,
			"case_type": _valid_case_type(case_type) or "Output",
			"target_skill": _valid_skill(target_skill),
			"input_context": _valid_input_context(input_context),
		}
	)
	_set_assertions(case, assertions)
	_set_expected_tool_calls(case, expected_tool_calls)
	case.insert()
	return case.name


CASE_TYPES = (
	"Output",
	"Trajectory",
	"Trigger Positive",
	"Trigger Negative",
	"Adversarial",
	"Co-Load Budget",
	"Memory",
)


def _valid_case_type(value) -> str:
	"""A case type, or "" for not given. An unknown one is refused rather than
	stored: a typo would put the case in a category nothing reports on."""
	value = (value or "").strip()
	if value and value not in CASE_TYPES:
		frappe.throw(_("'{0}' is not a case type. Choose one of: {1}.").format(value, ", ".join(CASE_TYPES)))
	return value


def _valid_input_context(value) -> str | None:
	"""Input Context as a JSON object string, or None for not given.

	For a Memory case this field is the test itself (scope, scope_key, k, user,
	agent_output, produced_memories), so a string that is not a JSON object is
	refused here instead of being stored and failing at run time with an error
	about a missing scope_key.
	"""
	if value is None:
		return None
	if isinstance(value, dict):
		return json.dumps(value)
	text = str(value).strip()
	if not text:
		return None
	try:
		parsed = json.loads(text)
	except ValueError:
		frappe.throw(_("Input Context must be valid JSON."))
	if not isinstance(parsed, dict):
		frappe.throw(
			_(
				'Input Context must be a JSON object, for example {"scope": "Agent", "scope_key": "run_general_chat_agent"}.'
			)
		)
	return json.dumps(parsed)


def _valid_skill(value) -> str | None:
	value = (value or "").strip()
	if not value:
		return None
	if not frappe.db.exists("AI Skill", value):
		frappe.throw(_("No AI Skill named '{0}'.").format(value))
	return value


def get_eval_case(name: str) -> dict:
	"""Full case (fields + assertions) for the edit form."""
	case = frappe.get_doc("AI Eval Case", name)
	frappe.get_doc("AI Eval Suite", case.suite).check_permission("read")
	return {
		"name": case.name,
		"title": case.title,
		"input_user_prompt": case.input_user_prompt,
		"expected_output": case.expected_output,
		"case_type": case.case_type or "Output",
		"target_skill": case.target_skill or "",
		# Where the case came from. Read-only: it is what produced the case, not
		# something an author chooses.
		"source_feedback": case.source_feedback or "",
		"source_security_event": case.source_security_event or "",
		"source_run": case.source_run or "",
		"input_context": case.input_context or "",
		"assertions": [{k: a.get(k) for k in _ASSERTION_FIELDS} for a in case.assertions],
		"expected_tool_calls": [
			{k: c.get(k) for k in _EXPECTED_CALL_FIELDS} for c in case.expected_tool_calls
		],
	}


CONVERSATION_LIST_MAX = 100


CONVERSATION_MESSAGES_MAX = 500


def list_conversations_for_case(suite: str, search: str = "", limit: int = 30) -> list:
	"""Real conversations with the suite's agent that a case can start from, newest first."""
	suite_doc = frappe.get_doc("AI Eval Suite", suite)
	suite_doc.check_permission("write")
	mode = frappe.db.get_value("AI Agent Configuration", suite_doc.agent_configuration, "chat_mode_label")
	if not mode:
		return []
	or_filters = None
	if (search or "").strip():
		term = f"%{search.strip()}%"
		or_filters = [["title", "like", term], ["owner", "like", term]]
	return frappe.get_list(
		"Chat Conversation",
		filters={"agent_mode": mode, "is_eval": 0},
		or_filters=or_filters,
		fields=["name", "title", "owner", "modified"],
		order_by="modified desc",
		limit_page_length=min(max(cint(limit), 1), CONVERSATION_LIST_MAX),
	)


def _readable_conversation(suite: str, conversation: str):
	frappe.get_doc("AI Eval Suite", suite).check_permission("write")
	frappe.get_doc("Chat Conversation", conversation).check_permission("read")


def get_conversation_for_case(suite: str, conversation: str) -> list:
	"""The User and Bot messages of a conversation, oldest first, for picking where a case starts."""
	_readable_conversation(suite, conversation)
	return frappe.get_list(
		"Chat Message",
		filters={"conversation": conversation, "message_type": ["in", ["User", "Bot"]]},
		fields=["name", "message_type", "text", "creation"],
		order_by="creation asc",
		limit_page_length=CONVERSATION_MESSAGES_MAX,
	)


def conversation_context_for_case(
	suite: str, conversation: str, message: str, include_message: int = 0
) -> dict:
	"""A conversation's turns before ``message`` (or through it) as a case's earlier conversation.

	Carries the agent's latest saved progress before that point and what its tools fetched.
	"""
	_readable_conversation(suite, conversation)
	cutoff = frappe.db.get_value("Chat Message", {"name": message, "conversation": conversation}, "creation")
	if not cutoff:
		frappe.throw(_("That message is not part of this conversation."))
	before = "<=" if cint(include_message) else "<"
	rows = frappe.get_list(
		"Chat Message",
		filters={
			"conversation": conversation,
			"message_type": ["in", ["User", "Bot"]],
			"creation": [before, cutoff],
		},
		fields=["message_type", "text"],
		order_by="creation asc",
		limit_page_length=CONVERSATION_MESSAGES_MAX,
	)
	messages = [{"message_type": r.message_type, "text": r.text or ""} for r in rows]
	snapshot = frappe.get_list(
		"Chat Message",
		filters={"conversation": conversation, "message_type": "Tool", "creation": [before, cutoff]},
		fields=["text", "metadata"],
		order_by="creation desc",
		limit_page_length=1,
	)
	if snapshot:
		messages.append(
			{
				"message_type": "Tool",
				"text": snapshot[0].text or "",
				"metadata": frappe.parse_json(snapshot[0].metadata) if snapshot[0].metadata else None,
			}
		)

	from processa.ai_agent_conversations import session_state

	return {
		"conversation_messages": messages,
		"session_state": session_state.get_state(conversation),
		"message_text": frappe.db.get_value("Chat Message", message, "text") or "",
	}


def update_eval_case(
	name: str,
	title: str = None,
	input_user_prompt: str = None,
	expected_output: str = None,
	assertions=None,
	expected_tool_calls=None,
	case_type: str = None,
	target_skill: str = None,
	input_context=None,
) -> str:
	"""Edit an existing case, including its assertions. Gated by the
	suite's write permission."""
	case = frappe.get_doc("AI Eval Case", name)
	frappe.get_doc("AI Eval Suite", case.suite).check_permission("write")

	for field, val in (
		("title", title),
		("input_user_prompt", input_user_prompt),
		("expected_output", expected_output),
	):
		if val is not None:
			case.set(field, val)
	if case_type is not None:
		case.case_type = _valid_case_type(case_type) or case.case_type
	if target_skill is not None:
		# An empty string clears the link - the caller means "no skill", which
		# is different from not mentioning the field at all.
		case.target_skill = _valid_skill(target_skill)
	if input_context is not None:
		case.input_context = _valid_input_context(input_context)
	if assertions is not None:
		_set_assertions(case, assertions)
	if expected_tool_calls is not None:
		_set_expected_tool_calls(case, expected_tool_calls)

	case.save()
	return case.name


def case_consistency(suite: str, days: int = 7, limit: int = 100) -> dict:
	"""Per-case pass history for a suite over the last *days*, newest run first.

	A single run says whether a case passed; only the history says whether it
	AGREES with itself. A case at 80% over five runs is the one that will fail
	the week after go-live, and it looks identical to a solid case in any one
	run's results.

	A week by default, because that is the question being asked - "has this been
	steady lately" - and a fixed number of runs answers a different one: on a
	nightly suite twenty runs is three weeks, and on a quiet one it can reach
	back months. ``limit`` is only a ceiling so a chatty suite cannot return
	thousands. Cases are ordered worst first, because the point of the report is
	the flaky ones.
	"""
	frappe.get_doc("AI Eval Suite", suite).check_permission("read")

	since = add_days(now_datetime(), -abs(cint(days) or 7))
	runs = frappe.get_all(
		"AI Eval Run",
		filters={"suite": suite, "started_at": [">=", since]},
		fields=["name", "status", "backend", "started_at"],
		order_by="started_at desc",
		limit_page_length=cint(limit) or 100,
	)
	if not runs:
		return {"suite": suite, "runs": [], "cases": []}

	order = {r.name: idx for idx, r in enumerate(runs)}
	rows = frappe.get_all(
		"AI Eval Result",
		filters={"parenttype": "AI Eval Run", "parent": ["in", [r.name for r in runs]]},
		fields=["parent", "eval_case", "status", "runs", "passes", "consistency_rate"],
	)

	titles = {
		c.name: c.title
		for c in frappe.get_all("AI Eval Case", filters={"suite": suite}, fields=["name", "title"])
	}

	cases: dict = {}
	for row in rows:
		if not row.eval_case:
			continue
		entry = cases.setdefault(
			row.eval_case,
			{
				"case": row.eval_case,
				"title": titles.get(row.eval_case) or row.eval_case,
				"executions": 0,
				"passes": 0,
				"history": [],
			},
		)
		# A row written before cases ran more than once carries no runs count -
		# and its passes field is 0 rather than empty, so `runs` is the only
		# reliable marker. Such a row was one execution, and its status says how
		# that execution went.
		executions = cint(row.runs)
		if executions:
			passes = cint(row.passes)
		else:
			executions, passes = 1, (1 if row.status == "Passed" else 0)
		entry["executions"] += executions
		entry["passes"] += passes
		entry["history"].append(
			{
				"run": row.parent,
				"status": row.status,
				"runs": executions,
				"passes": passes,
				"consistency_rate": flt(row.consistency_rate)
				if cint(row.runs)
				else passes / executions * 100,
				"started_at": next((r.started_at for r in runs if r.name == row.parent), None),
				"order": order.get(row.parent, 0),
			}
		)

	out = []
	for entry in cases.values():
		# `runs` is newest-first, so a higher index is an OLDER run: the history
		# reads left to right as time passing, which is how the report is read.
		entry["history"].sort(key=lambda h: -h["order"])
		entry["consistency_rate"] = entry["passes"] / entry["executions"] * 100 if entry["executions"] else 0
		# "Flips" is what a reader is really looking for: a case that has both
		# passed and failed over this window, rather than one that always fails.
		statuses = {h["status"] for h in entry["history"]}
		entry["flips"] = len(statuses) > 1 or any(0 < h["passes"] < h["runs"] for h in entry["history"])
		out.append(entry)

	out.sort(key=lambda e: (e["consistency_rate"], e["title"]))
	return {
		"suite": suite,
		"min_pass_rate": flt(frappe.db.get_value("AI Eval Suite", suite, "min_pass_rate")),
		"pass_k": cint(frappe.db.get_value("AI Eval Suite", suite, "pass_k")) or 1,
		"runs": runs,
		"cases": out,
	}
