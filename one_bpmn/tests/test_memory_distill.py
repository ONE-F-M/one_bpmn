# Copyright (c) 2026, one-fm and contributors
# Tests for memory distillation: the salience gate rejects confirmations /
# clarifications / errors and keeps only durable facts, with deterministic
# dedup keys — driven by a fake executor (no live LLM call).

from __future__ import annotations

from frappe.tests.utils import FrappeTestCase

from one_bpmn.agents.executor import (
	ErrorCode,
	Executor,
	ExecutorResult,
	register_executor,
)
from one_bpmn.agents.memory import distill as DZ

# What the fake curator LLM "returns" for the next distill call.
_FAKE = {"output": {"memories": []}, "error": ErrorCode.SUCCESS}


class _FakeCurator(Executor):
	def run(self, config, context):
		return ExecutorResult(output=_FAKE["output"], error_code=_FAKE["error"])


register_executor("curatortest", _FakeCurator)


def _distill(output_text, model="test-model", exclude_context=None):
	return DZ.distill_memories(
		output_text,
		agent="prosally",
		scope="Agent",
		scope_key="run_prosally_agent",
		provider_name="",
		backend="curatortest",
		model=model,
		exclude_context=exclude_context,
	)


# A real confirmation blob from the audited store — the gate must yield nothing.
_NOISE = (
	"✅ Complete! Your Visitor Sign In DocType has been successfully created "
	"with an auto-ID format (VSI-.#####). The schema passed all validation checks."
)


class TestDistillSalienceGate(FrappeTestCase):
	def test_noise_yields_nothing(self):
		# The curator returns [] for a confirmation message.
		_FAKE["output"] = {"memories": []}
		_FAKE["error"] = ErrorCode.SUCCESS
		self.assertEqual(_distill(_NOISE), [])

	def test_genuine_fact_is_kept_with_dedup_key(self):
		_FAKE["output"] = {
			"memories": [
				{"content": "Use exclusive gateways for yes/no decisions.", "topic": "Gateway Pattern"}
			]
		}
		_FAKE["error"] = ErrorCode.SUCCESS
		facts = _distill("some run output")
		self.assertEqual(len(facts), 1)
		self.assertEqual(facts[0]["content"], "Use exclusive gateways for yes/no decisions.")
		self.assertEqual(facts[0]["topic"], "gateway-pattern")            # slugified
		self.assertEqual(facts[0]["dedup_key"], "prosally:gateway-pattern")  # agent-namespaced

	def test_duplicate_topics_collapse(self):
		_FAKE["output"] = {
			"memories": [
				{"content": "first", "topic": "same topic"},
				{"content": "second", "topic": "same topic"},
			]
		}
		_FAKE["error"] = ErrorCode.SUCCESS
		facts = _distill("out")
		self.assertEqual(len(facts), 1)  # same dedup_key -> collapsed

	def test_executor_failure_yields_nothing(self):
		_FAKE["output"] = None
		_FAKE["error"] = ErrorCode.FAILED_MODEL_CALL
		self.assertEqual(_distill("out"), [])

	def test_empty_output_short_circuits(self):
		self.assertEqual(_distill("   "), [])

	def test_no_model_skips_distillation(self):
		# No hardcoded fallback: without a resolved model nothing is distilled.
		_FAKE["output"] = {"memories": [{"content": "c", "topic": "t"}]}
		_FAKE["error"] = ErrorCode.SUCCESS
		self.assertEqual(_distill("out", model=None), [])

	def test_json_string_output_is_parsed(self):
		# Tolerate a raw JSON string as well as a parsed dict.
		_FAKE["output"] = '{"memories": [{"content": "c", "topic": "t"}]}'
		_FAKE["error"] = ErrorCode.SUCCESS
		facts = _distill("out")
		self.assertEqual(facts[0]["dedup_key"], "prosally:t")


# WI-002165: the curator can still hand back a fact that just paraphrases the
# agent's own instructions (the prompt guardrail alone left confirmed echo
# rows in the store — see cleanup_ai_memory_store.py); exclude_context is the
# deterministic backstop that rejects those regardless of what the curator
# returned.
_LOGIX_DRIVING_PROMPT = (
	"The user's message is at the end of this prompt, and your tools read the "
	"conversation server-side, so NEVER ask them to repeat or provide it. "
	"HARD PIPELINE RULES: "
	"(1) ALWAYS call classify_intent first; it reads the user's message "
	"server-side and returns the intent plus a next field. "
	"(2) Follow next: write_script for CREATE or MODIFY, review_script after "
	"every write, clarify for DISAMBIGUATE. "
	"(3) Every turn MUST end by calling finalize — what finalize produces is "
	"the ONLY thing the user ever sees. "
	"(4) Never answer in plain text: text outside tool calls is discarded and "
	"the user sees an error instead of your words."
)
# The confirmed live echo (jrrd68247k) — a paraphrase, not a verbatim copy, of
# the driving prompt above.
_ECHOED_CONTENT = (
	"Always call classify_intent first to read the user's message and get "
	"intent plus next field. Follow the next instruction: write_script for "
	"CREATE or MODIFY, review_script after every write, clarify for "
	"DISAMBIGUATE. Every turn must end with finalize."
)


class TestDistillExcludeContext(FrappeTestCase):
	def test_echo_of_driving_prompt_is_rejected(self):
		_FAKE["output"] = {"memories": [{"content": _ECHOED_CONTENT, "topic": "pipeline order"}]}
		_FAKE["error"] = ErrorCode.SUCCESS
		facts = _distill("some run output", exclude_context=_LOGIX_DRIVING_PROMPT)
		self.assertEqual(facts, [])

	def test_genuine_fact_survives_alongside_exclude_context(self):
		# A real durable fact, unrelated to the driving prompt, must not be
		# collateral damage from the exclusion check.
		genuine = "When severity is marked as critical, records require approval from a designated approver before submission."
		_FAKE["output"] = {"memories": [{"content": genuine, "topic": "approval rule"}]}
		_FAKE["error"] = ErrorCode.SUCCESS
		facts = _distill("some run output", exclude_context=_LOGIX_DRIVING_PROMPT)
		self.assertEqual(len(facts), 1)
		self.assertEqual(facts[0]["content"], genuine)

	def test_verbatim_echo_is_rejected(self):
		# The exact system prompt text handed back as a "fact" (the false
		# qq9gekd7ah-style case) — verbatim, not just similar.
		_FAKE["output"] = {"memories": [{"content": _LOGIX_DRIVING_PROMPT, "topic": "rules"}]}
		_FAKE["error"] = ErrorCode.SUCCESS
		facts = _distill("some run output", exclude_context=_LOGIX_DRIVING_PROMPT)
		self.assertEqual(facts, [])

	def test_no_exclude_context_skips_the_check(self):
		# Back-compat: callers that don't pass exclude_context (the previous
		# behaviour) get no echo filtering at all.
		_FAKE["output"] = {"memories": [{"content": _ECHOED_CONTENT, "topic": "pipeline order"}]}
		_FAKE["error"] = ErrorCode.SUCCESS
		facts = _distill("some run output")
		self.assertEqual(len(facts), 1)


class TestIsEcho(FrappeTestCase):
	"""Direct coverage of the deterministic similarity check, independent of
	the curator — see distill.py's threshold rationale for the numbers below."""

	def test_paraphrase_of_driving_prompt_flagged(self):
		self.assertTrue(DZ._is_echo(_ECHOED_CONTENT, _LOGIX_DRIVING_PROMPT))

	def test_unrelated_fact_not_flagged(self):
		unrelated = "When severity is marked as critical, records require approval from a designated approver before submission."
		self.assertFalse(DZ._is_echo(unrelated, _LOGIX_DRIVING_PROMPT))

	def test_domain_adjacent_but_genuine_fact_not_flagged(self):
		# Shares vocabulary with a gateway-heavy prompt without being an echo
		# of it — the false-positive case the threshold is tuned against.
		prosally_gateway_rules = (
			"exclusiveGateway - decision point: exactly ONE outgoing path is "
			"taken. Use for: if/else branches, approval decisions, re-check "
			"loops. Every exclusiveGateway with multiple outgoing flows MUST "
			"have exactly one outgoing flow marked default true and a "
			"condition field on every other outgoing flow."
		)
		genuine = "Use exclusive gateways for yes/no decisions."
		self.assertFalse(DZ._is_echo(genuine, prosally_gateway_rules))

	def test_empty_exclude_context_never_flags(self):
		self.assertFalse(DZ._is_echo(_ECHOED_CONTENT, ""))
