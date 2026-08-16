# Copyright (c) 2026, one-fm and contributors
# For license information, please see license.txt
"""
What a user thought of an agent reply, and what to do with it (WI-001641).

Three whitelisted calls, and one rule running through all of them: the client
names the MESSAGE and nothing else. Conversation, run and agent configuration
are all read back from that message here. A browser that could name its own
agent_run could attach a complaint to somebody else's turn, and the join to
cost and latency — the only reason the run is recorded at all — would be worth
nothing.

Feedback is deliberately not an AG-UI event. The `onefm.*` contract is what an
agent sends to a screen; this travels the other way, after the turn has already
finished, so it is an ordinary endpoint like `end_chat_conversation`.
"""

import json

import frappe
from frappe import _

RATINGS = ("Positive", "Negative")
VALID_REASONS = (
	"Inaccurate",
	"Incomplete",
	"Not relevant",
	"Didn't follow instructions",
	"Wrong tone",
)


# ── helpers ──────────────────────────────────────────────────────────────────


def _load_rateable_message(message: str):
	"""The message, if it exists, is an agent reply, and this user may rate it."""
	if not message:
		frappe.throw(_("A message is required."))
	if not frappe.db.exists("Chat Message", message):
		frappe.throw(_("That message no longer exists."), frappe.DoesNotExistError)

	doc = frappe.get_doc("Chat Message", message)

	# Rating your own question is meaningless, and allowing it would quietly
	# pollute every per-agent average with rows no agent produced.
	if doc.message_type != "Bot":
		frappe.throw(_("Only an agent's reply can be rated."))

	_assert_participant(doc.conversation)
	return doc


def _assert_participant(conversation: str):
	"""Only someone in the conversation may rate what was said in it.

	Read permission on Chat Conversation is not enough on its own: a System
	Manager can read every conversation on the site, and satisfaction data
	gathered from people who were not in the room is not satisfaction data.
	"""
	if not conversation:
		frappe.throw(_("That message is not attached to a conversation."))

	user = frappe.session.user
	if user == "Guest":
		frappe.throw(_("Authentication required."), frappe.PermissionError)

	owner = frappe.db.get_value("Chat Conversation", conversation, "owner")
	if owner == user:
		return
	if frappe.db.exists("Chat Participant", {"parent": conversation, "user": user}):
		return

	frappe.throw(
		_("You can only rate replies in a conversation you took part in."),
		frappe.PermissionError,
	)


def _resolve_run_and_agent(msg) -> tuple[str | None, str | None]:
	"""Find the run behind a reply, and the agent configuration that produced it.

	The run id is stamped into the reply's metadata by the turn itself when it is
	available. When it is not — an older message, or a runner that persists no
	run — fall back to the instance driving the conversation and take the run
	closest to the message. Returning (None, config) is a normal outcome, not a
	failure: feedback on a reply whose run has been trimmed is still feedback.
	"""
	run = None
	meta = {}
	if msg.metadata:
		try:
			meta = json.loads(msg.metadata) or {}
		except Exception:
			meta = {}
	if isinstance(meta, dict):
		run = meta.get("agent_run") or (meta.get("agent_result") or {}).get("agent_run")

	if not run:
		instance = frappe.db.get_value(
			"BPMN Process Instance",
			{"context_doctype": "Chat Conversation", "context_docname": msg.conversation},
			"name",
		)
		if instance:
			rows = frappe.get_all(
				"AI Agent Run",
				filters={"instance": instance, "creation": ["<=", msg.creation]},
				fields=["name"],
				order_by="creation desc",
				limit=1,
			)
			if rows:
				run = rows[0].name

	# A run named in old metadata may since have been trimmed. Dropping it here
	# rather than storing it is what keeps the rating itself safe: agent_run is a
	# Link, so a dangling name makes the save throw, and the user's click would
	# be lost to a housekeeping job they never saw.
	if run and not frappe.db.exists("AI Agent Run", run):
		run = None

	agent = frappe.db.get_value("AI Agent Run", run, "agent_configuration") if run else None
	if not agent:
		# Every conversation is stamped with the agent's chat mode label.
		mode = frappe.db.get_value("Chat Conversation", msg.conversation, "agent_mode")
		if mode:
			agent = frappe.db.get_value(
				"AI Agent Configuration", {"chat_mode_label": mode, "enabled": 1}, "name"
			)
	return run, agent


def _clean_comment(text, agent_config, conversation=None, run=None) -> str:
	"""A comment is user-entered text arriving over an API, so it is screened
	exactly like anything typed into the composer — same PII redaction, same
	injection observation. Skipping it would leave one unscreened free-text field
	on a record that reviewers read and that eval cases are later built from,
	which is precisely the path by which an injected instruction would reach a
	model wearing the badge of a "test case".

	Both screens are already fail-open by design (see their own docstrings): they
	protect data in transit, they do not authorise anything, so a broken detector
	must not stop a user rating a reply."""
	text = (text or "").strip()
	if not text:
		return ""
	text = text[:2000]

	from one_bpmn.security import injection, pii

	redaction = pii.screen_input(text, agent_config)
	text = redaction.text or text

	# Observation only — it records an AI Security Event when a rule fires and
	# returns the text unchanged. Reported on the input boundary because that is
	# what this is: text arriving from a person.
	injection.screen_for_injection(
		text,
		boundary="input",
		agent_configuration=agent_config,
		conversation=conversation,
		run=run,
	)
	return text


def _normalise_reasons(reasons, rating: str) -> list:
	if isinstance(reasons, str):
		try:
			reasons = json.loads(reasons)
		except Exception:
			reasons = [r.strip() for r in reasons.split(",")]
	if not isinstance(reasons, (list, tuple)):
		return []
	if rating == "Positive":
		return []
	return [r for r in reasons if r in VALID_REASONS]


# ── the API ──────────────────────────────────────────────────────────────────


@frappe.whitelist()
def rate_response(message: str, rating: str, reasons=None, comment: str = "") -> dict:
	"""Record (or replace) this user's rating of one agent reply.

	Idempotent by construction: the row is keyed on message + user, so clicking
	the same thumb twice, or switching from down to up, updates in place. The
	change history is Frappe's own Version trail — the doctype has
	track_changes, so "who changed their mind and when" is answered without a
	bespoke audit table.
	"""
	if rating not in RATINGS:
		frappe.throw(_("Rating must be one of: {0}").format(", ".join(RATINGS)))

	msg = _load_rateable_message(message)
	run, agent = _resolve_run_and_agent(msg)
	reasons = _normalise_reasons(reasons, rating)
	comment = _clean_comment(comment, agent, conversation=msg.conversation, run=run)

	existing = frappe.db.get_value(
		"AI Response Feedback",
		{"dedup_key": f"{msg.name}|{frappe.session.user}"},
		"name",
	)
	doc = (
		frappe.get_doc("AI Response Feedback", existing)
		if existing
		else frappe.new_doc("AI Response Feedback")
	)

	doc.message = msg.name
	doc.conversation = msg.conversation
	doc.agent_run = run
	doc.agent_configuration = agent
	doc.rated_by = frappe.session.user
	doc.rating = rating
	doc.comment = comment
	doc.rated_on = frappe.utils.now_datetime()
	doc.set("reasons", [{"reason": r} for r in reasons])
	# A re-rating is new information: whatever a reviewer concluded about the old
	# one no longer describes what the user thinks. Converted feedback keeps its
	# status — the eval case it produced still exists.
	if doc.status in (None, "", "Reviewed", "Dismissed"):
		doc.status = "New"

	doc.save(ignore_permissions=True)
	frappe.db.commit()

	return {
		"name": doc.name,
		"message": doc.message,
		"rating": doc.rating,
		"reasons": [r.reason for r in doc.reasons or []],
		"comment": doc.comment or "",
		"agent_run": doc.agent_run,
		"agent_configuration": doc.agent_configuration,
	}


@frappe.whitelist()
def clear_response_rating(message: str) -> dict:
	"""Withdraw this user's rating. An unrated reply has no row at all, which is
	what keeps "nobody said anything" distinguishable from "somebody disliked
	it" — so withdrawing really does delete, rather than storing a third state."""
	msg = _load_rateable_message(message)
	name = frappe.db.get_value(
		"AI Response Feedback",
		{"dedup_key": f"{msg.name}|{frappe.session.user}"},
		"name",
	)
	if name:
		frappe.delete_doc("AI Response Feedback", name, ignore_permissions=True, delete_permanently=False)
		frappe.db.commit()
	return {"message": msg.name, "cleared": bool(name)}


@frappe.whitelist()
def create_eval_case_from_feedback(feedback: str, suite: str = None) -> dict:
	"""Turn a reviewed complaint into a permanent regression test.

	This is the point of collecting any of it. A thumbs-down that only moves a
	percentage is a statistic; a thumbs-down that becomes an eval case is a test
	the agent can never silently fail again.

	Two guards, both deliberate:

	* Only NEGATIVE feedback. A case built from a reply somebody liked would
	  pin the current behaviour as correct, which is a different job (baseline
	  capture) already served by creating a case from the run directly.
	* Only REVIEWED feedback. Every thumbs-down is not a regression — people
	  press it because an answer was slow, or because they disagreed with a
	  correct answer. Auto-converting the raw stream would fill the suite with
	  noise and quietly destroy trust in it. A person decides.

	The case itself is built by the existing factory, so the permission model,
	the starter assertion and the source_run linkage are the ones already in use
	— this only adds the link back to the complaint.
	"""
	doc = frappe.get_doc("AI Response Feedback", feedback)
	doc.check_permission("write")

	if doc.rating != "Negative":
		frappe.throw(_("Only negative feedback becomes a regression test."))
	if doc.status not in ("Reviewed", "Converted"):
		frappe.throw(
			_("Review this feedback first — a case is only created from feedback a person has looked at.")
		)
	if doc.eval_case and frappe.db.exists("AI Eval Case", doc.eval_case):
		return {"feedback": doc.name, "eval_case": doc.eval_case, "created": False}
	if not doc.agent_run:
		frappe.throw(
			_("This feedback has no agent run behind it, so there is no prompt or context to build a case from.")
		)

	from one_bpmn.agents.eval_case_factory import create_eval_case_from_run

	# No starter assertion: the reply was wrong, so pinning "match what it did"
	# would certify the failure as the expected answer. What should have
	# happened is the reviewer's to write.
	case = create_eval_case_from_run(doc.agent_run, suite=suite, add_starter_assertion=False)

	frappe.db.set_value("AI Eval Case", case, "source_feedback", doc.name)
	doc.db_set("eval_case", case)
	doc.db_set("status", "Converted")
	frappe.db.commit()

	return {"feedback": doc.name, "eval_case": case, "created": True}


@frappe.whitelist()
def get_response_rating(message: str) -> dict:
	"""This user's current rating of a reply, so a reopened conversation shows
	the thumbs they already pressed instead of a blank slate."""
	msg = _load_rateable_message(message)
	name = frappe.db.get_value(
		"AI Response Feedback",
		{"dedup_key": f"{msg.name}|{frappe.session.user}"},
		"name",
	)
	if not name:
		return {"message": msg.name, "rating": None, "reasons": [], "comment": ""}

	doc = frappe.get_doc("AI Response Feedback", name)
	return {
		"message": doc.message,
		"rating": doc.rating,
		"reasons": [r.reason for r in doc.reasons or []],
		"comment": doc.comment or "",
	}
