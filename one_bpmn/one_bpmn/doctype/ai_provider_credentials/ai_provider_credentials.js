// Copyright (c) 2026, one-fm and contributors
// For license information, please see license.txt

frappe.ui.form.on("AI Provider Credentials", {
	refresh(frm) {
		// A live test needs a saved provider (the key lives in the __Auth table).
		if (frm.is_new()) {
			return;
		}

		frm.add_custom_button(__("Test Connection"), () => {
			frappe.call({
				method: "one_bpmn.one_bpmn.doctype.ai_provider_credentials.ai_provider.test_connection",
				args: { provider_name: frm.doc.name },
				freeze: true,
				freeze_message: __("Testing connection…"),
				callback(r) {
					const res = r.message || {};
					if (res.ok) {
						frappe.show_alert(
							{
								message: __("Connection successful ({0})", [res.model]),
								indicator: "green",
							},
							5
						);
					} else {
						frappe.msgprint({
							title: __("Connection Failed"),
							indicator: "red",
							message: __("{0}: {1}", [
								res.error_code || __("Error"),
								res.message,
							]),
						});
					}
				},
			});
		});
	},

	validate(frm) {
		if (frm.doc.api_endpoint && !/^https?:\/\//.test(frm.doc.api_endpoint)) {
			frappe.throw(__("API Endpoint must start with http:// or https://"));
		}
	},
});
