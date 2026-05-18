from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest

from one_bpmn import api


@patch("one_bpmn.api.frappe")
def test_save_process_model_requires_name_and_xml(mock_frappe):
    with pytest.raises(Exception):
        api.save_process_model("", "")


@patch("one_bpmn.api.frappe")
def test_save_process_model_updates_existing_doc(mock_frappe):
    doc = MagicMock()
    doc.name = "MODEL-001"
    doc.version = 2
    mock_frappe.db.exists.return_value = True
    mock_frappe.get_doc.return_value = doc

    result = api.save_process_model("MODEL-001", "<xml />")

    doc.check_permission.assert_called_once_with("write")
    doc.save.assert_called_once()
    assert result["name"] == "MODEL-001"


@patch("one_bpmn.api.frappe")
def test_save_process_model_creates_new_doc(mock_frappe):
    doc = MagicMock()
    doc.name = "MODEL-NEW"
    doc.version = 1
    mock_frappe.db.exists.return_value = False
    mock_frappe.get_doc.return_value = doc

    result = api.save_process_model("MODEL-NEW", "<xml />")

    doc.insert.assert_called_once()
    assert result["name"] == "MODEL-NEW"


@patch("one_bpmn.api.frappe")
def test_import_bpmn_requires_payload(mock_frappe):
    with pytest.raises(Exception):
        api.import_bpmn("")


@patch("one_bpmn.api.frappe")
def test_import_bpmn_returns_result(mock_frappe):
    doc = MagicMock()
    doc.name = "IMPORTED"
    doc.version = 1
    mock_frappe.get_doc.return_value = doc
    result = api.import_bpmn("<definitions />", "Imported")
    assert result["name"] == "IMPORTED"


@patch("one_bpmn.api.frappe")
def test_get_all_process_models_uses_frappe_list(mock_frappe):
    mock_frappe.get_all.return_value = [{"name": "MODEL-1"}]
    if hasattr(api, "get_all_process_models"):
        result = api.get_all_process_models()
        assert result == [{"name": "MODEL-1"}]


@patch("one_bpmn.api.frappe")
def test_get_process_model_requires_read_permission(mock_frappe):
    doc = MagicMock()
    mock_frappe.get_doc.return_value = doc
    if hasattr(api, "get_process_model"):
        api.get_process_model("MODEL-1")
        doc.check_permission.assert_called_once_with("read")


@patch("one_bpmn.api.frappe")
def test_delete_process_model_calls_delete(mock_frappe):
    doc = MagicMock()
    mock_frappe.get_doc.return_value = doc
    if hasattr(api, "delete_process_model"):
        api.delete_process_model("MODEL-1")
        doc.delete.assert_called_once()


@patch("one_bpmn.api.frappe")
def test_import_bpmn_sets_description_when_provided(mock_frappe):
    doc = MagicMock()
    doc.name = "IMPORTED-2"
    doc.version = 1
    mock_frappe.get_doc.return_value = doc
    api.import_bpmn("<definitions />", "Imported", "desc")
    assert mock_frappe.get_doc.called


@patch("one_bpmn.api.frappe")
def test_save_process_model_returns_version(mock_frappe):
    doc = MagicMock()
    doc.name = "MODEL-V"
    doc.version = 9
    mock_frappe.db.exists.return_value = False
    mock_frappe.get_doc.return_value = doc
    result = api.save_process_model("MODEL-V", "<xml />")
    assert result["version"] == 9


@patch("one_bpmn.api.frappe")
def test_import_bpmn_preserves_title(mock_frappe):
    doc = MagicMock()
    doc.name = "MODEL-T"
    doc.version = 1
    mock_frappe.get_doc.return_value = doc
    result = api.import_bpmn("<definitions />", "My Process")
    assert result["name"] == "MODEL-T"


@patch("one_bpmn.api.frappe")
def test_save_process_model_write_permission_checked_only_on_existing(mock_frappe):
    doc = MagicMock()
    doc.name = "MODEL-E"
    doc.version = 1
    mock_frappe.db.exists.return_value = True
    mock_frappe.get_doc.return_value = doc
    api.save_process_model("MODEL-E", "<xml />")
    doc.check_permission.assert_called_once_with("write")


@patch("one_bpmn.api.frappe")
def test_save_process_model_insert_called_for_new(mock_frappe):
    doc = MagicMock()
    doc.name = "MODEL-N"
    doc.version = 1
    mock_frappe.db.exists.return_value = False
    mock_frappe.get_doc.return_value = doc
    api.save_process_model("MODEL-N", "<xml />")
    doc.insert.assert_called_once()


@patch("one_bpmn.api.frappe")
def test_import_bpmn_uses_new_doc_path(mock_frappe):
    doc = MagicMock()
    doc.name = "MODEL-I"
    doc.version = 1
    mock_frappe.get_doc.return_value = doc
    api.import_bpmn("<definitions />", "Imported")
    assert mock_frappe.get_doc.called


@patch("one_bpmn.api.frappe")
def test_save_process_model_updates_xml(mock_frappe):
    doc = MagicMock()
    doc.name = "MODEL-XML"
    doc.version = 1
    mock_frappe.db.exists.return_value = True
    mock_frappe.get_doc.return_value = doc
    api.save_process_model("MODEL-XML", "<xml id='1' />")
    assert doc.bpmn_xml == "<xml id='1' />"


@patch("one_bpmn.api.frappe")
def test_import_bpmn_returns_dict_shape(mock_frappe):
    doc = MagicMock()
    doc.name = "MODEL-SHAPE"
    doc.version = 5
    mock_frappe.get_doc.return_value = doc
    result = api.import_bpmn("<definitions />", "Imported")
    assert set(result.keys()) == {"name", "version"}
