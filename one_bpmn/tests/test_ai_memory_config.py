# Copyright (c) 2026, one-fm and contributors
# Memory config: the AI Agent modal's spiffworkflow:aiMemory* attributes are
# lifted into the compiled spec by the generic service-task extraction.

from __future__ import annotations

from frappe.tests.utils import FrappeTestCase

from one_bpmn.api.compilation import _extract_service_task_config

MEMORY_XML = """<?xml version="1.0" encoding="UTF-8"?>
<bpmn:definitions xmlns:bpmn="http://www.omg.org/spec/BPMN/20100524/MODEL"
    xmlns:spiffworkflow="http://spiffworkflow.org/bpmn/schema/1.0/core"
    id="Defs_Memory" targetNamespace="http://bpmn.io/schema/bpmn">
  <bpmn:process id="Process_Memory" isExecutable="true">
    <bpmn:serviceTask id="ai_task" name="AI Agent Task"
        spiffworkflow:serviceType="ai_agent"
        spiffworkflow:aiConversationStore="document_store"
        spiffworkflow:aiContextMaxMessages="20"
        spiffworkflow:aiLongTermMemory="true"
        spiffworkflow:aiMemoryScope="Entity"
        spiffworkflow:aiMemoryAutoWrite="true" />
  </bpmn:process>
</bpmn:definitions>
"""

# Same task with long-term memory off and no scope/auto-write attributes —
# mirrors what the modal writes when the designer leaves memory disabled.
MEMORY_OFF_XML = """<?xml version="1.0" encoding="UTF-8"?>
<bpmn:definitions xmlns:bpmn="http://www.omg.org/spec/BPMN/20100524/MODEL"
    xmlns:spiffworkflow="http://spiffworkflow.org/bpmn/schema/1.0/core"
    id="Defs_MemoryOff" targetNamespace="http://bpmn.io/schema/bpmn">
  <bpmn:process id="Process_MemoryOff" isExecutable="true">
    <bpmn:serviceTask id="ai_task" name="AI Agent Task"
        spiffworkflow:serviceType="ai_agent"
        spiffworkflow:aiConversationStore="process_variable"
        spiffworkflow:aiContextMaxMessages="20" />
  </bpmn:process>
</bpmn:definitions>
"""


class TestAIMemoryConfig(FrappeTestCase):
	def test_memory_attributes_lifted_into_spec(self):
		cfg = _extract_service_task_config(MEMORY_XML)["ai_task"]
		self.assertEqual(cfg["aiConversationStore"], "document_store")
		self.assertEqual(cfg["aiContextMaxMessages"], "20")
		self.assertEqual(cfg["aiLongTermMemory"], "true")
		self.assertEqual(cfg["aiMemoryScope"], "Entity")
		self.assertEqual(cfg["aiMemoryAutoWrite"], "true")

	def test_memory_off_omits_scope_and_autowrite(self):
		cfg = _extract_service_task_config(MEMORY_OFF_XML)["ai_task"]
		# Store + window still present; scope/auto-write absent so the
		# dispatcher falls back to its safe defaults (long-term memory off).
		self.assertEqual(cfg["aiConversationStore"], "process_variable")
		self.assertEqual(cfg["aiContextMaxMessages"], "20")
		self.assertNotIn("aiLongTermMemory", cfg)
		self.assertNotIn("aiMemoryScope", cfg)
		self.assertNotIn("aiMemoryAutoWrite", cfg)
