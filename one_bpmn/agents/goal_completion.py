# Copyright (c) 2026, one-fm and contributors
# For license information, please see license.txt
"""
Did the run achieve what it was asked to do? (WI-001823)

Satisfaction is sparse and self-selected — under 1% of replies are ever rated,
by people at the extremes. Completion can be recorded on EVERY run with no user
effort, which is what makes it usable as the primary comparison between agents.

Three values, and the third is load-bearing. **Unknown is never coerced.** An
agent whose outcome cannot be determined must not be quietly counted as a
success or a failure: either would bias every average built on it, and the bias
would be invisible because the row still says something definite.

Two moments contribute, in order of how much they know:

1. **When the run finishes** — what the executor itself reports. An error, the
   turn cap, an empty answer. This is available for every run, including
   background AI Agent Tasks that no process ever "completes".
2. **When the process instance settles** — whether the map reached its end
   event. This is the strongest signal in the story's own ranking, and it can
   only be read later, because the run finishes long before the instance does.

Nothing here asks a model to judge itself.
"""

from __future__ import annotations

import frappe

ACHIEVED = "Achieved"
NOT_ACHIEVED = "Not Achieved"
UNKNOWN = "Unknown"


def _output_text(output) -> str:
	if output is None:
		return ""
	if isinstance(output, dict):
		# A structured reply is "usable" if it said anything at all.
		for key in ("response", "text", "output", "message"):
			value = output.get(key)
			if isinstance(value, str) and value.strip():
				return value.strip()
		return "" if not any(output.values()) else "structured"
	return str(output).strip()


def _declared_goal_met(output, goal_key: str) -> bool:
	"""Did the reply carry the key this map declared as its definition of done?

	Agents differ in what finishing means, so a map may name the reply key that
	proves it — Logix's finalize writes a script, ProsAlly's writes a diagram.
	Declarative on purpose: a key to look for, not an expression to evaluate, so
	nothing in a diagram can execute here.
	"""
	if not isinstance(output, dict):
		return False
	value = output.get(goal_key)
	if isinstance(value, str):
		return bool(value.strip())
	if isinstance(value, (list, dict)):
		return bool(value)
	return value is not None and value is not False


def determine(result, goal_key: str | None = None) -> tuple[str, str]:
	"""(state, basis) from what the executor reported. Pure — no database.

	Deliberately conservative: anything this cannot read confidently returns
	Unknown with a basis saying why, rather than guessing.
	"""
	if result is None:
		return UNKNOWN, "No executor result was recorded for this run."

	error_code = getattr(result, "error_code", None)
	code = getattr(error_code, "value", error_code)

	# Suspended is not an outcome — the run is still open, waiting on a person.
	if code == "SUSPENDED":
		return UNKNOWN, "Run is suspended, waiting for a person; the outcome is not decided yet."

	if getattr(result, "hit_turn_cap", False):
		return (
			NOT_ACHIEVED,
			"The tool-calling loop ran out of turns before reaching a final answer.",
		)

	if code and code != "SUCCESS":
		return NOT_ACHIEVED, f"The run ended with an error ({code})."

	output = getattr(result, "output", None)

	if goal_key:
		if _declared_goal_met(output, goal_key):
			return ACHIEVED, f"The run produced '{goal_key}', which this map declares as done."
		return (
			NOT_ACHIEVED,
			f"The run finished without producing '{goal_key}', which this map declares as done.",
		)

	if _output_text(output):
		return ACHIEVED, "The run finished without error and produced an answer."

	# Finished cleanly but said nothing. That is not a success, and it is not
	# evidence of failure either — some tasks legitimately write elsewhere.
	return UNKNOWN, "The run finished without error but produced no output to judge."


def settle_for_instance(instance_name: str, instance_status: str) -> int:
	"""Apply the strongest signal — did the map reach its end event — to the runs
	that could not decide for themselves.

	Only ever fills in Unknown. A run that already reported an error is NOT
	promoted just because the map went on to complete through its error branch:
	the map recovering is not the agent having achieved its goal. Equally, a run
	that produced its answer stays Achieved even if the instance later fails for
	unrelated reasons.

	Returns how many runs it settled, so callers can log it.
	"""
	if not instance_name:
		return 0

	if instance_status == "Completed":
		state = ACHIEVED
		basis = "The process reached its end event."
	elif instance_status in ("Errored", "Cancelled"):
		state = NOT_ACHIEVED
		basis = f"The process {instance_status.lower()} before finishing."
	else:
		return 0

	undecided = frappe.get_all(
		"AI Agent Run",
		filters={"instance": instance_name, "goal_completion": UNKNOWN},
		fields=["name", "status"],
		limit_page_length=0,
	)
	settled = 0
	for row in undecided:
		# A still-running or suspended run has not finished; leave it alone, its
		# own finalize will decide.
		if row["status"] not in ("Success", "Error"):
			continue
		# An errored run is never promoted by the map completing around it.
		if state == ACHIEVED and row["status"] == "Error":
			continue
		frappe.db.set_value(
			"AI Agent Run",
			row["name"],
			{"goal_completion": state, "completion_basis": basis},
			update_modified=False,
		)
		settled += 1
	return settled
