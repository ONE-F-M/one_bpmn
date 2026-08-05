"""
WI-001793: memory settings move from the BPMN diagram onto the agent.

Conversation store, context window, the long-term-memory toggle, memory scope,
write mode and the distillation model were all stored as ``spiffworkflow:ai*``
attributes on the AI Agent Task shape — the distillation model only ever
reachable by hand-editing XML. They now live on the AI Agent Configuration,
where an admin can see and change them, and where a new reconciliation model
sits beside the distillation one.

This patch copies what each diagram already has onto the agent it links, so
behaviour is unchanged the moment the code lands:

1. Ensures every distillation model named in a diagram exists in the AI Model
   catalog. The field is a Link, and sites carry model ids that predate the
   catalog (e.g. claude-sonnet-4-5-20250929) — without this the copy would fail
   on exactly the agents that had a distill model configured. The credentials
   link is inferred from a sibling model of the same family so the new record is
   usable, not a stub.
2. Copies each AI shape's memory attributes onto its linked AI Agent
   Configuration, skipping any field the agent has already set.

The shape's attributes are deliberately left in place: dispatch reads the agent
first and falls through to them, so a diagram imported from another site (or
restored from an older export) keeps working until its agent is configured.

Idempotent: a field already set on the agent is never overwritten, and re-runs
create nothing new.
"""

import re

import frappe

# Shape attribute -> (config fieldname, coercion). Mirrors _SHAPE_TO_CONFIG in
# agents/agent_config_resolver.py; kept explicit here so the patch is readable
# on its own and cannot drift silently if that map grows.
_ATTR_TO_FIELD = {
	"aiConversationStore": ("conversation_store", lambda v: v.strip()),
	"aiContextMaxMessages": ("context_max_messages", lambda v: frappe.utils.cint(v)),
	"aiLongTermMemory": (
		"long_term_memory",
		lambda v: "Enabled" if v.strip().lower() in ("1", "true", "yes", "on", "enabled") else "Disabled",
	),
	"aiMemoryScope": ("memory_scope", lambda v: v.strip()),
	"aiMemoryWriteMode": ("memory_write_mode", lambda v: v.strip()),
	"aiMemoryDistillModel": ("memory_distill_model", lambda v: v.strip()),
	# Legacy: diagrams predating aiMemoryWriteMode carry aiMemoryAutoWrite, which
	# the dispatcher reads as "distilled". Record the EFFECTIVE mode so the agent
	# shows what actually runs — the Memory Models fields only surface on the
	# distilled path, so a blank mode would hide a distill model that is in use.
	"aiMemoryAutoWrite": (
		"memory_write_mode",
		lambda v: "distilled" if v.strip().lower() in ("1", "true", "yes", "on", "enabled") else "",
	),
}

# When both are present the explicit mode wins, so it must be applied first.
_ATTR_ORDER = (
	"aiConversationStore",
	"aiContextMaxMessages",
	"aiLongTermMemory",
	"aiMemoryScope",
	"aiMemoryWriteMode",
	"aiMemoryAutoWrite",
	"aiMemoryDistillModel",
)

# Attributes that name an AI Model and therefore need a catalog record.
_MODEL_ATTRS = ("aiMemoryDistillModel",)


def execute():
	shapes = _memory_shapes()
	if not shapes:
		return

	_ensure_models_in_catalog(shapes)

	migrated = 0
	for shape in shapes:
		if _apply_to_agent(shape):
			migrated += 1

	if migrated:
		frappe.db.commit()


def _memory_shapes() -> list[dict]:
	"""Every AI shape carrying memory attributes, with its linked agent.

	Parsed with a regex rather than an XML parser on purpose: some stored
	diagrams contain base64-wrapped HTML and other payloads that have tripped
	strict parsing before, and a patch must not fail on one bad map.
	"""
	out = []
	for model in frappe.get_all("BPMN Process Model", fields=["name", "bpmn_xml"], limit_page_length=0):
		xml = model.bpmn_xml or ""
		if "spiffworkflow:ai" not in xml:
			continue
		for tag in re.finditer(r"<bpmn:\w+\b([^>]*)>", xml):
			attrs = tag.group(1)
			if "spiffworkflow:aiAgentConfig" not in attrs:
				continue
			values = {}
			for attr in _ATTR_TO_FIELD:
				found = re.search(rf'spiffworkflow:{attr}="([^"]*)"', attrs)
				if found and found.group(1).strip():
					values[attr] = found.group(1)
			if not values:
				continue
			config = re.search(r'spiffworkflow:aiAgentConfig="([^"]*)"', attrs)
			config_name = (config.group(1) or "").strip() if config else ""
			if not config_name:
				continue
			out.append({"model": model.name, "config": config_name, "values": values})
	return out


def _ensure_models_in_catalog(shapes: list[dict]) -> None:
	"""Create AI Model records for any model id a diagram names but the catalog lacks."""
	wanted = {
		shape["values"][attr].strip()
		for shape in shapes
		for attr in _MODEL_ATTRS
		if shape["values"].get(attr, "").strip()
	}
	for model_id in sorted(wanted):
		if frappe.db.exists("AI Model", model_id):
			continue
		credentials = _infer_credentials(model_id)
		if not credentials:
			# Nothing sensible to link it to — leave it out and let the copy skip
			# this field rather than create an unusable catalog row.
			frappe.log_error(
				title="WI-001793: could not add memory model to the catalog",
				message=f"{model_id} has no obvious AI Provider Credentials; its agent keeps today's fallback.",
			)
			continue
		frappe.get_doc(
			{"doctype": "AI Model", "model_name": model_id, "ai_provider_credentials": credentials}
		).insert(ignore_permissions=True)


def _infer_credentials(model_id: str) -> str | None:
	"""Credentials of an existing catalog model sharing this one's family prefix.

	``claude-sonnet-4-5-20250929`` matches ``claude-sonnet-5`` / ``claude-opus-5``
	on the ``claude`` prefix and inherits their Anthropic link. Falls back to any
	enabled credential whose provider name looks like the family.
	"""
	family = (model_id.split("-", 1)[0] or "").strip().lower()
	if not family:
		return None

	for row in frappe.get_all(
		"AI Model",
		filters={"ai_provider_credentials": ["is", "set"]},
		fields=["name", "ai_provider_credentials"],
		order_by="name asc",
		limit_page_length=0,
	):
		if row.name.lower().startswith(family):
			return row.ai_provider_credentials

	for row in frappe.get_all("AI Provider Credentials", fields=["name"], limit_page_length=0):
		if family in row.name.lower():
			return row.name
	return None


def _apply_to_agent(shape: dict) -> bool:
	"""Copy one shape's memory attributes onto its agent. Returns True if anything changed."""
	if not frappe.db.exists("AI Agent Configuration", shape["config"]):
		return False

	doc = frappe.get_doc("AI Agent Configuration", shape["config"])
	changed = []
	for attr in _ATTR_ORDER:
		if attr not in shape["values"]:
			continue
		raw = shape["values"][attr]
		field, coerce = _ATTR_TO_FIELD[attr]
		# Never overwrite a value an admin has already set on the agent.
		if doc.get(field) not in (None, "", 0):
			continue
		value = coerce(raw)
		if not value:
			continue
		if field == "memory_distill_model" and not frappe.db.exists("AI Model", value):
			continue  # catalog entry could not be created — keep today's fallback
		doc.set(field, value)
		changed.append(field)

	if not changed:
		return False

	# db_set avoids doc.save(), which would fire the Edit_Action message and
	# re-provision every Live chat agent during a migrate. Nothing about the
	# agent's behaviour changes here — the values already applied via the XML.
	doc.db_set({f: doc.get(f) for f in changed}, update_modified=False)
	return True
