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


def _distill(output_text, model="test-model"):
	return DZ.distill_memories(
		output_text,
		agent="prosally",
		scope="Agent",
		scope_key="run_prosally_agent",
		provider_name="",
		backend="curatortest",
		model=model,
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
