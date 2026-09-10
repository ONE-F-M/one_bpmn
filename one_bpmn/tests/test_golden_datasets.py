# Copyright (c) 2026, one-fm and contributors
"""Case types, and the golden dataset an agent or skill carries.

The cases already existed; what is tested here is what makes a set of them an
artifact — that authoring can say what a case measures and which skill it
belongs to, that a version records what the dataset WAS, and that moving a
dataset to another site does not have it claim a history it never had.
"""

from __future__ import annotations

import json

import frappe
from frappe.tests.utils import FrappeTestCase

from one_bpmn.agents._eval_test_factories import make_eval_case, make_eval_suite
from one_bpmn.api.eval_api import create_eval_case, get_eval_case, update_eval_case
from one_bpmn.api.golden_dataset import (
	CASE_TYPES,
	DATASET_MINIMUM,
	dataset_readiness,
	export_dataset,
	import_dataset,
	snapshot_dataset,
)


def _skill(name_hint="dataset"):
	skill = frappe.get_doc({
		"doctype": "AI Skill",
		"skill_name": f"_Test {name_hint} skill " + frappe.generate_hash(length=6),
		"status": "Draft",
		"tier": "Draft-Only",
		"description": "Use this skill when testing datasets. Do NOT use it for anything real.",
		"body": "# test skill",
	})
	skill.flags.ignore_mandatory = True
	skill.flags.ignore_links = True
	return skill.insert(ignore_permissions=True)


class TestCaseTypes(FrappeTestCase):
	def setUp(self):
		frappe.set_user("Administrator")
		self.suite = make_eval_suite(process_model=None, title="_Test types " + frappe.generate_hash(length=6))

	def test_the_seven_types_are_what_the_field_offers(self):
		options = frappe.db.get_value(
			"DocField", {"parent": "AI Eval Case", "fieldname": "case_type"}, "options"
		)
		self.assertEqual(tuple(options.split("\n")), CASE_TYPES)

	def test_a_case_is_an_output_case_unless_it_says_otherwise(self):
		name = create_eval_case(suite=self.suite.name, title="plain", input_user_prompt="hi")
		self.assertEqual(frappe.db.get_value("AI Eval Case", name, "case_type"), "Output")

	def test_authoring_can_set_the_type_and_the_skill(self):
		skill = _skill()
		name = create_eval_case(
			suite=self.suite.name, title="fires when it should", input_user_prompt="do the thing",
			case_type="Trigger Positive", target_skill=skill.name,
		)
		case = get_eval_case(name)
		self.assertEqual(case["case_type"], "Trigger Positive")
		self.assertEqual(case["target_skill"], skill.name)

	def test_a_type_nobody_reports_on_is_refused(self):
		"""A typo would file the case under a category no report looks at."""
		with self.assertRaises(frappe.ValidationError):
			create_eval_case(suite=self.suite.name, title="typo", input_user_prompt="x",
							 case_type="Trajectry")

	def test_a_skill_that_does_not_exist_is_refused(self):
		with self.assertRaises(frappe.ValidationError):
			create_eval_case(suite=self.suite.name, title="ghost", input_user_prompt="x",
							 target_skill="No Such Skill")

	def test_the_type_and_skill_can_be_changed_later(self):
		skill = _skill()
		name = create_eval_case(suite=self.suite.name, title="edit me", input_user_prompt="x")
		update_eval_case(name=name, case_type="Memory", target_skill=skill.name)
		case = get_eval_case(name)
		self.assertEqual((case["case_type"], case["target_skill"]), ("Memory", skill.name))

	def test_an_empty_skill_clears_the_link(self):
		skill = _skill()
		name = create_eval_case(suite=self.suite.name, title="unlink me", input_user_prompt="x",
								target_skill=skill.name)
		update_eval_case(name=name, target_skill="")
		self.assertFalse(get_eval_case(name)["target_skill"])

	def test_provenance_is_readable_but_not_authorable(self):
		"""Where a case came from is written by what promoted it."""
		name = create_eval_case(suite=self.suite.name, title="provenance", input_user_prompt="x")
		case = get_eval_case(name)
		for field in ("source_feedback", "source_security_event", "source_run"):
			self.assertIn(field, case)
		self.assertFalse(case["source_feedback"])


class TestReadiness(FrappeTestCase):
	def setUp(self):
		frappe.set_user("Administrator")
		self.suite = make_eval_suite(process_model=None, title="_Test readiness " + frappe.generate_hash(length=6))
		self.agent = self.suite.agent_configuration

	def test_it_counts_what_the_agent_has_and_what_it_is_short(self):
		for index in range(3):
			make_eval_case(suite=self.suite.name, title=f"case {index}")
		out = dataset_readiness(agent=self.agent)
		self.assertEqual(out["cases"], 3)
		self.assertEqual(out["minimum"], DATASET_MINIMUM)
		self.assertEqual(out["short_by"], DATASET_MINIMUM - 3)

	def test_it_says_which_types_are_absent(self):
		make_eval_case(suite=self.suite.name, title="an output case")
		out = dataset_readiness(agent=self.agent)
		self.assertEqual(out["by_type"]["Output"], 1)
		self.assertIn("Adversarial", out["missing_types"])
		self.assertNotIn("Output", out["missing_types"])

	def test_a_skill_dataset_is_the_cases_naming_it(self):
		"""A skill's trigger cases usually live in the agent's suite."""
		skill = _skill()
		case = make_eval_case(suite=self.suite.name, title="skill case")
		frappe.db.set_value("AI Eval Case", case.name, "target_skill", skill.name)
		out = dataset_readiness(skill=skill.name)
		self.assertEqual(out["cases"], 1)
		self.assertEqual(out["subject_type"], "Skill")

	def test_naming_both_or_neither_is_refused(self):
		with self.assertRaises(frappe.ValidationError):
			dataset_readiness()
		with self.assertRaises(frappe.ValidationError):
			dataset_readiness(agent=self.agent, skill="anything")

	def test_readiness_does_not_block_anything(self):
		"""It reports. The only hard case-count bar is a skill going
		Action-Allowed — a go-live bar at 20 would strand nearly every agent."""
		out = dataset_readiness(agent=self.agent)
		self.assertIn("short_by", out)
		self.assertNotIn("blocked", out)


class TestVersions(FrappeTestCase):
	def setUp(self):
		frappe.set_user("Administrator")
		self.suite = make_eval_suite(process_model=None, title="_Test versions " + frappe.generate_hash(length=6))
		self.agent = self.suite.agent_configuration
		self.case = make_eval_case(suite=self.suite.name, title="the one case")

	def test_a_snapshot_records_the_cases_as_they_stand(self):
		out = snapshot_dataset(agent=self.agent, notes="before the rewrite")
		doc = frappe.get_doc("AI Golden Dataset Version", out["name"])
		self.assertEqual(doc.version, 1)
		self.assertEqual(doc.case_count, 1)
		self.assertEqual(json.loads(doc.cases)[0]["title"], "the one case")
		self.assertIn("Output: 1", doc.type_breakdown)
		self.assertEqual(doc.label, f"{self.agent} v1")

	def test_versions_count_up_per_subject(self):
		snapshot_dataset(agent=self.agent)
		second = snapshot_dataset(agent=self.agent)
		self.assertEqual(second["version"], 2)

	def test_a_snapshot_stays_put_when_the_cases_move_on(self):
		snapshot_dataset(agent=self.agent)
		make_eval_case(suite=self.suite.name, title="added afterwards")
		out = dataset_readiness(agent=self.agent)
		self.assertEqual(out["cases"], 2)
		self.assertEqual(out["latest_version"]["case_count"], 1)
		self.assertTrue(out["drifted_from_version"], "the version is about a dataset that has since changed")

	def test_there_is_nothing_to_version_without_cases(self):
		empty = make_eval_suite(process_model=None, title="_Test empty " + frappe.generate_hash(length=6))
		with self.assertRaises(frappe.ValidationError):
			snapshot_dataset(agent=empty.agent_configuration)

	def test_the_newest_version_cannot_be_deleted(self):
		"""Deleting it would let the next snapshot reuse its number."""
		first = snapshot_dataset(agent=self.agent)
		with self.assertRaises(frappe.ValidationError):
			frappe.delete_doc("AI Golden Dataset Version", first["name"])


class TestExportImport(FrappeTestCase):
	def setUp(self):
		frappe.set_user("Administrator")
		self.suite = make_eval_suite(process_model=None, title="_Test export " + frappe.generate_hash(length=6))
		self.agent = self.suite.agent_configuration
		case = make_eval_case(suite=self.suite.name, title="carried across",
							  expected_output="the answer")
		case.reload()
		case.case_type = "Trajectory"
		case.set("assertions", [{"assertion_type": "contains", "value": "answer"}])
		case.set("expected_tool_calls", [{"call_order": 1, "tool_name": "read_file",
										  "argument": "path", "matcher": "contains",
										  "expected_value": "README"}])
		case.flags.ignore_mandatory = True
		case.save(ignore_permissions=True)

	def test_an_export_carries_the_case_its_assertions_and_its_calls(self):
		payload = export_dataset(agent=self.agent)
		self.assertEqual(payload["format"], "one_bpmn.golden_dataset.v1")
		case = payload["cases"][0]
		self.assertEqual(case["case_type"], "Trajectory")
		self.assertEqual(case["assertions"][0]["value"], "answer")
		self.assertEqual(case["expected_tool_calls"][0]["tool_name"], "read_file")

	def test_an_export_does_not_carry_provenance(self):
		"""A dataset moved to another site must not point at that site's runs."""
		payload = export_dataset(agent=self.agent)
		for field in ("source_run", "source_feedback", "source_security_event"):
			self.assertNotIn(field, payload["cases"][0])

	def test_importing_twice_updates_rather_than_doubles(self):
		target = make_eval_suite(process_model=None, title="_Test target " + frappe.generate_hash(length=6))
		payload = export_dataset(agent=self.agent)

		first = import_dataset(json.dumps(payload), suite=target.name)
		second = import_dataset(json.dumps(payload), suite=target.name)

		self.assertEqual(first["created"], ["carried across"])
		self.assertEqual(second["updated"], ["carried across"])
		self.assertEqual(frappe.db.count("AI Eval Case", {"suite": target.name}), 1)

	def test_an_import_reports_what_it_left_alone(self):
		target = make_eval_suite(process_model=None, title="_Test keep " + frappe.generate_hash(length=6))
		make_eval_case(suite=target.name, title="someone else's case")
		out = import_dataset(json.dumps(export_dataset(agent=self.agent)), suite=target.name)
		self.assertEqual(out["left_alone"], ["someone else's case"])
		self.assertEqual(frappe.db.count("AI Eval Case", {"suite": target.name}), 2)

	def test_a_dry_run_writes_nothing(self):
		target = make_eval_suite(process_model=None, title="_Test dry " + frappe.generate_hash(length=6))
		out = import_dataset(json.dumps(export_dataset(agent=self.agent)), suite=target.name, dry_run=1)
		self.assertEqual(out["created"], ["carried across"])
		self.assertEqual(frappe.db.count("AI Eval Case", {"suite": target.name}), 0)

	def test_a_skill_the_target_site_does_not_have_is_dropped(self):
		"""An imported dataset must not invent the skill it claims to test."""
		payload = export_dataset(agent=self.agent)
		payload["cases"][0]["target_skill"] = "A Skill That Is Not Here"
		target = make_eval_suite(process_model=None, title="_Test ghost " + frappe.generate_hash(length=6))
		import_dataset(json.dumps(payload), suite=target.name)
		name = frappe.db.get_value("AI Eval Case", {"suite": target.name}, "name")
		self.assertFalse(frappe.db.get_value("AI Eval Case", name, "target_skill"))

	def test_something_that_is_not_a_dataset_is_refused(self):
		target = make_eval_suite(process_model=None, title="_Test junk " + frappe.generate_hash(length=6))
		with self.assertRaises(frappe.ValidationError):
			import_dataset(json.dumps({"cases": []}), suite=target.name)
		with self.assertRaises(frappe.ValidationError):
			import_dataset("not json at all", suite=target.name)

	def test_a_version_can_be_exported_as_it_was(self):
		version = snapshot_dataset(agent=self.agent)
		make_eval_case(suite=self.suite.name, title="added later")
		payload = export_dataset(agent=self.agent, version=version["name"])
		self.assertEqual(payload["case_count"], 1)
		self.assertEqual(payload["version"], 1)


class TestSkillGraduation(FrappeTestCase):
	"""The dataset rule that DOES block something, and the defect that made it
	unreachable.

	Graduation looked for eval runs with status "Completed". A run is Running,
	Passed, Failed or Error — never Completed — so the query matched nothing and
	no skill could leave Draft-Only. It went unnoticed because no AI Skill
	records exist yet.
	"""

	def setUp(self):
		frappe.set_user("Administrator")
		self.skill = _skill("graduation")
		self.suite = make_eval_suite(process_model=None,
									 title="_Test grad " + frappe.generate_hash(length=6))
		for case_type in ("Trigger Positive", "Trigger Negative"):
			case = make_eval_case(suite=self.suite.name, title=f"{case_type} case")
			frappe.db.set_value("AI Eval Case", case.name,
								{"target_skill": self.skill.name, "case_type": case_type})

	def _run(self, status, passed, total):
		run = frappe.get_doc({
			"doctype": "AI Eval Run", "suite": self.suite.name, "status": status,
			"backend": "live", "started_at": frappe.utils.now_datetime(),
			"passed_cases": passed, "total_cases": total,
		})
		run.flags.ignore_mandatory = True
		run.flags.ignore_links = True
		return run.insert(ignore_permissions=True)

	def test_a_finished_run_lets_a_skill_graduate(self):
		self._run("Passed", 10, 10)
		self.skill.tier = "Read-Only"
		self.skill.save(ignore_permissions=True)
		self.assertEqual(frappe.db.get_value("AI Skill", self.skill.name, "tier"), "Read-Only")

	def test_a_failing_run_is_still_a_finished_run_and_is_judged_on_its_rate(self):
		"""Failed is not "did not happen" — it is evidence, and a bad rate is
		what should refuse the graduation."""
		self._run("Failed", 5, 10)
		self.skill.tier = "Read-Only"
		with self.assertRaises(frappe.ValidationError):
			self.skill.save(ignore_permissions=True)

	def test_no_run_at_all_still_refuses(self):
		self.skill.tier = "Read-Only"
		with self.assertRaises(frappe.ValidationError):
			self.skill.save(ignore_permissions=True)

	def test_action_allowed_still_wants_a_dataset_of_twenty(self):
		self._run("Passed", 10, 10)
		self._run("Passed", 10, 10)
		self.skill.tier = "Action-Allowed"
		with self.assertRaises(frappe.ValidationError) as caught:
			self.skill.save(ignore_permissions=True)
		self.assertIn("20+", str(caught.exception))
