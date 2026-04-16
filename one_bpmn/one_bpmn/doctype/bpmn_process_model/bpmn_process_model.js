// Copyright (c) 2026, kartiksharma9319@gmail.com and contributors
// For license information, please see license.txt

frappe.ui.form.on("BPMN Process Model", {
	refresh(frm) {
		// ── Pretty-print JSON fields for readability (display-only) ──
		one_bpmn.prettify_json_fields(frm, ["serialized_spec", "subprocess_specs"]);

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
