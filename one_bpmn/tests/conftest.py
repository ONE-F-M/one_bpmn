from __future__ import annotations

from pathlib import Path
from unittest.mock import MagicMock

import pytest

try:
    import frappe
    frappe.init(site="development.local", sites_path="sites")
    frappe.connect()
except Exception:
    pass



@pytest.fixture
def fixtures_path() -> Path:
    return Path(__file__).parent / "fixtures"


@pytest.fixture
def simple_bpmn_xml(fixtures_path: Path) -> str:
    return (fixtures_path / "simple_sequential.bpmn").read_text()


@pytest.fixture
def gateway_bpmn_xml(fixtures_path: Path) -> str:
    return (fixtures_path / "exclusive_gateway.bpmn").read_text()


@pytest.fixture
def mock_spiff_engine():
    engine = MagicMock(name="SpiffEngine")
    engine.next_task.return_value = None
    return engine


@pytest.fixture
def process_definition_doc(simple_bpmn_xml: str):
    doc = MagicMock()
    doc.name = "BPMN-MODEL-001"
    doc.title = "Sample Process"
    doc.bpmn_xml = simple_bpmn_xml
    return doc


@pytest.fixture
def process_instance_doc(process_definition_doc):
    doc = MagicMock()
    doc.name = "BPMN-INSTANCE-001"
    doc.process_model = process_definition_doc.name
    doc.status = "Running"
    return doc


def advance_to_next_task(engine):
    return engine.next_task()
