from __future__ import annotations

from unittest.mock import MagicMock, patch

from frappe.tests.utils import FrappeTestCase

from one_bpmn.api import process_maps

# ---------------------------------------------------------------------------
# Valid BPMN XML snippet for import_bpmn tests (needs <bpmn:process id="...">)
# ---------------------------------------------------------------------------
VALID_BPMN_XML = """\
<?xml version="1.0" encoding="UTF-8"?>
<bpmn:definitions xmlns:bpmn="http://www.omg.org/spec/BPMN/20100524/MODEL"
                  id="Definitions_1" targetNamespace="http://bpmn.io/schema/bpmn">
  <bpmn:process id="Process_1" isExecutable="true">
    <bpmn:startEvent id="Start_1" />
  </bpmn:process>
</bpmn:definitions>
"""


class TestProcessMapsApi(FrappeTestCase):
	def setUp(self):
		snapshot = patch("one_bpmn.api.versions.create_diagram_snapshot")
		snapshot.start()
		self.addCleanup(snapshot.stop)

	# ===========================================================================
	# save_process_model
	# ===========================================================================

	@patch("one_bpmn.processa_engine.maps.saving.frappe")
	def test_save_process_model_requires_name_and_xml(self, mock_frappe):
		mock_frappe.throw.side_effect = Exception("validation")
		with self.assertRaises(Exception):
			process_maps.save_process_model("", "")

	@patch("one_bpmn.processa_engine.maps.saving.frappe")
	def test_save_process_model_updates_existing_doc(self, mock_frappe):
		doc = MagicMock()
		doc.name = "MODEL-001"
		doc.version = 2
		mock_frappe.db.exists.return_value = True
		mock_frappe.get_doc.return_value = doc

		result = process_maps.save_process_model("MODEL-001", "<xml />")

		doc.check_permission.assert_called_once_with("write")
		doc.save.assert_called_once()
		assert result["name"] == "MODEL-001"

	@patch("one_bpmn.processa_engine.maps.saving.frappe")
	def test_save_process_model_creates_new_doc(self, mock_frappe):
		doc = MagicMock()
		doc.name = "MODEL-NEW"
		doc.version = 1
		mock_frappe.db.exists.return_value = False
		mock_frappe.new_doc.return_value = doc

		result = process_maps.save_process_model("MODEL-NEW", "<xml />")

		mock_frappe.new_doc.assert_called_once_with("BPMN Process Model")
		doc.check_permission.assert_called_once_with("create")
		doc.insert.assert_called_once()
		assert result["name"] == "MODEL-NEW"

	@patch("one_bpmn.processa_engine.maps.saving.frappe")
	def test_save_process_model_returns_version(self, mock_frappe):
		doc = MagicMock()
		doc.name = "MODEL-V"
		doc.version = 9
		mock_frappe.db.exists.return_value = True
		mock_frappe.get_doc.return_value = doc

		result = process_maps.save_process_model("MODEL-V", "<xml />")
		assert result["version"] == 9

	@patch("one_bpmn.processa_engine.maps.saving.frappe")
	def test_save_process_model_write_permission_checked_only_on_existing(self, mock_frappe):
		doc = MagicMock()
		doc.name = "MODEL-E"
		doc.version = 1
		mock_frappe.db.exists.return_value = True
		mock_frappe.get_doc.return_value = doc

		process_maps.save_process_model("MODEL-E", "<xml />")
		doc.check_permission.assert_called_once_with("write")

	@patch("one_bpmn.processa_engine.maps.saving.frappe")
	def test_save_process_model_insert_called_for_new(self, mock_frappe):
		doc = MagicMock()
		doc.name = "MODEL-N"
		doc.version = 1
		mock_frappe.db.exists.return_value = False
		mock_frappe.new_doc.return_value = doc

		process_maps.save_process_model("MODEL-N", "<xml />")
		doc.insert.assert_called_once()

	@patch("one_bpmn.processa_engine.maps.saving.frappe")
	def test_save_process_model_updates_xml(self, mock_frappe):
		doc = MagicMock()
		doc.name = "MODEL-XML"
		doc.version = 1
		mock_frappe.db.exists.return_value = True
		mock_frappe.get_doc.return_value = doc

		process_maps.save_process_model("MODEL-XML", "<xml id='1' />")
		assert doc.bpmn_xml == "<xml id='1' />"

	# ===========================================================================
	# import_bpmn
	# ===========================================================================

	@patch("one_bpmn.processa_engine.maps.saving.frappe")
	def test_import_bpmn_requires_payload(self, mock_frappe):
		mock_frappe.throw.side_effect = Exception("validation")
		with self.assertRaises(Exception):
			process_maps.import_bpmn("")

	@patch("one_bpmn.processa_engine.maps.saving.frappe")
	def test_import_bpmn_creates_new_model(self, mock_frappe):
		doc = MagicMock()
		doc.name = "IMPORTED"
		doc.title = "Imported"
		doc.process_id = "Process_1"
		mock_frappe.db.get_value.return_value = None  # no existing model
		mock_frappe.new_doc.return_value = doc

		result = process_maps.import_bpmn(VALID_BPMN_XML, "Imported")

		mock_frappe.new_doc.assert_called_once_with("BPMN Process Model")
		doc.check_permission.assert_called_once_with("create")
		doc.insert.assert_called_once()
		assert result["name"] == "IMPORTED"
		assert result["action"] == "created"

	@patch("one_bpmn.processa_engine.maps.saving.frappe")
	def test_import_bpmn_updates_existing_model(self, mock_frappe):
		doc = MagicMock()
		doc.name = "EXISTING"
		doc.title = "Imported"
		doc.process_id = "Process_1"
		mock_frappe.db.get_value.return_value = "EXISTING"  # existing model found
		mock_frappe.get_doc.return_value = doc

		result = process_maps.import_bpmn(VALID_BPMN_XML, "Imported")

		mock_frappe.get_doc.assert_any_call("BPMN Process Model", "EXISTING")
		doc.check_permission.assert_called_once_with("write")
		doc.save.assert_called_once()
		assert result["action"] == "updated"

	@patch("one_bpmn.processa_engine.maps.saving.frappe")
	def test_import_bpmn_passes_process_arg(self, mock_frappe):
		"""Third positional arg is 'process' (link to Process DocType), not 'description'."""
		doc = MagicMock()
		doc.name = "IMPORTED-2"
		doc.title = "Imported"
		doc.process_id = "Process_1"
		mock_frappe.db.get_value.return_value = None
		mock_frappe.new_doc.return_value = doc

		process_maps.import_bpmn(VALID_BPMN_XML, "Imported", "My Process")

		assert doc.process_name == "My Process"

	@patch("one_bpmn.processa_engine.maps.saving.frappe")
	def test_import_bpmn_preserves_title(self, mock_frappe):
		doc = MagicMock()
		doc.name = "MODEL-T"
		doc.title = "My Process"
		doc.process_id = "Process_1"
		mock_frappe.db.get_value.return_value = None
		mock_frappe.new_doc.return_value = doc

		result = process_maps.import_bpmn(VALID_BPMN_XML, "My Process")
		assert result["name"] == "MODEL-T"

	@patch("one_bpmn.processa_engine.maps.saving.frappe")
	def test_import_bpmn_returns_dict_shape(self, mock_frappe):
		doc = MagicMock()
		doc.name = "MODEL-SHAPE"
		doc.title = "Imported"
		doc.process_id = "Process_1"
		mock_frappe.db.get_value.return_value = None
		mock_frappe.new_doc.return_value = doc

		result = process_maps.import_bpmn(VALID_BPMN_XML, "Imported")
		assert set(result.keys()) == {"name", "model_name", "process_id", "action", "compiled", "warnings"}

	# ===========================================================================
	# get / list / delete (guarded by hasattr - kept as-is)
	# ===========================================================================

	@patch("one_bpmn.api.process_maps.frappe")
	def test_get_all_process_models_uses_frappe_list(self, mock_frappe):
		mock_frappe.get_all.return_value = [{"name": "MODEL-1"}]
		if hasattr(process_maps, "get_all_process_models"):
			result = process_maps.get_all_process_models()
			assert result == [{"name": "MODEL-1"}]

	@patch("one_bpmn.processa_engine.maps.listing.frappe")
	def test_get_process_model_requires_read_permission(self, mock_frappe):
		doc = MagicMock()
		mock_frappe.get_doc.return_value = doc
		if hasattr(process_maps, "get_process_model"):
			process_maps.get_process_model("MODEL-1")
			doc.check_permission.assert_called_once_with("read")

	@patch("one_bpmn.processa_engine.maps.listing.frappe")
	def test_get_process_model_returns_owning_process_name(self, mock_frappe):
		doc = MagicMock()
		doc.process_name = "Dev Agent"
		doc.bpmn_xml = ""
		mock_frappe.get_doc.return_value = doc
		result = process_maps.get_process_model("MODEL-1")
		assert result["process_name"] == "Dev Agent"

	@patch("one_bpmn.api.process_maps.frappe")
	def test_delete_process_model_calls_delete(self, mock_frappe):
		doc = MagicMock()
		mock_frappe.get_doc.return_value = doc
		if hasattr(process_maps, "delete_process_model"):
			process_maps.delete_process_model("MODEL-1")
			doc.delete.assert_called_once()

	@patch("one_bpmn.processa_engine.maps.saving.frappe")
	def test_import_bpmn_uses_new_doc_path(self, mock_frappe):
		doc = MagicMock()
		doc.name = "MODEL-I"
		doc.title = "Imported"
		doc.process_id = "Process_1"
		mock_frappe.db.get_value.return_value = None
		mock_frappe.new_doc.return_value = doc

		process_maps.import_bpmn(VALID_BPMN_XML, "Imported")
		mock_frappe.new_doc.assert_called_once_with("BPMN Process Model")
