import os

import frappe

no_cache = 1

BUNDLE = ("public", "one_ai", "one-ai.iife.js")


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
	context.asset_version = _asset_version()
	return context


def _asset_version() -> str:
	"""Cache-buster stamped from the BUNDLE's own mtime.

	Not ``build_version``: that tracks the site's asset build (assets.json),
	which ``npm run build:oneai`` never touches — so a rebuilt bundle kept its
	old ``?v=`` and the 12h Cache-Control on /assets served stale JS to a
	browser that had ever loaded the page (caught live 2026-08-16, the same
	way it masked three fixes during the first one-ai build).
	"""
	try:
		return str(int(os.path.getmtime(frappe.get_app_path("one_bpmn", *BUNDLE))))
	except OSError:
		# Bundle not built on this site — fall back rather than 500 the page.
		return frappe.utils.get_build_version()
