"""
Debug and diagnostic API endpoints for support engineers.
Shows system configuration and environment variables.
"""
import os
import json
from frappe.auth import check_password
import frappe


@frappe.whitelist(allow_guest=False)
def get_environment_configuration():
	"""
	Return environment configuration and selected environment variables.
	Only accessible to users with 'System Manager' role for security.
	"""
	# Check if user has System Manager role
	if not frappe.has_role("System Manager"):
		frappe.throw("Only System Managers can access debug information", frappe.PermissionError)
	
	# List of safe environment variables to expose (avoid exposing all)
	# Focus on configuration that helps with debugging deployments
	safe_env_vars = [
		"FRAPPE_APP",
		"FRAPPE_BENCH_PATH",
		"FRAPPE_SITES_PATH",
		"FRAPPE_PY",
		"FRAPPE_VERSION",
		"NODE_ENV",
		"ENVIRONMENT",
		"APP_ENV",
		"DEBUG",
		"LOG_LEVEL",
		"CELERY_BROKER_URL",
		"CELERY_RESULT_BACKEND",
		"REDIS_URL",
		"REDIS_CACHE_URL",
		"DB_HOST",
		"DB_NAME",
		"DB_TYPE",
		"SITE_NAME",
		"HTTP_HOST",
		"API_BASE_URL",
		"SOCKETIO_MESSAGE_QUEUE",
		"PUSH_NOTIFICATIONS_URL",
		"PLATFORM",
		"PYTHON_VERSION",
		"BENCH_MODE",
		"FRAPPE_ENABLE_TESTING",
	]
	
	config = {}
	
	# Collect safe environment variables
	environment_vars = {}
	for var_name in safe_env_vars:
		value = os.environ.get(var_name)
		if value is not None:
			environment_vars[var_name] = value
	
	config["environment_variables"] = environment_vars
	
	# System information
	try:
		import platform
		config["system_info"] = {
			"platform": platform.system(),
			"platform_release": platform.release(),
			"python_version": platform.python_version(),
			"processor": platform.processor() if hasattr(platform, "processor") else "unknown",
		}
	except Exception as e:
		config["system_info"] = {"error": str(e)}
	
	# Frappe configuration
	try:
		config["frappe_info"] = {
			"version": frappe.get_version() if hasattr(frappe, "get_version") else "unknown",
			"current_site": frappe.local.site if hasattr(frappe, "local") and hasattr(frappe.local, "site") else "unknown",
			"sites_path": frappe.get_app_path("frappe", "..", "..", "sites") if hasattr(frappe, "get_app_path") else "unknown",
		}
	except Exception as e:
		config["frappe_info"] = {"error": str(e)}
	
	# Application-specific info
	try:
		import one_bpmn
		config["one_bpmn_info"] = {
			"module_path": os.path.dirname(one_bpmn.__file__),
		}
	except Exception as e:
		config["one_bpmn_info"] = {"error": str(e)}
	
	return config


@frappe.whitelist(allow_guest=False)
def get_debug_status():
	"""
	Return overall system status for debugging purposes.
	Simple health check endpoint.
	"""
	if not frappe.has_role("System Manager"):
		frappe.throw("Only System Managers can access debug information", frappe.PermissionError)
	
	status = {
		"status": "healthy",
		"timestamp": frappe.utils.now(),
		"user": frappe.session.user,
	}
	
	# Database connection check
	try:
		frappe.db.get_connection().ping()
		status["database"] = "connected"
	except Exception as e:
		status["database"] = f"error: {str(e)}"
	
	# Redis check if available
	try:
		import redis
		try:
			r = redis.from_url(os.environ.get("REDIS_URL", ""))
			r.ping()
			status["redis"] = "connected"
		except Exception as e:
			status["redis"] = f"not configured or error: {str(e)}"
	except ImportError:
		status["redis"] = "redis module not installed"
	
	return status
