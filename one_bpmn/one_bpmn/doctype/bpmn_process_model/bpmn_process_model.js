// Copyright (c) 2026, kartiksharma9319@gmail.com and contributors
// For license information, please see license.txt

frappe.ui.form.on("BPMN Process Model", {
	refresh(frm) {
		// ── Pretty-print JSON fields for readability ──
		prettify_json_field(frm, "serialized_spec");
		prettify_json_field(frm, "subprocess_specs");

		if (frm.is_new()) return;

		// ── Open in Editor ──
		frm.add_custom_button(__("Open in Editor"), function () {
			window.open(
				`/processa/process/${encodeURIComponent(frm.doc.process_name)}/diagram/${encodeURIComponent(frm.doc.name)}`,
				"_blank"
			);
		});

		// ── Deploy ──
		frm.add_custom_button(__("Deploy"), function () {
			frappe.call({
				method: "one_bpmn.api.compile_process_model",
				args: { model_name: frm.doc.name },
				freeze: true,
				freeze_message: __("Deploying BPMN…"),
				callback(r) {
					if (r.message && r.message.success) {
						frappe.show_alert({
							message: __(
								"Deployed successfully — version {0}, {1} subprocess(es)",
								[r.message.version, r.message.subprocess_count]
							),
							indicator: "green",
						});
						frm.reload_doc();
					}
				},
			});
		}, __("Actions"));
	},
});

/**
 * Parse and pretty-print a JSON field value with 2-space indentation.
 * Silently skips empty values or invalid JSON.
 */
function prettify_json_field(frm, fieldname) {
	let raw = frm.doc[fieldname];
	if (!raw) return;

	try {
		let parsed = JSON.parse(raw);
		let formatted = JSON.stringify(parsed, null, 2);
		// Only update the control display if the value actually changed
		if (formatted !== raw) {
			frm.doc[fieldname] = formatted;
			frm.fields_dict[fieldname].refresh_input();
		}
	} catch (e) {
		// Not valid JSON — leave as-is
	}
}
