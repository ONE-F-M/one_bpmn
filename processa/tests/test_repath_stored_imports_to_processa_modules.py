from frappe.tests.utils import FrappeTestCase

from processa.patches.v1_0.rename_stored_one_bpmn_paths import renamed
from processa.patches.v1_0.repath_stored_imports_to_processa_modules import repath


def migrated(text: str) -> str:
	return repath(renamed(text))


class TestRepathStoredImports(FrappeTestCase):
	def test_moved_module_keeps_the_names(self):
		self.assertEqual(
			migrated("from one_bpmn.agents.turn_state import get_turn, update_turn"),
			"from processa.processa_engine.agent_runtime.turn_state import get_turn, update_turn",
		)

	def test_split_module_gives_one_line_per_new_module_at_the_same_indent(self):
		script = "def run():\n    from one_bpmn.agents.logix_debug import debug_inputs, run_debug_stage\n    return 1"
		self.assertEqual(
			migrated(script),
			"def run():\n"
			"    from processa.ai_agent_registry.definitions.logix.helpers import debug_inputs\n"
			"    from processa.ai_agent_registry.definitions.logix.tools import run_debug_stage\n"
			"    return 1",
		)

	def test_submodule_import_keeps_the_bound_name(self):
		self.assertEqual(
			migrated("from one_bpmn.one_bpmn.connectors import http_ops, manifest"),
			"from processa.processa_connectors.operations import http as http_ops\n"
			"from processa.processa_connectors import manifest",
		)

	def test_dotted_path_in_a_string(self):
		self.assertEqual(
			migrated('frappe.enqueue("one_bpmn.api.instance_api.send_message")'),
			'frappe.enqueue("processa.api.instances.send_message")',
		)

	def test_import_inside_map_xml_uses_the_xml_newline(self):
		xml = "x&#10;    from one_bpmn.agents.logix_debug import debug_inputs, run_debug_stage&#10;y"
		self.assertEqual(
			migrated(xml),
			"x&#10;    from processa.ai_agent_registry.definitions.logix.helpers import debug_inputs"
			"&#10;    from processa.ai_agent_registry.definitions.logix.tools import run_debug_stage&#10;y",
		)

	def test_bare_mention_in_a_comment(self):
		self.assertEqual(
			migrated("# reads come from one_bpmn.agents.codebase_index, because"),
			"# reads come from processa.ai_agent_registry.definitions.lucrusher.tools, because",
		)

	def test_patch_name_that_keeps_one_bpmn_is_left_alone(self):
		self.assertEqual(renamed("processa.patches.v1_0.delete_one_bpmn_module"), "processa.patches.v1_0.delete_one_bpmn_module")

	def test_unrelated_import_is_unchanged(self):
		self.assertEqual(migrated("from frappe.utils import cint"), "from frappe.utils import cint")
