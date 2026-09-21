import json

import frappe
from frappe.model.document import Document
from frappe import _


class AISkill(Document):
	def validate(self):
		self._compute_token_estimate()
		self._validate_description()
		self._validate_allowed_tools_exist()
		self._validate_tier_graduation()

	def _compute_token_estimate(self):
		# US 1: rough rule of thumb, 1 token ~= 4 chars
		chars_per_token = 4
		self.token_estimate = len(self.body) // chars_per_token if self.body else 0

		if self.token_estimate > 5000:
			frappe.throw(_(
				"Skill body exceeds the token ceiling of 5,000 tokens (estimated {0} tokens). "
				"Please move details to resources."
			).format(self.token_estimate))

	def _validate_description(self):
		if not self.description:
			return

		if len(self.description) > 1024:
			frappe.throw(_("Description is too long (must be <= 1024 characters)."))

		# US: the hard "must contain this literal phrase" checks used to block
		# saving on wording alone. That is replaced by a non-blocking AI review:
		# an LLM judges whether the description makes clear when to use (and
		# when NOT to use) the skill, and - if it thinks the wording is
		# ambiguous - offers a suggested rephrasing as feedback. The author can
		# take it or leave it; nothing here ever raises for wording quality.
		self._ai_review_description()

	def _ai_review_description(self):
		"""Non-blocking AI review of description clarity (US 8).

		Runs ONE synchronous LLM call during save and, if the model thinks the
		description does not make clear when to use this skill and when not
		to, surfaces a suggested rephrasing via msgprint. Any failure here
		(no provider configured, network error, bad LLM output, ...) is
		logged and swallowed - an AI review outage must never block saving a
		skill, and it must never be confused with a genuine validation error.
		"""
		try:
			from one_bpmn.agents.executor.direct_api import _run_coro_blocking
			from one_bpmn.agents.llm_provider.factory import get_llm_adapter_from_settings

			adapter = get_llm_adapter_from_settings()

			system_prompt = (
				"You are reviewing the routing description of an AI Skill - the "
				"text an agent reads to decide whether to load this skill. "
				"Judge only ONE thing: does the description make it clear (a) "
				"when the skill SHOULD be used and (b) when it should NOT be "
				"used? Minor style issues do not matter.\n\n"
				"Respond with ONLY a JSON object, no markdown fences, no other "
				"text:\n"
				'{"clear": true} if the description is clear enough, or\n'
				'{"clear": false, "suggestion": "<a rewritten description that '
				'fixes the ambiguity>"} if it is not.'
			)
			user_prompt = f"Description:\n{self.description}"

			# _run_coro_blocking (agents/executor/direct_api.py, WI-001356)
			# already solves "call async LLM code from this synchronous
			# validate() hook" -- including falling back to a dedicated
			# thread (with the caller's contextvars, so frappe.local
			# survives) when a loop is already running. Reusing it here
			# instead of hand-rolling asyncio.get_event_loop() keeps this
			# codebase's one pattern for the problem instead of a second,
			# less battle-tested one.
			step_result = _run_coro_blocking(
				adapter.step(
					system=system_prompt,
					transcript=[{"role": "user", "content": user_prompt}],
				)
			)

			text = (step_result.content or "").strip()
			if text.startswith("```"):
				text = text.strip("`")
				if text.lower().startswith("json"):
					text = text[4:]
				text = text.strip()

			if not text:
				return

			review = json.loads(text)
			if review.get("clear") is False and review.get("suggestion"):
				frappe.msgprint(
					_(
						"AI review: this description may not make it clear when to "
						"use this skill and when not to. Suggested rephrasing "
						"(optional - you can save as-is):<br><br>{0}"
					).format(frappe.utils.escape_html(review["suggestion"])),
					title=_("AI Suggestion"),
					indicator="blue",
				)
		except Exception:
			# The AI review is a courtesy, not a gate. A failed or unavailable
			# LLM call must never stop the skill from saving, and must never be
			# mistaken for a real validation failure (bad tool refs, token
			# ceiling, tier graduation - all of which still raise for real).
			frappe.log_error(
				title="AI Skill: description AI review failed",
				message=frappe.get_traceback(),
			)

	def _validate_allowed_tools_exist(self):
		for tool_row in self.allowed_tools or []:
			if not frappe.db.exists("AI Agent Tool", tool_row.tool):
				frappe.throw(_("Allowed tool '{0}' does not exist.").format(tool_row.tool))

	def _validate_tier_graduation(self):
		"""US 5: tier is earned through eval evidence, not assigned by hand.

		Draft-Only has no requirements (it's the sandboxed starting point).
		Read-Only and Action-Allowed require eval cases + run results linked
		to this skill before they can be selected.
		"""
		if self.tier == "Draft-Only":
			return

		cases = frappe.get_all(
			"AI Eval Case",
			filters={"target_skill": self.name},
			fields=["name", "suite", "case_type"],
		)
		if not cases:
			frappe.throw(_("Cannot graduate skill to {0}: no AI Eval Cases target this skill.").format(self.tier))

		suites = sorted({c.suite for c in cases if c.suite})
		if not suites:
			frappe.throw(_("Cannot graduate skill to {0}: eval cases must belong to an AI Eval Suite.").format(self.tier))

		has_trigger_positive = any(c.case_type == "Trigger Positive" for c in cases)
		has_trigger_negative = any(c.case_type == "Trigger Negative" for c in cases)
		if not (has_trigger_positive and has_trigger_negative):
			frappe.throw(_(
				"Cannot graduate skill to {0}: needs both a Trigger Positive and a "
				"Trigger Negative eval case."
			).format(self.tier))

		# A finished run is Passed or Failed. There is no "Completed" status on
		# AI Eval Run, so the old filter matched nothing and no skill could ever
		# leave Draft-Only. Error is excluded: it means the run did not produce a
		# result to judge.
		runs = frappe.get_all(
			"AI Eval Run",
			filters={"suite": ["in", suites], "status": ["in", ("Passed", "Failed")]},
			fields=["name", "passed_cases", "total_cases"],
			order_by="creation desc",
			limit=5,
		)
		if not runs:
			frappe.throw(_("Cannot graduate skill to {0}: no completed AI Eval Run for its suite yet.").format(self.tier))

		latest = runs[0]
		accuracy = (latest.passed_cases / latest.total_cases) if latest.total_cases else 0

		if self.tier == "Read-Only":
			if accuracy < 0.90:
				frappe.throw(_(
					"Cannot graduate to Read-Only: latest eval run trigger accuracy is {0}%, "
					"needs at least 90%."
				).format(round(accuracy * 100, 1)))

		elif self.tier == "Action-Allowed":
			# Same number the dataset readings quote, so the bar a skill must
			# clear and the count shown beside it can never disagree. The bar is
			# set per agent; when none of the agents holding this skill's cases
			# has set one, there is no case-count bar to clear.
			from one_bpmn.api.golden_dataset import subject_sizes

			minimum = subject_sizes("Skill", self.name)[0]
			case_count = len({c.name for c in cases})
			if minimum and case_count < minimum:
				frappe.throw(_(
					"Cannot graduate to Action-Allowed: needs a golden dataset of {0}+ eval "
					"cases targeting this skill (found {1})."
				).format(minimum, case_count))

			sustained = runs[:2]
			if len(sustained) < 2 or any(
				not r.total_cases or r.passed_cases != r.total_cases for r in sustained
			):
				frappe.throw(_(
					"Cannot graduate to Action-Allowed: needs sustained 100% pass across "
					"multiple recent runs (pass^k), not just a single lucky pass."
				))
