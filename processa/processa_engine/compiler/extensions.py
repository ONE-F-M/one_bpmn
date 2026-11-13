# Copyright (c) 2026, one-fm and contributors
"""Shape configuration read from spiffworkflow:* attributes and embedded in the compiled spec."""


def extract_service_task_config(bpmn_xml: str) -> dict:
	"""The spiffworkflow:* attributes of each Service and Send Task, keyed by bpmn_id."""
	import xml.etree.ElementTree as _ET

	BPMN_NS = "http://www.omg.org/spec/BPMN/20100524/MODEL"
	SPIFF_NS = "http://spiffworkflow.org/bpmn/schema/1.0/core"

	try:
		root = _ET.fromstring(bpmn_xml.strip().encode("utf-8") if isinstance(bpmn_xml, str) else bpmn_xml)
	except Exception:
		return {}

	config = {}
	for tag in ("serviceTask", "sendTask"):
		for service_task in root.iter(f"{{{BPMN_NS}}}{tag}"):
			bpmn_id = service_task.get("id")
			if not bpmn_id:
				continue

			task_cfg = {}
			for attr_name, attr_value in service_task.attrib.items():
				if attr_name.startswith(f"{{{SPIFF_NS}}}"):
					key = attr_name[len(f"{{{SPIFF_NS}}}") :]
					task_cfg[key] = attr_value

			if task_cfg:
				config[bpmn_id] = task_cfg

	return config


def extract_adhoc_selector_config(bpmn_xml: str) -> dict:
	"""The spiffworkflow:* attributes of each ad-hoc sub-process tagged as an AI Task Selector, keyed by bpmn_id."""
	import xml.etree.ElementTree as _ET

	BPMN_NS = "http://www.omg.org/spec/BPMN/20100524/MODEL"
	SPIFF_NS = "http://spiffworkflow.org/bpmn/schema/1.0/core"

	try:
		root = _ET.fromstring(bpmn_xml.strip().encode("utf-8") if isinstance(bpmn_xml, str) else bpmn_xml)
	except Exception:
		return {}

	config = {}
	for adhoc in root.iter(f"{{{BPMN_NS}}}adHocSubProcess"):
		bpmn_id = adhoc.get("id")
		if not bpmn_id:
			continue

		task_cfg = {}
		for attr_name, attr_value in adhoc.attrib.items():
			if attr_name.startswith(f"{{{SPIFF_NS}}}"):
				key = attr_name[len(f"{{{SPIFF_NS}}}") :]
				task_cfg[key] = attr_value

		if task_cfg.get("serviceType") != "ai_task_selector":
			continue

		config[bpmn_id] = task_cfg

	return config


def extract_user_task_config(bpmn_xml: str) -> dict:
	"""The spiffworkflow:* attributes of each User Task, keyed by bpmn_id."""
	import xml.etree.ElementTree as _ET

	BPMN_NS = "http://www.omg.org/spec/BPMN/20100524/MODEL"
	SPIFF_NS = "http://spiffworkflow.org/bpmn/schema/1.0/core"

	try:
		root = _ET.fromstring(bpmn_xml.strip().encode("utf-8") if isinstance(bpmn_xml, str) else bpmn_xml)
	except Exception:
		return {}

	config = {}
	for user_task in root.iter(f"{{{BPMN_NS}}}userTask"):
		bpmn_id = user_task.get("id")
		if not bpmn_id:
			continue

		task_cfg = {}
		for attr_name, attr_value in user_task.attrib.items():
			if attr_name.startswith(f"{{{SPIFF_NS}}}"):
				key = attr_name[len(f"{{{SPIFF_NS}}}") :]
				task_cfg[key] = attr_value

		if task_cfg:
			config[bpmn_id] = task_cfg

	return config


def extract_script_task_config(bpmn_xml: str) -> dict:
	"""The Server Script each Script Task runs, keyed by bpmn_id; an inline script that looks like a record name counts."""
	import keyword as _kw
	import xml.etree.ElementTree as _ET

	BPMN_NS = "http://www.omg.org/spec/BPMN/20100524/MODEL"
	SPIFF_NS = "http://spiffworkflow.org/bpmn/schema/1.0/core"

	def _looks_like_python(text: str) -> bool:
		"""Return True if the text is likely inline Python (not a record name)."""
		if not text:
			return False
		py_chars = ("=", "(", ")", "{", "}", ":", "\n", ".", "import", "def ", "class ", "return")
		lower = text.strip().lower()
		if any(c in lower for c in py_chars):
			return True
		if lower in _kw.kwlist:
			return True
		return False

	try:
		root = _ET.fromstring(bpmn_xml.strip().encode("utf-8"))
	except Exception:
		return {}

	extensions = {}
	for elem in root.iter(f"{{{BPMN_NS}}}scriptTask"):
		bpmn_id = elem.get("id", "")
		if not bpmn_id:
			continue

		server_script = elem.get(f"{{{SPIFF_NS}}}serverScript", "").strip()

		if not server_script:
			script_elem = elem.find(f"{{{BPMN_NS}}}script")
			if script_elem is not None and script_elem.text:
				inline = script_elem.text.strip()
				if inline and not _looks_like_python(inline):
					server_script = inline

		if server_script:
			extensions[bpmn_id] = {"serverScript": server_script}

	return extensions
