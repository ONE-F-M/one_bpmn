# Copyright (c) 2026, kartiksharma9319@gmail.com and contributors
# For license information, please see license.txt

"""Real-time collaboration on the BPMN process model editor (server side).

Several users can have one BPMN Process Model open at once. This module lets an
editing client

* announce that it is editing (presence) and see who else is,
* publish a live diagram change that is broadcast to the other editors,
* save the diagram with a revision check so a stale save is refused instead of
  silently overwriting someone else's work.

Realtime scoping
----------------
Every event is published to the model's Frappe *doc room*
(``frappe.publish_realtime(..., doctype="BPMN Process Model", docname=<model>)``).
Only sockets that subscribed to that document (``doc_subscribe``, which Frappe
only allows with read permission on the model) receive it, so events never leak
to users who do not have that model open.

Frappe's realtime layer cannot leave one socket out of a room, so the sender is
identified in every payload (``sender.user`` and the caller's ``client_id``) and
the client ignores events carrying its own ``client_id``.

Revision
--------
``BPMN Process Model.diagram_revision`` increases by one on every change of the
diagram XML (see ``BPMNProcessModel.bump_diagram_revision``). It is separate from
``version``, which is the deployment version.
"""

import json
import time

import frappe
from frappe import _
from frappe.utils import cint

MODEL_DOCTYPE = "BPMN Process Model"

# Realtime event names
EVENT_DIAGRAM_CHANGE = "bpmn_diagram_change"
EVENT_DIAGRAM_SAVED = "bpmn_diagram_saved"
EVENT_PRESENCE = "bpmn_editor_presence"
EVENT_AWARENESS = "bpmn_diagram_awareness"

# Presence shares the cache entry that ``editability.check_and_update_editor_lock``
# maintains ({user: last heartbeat epoch seconds}) so both stay consistent.
PRESENCE_CACHE_KEY = "bpmn_editor_lock:{}"
PRESENCE_TTL_SECONDS = 45
PRESENCE_CACHE_EXPIRY_SECONDS = 60

# A live change is a small delta, not a whole diagram. Whole diagrams go through save_diagram.
MAX_CHANGE_BYTES = 256 * 1024


# Awareness (who is looking at / editing which element) is ephemeral: relayed, never stored.
AWARENESS_MODES = ("editing", "viewing", "idle")
MAX_AWARENESS_SELECTION = 50
MAX_ELEMENT_ID_LENGTH = 140


class StaleDiagramRevision(frappe.ValidationError):
	"""The diagram was changed by someone else after the caller loaded it."""

	http_status_code = 409


# ----------------------------------------------------------------------------
# Helpers
# ----------------------------------------------------------------------------


def _load_model(model_name: str, ptype: str):
	"""Return the model, raising if it is missing or the user lacks ``ptype`` permission."""
	if not model_name:
		frappe.throw(_("Model name is required"))
	if frappe.session.user == "Guest":
		frappe.throw(_("Please log in to collaborate on a process model"), frappe.PermissionError)
	if not frappe.db.exists(MODEL_DOCTYPE, model_name):
		frappe.throw(_("BPMN Process Model {0} not found").format(model_name), frappe.DoesNotExistError)
	doc = frappe.get_doc(MODEL_DOCTYPE, model_name)
	doc.check_permission(ptype)
	return doc


def _is_editable(doc) -> bool:
	"""Same gate as ``BPMNProcessModel.validate_is_editable`` for an existing model."""
	if frappe.session.user == "Administrator":
		return True
	from processa.api.editability import annotate_model_editability

	row = {"process_implementation": doc.process_implementation}
	annotate_model_editability([row])
	return bool(row.get("implementation_editable"))


def _assert_can_edit(doc) -> None:
	"""Require write permission and an unlocked model (Process Implementation / site gates)."""
	doc.check_permission("write")
	if not _is_editable(doc):
		from processa.api.editability import NOT_EDITABLE_REASON

		frappe.throw(_(NOT_EDITABLE_REASON), frappe.PermissionError)


def _can_edit(doc) -> bool:
	try:
		_assert_can_edit(doc)
	except frappe.PermissionError:
		return False
	return True


def _current_revision(model_name: str, for_update: bool = False) -> int:
	return cint(frappe.db.get_value(MODEL_DOCTYPE, model_name, "diagram_revision", for_update=for_update))


def _sender(client_id: str | None = None) -> dict:
	user = frappe.session.user
	return {"user": user, "full_name": frappe.utils.get_fullname(user), "client_id": client_id}


def _read_editors(model_name: str) -> dict:
	"""Active editors as ``{user: last_heartbeat}``; expired heartbeats are dropped."""
	now = time.time()
	raw = frappe.cache.get_value(PRESENCE_CACHE_KEY.format(model_name)) or {}
	return {user: ts for user, ts in raw.items() if now - ts < PRESENCE_TTL_SECONDS}


def _write_editors(model_name: str, editors: dict) -> None:
	# Staleness is enforced on read (PRESENCE_TTL_SECONDS), so no cache expiry is needed.
	frappe.cache.set_value(PRESENCE_CACHE_KEY.format(model_name), editors)


def _editor_details(users) -> list[dict]:
	"""``name``, ``full_name`` and ``user_image`` for each user (same shape as the editor lock)."""
	users = list(users)
	if not users:
		return []
	return frappe.get_all(
		"User",
		filters={"name": ["in", users]},
		fields=["name", "full_name", "user_image"],
		order_by="full_name asc",
	)


def _broadcast(event: str, model_name: str, payload: dict, after_commit: bool = False) -> None:
	"""Publish to everyone subscribed to this model's doc room, and nobody else."""
	frappe.publish_realtime(
		event,
		payload,
		doctype=MODEL_DOCTYPE,
		docname=model_name,
		after_commit=after_commit,
	)


def _announce_presence(model_name: str, action: str, editors: dict, client_id: str | None) -> None:
	_broadcast(
		EVENT_PRESENCE,
		model_name,
		{
			"model": model_name,
			"action": action,
			"user": frappe.session.user,
			"client_id": client_id,
			"editors": _editor_details(editors),
		},
	)


# ----------------------------------------------------------------------------
# Presence
# ----------------------------------------------------------------------------


@frappe.whitelist(methods=["POST"])
def join_model(model_name: str, client_id: str = None) -> dict:
	"""Register the caller as an active editor of a model. Also the heartbeat.

	Call when the editor opens a model and then every ~20-30 seconds; a user whose
	last heartbeat is older than 45 seconds is treated as gone. Other editors get an
	``bpmn_editor_presence`` event when a user newly joins.

	Args:
		model_name: Name of the BPMN Process Model.
		client_id: Opaque id the client generated for this browser tab.

	Returns:
		dict with ``model``, ``revision`` (current diagram revision), ``can_edit``
		and ``editors`` (every active editor including the caller).
	"""
	doc = _load_model(model_name, "read")
	user = frappe.session.user

	editors = _read_editors(model_name)
	newly_joined = user not in editors
	editors[user] = time.time()
	_write_editors(model_name, editors)

	if newly_joined:
		_announce_presence(model_name, "joined", editors, client_id)

	return {
		"model": model_name,
		"revision": cint(doc.diagram_revision),
		"can_edit": _can_edit(doc),
		"editors": _editor_details(editors),
	}


@frappe.whitelist(methods=["POST"])
def leave_model(model_name: str, client_id: str = None) -> dict:
	"""Remove the caller from the active editors and tell the others."""
	_load_model(model_name, "read")
	user = frappe.session.user

	editors = _read_editors(model_name)
	if editors.pop(user, None) is not None:
		_write_editors(model_name, editors)
		_announce_presence(model_name, "left", editors, client_id)

	return {"model": model_name, "editors": _editor_details(editors)}


@frappe.whitelist(methods=["POST"])
def set_awareness(
	model_name: str, client_id: str, mode: str = "viewing", selection=None, left: int = 0, reply: int = 0
) -> dict:
	"""Relay what the caller is doing on the canvas to everyone with the model open.

	Read permission is enough (viewers show up too); "editing" is downgraded to
	"viewing" unless the caller may edit. Nothing is stored. ``left`` announces a
	departure; ``reply`` marks an answer to a newcomer so it is not answered again.
	"""
	doc = _load_model(model_name, "read")
	if not client_id:
		frappe.throw(_("client_id is required"))
	if isinstance(selection, str):
		selection = frappe.parse_json(selection)
	selection = [
		element_id[:MAX_ELEMENT_ID_LENGTH]
		for element_id in (selection or [])[:MAX_AWARENESS_SELECTION]
		if isinstance(element_id, str)
	]
	if mode not in AWARENESS_MODES:
		mode = "viewing"
	if mode == "editing" and not _can_edit(doc):
		mode = "viewing"

	_broadcast(
		EVENT_AWARENESS,
		model_name,
		{
			"model": model_name,
			"client_id": client_id,
			"user": frappe.session.user,
			"full_name": frappe.utils.get_fullname(frappe.session.user),
			"mode": mode,
			"selection": selection,
			"left": bool(cint(left)),
			"reply": bool(cint(reply)),
		},
	)
	return {"ok": True}


@frappe.whitelist()
def get_active_editors(model_name: str) -> list[dict]:
	"""Users currently editing the model (heartbeat within the last 45 seconds)."""
	_load_model(model_name, "read")
	return _editor_details(_read_editors(model_name))


@frappe.whitelist()
def get_model_state(model_name: str) -> dict:
	"""Current diagram, its revision and who is editing - used to (re)sync a client."""
	doc = _load_model(model_name, "read")
	return {
		"model": model_name,
		"revision": cint(doc.diagram_revision),
		"bpmn_xml": doc.bpmn_xml,
		"modified": str(doc.modified),
		"modified_by": doc.modified_by,
		"can_edit": _can_edit(doc),
		"editors": _editor_details(_read_editors(model_name)),
	}


# ----------------------------------------------------------------------------
# Live changes and saving
# ----------------------------------------------------------------------------


@frappe.whitelist(methods=["POST"])
def publish_diagram_change(model_name: str, base_revision: int, change, client_id: str = None) -> dict:
	"""Broadcast a live, unsaved diagram change to the other editors of the model.

	Nothing is written to the database. If ``base_revision`` is no longer the model's
	revision (someone saved in between) the change is NOT broadcast and the caller is
	told it is stale, so it can fetch ``get_model_state`` and rebase.

	Args:
		model_name: Name of the BPMN Process Model.
		base_revision: The ``diagram_revision`` the caller's diagram is based on.
		change: The change itself (object/array or JSON string); opaque to the server.
		client_id: Opaque id of the sending browser tab, echoed in the event.

	Returns:
		``{"ok": True, "stale": False, "revision": n}`` when broadcast, otherwise
		``{"ok": False, "stale": True, "current_revision": n}``.
	"""
	doc = _load_model(model_name, "write")
	_assert_can_edit(doc)

	if isinstance(change, str):
		try:
			change = frappe.parse_json(change)
		except Exception:
			frappe.throw(_("Invalid change: expected JSON."), title=_("Validation Error"))
	if not change:
		frappe.throw(_("A change is required"))
	if len(json.dumps(change, default=str)) > MAX_CHANGE_BYTES:
		frappe.throw(_("The change is too large to broadcast. Save the diagram instead."))

	current = _current_revision(model_name)
	if cint(base_revision) != current:
		return {"ok": False, "stale": True, "current_revision": current}

	# A user who is publishing is plainly still editing: keep their presence fresh.
	editors = _read_editors(model_name)
	editors[frappe.session.user] = time.time()
	_write_editors(model_name, editors)

	_broadcast(
		EVENT_DIAGRAM_CHANGE,
		model_name,
		{
			"model": model_name,
			"revision": current,
			"change": change,
			"sender": _sender(client_id),
			"client_id": client_id,
			"sent_at": str(frappe.utils.now_datetime()),
		},
	)
	return {"ok": True, "stale": False, "revision": current}


@frappe.whitelist(methods=["POST"])
def save_diagram(
	model_name: str, xml_content: str, base_revision: int, client_id: str = None, description: str = None
) -> dict:
	"""Save the diagram if - and only if - nobody changed it since ``base_revision``.

	The stored revision is read under a row lock, so two simultaneous saves cannot
	both pass the check. A stale save raises ``StaleDiagramRevision`` (HTTP 409) and
	changes nothing. On success the others receive ``bpmn_diagram_saved``.

	Args:
		model_name: Name of the BPMN Process Model.
		xml_content: Full BPMN XML.
		base_revision: The ``diagram_revision`` the caller loaded (from ``join_model``,
			``get_model_state`` or the previous ``save_diagram``).
		client_id: Opaque id of the saving browser tab, echoed in the event.
		description: Optional description to store with the model.

	Returns:
		``{"saved": True, "name", "revision", "modified"}``.
	"""
	if not xml_content:
		frappe.throw(_("XML content is required"))
	if base_revision is None or base_revision == "":
		frappe.throw(_("base_revision is required to save a shared diagram"))

	doc = _load_model(model_name, "write")
	_assert_can_edit(doc)

	current = _current_revision(model_name, for_update=True)
	if cint(base_revision) != current:
		modified_by = frappe.db.get_value(MODEL_DOCTYPE, model_name, "modified_by")
		raise StaleDiagramRevision(
			_(
				"{0} changed this diagram (revision {1}) after you opened it (revision {2}). "
				"Reload the latest version before saving."
			).format(frappe.utils.get_fullname(modified_by) if modified_by else _("Someone"), current, cint(base_revision))
		)

	from processa.api.process_maps import save_process_model

	save_process_model(model_name, xml_content, description=description)

	revision = _current_revision(model_name)
	modified = str(frappe.db.get_value(MODEL_DOCTYPE, model_name, "modified"))

	_broadcast(
		EVENT_DIAGRAM_SAVED,
		model_name,
		{
			"model": model_name,
			"revision": revision,
			"previous_revision": cint(base_revision),
			"saved_by": _sender(client_id),
			"client_id": client_id,
			"modified": modified,
		},
		after_commit=True,
	)
	return {"saved": True, "name": model_name, "revision": revision, "modified": modified}
