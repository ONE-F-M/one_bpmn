"""
A golden memory set for Docu, the DocType design agent.

Docu helps a business user design Frappe DocTypes in plain language. What is
worth remembering about that work is a standing convention ("every form we
build needs a naming series"), and what is not worth remembering is the much
larger pile of confirmations, clarifying questions and details about one
particular form.

The set is written against that distinction, because it is where memory
actually goes wrong. Three of the five generation cases expect **nothing** to
be produced. That is deliberate: a distiller that keeps everything scores well
on recall and makes the store useless, and only a case expecting silence
catches it.

The retrieval cases ask their questions in words the stored memory does not
use. A question sharing vocabulary with its answer proves nothing about
retrieval, because plain word matching would find it.

Nothing here touches an agent's real memories. ``seed`` writes the set under
its own scope key, so running the suite never reads or changes what Docu has
actually learned.
"""

from __future__ import annotations

import json

import frappe

# Its own scope key, so the suite never reads or writes Docu's real memories.
SCOPE = "Agent"
SCOPE_KEY = "golden_docu_agent"
SUITE_TITLE = "Docu memory"

# The memories the retrieval cases search. Seeded once, then queried.
STORE = [
	"Every DocType must include a naming series field.",
	"A field pointing at a person is a Link to Employee, and it stores the employee ID, not their name.",
	"Any form holding a monetary amount needs a currency field beside it.",
	"Child tables are only used where a parent record genuinely has many of something, never to group unrelated fields.",
	"Draft records stay editable; once submitted, a record is amended, never edited.",
]

# ── Generation: what should come out of one interaction ──────────────────────
# "produced" is filled in at run time by the distiller; these say what SHOULD
# come out. An empty "golden" means the right answer is to keep nothing.
GENERATION_CASES = [
	{
		"title": "A standing constraint the user states outright",
		"output": (
			"Understood. From now on every DocType I design will include a naming series, "
			"so each record gets a readable identifier automatically."
		),
		"golden": ["Every DocType must include a naming series field."],
		"why": "A rule that changes what the agent must do on every future design.",
	},
	{
		"title": "A convention the agent explains while applying it",
		"output": (
			"I have pointed the Requested By field at Employee instead of storing a typed name, "
			"because a Link keeps the two records connected and survives someone changing their name. "
			"I will use a Link to Employee for any person field from now on."
		),
		"golden": [
			"A field pointing at a person is a Link to Employee, and it stores the employee ID, not their name."
		],
		"why": "Reusable on the next form, and it explains itself instead of restating the request.",
	},
	{
		"title": "A confirmation of work just completed",
		"output": (
			"I've designed a DocType that captures each chat interaction where the AI agent receives a "
			"user message, interprets it, extracts the key information, and records what action was taken. "
			"This form tracks the conversation, the intent and the outcome."
		),
		"golden": [],
		"why": (
			"Observed on this bench. It reads like a fact and is really a summary of what just happened, "
			"useful to nobody next week. If anything survives this case, the distiller is keeping noise."
		),
	},
	{
		"title": "A clarifying question",
		"output": "Before I add the field: should a leave request be able to cover more than one date range? Yes or no.",
		"golden": [],
		"why": "Docu is told to ask a single polar question when a request is ambiguous. Questions are not knowledge.",
	},
	{
		"title": "A detail about one particular form",
		"output": (
			"The Purchase Request form now has nine fields and its naming series is PR-.YYYY.-. "
			"I have set the Requested By field as mandatory."
		),
		"golden": [],
		"why": (
			"True, specific, and worthless on an unrelated request next month. This is the case that "
			"separates a memory store from a changelog."
		),
	},
]

# ── Retrieval: a question, and the memories that should answer it ────────────
# Every question is worded to share no meaningful word with its answer, so a
# hit cannot come from plain word matching.
RETRIEVAL_CASES = [
	{
		"title": "Asking about identifiers without saying naming series",
		"query": "What has to be in place before a new record can be saved?",
		"expect": ["Every DocType must include a naming series field."],
	},
	{
		"title": "Asking about people without saying Link or Employee",
		"query": "How should one form point at a member of staff?",
		"expect": [
			"A field pointing at a person is a Link to Employee, and it stores the employee ID, not their name."
		],
	},
	{
		"title": "Asking about money without saying currency",
		"query": "If a form records how much something cost, what else does it need?",
		"expect": ["Any form holding a monetary amount needs a currency field beside it."],
	},
	{
		"title": "Asking about changing a record after the fact",
		"query": "Can somebody correct a record once it has been finalised?",
		"expect": ["Draft records stay editable; once submitted, a record is amended, never edited."],
	},
]


def draft() -> dict:
	"""The set as data, for reading and reviewing without writing anything."""
	return {
		"scope": SCOPE,
		"scope_key": SCOPE_KEY,
		"store": list(STORE),
		"generation": [dict(c) for c in GENERATION_CASES],
		"retrieval": [dict(c) for c in RETRIEVAL_CASES],
	}


def seed(agent_configuration: str | None = None) -> dict:
	"""Write the suite, its cases and the memories they search.

	Idempotent: the suite is found by title and its cases are replaced, so
	editing the set above and running this again leaves one copy of each.
	"""
	frappe.only_for("System Manager")

	suite = _suite(agent_configuration)
	_seed_store()
	for case in frappe.get_all("AI Eval Case", filters={"suite": suite}, pluck="name"):
		frappe.delete_doc("AI Eval Case", case, force=True, ignore_permissions=True)

	made = []
	for case in GENERATION_CASES:
		made.append(
			_case(
				suite,
				# The agent's own words are this case's input, so they go in the
				# field that holds a case's input. The runner reads them as the
				# thing to distil, not as a question, because the context names
				# them.
				prompt=case["output"],
				title=f"Generation: {case['title']}",
				expected="\n".join(case["golden"]),
				context={"scope": SCOPE, "scope_key": SCOPE_KEY, "agent_output": case["output"]},
			)
		)
	for case in RETRIEVAL_CASES:
		made.append(
			_case(
				suite,
				title=f"Retrieval: {case['title']}",
				prompt=case["query"],
				expected="\n".join(case["expect"]),
				context={"scope": SCOPE, "scope_key": SCOPE_KEY, "k": 5},
			)
		)
	return {"suite": suite, "cases": made, "memories": len(STORE)}


def _suite(agent_configuration: str | None) -> str:
	existing = frappe.db.get_value("AI Eval Suite", {"title": SUITE_TITLE}, "name")
	if existing:
		return existing
	doc = frappe.get_doc(
		{
			"doctype": "AI Eval Suite",
			"title": SUITE_TITLE,
			"eval_type": "Memory",
			"description": (
				"Whether Docu keeps the right things and finds them again. Three of the five generation "
				"cases expect nothing to be kept, because a distiller that keeps everything is the failure "
				"worth catching."
			),
			"agent_configuration": agent_configuration
			or frappe.db.get_value("AI Agent Configuration", {"agent_id": "docu_agent"}, "name"),
		}
	)
	doc.insert(ignore_permissions=True)
	return doc.name


def _case(suite: str, *, title: str, expected: str, context: dict, prompt: str = "") -> str:
	doc = frappe.get_doc(
		{
			"doctype": "AI Eval Case",
			"suite": suite,
			"case_type": "Memory",
			"title": title,
			"input_user_prompt": prompt,
			"expected_output": expected,
			"input_context": json.dumps(context),
		}
	)
	doc.insert(ignore_permissions=True)
	return doc.name


def _seed_store() -> None:
	"""Put the memories the retrieval cases search into the store, once."""
	from one_bpmn.agents.memory.tools import memory_search, memory_write

	for content in STORE:
		if any(row["content"] == content for row in memory_search(SCOPE, SCOPE_KEY, content, ignore_permissions=True)):
			continue
		memory_write(SCOPE, SCOPE_KEY, content, ignore_permissions=True)
