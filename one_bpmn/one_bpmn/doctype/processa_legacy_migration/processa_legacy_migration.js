// Copyright (c) 2026, one-fm and contributors
// For license information, please see license.txt

frappe.ui.form.on("Processa Legacy Migration", {
	refresh(frm) {
		// ── Primary action button ────────────────────────────────────────
		if (frm.doc.status === "Draft" || frm.doc.status === "Failed") {
			frm.add_custom_button(
				__("Run Migration"),
				function () {
					frappe.confirm(
						__(
							"This will transition <b>{0}</b> records from <b>{1}</b> to <b>{2}</b>. " +
							"This action cannot be undone. Continue?",
							[frm.doc.target_doctype, frm.doc.old_status, frm.doc.target_status]
						),
						function () {
							frappe.call({
								method: "one_bpmn.one_bpmn.doctype.processa_legacy_migration.processa_legacy_migration.enqueue_migration",
								args: { migration_name: frm.doc.name },
								callback: function (r) {
									if (r.message) {
										frappe.show_alert({
											message: r.message.message || __("Migration queued."),
											indicator: "blue",
										});
										frm.reload_doc();
									}
								},
							});
						}
					);
				},
				null
			);
			// Make it primary (blue)
			frm.change_custom_button_type(__("Run Migration"), null, "primary");
		}

		// ── Preview button ───────────────────────────────────────────────
		if (
			frm.doc.status === "Draft" &&
			frm.doc.target_doctype &&
			frm.doc.old_status
		) {
			frm.add_custom_button(
				__("Preview Records"),
				function () {
					frappe.call({
						method: "one_bpmn.one_bpmn.doctype.processa_legacy_migration.processa_legacy_migration.preview_migration",
						args: {
							target_doctype: frm.doc.target_doctype,
							old_status: frm.doc.old_status,
						},
						callback: function (r) {
							if (!r.message) return;
							let data = r.message;

							if (data.error) {
								frappe.msgprint(data.error);
								return;
							}

							let msg = __(
								"Found <b>{0}</b> records in <b>{1}</b> with {2} = <b>{3}</b>",
								[data.count, frm.doc.target_doctype, data.state_field, frm.doc.old_status]
							);

							if (data.samples && data.samples.length > 0) {
								msg += "<br><br>" + __("Sample records:") + "<ul>";
								data.samples.forEach(function (name) {
									msg +=
										"<li><a href='/app/" +
										frappe.router.slug(frm.doc.target_doctype) +
										"/" +
										name +
										"' target='_blank'>" +
										name +
										"</a></li>";
								});
								msg += "</ul>";
							}

							frappe.msgprint({
								title: __("Migration Preview"),
								message: msg,
								indicator: "blue",
							});
						},
					});
				},
				__("Actions")
			);
		}

		// ── Status-based indicators ──────────────────────────────────────
		if (frm.doc.status === "Running" || frm.doc.status === "Queued") {
			frm.dashboard.set_headline(
				__(
					"Migration is {0}. Migrated: {1} | Failed: {2} | Total: {3}",
					[frm.doc.status, frm.doc.migrated_count, frm.doc.failed_count, frm.doc.total_records]
				)
			);
			frm.disable_save();

			// Auto-refresh while running
			if (frm.doc.status === "Running") {
				setTimeout(function () {
					frm.reload_doc();
				}, 5000);
			}
		}

		if (frm.doc.status === "Completed") {
			frm.dashboard.set_headline(
				__(
					"Migration completed. Migrated: {0} | Failed: {1} | Total: {2}",
					[frm.doc.migrated_count, frm.doc.failed_count, frm.doc.total_records]
				),
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
		// When process model changes, fetch available service tasks and target doctypes
		if (!frm.doc.process_model) {
			frm.set_value("target_task_id", "");
			frm.set_value("target_task_name", "");
			frm.set_value("target_doctype", "");
			return;
		}

		// Fetch target doctypes from the process model
		frappe.db.get_doc("BPMN Process Model", frm.doc.process_model).then((model) => {
			let doctypes = (model.target_doctypes || []).map((d) => d.doctype_name);

			// Also check start_events for trigger_doctype as a fallback
			if (!doctypes.length && model.start_events) {
				let start_doctypes = model.start_events
					.filter((e) => e.trigger_doctype)
					.map((e) => e.trigger_doctype);
				doctypes = [...new Set(start_doctypes)];
			}

			if (doctypes.length === 1) {
				// Single target doctype — auto-set
				frm.set_value("target_doctype", doctypes[0]);
			} else if (doctypes.length > 1) {
				// Multiple — filter the link field to only these doctypes
				frm.set_value("target_doctype", "");
				frm.set_query("target_doctype", () => ({
					filters: { name: ["in", doctypes] },
				}));
			}
		});

		// Fetch service tasks for target_status auto-matching
		frappe.call({
			method: "one_bpmn.one_bpmn.doctype.processa_legacy_migration.processa_legacy_migration.get_bpmn_service_tasks",
			args: { process_model: frm.doc.process_model },
			callback: function (r) {
				if (!r.message || r.message.length === 0) return;

				// Store for later use by target_status handler
				frm._bpmn_service_tasks = r.message;
			},
		});
	},

	target_status(frm) {
		// Auto-match target_task_id when target_status changes
		if (!frm.doc.target_status || !frm._bpmn_service_tasks) return;

		let match = frm._bpmn_service_tasks.find(
			(t) => t.workflow_state === frm.doc.target_status
		);

		if (match) {
			frm.set_value("target_task_id", match.id);
			frm.set_value("target_task_name", match.name);
		} else {
			frm.set_value("target_task_id", "");
			frm.set_value("target_task_name", "");
		}
	},

	// Listen for realtime progress updates
	onload(frm) {
		frappe.realtime.on("legacy_migration_progress", function (data) {
			if (data.migration_name !== frm.doc.name) return;

			if (data.completed) {
				frm.reload_doc();
			} else {
				frm.dashboard.set_headline(
					__(
						"Migration running… Migrated: {0} | Failed: {1} | Total: {2}",
						[data.migrated, data.failed, data.total]
					)
				);
			}
		});
	},
});
