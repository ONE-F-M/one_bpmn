import frappe


no_cache = 1


def get_context(context):
	# Redirect to login if not logged in
	if frappe.session.user == "Guest":
		frappe.local.flags.redirect_location = "/login?redirect-to=/spiff"
		raise frappe.Redirect
	
	frappe.db.commit()
	context.boot = get_boot()
	return context


@frappe.whitelist(methods=["POST"], allow_guest=True)
def get_context_for_dev():
	if not frappe.conf.developer_mode:
		frappe.throw("This method is only meant for developer mode")
	return get_boot()


def get_boot():
	return frappe._dict(
		{
			"default_route": "/spiff",
			"site_name": frappe.local.site,
			"csrf_token": frappe.sessions.get_csrf_token(),
			"session_user": frappe.session.user,
		}
	)
