// Copyright (c) 2026, one-fm and contributors
// For license information, please see license.txt

frappe.ui.form.on("Processa Legacy Migration", {
	setup(frm) {
		// The server refuses maps of other owners on save; this only narrows the pickers.
		if (frappe.user.has_role("System Manager")) return;

		frappe.db
			.get_list("Process", {
				filters: { process_owner: frappe.session.user },
				limit: 0,
			})
			.then((rows) => {
				const processes = rows.map((r) => r.name);
				for (const fieldname of ["from_model", "to_model"]) {
					frm.set_query(fieldname, () => ({
						filters: { process_name: ["in", processes] },
					}));
				}
			});
	},

	refresh(frm) {
		if (frm.doc.status === "Running" || frm.doc.status === "Queued") {
			show_progress(frm, {
				migrated: frm.doc.migrated_count,
				failed: frm.doc.failed_count,
				total: frm.doc.total_records,
				batches_done: frm.doc.batches_done,
				total_batches: frm.doc.total_batches,
			});
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

		// Lock fields once the migration has left Draft/Failed
		if (frm.doc.status && !["Draft", "Failed"].includes(frm.doc.status)) {
			frm.set_read_only(true);
		}
	},

	from_model(frm) {
		frm.clear_table("state_map");
		frm.refresh_field("state_map");
	},

	to_model(frm) {
		// Derive the target doctype(s) from the selected process model.
		if (!frm.doc.to_model) {
			frm.set_value("target_doctype", "");
			return;
		}

		frappe.db.get_doc("BPMN Process Model", frm.doc.to_model).then((model) => {
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

	onload(frm) {
		// onload runs on every open of the form, so drop the previous listener first.
		frappe.realtime.off("legacy_migration_progress");
		frappe.realtime.on("legacy_migration_progress", function (data) {
			if (data.migration_name !== frm.doc.name) return;

			if (data.completed) {
				frm.reload_doc();
			} else {
				show_progress(frm, {
					migrated: data.migrated,
					failed: data.failed,
					total: data.total,
					batches_done: data.batches_done,
					total_batches: data.total_batches,
				});
			}
		});
	},
});

function show_progress(frm, progress) {
	// set_headline appends a new block, so the previous one goes first.
	frm.dashboard.clear_headline();
	frm.dashboard.set_headline(
		__("Migration is {0}. Migrated: {1} | Failed: {2} | Total: {3} | Batches Done: {4} of {5}", [
			frm.doc.status,
			progress.migrated,
			progress.failed,
			progress.total,
			progress.batches_done,
			progress.total_batches,
		])
	);
}
