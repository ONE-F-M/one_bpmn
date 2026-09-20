# Copyright (c) 2026, one-fm and contributors
"""What the desk needs to know at boot.

Only the ONE AI bundle's version so far. The desk loads that bundle by a bare
path through ``frappe.require``, so without a version the 12h Cache-Control on
/assets keeps a browser on whatever build it first saw — the standalone page
already solved this by stamping the bundle's mtime, and the desk has to do the
same or a rebuilt chat panel never reaches anyone who opens it from a form.
"""

import os

import frappe

BUNDLE = ("public", "one_ai", "one-ai.iife.js")


def boot_session(bootinfo):
	bootinfo.one_ai_asset_version = asset_version()


def asset_version() -> str:
	"""The bundle's mtime, matching www/one_ai/index.py.

	A missing bundle falls back to the site's build version rather than raising:
	the desk must boot on a site where the chat was never built.
	"""
	try:
		return str(int(os.path.getmtime(frappe.get_app_path("one_bpmn", *BUNDLE))))
	except OSError:
		return frappe.utils.get_build_version()
