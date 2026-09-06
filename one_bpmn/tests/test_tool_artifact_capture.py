# Copyright (c) 2026, one-fm and contributors
"""What a tool actually produced, kept where the run can be reviewed.

A generating tool — write_script, write_schema, generate_process — hands the
model a short preview of its work, because the whole script or schema costs more
context than it is worth. The preview was then the only trace: the tool-call row
held 400 characters cut mid-word and nothing else, so the agent's real output
could not be reviewed, evaluated or audited afterwards.

The tool now records the artifact and takes its preview back from the same call.
Oversized artifacts and argument blobs go to a private File on the run rather
than inline, so the record stays complete without a generated script sitting in
every list query.

Run with:
    bench --site SITE run-tests --app one_bpmn --module one_bpmn.tests.test_tool_artifact_capture
"""

from __future__ import annotations

import frappe
from frappe.tests.utils import FrappeTestCase

from one_bpmn.agents.executor import ExecutorConfig
from one_bpmn.agents.observability import (
	_MAX_INLINE_CHARS,
	clear_tool_artifacts,
	create_ai_run,
	pop_tool_artifact,
	record_ai_step,
	record_tool_artifact,
)

SCRIPT = "def handler(doc):\n    return frappe.get_doc('Task', doc.task).as_dict()\n"


class TestToolArtifactCapture(FrappeTestCase):
	def setUp(self):
		super().setUp()
		clear_tool_artifacts()
		self.addCleanup(clear_tool_artifacts)

	# -- helpers --------------------------------------------------------

	def _run(self):
		model = frappe.get_doc({
			"doctype": "BPMN Process Model",
			"title": f"artifact-test-{frappe.generate_hash(length=8)}",
			"process_id": f"artifact_test_{frappe.generate_hash(length=8)}",
			"version": 1,
		})
		model.flags.skip_editability_check = True
		model.flags.skip_script_security_check = True
		model.insert(ignore_permissions=True)
		instance = frappe.get_doc({
			"doctype": "BPMN Process Instance",
			"process_model": model.name,
			"status": "Active",
		}).insert(ignore_permissions=True)
		config = ExecutorConfig(
			backend="direct_api", provider_name="", model="gpt-4o",
			system_prompt="s", user_prompt="u",
		)
		return create_ai_run(frappe._dict({"name": instance.name}), "A1", "task", config)

	def _call(self, name="write_script", **kwargs):
		call = {"name": name, "tool_source": "diagram_task", "result": "ok", "status": "Success"}
		call.update(kwargs)
		return call

	def _row(self, step, index=0):
		return step.tool_calls[index]

	# -- the preview ----------------------------------------------------

	def test_a_short_artifact_is_its_own_preview(self):
		self.assertEqual(record_tool_artifact("write_script", SCRIPT), SCRIPT)

	def test_a_long_preview_ends_on_a_word_boundary(self):
		"""The reported symptom: a preview cut at exactly 400 characters left a
		half-finished token on screen and in the transcript."""
		artifact = "alpha bravo charlie delta echo foxtrot golf hotel " * 40
		preview = record_tool_artifact("write_script", artifact, 400)

		self.assertLessEqual(len(preview), 401)
		self.assertTrue(preview.endswith("…"))
		self.assertTrue(artifact.startswith(preview[:-1]))
		# The last whole word survives intact — nothing is half a word.
		self.assertIn(preview[:-1].split()[-1], artifact.split())

	def test_nothing_is_recorded_for_an_empty_artifact(self):
		self.assertEqual(record_tool_artifact("write_script", ""), "")
		self.assertEqual(pop_tool_artifact("write_script"), "")

	# -- the stash ------------------------------------------------------

	def test_two_calls_to_one_tool_keep_both_artifacts_in_order(self):
		"""A turn can call the same tool twice; the second must not overwrite
		the first, or one of the two scripts is lost."""
		record_tool_artifact("write_script", "first")
		record_tool_artifact("write_script", "second")

		self.assertEqual(pop_tool_artifact("write_script"), "first")
		self.assertEqual(pop_tool_artifact("write_script"), "second")

	def test_leftovers_are_dropped_at_the_start_of_a_loop(self):
		"""frappe.flags outlive the call. An artifact nobody recorded must not
		attach itself to a later run's tool call."""
		record_tool_artifact("write_script", SCRIPT)
		clear_tool_artifacts()
		self.assertEqual(pop_tool_artifact("write_script"), "")

	# -- what reaches the row -------------------------------------------

	def test_the_artifact_reaches_the_tool_call_row(self):
		run = self._run()
		record_tool_artifact("write_script", SCRIPT)

		step = record_ai_step(run, 1, "tool", "", tool_calls=[self._call()])

		self.assertEqual(self._row(step).tool_artifact, SCRIPT)

	def test_the_artifact_goes_to_the_call_that_produced_it(self):
		run = self._run()
		record_tool_artifact("write_schema", "the schema")
		record_tool_artifact("write_script", "the script")

		step = record_ai_step(run, 1, "tool", "", tool_calls=[
			self._call("write_script"), self._call("write_schema"),
		])

		self.assertEqual(self._row(step, 0).tool_artifact, "the script")
		self.assertEqual(self._row(step, 1).tool_artifact, "the schema")

	def test_a_tool_that_produced_nothing_records_nothing(self):
		run = self._run()
		step = record_ai_step(run, 1, "tool", "", tool_calls=[self._call("classify_intent")])

		self.assertFalse(self._row(step).tool_artifact)
		self.assertFalse(self._row(step).artifact_file)

	# -- arguments ------------------------------------------------------

	def test_a_call_with_no_arguments_says_so(self):
		"""The shape tools on the chat maps declare no parameters, so the model
		sends nothing. Recording {} says that; a blank cell reads as a capture
		failure, which is how this looked for months."""
		run = self._run()
		step = record_ai_step(run, 1, "tool", "", tool_calls=[self._call(arguments={})])

		self.assertEqual(self._row(step).tool_args, {})

	def test_arguments_are_stored_as_sent(self):
		run = self._run()
		args = {"doctype": "Task", "fields": ["subject", "status"]}
		step = record_ai_step(run, 1, "tool", "", tool_calls=[self._call(arguments=args)])

		self.assertEqual(self._row(step).tool_args, args)

	# -- the size guardrail ---------------------------------------------

	def test_an_oversized_artifact_is_written_to_a_file_on_the_run(self):
		run = self._run()
		artifact = "x" * (_MAX_INLINE_CHARS + 1)
		record_tool_artifact("write_script", artifact)

		step = record_ai_step(run, 1, "tool", "", tool_calls=[self._call()])
		row = self._row(step)

		self.assertFalse(row.tool_artifact, "the row must not carry it inline")
		self.assertTrue(row.artifact_file)
		attached = frappe.get_doc("File", row.artifact_file)
		self.assertEqual(attached.attached_to_doctype, "AI Agent Run")
		self.assertEqual(attached.attached_to_name, run.name)
		self.assertEqual(attached.get_content(), artifact)

	def test_an_oversized_argument_blob_leaves_a_pointer_behind(self):
		"""The arguments column stays queryable, and still says where the rest
		went — an argument dropped silently is the bug this story is about."""
		run = self._run()
		args = {"body": "y" * (_MAX_INLINE_CHARS + 1)}

		step = record_ai_step(run, 1, "tool", "", tool_calls=[self._call(arguments=args)])
		stored = self._row(step).tool_args

		self.assertTrue(stored.get("offloaded"))
		self.assertGreater(stored.get("chars"), _MAX_INLINE_CHARS)
		self.assertTrue(frappe.db.exists("File", stored.get("file")))


class TestAiShapeArtifacts(FrappeTestCase):
	"""A tool shape that is a model call, not a script, records its answer too.

	Logix's write_script is an AI Agent Task on the map — there is no Server
	Script to hand the draft over, so the shape runner does it. Without this the
	generated script lived only inside the tool result's JSON blob.
	"""

	def setUp(self):
		super().setUp()
		clear_tool_artifacts()
		self.addCleanup(clear_tool_artifacts)

	def _instance(self, produced):
		instance = frappe._dict(
			context_doctype="", context_docname="",
			_service_task_extensions={},
		)

		def dispatch(task, task_cfg):
			task.data.update(produced)

		instance._dispatch_service_task = dispatch
		return instance

	def test_the_shapes_answer_is_recorded_as_its_artifact(self):
		from one_bpmn.agents.shape_tools import execute_shape

		instance = self._instance({"write_script_output": SCRIPT})
		execute_shape(instance, "write_script", {
			"serviceType": "ai_agent", "aiAgentConfig": "x", "aiUserPrompt": "p",
		}, {})

		self.assertEqual(pop_tool_artifact("write_script"), SCRIPT)

	def test_a_script_shape_is_left_to_record_its_own(self):
		"""Script Task shapes call record_tool_artifact themselves, with the
		draft rather than the whole result dict — recording here as well would
		file the wrong thing twice."""
		from one_bpmn.agents.shape_tools import execute_shape

		instance = self._instance({})
		instance._service_task_extensions = {}
		execute_shape(instance, "classify_intent", {"serverScript": "_no_such_script_"}, {})

		self.assertEqual(pop_tool_artifact("classify_intent"), "")
