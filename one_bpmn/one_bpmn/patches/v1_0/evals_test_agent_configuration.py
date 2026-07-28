"""
WI-001751: evals now test the suite's AI Agent Configuration end-to-end.

- AI Eval Assertion.judge_model became a Link -> AI Model. Ensure an AI Model
  record exists for every judge_model already stored, so the links validate.
- AI Eval Case dropped provider/model/backend/input_system_prompt — Frappe keeps
  those columns as orphans; nothing to migrate (execution now reads the agent).
- AI Eval Suite.agent_configuration is now mandatory: log suites without one so
  they can be fixed (they are not runnable until an agent is set).

Idempotent.
"""

import frappe


def execute():
	from one_bpmn.api.eval_api import _ensure_ai_model

	seen = set()
	for row in frappe.get_all(
		"AI Eval Assertion",
		filters={"assertion_type": "llm_judge"},
		fields=["judge_model", "judge_provider"],
	):
		model = (row.get("judge_model") or "").strip()
		if not model or model in seen:
			continue
		seen.add(model)
		_ensure_ai_model(model, row.get("judge_provider"))

	# Backfill the new eval_type (required, default Direct) on existing suites.
	if frappe.db.has_column("AI Eval Suite", "eval_type"):
		frappe.db.set_value(
			"AI Eval Suite", {"eval_type": ["in", ["", None]]}, "eval_type", "Direct",
			update_modified=False,
		)

	orphan_suites = frappe.get_all(
		"AI Eval Suite", filters={"agent_configuration": ["in", ["", None]]}, pluck="name"
	)
	if orphan_suites:
		frappe.log_error(
			title="WI-001751: eval suites without an agent",
			message="These suites now require an agent_configuration and are not "
			"runnable until one is set: " + ", ".join(orphan_suites),
		)

	frappe.db.commit()
