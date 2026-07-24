"""Seed the Policy and Manual document-generation process maps.

These are clones of the live "SOP Generation from Guidelines" model, scoped to
their own document_type via the conditional start event, so the same two-phase
approval + Google Drive + AI-drafting pipeline produces Policy and Manual
documents. Seeded as inactive DRAFTS (mirrors how SOP started): a designer
deploys/compiles/activates them from the Processa editor when ready.

The diagrams reuse the generic Drive Server Scripts unchanged. The only
document-type-specific bit still shared with SOP is template fetching
("Drive - Fetch SOP Template" reads AI Chat Settings > SOP Template File ID);
generalising template resolution per document_type is tracked separately.

Idempotent: keyed on process_id, so re-runs (or a map already drawn by hand)
are left untouched.
"""

import os

import frappe

MAPS = [
	{
		"title": "Policy Generation from Guidelines",
		"process_id": "policy_generation_process",
		"file": "policy_generation.bpmn",
		"document_type": "Policy",
	},
	{
		"title": "Manual Generation from Guidelines",
		"process_id": "manual_generation_process",
		"file": "manual_generation.bpmn",
		"document_type": "Manual",
	},
]


def execute():
	if not frappe.db.exists("DocType", "BPMN Process Model"):
		return

	data_dir = os.path.join(os.path.dirname(os.path.abspath(__file__)), "data")

	for m in MAPS:
		# Idempotent — leave any existing model (seeded or hand-drawn) alone.
		if frappe.db.exists("BPMN Process Model", {"process_id": m["process_id"]}):
			continue

		path = os.path.join(data_dir, m["file"])
		with open(path, encoding="utf-8") as fh:
			bpmn_xml = fh.read()

		doc = frappe.new_doc("BPMN Process Model")
		doc.title = m["title"]
		doc.bpmn_xml = bpmn_xml
		doc.is_active = 0
		doc.description = (
			f"Seeded clone of the SOP Generation pipeline, scoped to "
			f'document_type == "{m["document_type"]}". Draft — deploy/compile/'
			f"activate it in the Processa editor to go live."
		)

		# Mirror SOP's start-event config so the model is discoverable by the
		# universal doc-event trigger once it is deployed and activated.
		doc.append(
			"start_events",
			{
				"event_type": "Conditional",
				"bpmn_element_id": "start1",
				"trigger_type": "DocType Event",
				"trigger_doctype": "Document Request",
				"trigger_event": "After Insert",
			},
		)

		# Trusted-seed bypasses: the content is a clone of an already-validated,
		# deployed model; preserve the process_id embedded in the XML.
		doc.flags.skip_script_security_check = True
		doc.flags.skip_editability_check = True
		doc.flags.skip_process_id_regeneration = True
		doc.insert(ignore_permissions=True)

	frappe.db.commit()
