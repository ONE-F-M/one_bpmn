// Copyright (c) 2026, one-fm and contributors
// For license information, please see license.txt
//
// This DocType is the context document for the self-hosted "Processa Legacy
// Migration V1" BPMN process. Preview Records and Run Migration are BPMN
// user-task actions performed in Processa — not form buttons here. The only
// action offered on the form is starting the process against this record.

const LEGACY_MIGRATION_MODEL = "Processa Legacy Migration V1";

frappe.ui.form.on("Processa Legacy Migration", {
	refresh(frm) {
		// ── Start the Processa process against this record ────────────────
		if (
			!frm.is_new() &&
			(frm.doc.status === "Draft" || frm.doc.status === "Failed") &&
			frm.doc.process_model &&
			frm.doc.target_doctype &&
			frm.doc.old_status &&
			frm.doc.target_status
		) {
			frm.add_custom_button(__("Start in Processa"), function () {
				frappe.call({
					method: "one_bpmn.api.instance_api.start_process",
					args: {
						model_name: LEGACY_MIGRATION_MODEL,
						context_doctype: "Processa Legacy Migration",
						context_docname: frm.doc.name,
					},
					freeze: true,
					freeze_message: __("Starting migration process…"),
					callback: function (r) {
						if (!r.message) return;
						frappe.msgprint({
							title: __("Migration process started"),
							message: __(
								"Open <b>Processa</b> to run <b>Preview Records</b> or " +
									"<b>Run Migration</b> from your task inbox. Instance: {0}",
								[r.message.instance]
							),
							indicator: "green",
						});
						frm.reload_doc();
					},
				});
			});
			frm.change_custom_button_type(__("Start in Processa"), null, "primary");
		}

		// ── Status-based indicators ───────────────────────────────────────
		if (frm.doc.status === "Running" || frm.doc.status === "Queued") {
			frm.dashboard.set_headline(
				__("Migration is {0}. Migrated: {1} | Failed: {2} | Total: {3}", [
					frm.doc.status,
					frm.doc.migrated_count,
					frm.doc.failed_count,
					frm.doc.total_records,
				])
			);
			frm.disable_save();

			if (frm.doc.status === "Running") {
				setTimeout(function () {
					frm.reload_doc();
				}, 5000);
			}
		}

		if (frm.doc.status === "Completed") {
			frm.dashboard.set_headline(
				__("Migration completed. Migrated: {0} | Failed: {1} | Total: {2}", [
					frm.doc.migrated_count,
					frm.doc.failed_count,
					frm.doc.total_records,
				]),
				frm.doc.failed_count > 0 ? "orange" : "green"
			);
		}

		if (frm.doc.status === "Failed") {
			frm.dashboard.set_headline(
				__("Migration failed. Check error logs below."),
				"red"
			);
		}

		// Disable form fields when not in Draft/Failed
		if (frm.doc.status && !["Draft", "Failed"].includes(frm.doc.status)) {
			frm.set_read_only(true);
		}
	},

	process_model(frm) {
		// Derive the target doctype(s) from the selected process model.
		if (!frm.doc.process_model) {
			frm.set_value("target_doctype", "");
			return;
		}

		frappe.db.get_doc("BPMN Process Model", frm.doc.process_model).then((model) => {
			let doctypes = (model.target_doctypes || []).map((d) => d.doctype_name);

			if (!doctypes.length && model.start_events) {
				let start_doctypes = model.start_events
					.filter((e) => e.trigger_doctype)
					.map((e) => e.trigger_doctype);
				doctypes = [...new Set(start_doctypes)];
			}

			if (doctypes.length === 1) {
				frm.set_value("target_doctype", doctypes[0]);
			} else if (doctypes.length > 1) {
				frm.set_value("target_doctype", "");
				frm.set_query("target_doctype", () => ({
					filters: { name: ["in", doctypes] },
				}));
			}
		});
	},

	// Listen for realtime progress updates published by the Run Migration action
	onload(frm) {
		frappe.realtime.on("legacy_migration_progress", function (data) {
			if (data.migration_name !== frm.doc.name) return;

			if (data.completed) {
				frm.reload_doc();
			} else {
				frm.dashboard.set_headline(
					__("Migration running… Migrated: {0} | Failed: {1} | Total: {2}", [
						data.migrated,
						data.failed,
						data.total,
					])
				);
			}
		});
	},
});
