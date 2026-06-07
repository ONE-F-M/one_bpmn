// Copyright (c) 2026, kartiksharma9319@gmail.com and contributors
// For license information, please see license.txt

frappe.ui.form.on("Contingency Task Completion", {
	refresh(frm) {
		if (frm.is_new()) {
			frappe.call({
				method: "frappe.client.get_value",
				args: {
					doctype: "Employee",
					filters: { user_id: frappe.session.user },
					fieldname: "name"
				},
				callback(r) {
					if (r.message) {
						frm.set_value("process_owner", r.message.name);
					}
				}
			});
		}

		frm.set_query("process_name", function () {
			return {
				filters: { process_owner: frappe.session.user }
			};
		});

		if (frm.doc.process_name) {
			set_context_doctype_filter(frm);
		}

		if (frm.doc.context_doctype) {
			set_context_docname_filter(frm);
		}
	},

	process_name(frm) {
		frm.set_value("context_doctype", null);
		frm.set_value("context_docname", null);
		if (frm.doc.process_name) {
			set_context_doctype_filter(frm);
		}
	},

	context_doctype(frm) {
		frm.set_value("context_docname", null);
		if (frm.doc.context_doctype) {
			set_context_docname_filter(frm);
		}
	}
});

function set_context_doctype_filter(frm) {
	frm.set_query("context_doctype", function () {
		return {
			query: "one_bpmn.one_bpmn.doctype.contingency_task_completion.contingency_task_completion.get_process_doctypes",
			filters: { process_name: frm.doc.process_name }
		};
	});
}

function set_context_docname_filter(frm) {
	frm.set_query("context_docname", function () {
		return {
			query: "one_bpmn.one_bpmn.doctype.contingency_task_completion.contingency_task_completion.get_active_task_documents",
			filters: {
				process_name: frm.doc.process_name,
				context_doctype: frm.doc.context_doctype
			}
		};
	});
}
