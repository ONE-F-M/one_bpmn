def get_email_queue_custom_fields():
	return {
		"Email Queue": [
			{
				"fieldname": "amp_html",
				"fieldtype": "Long Text",
				"insert_after": "message",
				"label": "AMP HTML",
				"description": "AMP4Email document attached as text/x-amp-html MIME part.",
				"read_only": 1,
				"hidden": 1,
			}
		]
	}
