# Copyright (c) 2026, one-fm and contributors
# SPIKE (semantic-memory research, AC1): can a Connector Service Task modelled
# inside an AI Agent Task's ad-hoc Tools sub-process be called by the agent as a
# tool, end to end?
#
# The chain under test:
#   1. _extract_tool_shapes      — is the connector exposed to the LLM as a tool?
#   2. _extract_service_task_config — is its config indexed, even though it is
#                                     nested inside an adHocSubProcess?
#   3. compile_shape_tools       — does it become a callable ToolSpec?
#   4. execute_shape             — does calling it reach dispatch_connector?
#   5. connectorParams Jinja     — can the LLM's OWN arguments reach the
#                                  connector's inputs (the mechanism a vector
#                                  search tool would need)?
#   6. result propagation        — does the connector's return reach the agent?
#
# Deliberately uses a throwaway registered connector rather than Google Drive so
# the test needs no credentials and no network.

from __future__ import annotations

import json

import frappe
from frappe.tests.utils import FrappeTestCase

from one_bpmn.agents.shape_tools import compile_shape_tools
from one_bpmn.api.compilation import (
	_extract_service_task_config,
	_extract_tool_shapes,
)

BPMN_NS = "http://www.omg.org/spec/BPMN/20100524/MODEL"
SPIFF_NS = "http://spiffworkflow.org/bpmn/schema/1.0/core"

# An AI Agent Task whose Tools ad-hoc sub-process contains ONE connector service
# task standing in for a vector-DB search.
XML = f"""<?xml version="1.0" encoding="UTF-8"?>
<bpmn:definitions xmlns:bpmn="{BPMN_NS}" xmlns:spiffworkflow="{SPIFF_NS}" id="Defs_1"
                  targetNamespace="http://bpmn.io/schema/bpmn">
  <bpmn:process id="Proc_1" isExecutable="true">
    <bpmn:serviceTask id="agent_task" name="Answer with memory"
        spiffworkflow:serviceType="ai_agent"
        spiffworkflow:aiToolsAdhoc="agent_tools" />
    <bpmn:adHocSubProcess id="agent_tools" name="Tools">
      <bpmn:serviceTask id="memory_lookup" name="Memory Lookup"
          spiffworkflow:serviceType="connector"
          spiffworkflow:connectorId="spike_vector"
          spiffworkflow:operation="search"
          spiffworkflow:connectorParams="{{&#34;query&#34;: &#34;{{{{ task_data.query }}}}&#34;, &#34;top_k&#34;: 3}}"
          spiffworkflow:resultVariable="memory_hits"
          spiffworkflow:aiToolParams="{{&#34;properties&#34;: {{&#34;query&#34;: {{&#34;type&#34;: &#34;string&#34;}}}}, &#34;required&#34;: [&#34;query&#34;]}}">
        <bpmn:documentation>Search long-term memory for relevant context.</bpmn:documentation>
      </bpmn:serviceTask>
    </bpmn:adHocSubProcess>
  </bpmn:process>
</bpmn:definitions>
"""

_CALLS = []


def _spike_search(params, ctx):
	"""Stand-in for a vector-DB search operation."""
	_CALLS.append(params)
	return {"chunks": [f"chunk about {params.get('query')}"], "top_k": params.get("top_k")}


class _FakeInstance:
	"""Minimal stand-in for BPMNProcessInstance: only the attributes the
	connector dispatch path actually touches."""

	def __init__(self, extensions):
		self.name = "INST-SPIKE"
		self.context_doctype = ""
		self.context_docname = ""
		self.process_model = ""
		self.initiated_by = "Administrator"
		self._service_task_extensions = extensions

	def _dispatch_service_task(self, task):
		# Same routing the real controller performs, reduced to the branch under
		# test. Reads config by bpmn_id from _service_task_extensions — which is
		# precisely the behaviour this spike needs to confirm for a NESTED shape.
		from one_bpmn.one_bpmn.doctype.bpmn_process_instance.dispatchers import dispatch_connector

		bpmn_id = task.task_spec.bpmn_id
		cfg = self._service_task_extensions.get(bpmn_id, {})
		assert cfg.get("serviceType") == "connector", f"nested shape not indexed: {cfg!r}"
		dispatch_connector(self, task, cfg, bpmn_id)
		return True


def _ensure_spike_connector():
	"""The spike's connector, configured the only way connectors exist now.

	It used to register itself with an @connector decorator; that registry is
	gone, so the operation names its handler on its row like every other one.
	"""
	if not frappe.db.exists("BPMN Connector", "spike_vector"):
		frappe.get_doc({
			"doctype": "BPMN Connector",
			"connector_id": "spike_vector",
			"label": "Spike Vector Search",
			"enabled": 1,
			"execution_type": "Python Handler",
		}).insert(ignore_permissions=True)
	if not frappe.db.exists(
		"BPMN Connector Operation", {"connector": "spike_vector", "operation_id": "search"}
	):
		op = frappe.get_doc({
			"doctype": "BPMN Connector Operation",
			"connector": "spike_vector",
			"operation_id": "search",
			"label": "Search",
			"enabled": 1,
			"execution_type": "Python Handler",
			"handler_path": "one_bpmn.tests.test_connector_as_agent_tool._spike_search",
		})
		for name in ("query", "top_k"):
			op.append("fields", {"field_name": name, "field_type": "String", "expression": 1})
		op.insert(ignore_permissions=True)
	from one_bpmn.one_bpmn.connectors.manifest import clear_manifest_cache

	clear_manifest_cache()


class TestConnectorAsAgentTool(FrappeTestCase):
	@classmethod
	def setUpClass(cls):
		super().setUpClass()
		_ensure_spike_connector()

	def setUp(self):
		_CALLS.clear()

	# ── 1. Is the connector exposed to the LLM as a tool? ────────────────────
	def test_connector_shape_is_extracted_as_a_tool(self):
		import xml.etree.ElementTree as ET

		root = ET.fromstring(XML)
		adhoc = root.find(f".//{{{BPMN_NS}}}adHocSubProcess")
		shapes = _extract_tool_shapes(adhoc, BPMN_NS, SPIFF_NS)

		self.assertEqual(len(shapes), 1)
		shape = shapes[0]
		self.assertEqual(shape["bpmn_id"], "memory_lookup")
		self.assertEqual(shape["serviceType"], "connector")
		self.assertEqual(shape["description"], "Search long-term memory for relevant context.")
		# aiToolParams must survive, or the LLM gets a zero-argument tool and can
		# never pass a search string.
		self.assertIn("query", shape["parameters"])
		self.assertEqual(shape["required"], ["query"])

	# ── 2. Is a NESTED service task's config indexed? ────────────────────────
	def test_nested_connector_config_is_indexed_by_the_compiler(self):
		cfg = _extract_service_task_config(XML)

		self.assertIn("memory_lookup", cfg, "connector inside adHocSubProcess was not indexed")
		self.assertEqual(cfg["memory_lookup"]["serviceType"], "connector")
		self.assertEqual(cfg["memory_lookup"]["connectorId"], "spike_vector")
		self.assertEqual(cfg["memory_lookup"]["operation"], "search")
		self.assertEqual(cfg["memory_lookup"]["resultVariable"], "memory_hits")

	# ── 3. Does it become a callable ToolSpec? ───────────────────────────────
	def test_shape_compiles_to_a_callable_tool(self):
		import xml.etree.ElementTree as ET

		root = ET.fromstring(XML)
		adhoc = root.find(f".//{{{BPMN_NS}}}adHocSubProcess")
		shapes = _extract_tool_shapes(adhoc, BPMN_NS, SPIFF_NS)
		instance = _FakeInstance(_extract_service_task_config(XML))

		tools = compile_shape_tools(shapes, instance)

		self.assertEqual(len(tools), 1)
		self.assertEqual(tools[0].name, "memory_lookup")
		self.assertFalse(getattr(tools[0], "human", False))

	# ── 4-6. The whole path: call it as the LLM would ────────────────────────
	def test_agent_calling_the_tool_reaches_the_connector_and_gets_results_back(self):
		import xml.etree.ElementTree as ET

		root = ET.fromstring(XML)
		adhoc = root.find(f".//{{{BPMN_NS}}}adHocSubProcess")
		shapes = _extract_tool_shapes(adhoc, BPMN_NS, SPIFF_NS)
		instance = _FakeInstance(_extract_service_task_config(XML))
		tool = compile_shape_tools(shapes, instance)[0]

		# This is the LLM invoking the tool with its own generated search string.
		raw = tool.fn(query="overdue invoice policy")
		out = json.loads(raw)

		# The connector actually ran...
		self.assertEqual(len(_CALLS), 1, "connector handler was never invoked")
		# ...and the LLM's argument reached the connector input via Jinja
		# ({{ task_data.query }}) — the mechanism a vector search tool depends on.
		self.assertEqual(_CALLS[0]["query"], "overdue invoice policy")
		self.assertEqual(_CALLS[0]["top_k"], 3)
		# ...and its return value came back to the agent under resultVariable.
		self.assertIn("memory_hits", out)
		self.assertEqual(out["memory_hits"]["chunks"], ["chunk about overdue invoice policy"])

	def test_the_connector_is_configuration_the_dispatcher_can_resolve(self):
		"""The operation is reached by the dotted path on its row — the same way
		every real connector operation is."""
		from one_bpmn.one_bpmn.connectors.manifest import get_execution_spec

		spec = get_execution_spec("spike_vector", "search")
		self.assertIsNotNone(spec, "the spike connector must be configured, not registered")
		self.assertTrue(spec.handler_path)
		self.assertTrue(callable(frappe.get_attr(spec.handler_path)))
