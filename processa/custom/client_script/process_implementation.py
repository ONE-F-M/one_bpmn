def get_process_implementation_client_scripts():
	return [
		{
			"name": "Process Implementation",
			"dt": "Process Implementation",
			"view": "Form",
			"enabled": 1,
			"script": "frappe.ui.form.on('Process Implementation', {\r\n    onload: function(frm) {\r\n        toggle_processa_banner(frm);\r\n    },\r\n    refresh: function(frm) {\r\n        toggle_processa_banner(frm);\r\n    },\r\n    workflow_state: function(frm) {\r\n        toggle_processa_banner(frm);\r\n    }\r\n});\r\n\r\nfunction toggle_processa_banner(frm) {\r\n    // Clear any existing intro messages to prevent duplicating banners\r\n    frm.set_intro(\"\");\r\n\r\n    // If active, show the custom Processa banner with a link to Processa (opens in a new tab)\r\n    if (frm.doc.workflow_state === \"Active\") {\r\n        const processa_link = '<a href=\"https://business-analyst.one-fm.com/processa\" target=\"_blank\" rel=\"noopener noreferrer\" style=\"text-decoration: underline; font-weight: bold;\">'\r\n            + __(\"Processa on the BA site\") + '</a>';\r\n        frm.set_intro(__(\"You can now define the process in {0}.\", [processa_link]), \"blue\");\r\n    }\r\n}",
		},
		{
			"name": "Process Implementation FIlters",
			"dt": "Process Implementation",
			"view": "Form",
			"enabled": 0,
			"script": "frappe.ui.form.on('Process Implementation', {\r\n    setup: function(frm) {\r\n        // 1. Filter 'process_name' to show only records where current user is the process_owner\r\n        frm.set_query('process_name', function() {\r\n            return {\r\n                filters: {\r\n                    'process_owner': frappe.session.user\r\n                }\r\n            };\r\n        });\r\n\r\n        // 2. Filter 'existing_process_model' based on the selected 'process_name'\r\n        //frm.set_query('existing_process_model', function() {\r\n          //  return {\r\n            //    filters: {\r\n              //      'process_name': frm.doc.process_name || ''\r\n                //}\r\n            //};\r\n        });\r\n    },\r\n\r\n    // Clear or re-evaluate the linked field when process_name changes\r\n    process_name: function(frm) {\r\n        // Clear existing model field if process_name is cleared/changed\r\n        if (!frm.doc.process_name) {\r\n            frm.set_value('existing_process_model', '');\r\n        }\r\n    }\r\n});",
		},
	]
