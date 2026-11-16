def get_process_implementation_client_scripts():
	return [
		{
			"name": "Process Implementation",
			"dt": "Process Implementation",
			"view": "Form",
			"enabled": 1,
			"script": "frappe.ui.form.on('Process Implementation', {\r\n    onload: function(frm) {\r\n        toggle_processa_banner(frm);\r\n    },\r\n    refresh: function(frm) {\r\n        toggle_processa_banner(frm);\r\n    },\r\n    workflow_state: function(frm) {\r\n        toggle_processa_banner(frm);\r\n    },\r\n    process_name: function(frm) {\r\n        // Always clear existing_process_model whenever process_name is changed or cleared\r\n        frm.set_value('existing_process_model', '');\r\n        frm.refresh_field('existing_process_model');\r\n    }\r\n});\r\n\r\nfunction toggle_processa_banner(frm) {\r\n    frm.set_intro(\"\");\r\n\r\n    if (frm.doc.workflow_state === \"Active\") {\r\n        const processa_link = '<a href=\"https://business-analyst.one-fm.com/processa\" target=\"_blank\" rel=\"noopener noreferrer\" style=\"text-decoration: underline; font-weight: bold;\">'\r\n            + __(\"Processa on the BA site\") + '</a>';\r\n        frm.set_intro(__(\"You can now define the process in {0}.\", [processa_link]), \"blue\");\r\n    }\r\n}",
		},
	]
