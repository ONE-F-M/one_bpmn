def get_process__client_scripts():
	return [
		{
			"name": "Process",
			"dt": "Process",
			"view": "Form",
			"enabled": 1,
			"script": "frappe.ui.form.on('Process', {\r\n    refresh: function(frm) {\r\n        // Check if the user has the Business Analyst role\r\n        if (!frappe.user.has_role('Business Analyst')) {\r\n            \r\n            // Make all standard fields read-only\r\n            frm.disable_form();\r\n            \r\n            // Lock down child tables completely\r\n            frm.get_docfields().forEach(field => {\r\n                if (field.fieldtype === 'Table') {\r\n                    frm.set_df_property(field.fieldname, 'read_only', 1);\r\n                }\r\n            });\r\n            \r\n        }\r\n    }\r\n});",
		},
	]
