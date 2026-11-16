"""Seed the "github_video_upload" Connector that holds the machine user's token for upload_videos.

Only the connector is seeded, never its token: paste the machine user's token into the connector's Auth Secret in the desk. Until
then upload_videos stops with "has no token in its Auth Secret". It has no operations: nothing calls it, upload_videos only reads
its Bearer Token secret (agents_sandbox.sandbox.ops.video_upload_token).

A seed must never stop a deploy, so a failure is logged and the migrate carries on.
"""

import frappe

VIDEO_UPLOAD_CONNECTOR = {
	"connectorId": "github_video_upload",
	"label": "GitHub video upload (machine user)",
	"description": (
		"Holds the machine user's token that upload_videos uses to attach test videos to a pull request. "
		"Paste the token into Auth Secret. Nothing calls this connector directly."
	),
	"execution": {
		"type": "HTTP Request",
		"baseUrl": "https://api.github.com",
		"timeout": 30,
		"auth": {"type": "Bearer Token", "source": "On this connector"},
	},
	"operations": [],
}


def execute():
	from processa.processa_connectors.seed import import_manifest

	try:
		import_manifest(VIDEO_UPLOAD_CONNECTOR, overwrite=False)
		frappe.db.commit()
	except Exception:
		frappe.log_error(title="seed_github_video_upload_connector failed", message=frappe.get_traceback())
