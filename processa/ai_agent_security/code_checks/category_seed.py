"""The Script Import Categories every site starts with, and the Application Manager role."""

import frappe

MODULE = "Module"
FUNCTION = "Frappe function"
BUILTIN = "Builtin"
SYNTAX = "Syntax"


def _rows(kind, *names, any_object=0):
	return [{"dotted_name": name, "kind": kind, "match_on_any_object": any_object} for name in names]


CATEGORIES = [
	{
		"category_name": "Python basics",
		"allowed_by_default": 1,
		"description": "Standard library modules that only work on data in memory.",
		"names": _rows(
			MODULE,
			"json",
			"re",
			"datetime",
			"time",
			"math",
			"decimal",
			"collections",
			"itertools",
			"functools",
			"textwrap",
			"uuid",
			"hashlib",
			"base64",
			"html",
			"copy",
			"typing",
			"dataclasses",
			"enum",
			"string",
			"difflib",
			"csv",
			"unicodedata",
			"urllib.parse",
		),
	},
	{
		"category_name": "Frappe records",
		"allowed_by_default": 1,
		"description": "Reading and writing documents through the Frappe API, which checks permissions.",
		"names": _rows(
			FUNCTION,
			"frappe.get_doc",
			"frappe.new_doc",
			"frappe.get_list",
			"frappe.db.get_value",
			"frappe.db.exists",
			"frappe.qb",
			"frappe.throw",
			"frappe._",
			"frappe.session.user",
		),
	},
	{
		"category_name": "Frappe helpers",
		"allowed_by_default": 1,
		"description": "Frappe conversion and date helpers with no side effects.",
		"names": _rows(
			FUNCTION,
			"frappe.utils.flt",
			"frappe.utils.cint",
			"frappe.utils.cstr",
			"frappe.utils.getdate",
			"frappe.utils.add_days",
			"frappe.utils.nowdate",
			"frappe.utils.now_datetime",
			"frappe.parse_json",
			"frappe.as_json",
			"frappe.scrub",
		),
	},
	{
		"category_name": "Language features",
		"allowed_by_default": 1,
		"description": "Python constructs and builtins that ordinary scripts use.",
		"names": _rows(SYNTAX, "def", "lambda", "while", "class")
		+ _rows(BUILTIN, "hasattr", "type", "id", "classmethod", "staticmethod"),
	},
	{
		"category_name": "Scripts on this map",
		"allowed_by_default": 1,
		"description": "import_script for a library Server Script on the same process.",
		"names": _rows(BUILTIN, "import_script"),
	},
	{
		"category_name": "Processa backend",
		"allowed_by_default": 0,
		"description": "Processa's own Python code and the workflow engine underneath it.",
		"sanctioned_alternative": "A Server Script tool or BPMN Connector operation that does the same job.",
		"names": _rows(MODULE, "processa", "SpiffWorkflow"),
	},
	{
		"category_name": "ONE FM apps",
		"allowed_by_default": 0,
		"description": "Python code of the other apps on the bench.",
		"sanctioned_alternative": "The Frappe API on the DocTypes those apps own.",
		"names": _rows(MODULE, "one_fm", "onefm_mcp", "erpnext", "hrms"),
	},
	{
		"category_name": "Installed third-party",
		"allowed_by_default": 0,
		"description": "Packages installed on the bench, listed one by one.",
		"names": _rows(MODULE, "dateutil", "bs4", "yaml", "pytz", "cloudscraper", "praw", "feedparser"),
	},
	{
		"category_name": "Network",
		"allowed_by_default": 0,
		"description": "Anything that sends data off the site: HTTP, sockets and the Frappe request helpers. "
		"Use a BPMN Connector operation where one exists.",
		"sanctioned_alternative": "A BPMN Connector operation, or frappe.integrations.utils.make_post_request with approval.",
		"names": _rows(
			MODULE,
			"requests",
			"httpx",
			"aiohttp",
			"urllib.request",
			"urllib3",
			"http.client",
			"socket",
			"ssl",
			"websocket",
			"ftplib",
			"telnetlib",
		)
		+ _rows(
			FUNCTION,
			"frappe.integrations.utils.make_get_request",
			"frappe.integrations.utils.make_post_request",
			"frappe.integrations.utils.make_put_request",
			"frappe.integrations.utils.make_request",
			"frappe.utils.get_request_session",
		),
	},
	{
		"category_name": "Email and notifications",
		"allowed_by_default": 0,
		"description": "Sending mail and pushing messages to browsers.",
		"sanctioned_alternative": "A Notification or an Email step on the map.",
		"names": _rows(FUNCTION, "frappe.sendmail", "frappe.publish_realtime")
		+ _rows(MODULE, "smtplib", "imaplib", "poplib"),
	},
	{
		"category_name": "Database direct",
		"allowed_by_default": 0,
		"description": "Writes and SQL that skip document validation and permissions.",
		"sanctioned_alternative": "frappe.get_doc and doc.save, or frappe.qb for reads.",
		"names": _rows(
			FUNCTION,
			"frappe.db.sql",
			"frappe.db.sql_ddl",
			"frappe.db.multisql",
			"frappe.db.set_value",
			"frappe.db.delete",
			"frappe.db.commit",
			"frappe.db.bulk_insert",
		)
		+ _rows(FUNCTION, "sql", "db_set", any_object=1)
		+ _rows(SYNTAX, "destructive_sql"),
	},
	{
		"category_name": "Concurrency",
		"allowed_by_default": 0,
		"description": "Threads, processes and background jobs started from a script.",
		"sanctioned_alternative": "A timer or a separate step on the map.",
		"names": _rows(MODULE, "asyncio", "threading", "concurrent", "multiprocessing")
		+ _rows(FUNCTION, "frappe.enqueue"),
	},
	{
		"category_name": "Shell and processes",
		"allowed_by_default": 0,
		"description": "The operating system, the interpreter and shell commands.",
		"names": _rows(MODULE, "os", "sys", "subprocess", "signal", "pty", "atexit", "platform", "webbrowser")
		+ _rows(FUNCTION, "frappe.utils.execute_in_shell"),
	},
	{
		"category_name": "Files on the server",
		"allowed_by_default": 0,
		"description": "Reading and writing files on the server's disk.",
		"sanctioned_alternative": "The File DocType.",
		"names": _rows(BUILTIN, "open")
		+ _rows(MODULE, "io", "pathlib", "shutil", "tempfile", "glob")
		+ _rows(FUNCTION, "frappe.get_site_path"),
	},
	{
		"category_name": "Dynamic code and reflection",
		"allowed_by_default": 0,
		"description": "Running code built from text and reaching objects by name. "
		"A script approved for this category can reach anything, because the check cannot see through it.",
		"names": _rows(
			BUILTIN,
			"exec",
			"eval",
			"compile",
			"__import__",
			"getattr",
			"setattr",
			"delattr",
			"globals",
			"locals",
			"vars",
			"dir",
		)
		+ _rows(
			MODULE,
			"importlib",
			"pkgutil",
			"types",
			"inspect",
			"dis",
			"gc",
			"traceback",
			"pickle",
			"marshal",
			"shelve",
			"dill",
			"cloudpickle",
			"ast",
			"builtins",
			"runpy",
			"code",
			"codeop",
			"timeit",
			"pdb",
			"bdb",
			"operator",
			"ctypes",
			"cffi",
			"mmap",
		)
		+ _rows(FUNCTION, "frappe.get_attr", "frappe.get_module", "frappe.call", "frappe.safe_eval")
		+ _rows(SYNTAX, "dunder_attribute", "dunder_subscript"),
	},
	{
		"category_name": "Secrets",
		"allowed_by_default": 0,
		"description": "Site configuration, passwords and environment variables.",
		"names": _rows(
			FUNCTION,
			"frappe.conf",
			"frappe.local.conf",
			"frappe.get_site_config",
			"frappe.get_common_site_config",
			"frappe.get_conf",
			"frappe.utils.password.get_decrypted_password",
		)
		+ _rows(FUNCTION, "get_password", any_object=1)
		+ _rows(MODULE, "os.environ"),
	},
	{
		"category_name": "Identity and permissions",
		"allowed_by_default": 0,
		"description": "Acting as another user, granting roles and skipping permission checks.",
		"names": _rows(FUNCTION, "frappe.flags", "frappe.set_user", "frappe.cache")
		+ _rows(FUNCTION, "ignore_permissions", "add_roles", "db_update", any_object=1)
		+ _rows(SYNTAX, "permission_kwarg", "session_write"),
	},
	{
		"category_name": "Size limits",
		"allowed_by_default": 0,
		"description": "Multiplying by a constant above the threshold, which can exhaust memory.",
		"threshold": 50000,
		"names": _rows(SYNTAX, "large_multiplication"),
	},
]


def seed_script_import_categories():
	"""Create the role and each category that does not exist yet; existing categories are left as they are."""
	if not frappe.db.exists("Role", "Application Manager"):
		frappe.get_doc({"doctype": "Role", "role_name": "Application Manager", "desk_access": 1}).insert()
	for category in CATEGORIES:
		if not frappe.db.exists("Script Import Category", category["category_name"]):
			frappe.get_doc({"doctype": "Script Import Category", **category}).insert()
