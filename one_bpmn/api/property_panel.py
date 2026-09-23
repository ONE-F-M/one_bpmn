# Copyright (c) 2026, ONE BPMN and contributors
# For license information, please see license.txt
#
# "Release Property Panel" — available from the Processa canvas Actions menu
# only on a Production instance (Processa Settings → Instance Type =
# "Production").
#
# It lets an authorised user edit the properties of flow objects on a locked
# process map without an editable Process Implementation. This began as
# "Reassign User Task", which could only change the six Assignment
# Configuration attributes of a userTask; releasing the whole panel is the same
# mechanism widened, with the carve-outs below taking the place of that single
# whitelist.
#
# WHAT STAYS LOCKED, AND WHY
# --------------------------
# The rule is that a released panel may change what a step DOES, never what the
# map IS. An edit that cannot be undone by editing again — one that breaks
# compilation, orphans a reference, or silently discards other settings — stays
# blocked even here:
#
#   * Script tasks and AI Agent tasks — code and prompts are not panel edits.
#     Their editors already open read-only while the canvas is read-only.
#   * Any attribute naming a script (preScript, postScript, scriptFormat …) on
#     any element, for the same reason.
#   * ``id`` — every sequence flow, the compiled spec and every running
#     instance reference it. Changing it dead-ends the map.
#   * ``serviceType`` — switching the kind of a Service Task makes its other
#     attributes meaningless, so the panel clears them. That is a silent
#     configuration loss on a live map.
#   * ``calledElement`` — repoints a Call Activity at a different process.
#   * ``default`` on a gateway — which flow is taken when no condition matches.
#     It is a reference to another element, and one that does not name a flow
#     off that gateway dead-ends the map.
#
# A sequence flow's condition and name ARE editable here. A wrong condition
# takes the wrong branch, which is a routing mistake and not a broken map: it
# still compiles, and editing again puts it right. Releasing the panel is for
# exactly this kind of non-breaking correction, and a condition that can only
# be fixed by unlocking the whole process is the wrong side of that line.
#
# Changes are audited by the document's own version history and nothing else.
# BPMN Process Model has track_changes enabled, so saving the map records a
# Version carrying the bpmn_xml before and after.
#
# Each change is written to the XML immediately, but the map is recompiled
# ("Deploy") only ONCE — when the editor locks the panel again — so a whole
# session of edits triggers a single Deploy. NOTE: recompiling rebuilds the
# model's serialized spec, so only NEW process instances pick up the change;
# already-running instances keep their own snapshot from start time.

import frappe
from frappe import _
from lxml import etree

from one_bpmn.api.editability import _is_production_instance

etree.register_namespace("xsi", "http://www.w3.org/2001/XMLSchema-instance")

SPIFF_NS = "http://spiffworkflow.org/bpmn/schema/1.0/core"

# Elements whose properties are never editable here, by BPMN local name.
LOCKED_ELEMENTS = ("scriptTask",)

BPMN_NS = "http://www.omg.org/spec/BPMN/20100524/MODEL"
XSI_NS = "http://www.w3.org/2001/XMLSchema-instance"

# A flow's condition is a child element, not an attribute, so it is read and
# written by name here rather than through the attribute path below.
CONDITION = "conditionExpression"

AI_AGENT_SERVICE_TYPE = "ai_agent"

# Attributes that stay locked on every element. See the note above.
LOCKED_ATTRS = frozenset({"id", "serviceType", "calledElement", "default"})

# Attributes written as plain BPMN attributes; everything else goes into the
# spiffworkflow namespace, which is where the properties panel keeps its values.
PLAIN_ATTRS = frozenset({"name"})

VALID_MODES = ("", "User", "DocField", "Round Robin", "Load Balancing", "Table Field")


def _require_production_instance():
	"""Guard: the property panel is only released on a Production instance.

	Enforced here rather than only in the frontend, so the gate holds even if
	the Actions menu is bypassed.
	"""
	if not _is_production_instance():
		frappe.throw(
			_("Release Property Panel is only available on a Production instance (Processa Settings → Instance Type)."),
			title=_("Not Available"),
		)


def locked_reason(node) -> str | None:
	"""Why this element's properties may not be edited, or None if they may."""
	tag = etree.QName(node).localname
	if tag == "scriptTask":
		return _("Script tasks stay read-only.")
	if tag == "serviceTask" and node.get(f"{{{SPIFF_NS}}}serviceType") == AI_AGENT_SERVICE_TYPE:
		return _("AI Agent tasks stay read-only.")
	return None


def blocked_attr(name: str) -> bool:
	"""True for an attribute that could break the map rather than reconfigure it."""
	return name in LOCKED_ATTRS or "script" in name.lower()


def _condition_node(node):
	return node.find(f"{{{BPMN_NS}}}{CONDITION}")


def _read(node, names) -> dict:
	out = {}
	for name in names:
		if name == CONDITION:
			found = _condition_node(node)
			out[name] = (found.text or "").strip() if found is not None else ""
			continue
		key = name if name in PLAIN_ATTRS else f"{{{SPIFF_NS}}}{name}"
		out[name] = node.get(key) or ""
	return out


def _write_condition(node, value):
	"""Set, replace or remove the flow's condition.

	Written the way bpmn-js writes one — a tFormalExpression — so the map reads
	the same whether the condition was drawn or corrected here. The schema puts
	conditionExpression last among a flow's children, so a new one is appended.
	"""
	found = _condition_node(node)
	if value in (None, ""):
		if found is not None:
			node.remove(found)
		return
	if found is None:
		found = etree.SubElement(node, f"{{{BPMN_NS}}}{CONDITION}")
		prefix = next((p for p, ns in node.nsmap.items() if ns == BPMN_NS and p), None)
		found.set(f"{{{XSI_NS}}}type", f"{prefix}:tFormalExpression" if prefix else "tFormalExpression")
	found.text = str(value)


@frappe.whitelist(methods=["POST"])
def update_element_properties(model_name: str, element_id: str, properties) -> dict:
	"""Write panel properties onto one flow object in a process map.

	Does NOT recompile — the editor calls deploy_property_changes() once when
	the panel is locked again, so a session is one Deploy.

	Args:
		model_name: BPMN Process Model name.
		element_id: BPMN element id of the flow object.
		properties: dict (or JSON string) of attribute → value. Unprefixed
			names are written into the spiffworkflow namespace, except
			``name``. Empty values remove the attribute.
	"""
	_require_production_instance()

	if not model_name or not element_id:
		frappe.throw(_("Process map name and element id are required."))

	properties = frappe.parse_json(properties) if isinstance(properties, str) else (properties or {})
	if not isinstance(properties, dict):
		frappe.throw(_("properties must be a JSON object."))

	refused = sorted(n for n in properties if blocked_attr(n))
	if refused:
		frappe.throw(
			_("These properties cannot be changed from a released panel: {0}").format(", ".join(refused))
		)
	if "assigneeMode" in properties and (properties.get("assigneeMode") or "") not in VALID_MODES:
		frappe.throw(_("Invalid Assignment Mode: {0}").format(properties.get("assigneeMode")))

	doc = frappe.get_doc("BPMN Process Model", model_name)
	doc.check_permission("write")

	xml = doc.bpmn_xml or ""
	if not xml.strip():
		frappe.throw(_("This process map has no BPMN content."))

	root = etree.fromstring(xml.encode("utf-8"))
	nodes = root.xpath("//*[@id=$eid]", eid=element_id)
	if not nodes:
		frappe.throw(_("Element '{0}' was not found in this process map.").format(element_id))
	node = nodes[0]

	reason = locked_reason(node)
	if reason:
		frappe.throw(reason, title=_("Read-only"))
	if CONDITION in properties and etree.QName(node).localname != "sequenceFlow":
		frappe.throw(_("Only a sequence flow carries a condition."))

	names = list(properties)
	before = _read(node, names)

	for name in names:
		value = properties.get(name)
		if name == CONDITION:
			_write_condition(node, value)
			continue
		key = name if name in PLAIN_ATTRS else f"{{{SPIFF_NS}}}{name}"
		if value in (None, ""):
			node.attrib.pop(key, None)
		else:
			node.set(key, str(value))

	after = _read(node, names)
	if before == after:
		return {"updated": False, "element_id": element_id, "redeployed": False}

	doc.bpmn_xml = etree.tostring(root, xml_declaration=True, encoding="UTF-8").decode("utf-8")
	# Trusted, attribute-scoped change — permitted even on locked processes
	# (the same flag used by import_bpmn / compile_process_model).
	doc.flags.skip_editability_check = True
	doc.save()

	return {
		"updated": True,
		"element_id": element_id,
		"element_label": node.get("name") or element_id,
		"properties": after,
	}


@frappe.whitelist(methods=["POST"])
def deploy_property_changes(model_name: str) -> dict:
	"""Recompile a process map once after a session of panel edits.

	Called when the editor locks the panel again, so a whole session triggers a
	single Deploy instead of one per element.

	Best-effort: each change is already saved, and saving is what records it in
	the version history, so a recompile failure never loses an edit — the user
	can Deploy manually.
	"""
	_require_production_instance()

	if not model_name:
		frappe.throw(_("Process map name is required."))
	frappe.has_permission("BPMN Process Model", "write", model_name, throw=True)

	xml = frappe.db.get_value("BPMN Process Model", model_name, "bpmn_xml")
	root = etree.fromstring(xml.encode("utf-8"))
	# A non-executable map is never deployed, so its saved edits are already final.
	if not any(
		p.get("isExecutable", "").strip().lower() == "true" for p in root.iter(f"{{{BPMN_NS}}}process")
	):
		return {"redeployed": False, "deploy_error": None}

	redeployed = False
	deploy_error = None
	try:
		from one_bpmn.api.compilation import compile_process_model

		compile_process_model(model_name)
		redeployed = True
	except Exception:
		deploy_error = _("Automatic redeploy failed — click Deploy to apply the changes to new instances.")
		frappe.log_error(frappe.get_traceback(), "deploy_property_changes: auto-deploy failed")

	return {"redeployed": redeployed, "deploy_error": deploy_error}
