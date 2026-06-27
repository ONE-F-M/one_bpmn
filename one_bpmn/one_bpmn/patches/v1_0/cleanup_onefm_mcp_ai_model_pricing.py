"""
Remove AI Model Pricing doctype from onefm_mcp app.

After this doctype was moved to one_bpmn, the old files in onefm_mcp become
orphans. On sites where both apps are installed, having the same doctype
defined in two apps can cause unpredictable migration ordering.

This patch removes:
1. The doctype directory: onefm_mcp/onefm_mcp/doctype/ai_model_pricing/
2. The seed patch:     onefm_mcp/patches/v15_0/seed_ai_model_pricing_data.py
3. The patch entry:    onefm_mcp/patches.txt (the line referencing seed_ai_model_pricing)

All operations are wrapped in try/except — if onefm_mcp isn't installed or
file paths differ, the patch silently skips.
"""

import os

import frappe


def execute():
	# Get onefm_mcp app module path
	# frappe.get_app_path() raises ModuleNotFoundError when the app
	# is not installed, so we must guard with try/except.
	try:
		onefm_mcp_mod = frappe.get_app_path("onefm_mcp")
	except (ModuleNotFoundError, ImportError):
		return  # onefm_mcp is not installed on this site

	if not onefm_mcp_mod or not os.path.isdir(onefm_mcp_mod):
		return

	# The app root is one level above the module
	app_root = os.path.dirname(onefm_mcp_mod)

	# 1. Remove the doctype directory tree
	# frappe.get_app_path returns the module dir (e.g. .../onefm_mcp/onefm_mcp)
	# so doctype/ is directly under it
	doctype_dir = os.path.join(onefm_mcp_mod, "doctype", "ai_model_pricing")
	if os.path.isdir(doctype_dir):
		try:
			import shutil
			shutil.rmtree(doctype_dir)
			frappe.logger("one_bpmn.patches").info(f"Removed {doctype_dir}")
		except Exception as e:
			frappe.log_error(
				message=f"Could not remove {doctype_dir}: {e}",
				title="AI Model Pricing cleanup (non-fatal)",
			)

	# 2. Remove the seed patch file
	# patches/ lives at the app root, not under the module directory
	seed_patch = os.path.join(app_root, "patches", "v15_0", "seed_ai_model_pricing_data.py")
	if os.path.isfile(seed_patch):
		try:
			os.remove(seed_patch)
		except Exception as e:
			frappe.log_error(
				message=f"Could not remove {seed_patch}: {e}",
				title="AI Model Pricing cleanup (non-fatal)",
			)

	# 3. Remove the patch entry from onefm_mcp/patches.txt
	# patches.txt lives at the app root
	patches_file = os.path.join(app_root, "patches.txt")
	if os.path.isfile(patches_file):
		try:
			with open(patches_file) as f:
				lines = f.readlines()
			new_lines = [
				line for line in lines
				if "seed_ai_model_pricing" not in line
			]
			if len(new_lines) != len(lines):
				with open(patches_file, "w") as f:
					f.writelines(new_lines)
		except Exception as e:
			frappe.log_error(
				message=f"Could not update {patches_file}: {e}",
				title="AI Model Pricing cleanup (non-fatal)",
			)
