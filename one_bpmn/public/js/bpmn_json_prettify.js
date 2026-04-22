/**
 * BPMN JSON Prettifier
 * Shared utility to display JSON fields with proper indentation in Frappe
 * forms, without mutating the underlying frm.doc values.
 *
 * Loaded globally via app_include_js in hooks.py.
 * Usage from doctype scripts:
 *   one_bpmn.prettify_json_fields(frm, ["serialized_spec", "workflow_state"]);
 */

frappe.provide("one_bpmn");

(function () {
	"use strict";

	/**
	 * Pretty-print one or more JSON fields on a Frappe form for readability.
	 *
	 * This is strictly a display-only operation — frm.doc is NOT mutated,
	 * so saving the form will NOT rewrite these fields in pretty-printed form.
	 *
	 * @param {Object} frm - The Frappe form object.
	 * @param {string[]} fieldnames - Array of JSON fieldnames to format.
	 */
	function prettify_json_fields(frm, fieldnames) {
		if (!frm || !fieldnames || !fieldnames.length) return;

		for (const fieldname of fieldnames) {
			_prettify_single(frm, fieldname);
		}
	}

	/**
	 * Format a single JSON field's editor display without mutating frm.doc.
	 */
	function _prettify_single(frm, fieldname) {
		const raw = frm.doc[fieldname];
		if (!raw) return;

		const control = frm.fields_dict[fieldname];
		if (!control) return;

		try {
			const parsed = JSON.parse(raw);
			const formatted = JSON.stringify(parsed, null, 2);

			// Nothing to do if it's already pretty-printed
			if (formatted === raw) return;

			// Update ONLY the editor display — leave frm.doc untouched.
			// Frappe's Code control uses `set_formatted_input` to update the
			// editor without triggering model sync.
			if (typeof control.set_formatted_input === "function") {
				control.set_formatted_input(formatted);
			}

			// Restore the original raw value in frm.doc in case the editor's
			// change handler propagated the formatted value back.
			frm.doc[fieldname] = raw;

			// Clear any false dirty state caused by the display update.
			if (frm.doc.__unsaved) {
				frm.doc.__unsaved = 0;
				frm.page && frm.page.clear_indicator && frm.page.clear_indicator();
			}
		} catch (e) {
			// Not valid JSON — leave as-is
		}
	}

	// Expose on the one_bpmn namespace
	one_bpmn.prettify_json_fields = prettify_json_fields;
})();
