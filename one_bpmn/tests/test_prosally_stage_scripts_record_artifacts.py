# Copyright (c) 2026, one-fm and contributors
"""The stage scripts inline_prosally_tool_scripts writes get their record_tool_artifact call back."""

from unittest.mock import patch

from frappe.tests.utils import FrappeTestCase

from one_bpmn.one_bpmn.patches.v1_0 import inline_prosally_tool_scripts as inline
from one_bpmn.one_bpmn.patches.v1_0 import prosally_stage_scripts_record_artifacts as artifacts_patch
from one_bpmn.one_bpmn.patches.v1_0 import record_tool_artifacts

BODIES = {"generate": inline.GENERATE, "modify": inline.MODIFY}


def _run(bodies):
	"""Run the patch against script bodies held in memory; return what it wrote per script."""
	store = dict(bodies)
	written = {}

	def find(doctype, filters, fieldname="name", *args, **kwargs):
		if fieldname == "script":
			return store[filters]
		return "generate" if "Generate" in filters["name"][1] else "modify"

	def write(doctype, name, fieldname, value, **kwargs):
		store[name] = written[name] = value

	db = record_tool_artifacts.frappe.db
	with patch.object(db, "get_value", side_effect=find), patch.object(db, "exists", return_value=True), patch.object(
		db, "set_value", side_effect=write
	), patch.object(record_tool_artifacts.frappe, "log_error"):
		artifacts_patch.execute()
	return written, store


class TestStageScriptsRecordArtifacts(FrappeTestCase):
	def test_both_inline_bodies_get_the_call_and_still_compile(self):
		written, _ = _run(BODIES)
		self.assertEqual(sorted(written), ["generate", "modify"])
		for name, script in written.items():
			self.assertIn("record_tool_artifact(bpmn_id", script, name)
			compile(script, name, "exec")

	def test_the_modify_call_records_the_merged_xml(self):
		written, _ = _run(BODIES)
		self.assertIn('"bpmn_xml": merged_xml', written["modify"])
		self.assertIn('"bpmn_xml": best_xml', written["generate"])

	def test_a_second_run_changes_nothing(self):
		_, once = _run(BODIES)
		written, _ = _run(once)
		self.assertEqual(written, {})
