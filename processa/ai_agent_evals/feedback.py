"""Response feedback queue and overview for the Evals console."""

import frappe
from frappe import _
from frappe.utils import cint

_FEEDBACK_FIELDS = [
	"name",
	"rating",
	"status",
	"comment",
	"rated_by",
	"rated_on",
	"message",
	"conversation",
	"agent_run",
	"agent_configuration",
	"eval_case",
]


def _agent_labels(configs: list) -> dict:
	if not configs:
		return {}
	rows = frappe.get_all(
		"AI Agent Configuration",
		filters={"name": ["in", list({c for c in configs if c})]},
		fields=["name", "agent_name", "chat_mode_label"],
	)
	return {r["name"]: (r["chat_mode_label"] or r["agent_name"] or r["name"]) for r in rows}


def _prompt_for_each_reply(replies: dict) -> dict:
	"""The user message that prompted each rated reply.

	A reply cannot be judged on its own - "that answer was wrong" means nothing
	without the question. Resolved in two bulk queries rather than one per row:
	every User message in the conversations involved, then the latest one before
	each reply.
	"""
	if not replies:
		return {}
	conversations = list({r["conversation"] for r in replies.values() if r.get("conversation")})
	if not conversations:
		return {}

	asked = frappe.get_all(
		"Chat Message",
		filters={"conversation": ["in", conversations], "message_type": "User"},
		fields=["conversation", "text", "creation"],
		order_by="creation asc",
		limit_page_length=0,
	)
	by_conversation: dict[str, list] = {}
	for row in asked:
		by_conversation.setdefault(row["conversation"], []).append(row)

	out = {}
	for message, reply in replies.items():
		candidates = by_conversation.get(reply.get("conversation"), [])
		previous = [c for c in candidates if c["creation"] <= reply["creation"]]
		out[message] = (previous[-1]["text"] if previous else "") or ""
	return out


def list_response_feedback(
	rating: str = "Negative",
	status: str = "New",
	agent: str = None,
	from_date: str = None,
	to_date: str = None,
	limit: int = 100,
) -> list:
	"""Feedback rows with enough context to judge them, newest first.

	Defaults to the triage queue - negative and unreviewed - because that is the
	only list anyone needs to act on. Pass "All" for rating or status to widen it.

	Permission scoping is the AI Response Feedback doctype's own: get_list here
	means a user sees exactly the rows their roles allow, with no second
	permission model to keep in step. The Chat Message text is then read with
	get_all for rows already authorised above - a join, not a widening.
	"""

	filters = {}
	if rating and rating != "All":
		filters["rating"] = rating
	if status and status != "All":
		filters["status"] = status
	if agent:
		filters["agent_configuration"] = agent
	if from_date:
		filters["rated_on"] = [">=", from_date]
	if to_date:
		filters["rated_on"] = ["between", [from_date, to_date]] if from_date else ["<=", to_date]

	rows = frappe.get_list(
		"AI Response Feedback",
		filters=filters,
		fields=_FEEDBACK_FIELDS,
		order_by="rated_on desc",
		limit_page_length=min(cint(limit) or 100, 500),
	)
	if not rows:
		return []

	names = [r["name"] for r in rows]
	message_ids = [r["message"] for r in rows if r.get("message")]

	replies = (
		{
			m["name"]: m
			for m in frappe.get_all(
				"Chat Message",
				filters={"name": ["in", message_ids]},
				fields=["name", "text", "conversation", "creation"],
				limit_page_length=0,
			)
		}
		if message_ids
		else {}
	)
	prompts = _prompt_for_each_reply(replies)

	reasons: dict[str, list] = {}
	for row in frappe.get_all(
		"AI Response Feedback Reason",
		filters={"parent": ["in", names]},
		fields=["parent", "reason"],
		limit_page_length=0,
	):
		reasons.setdefault(row["parent"], []).append(row["reason"])

	labels = _agent_labels([r.get("agent_configuration") for r in rows])

	# The suite each existing case belongs to, so "Open eval case" can go to it
	# inside Processa rather than out to the desk.
	case_suites = {}
	case_names = [r["eval_case"] for r in rows if r.get("eval_case")]
	if case_names:
		case_suites = {
			c["name"]: c["suite"]
			for c in frappe.get_all(
				"AI Eval Case",
				filters={"name": ["in", case_names]},
				fields=["name", "suite"],
				limit_page_length=0,
			)
		}

	out = []
	for row in rows:
		reply = replies.get(row.get("message")) or {}
		# Why a row cannot become a case is answered HERE, so the page can say so
		# instead of offering a button that fails.
		blocked = None
		if row["rating"] != "Negative":
			blocked = _("Only negative feedback becomes a regression test.")
		elif not row.get("agent_run"):
			blocked = _(
				"No agent run behind this reply - there is no prompt or context to build a case from."
			)
		elif not row.get("agent_configuration"):
			blocked = _("No agent configuration on this feedback, so there is no suite to file it under.")

		out.append(
			{
				**row,
				"agent_label": labels.get(row.get("agent_configuration"))
				or row.get("agent_configuration")
				or "",
				"reasons": reasons.get(row["name"], []),
				"reply_text": reply.get("text") or "",
				"prompt_text": prompts.get(row.get("message"), ""),
				"eval_suite": case_suites.get(row.get("eval_case")) or "",
				"can_convert": blocked is None and not row.get("eval_case"),
				"blocked_reason": blocked,
			}
		)
	return out


def get_feedback_overview(from_date: str = None, to_date: str = None, agent: str = None) -> dict:
	"""Counts for the cards above the queue.

	Counts WITH their denominator, never a satisfaction percentage. Fewer than 1%
	of replies are rated and the people who rate cluster at the extremes, so an
	average would be confidently wrong - and, sitting beside real cost figures,
	would be trusted exactly as much as they are.
	"""
	filters = {}
	if agent:
		filters["agent_configuration"] = agent
	if from_date and to_date:
		filters["rated_on"] = ["between", [from_date, to_date]]
	elif from_date:
		filters["rated_on"] = [">=", from_date]
	elif to_date:
		filters["rated_on"] = ["<=", to_date]

	rated = frappe.get_list(
		"AI Response Feedback",
		filters=filters,
		fields=["rating", "status"],
		limit_page_length=0,
	)

	# The denominator: agent replies in the same window. Scoped to the agent's
	# conversations when one is selected, so the ratio compares like with like.
	reply_filters = {"message_type": "Bot"}
	if from_date and to_date:
		reply_filters["creation"] = ["between", [from_date, to_date]]
	elif from_date:
		reply_filters["creation"] = [">=", from_date]
	elif to_date:
		reply_filters["creation"] = ["<=", to_date]
	if agent:
		label = frappe.db.get_value("AI Agent Configuration", agent, "chat_mode_label")
		conversations = (
			frappe.get_all(
				"Chat Conversation", filters={"agent_mode": label}, pluck="name", limit_page_length=0
			)
			if label
			else []
		)
		reply_filters["conversation"] = ["in", conversations or [""]]
	total_replies = frappe.db.count("Chat Message", reply_filters)

	negative = [r for r in rated if r["rating"] == "Negative"]
	return {
		"total_replies": total_replies,
		"total_rated": len(rated),
		"positive": len(rated) - len(negative),
		"negative": len(negative),
		"awaiting_review": len([r for r in negative if r["status"] == "New"]),
		"reviewed": len([r for r in negative if r["status"] == "Reviewed"]),
		"converted": len([r for r in rated if r["status"] == "Converted"]),
		"dismissed": len([r for r in rated if r["status"] == "Dismissed"]),
	}
