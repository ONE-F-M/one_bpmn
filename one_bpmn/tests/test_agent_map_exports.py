# Copyright (c) 2026, one-fm and contributors
"""The committed agent map exports are well formed, complete and free of credentials."""

from __future__ import annotations

import json
import os
import re

import frappe
from frappe.tests.utils import FrappeTestCase
from lxml import etree

SLUGS = ("orchestrator_agent", "bug_agent", "bug_planner", "bug_programmer", "bug_reviewer")
SPIFF = "http://spiffworkflow.org/bpmn/schema/1.0/core"
BPMN = "http://www.omg.org/spec/BPMN/20100524/MODEL"
SECRET = re.compile(r"(ghp_|github_pat_|gho_|sk-ant-|AKIA[0-9A-Z]{12}|-----BEGIN [A-Z ]*PRIVATE KEY)")


def _path(name: str) -> str:
	return os.path.join(frappe.get_app_path("one_bpmn"), "exports", name)


def _read(name: str) -> str:
	with open(_path(name), encoding="utf-8") as handle:
		return handle.read()


class TestAgentMapExports(FrappeTestCase):
	def test_each_diagram_is_one_executable_process(self):
		for slug in SLUGS:
			root = etree.fromstring(_read(f"{slug}.bpmn").strip().encode("utf-8"))
			processes = root.findall(f"{{{BPMN}}}process")
			self.assertEqual(len(processes), 1, slug)
			self.assertEqual(processes[0].get("isExecutable"), "true", slug)

	def test_every_script_a_diagram_names_is_in_its_bundle(self):
		for slug in SLUGS:
			root = etree.fromstring(_read(f"{slug}.bpmn").strip().encode("utf-8"))
			named = {e.get(f"{{{SPIFF}}}serverScript") for e in root.iter() if e.get(f"{{{SPIFF}}}serverScript")}
			bundled = {s["name"] for s in json.loads(_read(f"{slug}_config.json"))["server_scripts"]}
			self.assertFalse(named - bundled, (slug, sorted(named - bundled)))

	def test_the_counts_match_the_bundle(self):
		for slug in SLUGS:
			bundle = json.loads(_read(f"{slug}_config.json"))
			self.assertEqual(bundle["counts"]["server_scripts"], len(bundle["server_scripts"]), slug)
			self.assertEqual(bundle["export_metadata"]["version"], "1.0", slug)

	def test_no_credential_is_committed(self):
		for slug in SLUGS:
			for name in (f"{slug}.bpmn", f"{slug}_config.json"):
				self.assertIsNone(SECRET.search(_read(name)), name)
