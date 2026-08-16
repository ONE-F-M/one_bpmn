import frappe

no_cache = 1


def get_context(context):
	"""Serve the ONE AI chat page — the Lumina successor (WI-001678).

	A website route, not a Desk page, on purpose: Desk resolves ``/app/<slug>``
	against workspaces first, and onefm_mcp ships a public workspace literally
	named "ONE AI". That collision is what made the original ``/app/one-ai``
	page unreachable on every site; a website route cannot be shadowed by a
	workspace, so the page stays reachable no matter what onefm_mcp adds.
	"""
	if frappe.session.user == "Guest":
		frappe.local.flags.redirect_location = "/login?redirect-to=/one-ai"
		raise frappe.Redirect

	context.csrf_token = frappe.sessions.get_csrf_token()
	context.site_name = frappe.local.site
	context.session_user = frappe.session.user
	return context
