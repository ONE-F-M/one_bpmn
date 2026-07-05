import frappe


no_cache = 1


def get_context(context):
	"""Serve the Processa Vue SPA shell, redirecting guests to login."""
	if frappe.session.user == "Guest":
		frappe.local.flags.redirect_location = "/login?redirect-to=/processa"
		raise frappe.Redirect
	
	frappe.db.commit()
	context.boot = get_boot()
	return context


@frappe.whitelist(methods=["POST"])
def get_context_for_dev():
	"""Return boot context for the Vite dev server (developer_mode only)."""
	if not frappe.conf.developer_mode:
		frappe.throw("This method is only meant for developer mode")
	return get_boot()


def get_boot() -> dict:
	"""Build the boot payload passed to the Vue SPA."""
	return frappe._dict(
		{
			"default_route": "/processa",
			"site_name": frappe.local.site,
			"csrf_token": frappe.sessions.get_csrf_token(),
			"session_user": frappe.session.user,
			# The SPA's socket.io client needs the real port — frappe-ui
			# defaults to 9000, but bench configures socketio_port per bench
			# (webserver_port + 1000, e.g. 9001 on this bench).
			"socketio_port": frappe.conf.socketio_port or 9000,
		}
	)
