"""ProsAlly's map Server Script functions and the model, XML and confirmation basics its tools share."""

import re
from xml.etree import ElementTree as ET

import frappe
from frappe import _

from processa.ai_agent_memory.text_clean import strip_html
from processa.ai_agent_registry.definitions.shared.helpers import format_history
from processa.ai_agent_registry.doctype.ai_agent_configuration.ai_agent_configuration import get_agent_config
from processa.processa_engine.agent_runtime.llm_factory import get_llm_adapter_from_settings
from processa.processa_engine.agent_runtime.turn_state import run_sync

AGENT_ID = "prosally_agent"

# Whole replies that approve a pending confirmation, after punctuation and "please" or "thanks" are dropped.
AFFIRMATIONS = frozenset(
	{
		"yes",
		"y",
		"yeah",
		"yep",
		"yup",
		"sure",
		"ok",
		"okay",
		"alright",
		"all right",
		"go",
		"go ahead",
		"yes go ahead",
		"ok go ahead",
		"okay go ahead",
		"proceed",
		"yes proceed",
		"ok proceed",
		"do it",
		"yes do it",
		"do",
		"just do it",
		"go for it",
		"draw it",
		"yes draw it",
		"confirm",
		"confirmed",
		"yes confirm",
		"sounds good",
		"looks good",
		"yes sounds good",
		"yes looks good",
		"perfect",
		"correct",
		"yes correct",
		"thats right",
		"yes thats right",
		"absolutely",
		"of course",
	}
)
# Replies starting with one of these turn a pending confirmation down.
DECLINES = ("no", "nope", "nah", "wait", "change", "not yet", "hold on", "stop", "dont", "do not", "cancel")
_POLITE_WORDS = re.compile(r"\b(please|thanks|thank you)\b")

NS = {
	"bpmn": "http://www.omg.org/spec/BPMN/20100524/MODEL",
	"bpmndi": "http://www.omg.org/spec/BPMN/20100524/DI",
	"dc": "http://www.omg.org/spec/DD/20100524/DC",
	"di": "http://www.omg.org/spec/DD/20100524/DI",
	"spiffworkflow": "http://spiffworkflow.org/bpmn/schema/1.0/core",
	"custom": "http://custom/text-style",
	"camunda": "http://camunda.org/schema/1.0/bpmn",
}

STEP_TAGS = tuple(
	"{" + NS["bpmn"] + "}" + tag for tag in ("task", "userTask", "scriptTask", "serviceTask", "manualTask", "businessRuleTask")
)

DIAGRAM_REPLIES = ("BPMN_MODIFIED", "BPMN_GENERATED")
DIAGRAM_VERSION_SUFFIX = re.compile(r"\s+-\s+v\d+\s*$", re.I)
MEMORY_NOTES_LIMIT = 8
MEMORY_NOTES_HEADER = "Notes from earlier work on this process:"
MEMORY_NOTES_PROVENANCE = "These were agreed in other conversations; they do not mean the diagram exists."
MEMORY_BACKEND = "direct_api"
REQUEST_STOPWORDS = frozenset(
	("create", "sub", "process", "subprocess", "step", "steps", "with", "that", "this", "from", "into", "inside", "when", "then", "should")
)

DMS_SOURCES_LIMIT = 4


def prosally_config() -> dict:
	"""ProsAlly's resolved agent configuration."""
	cfg = get_agent_config(AGENT_ID) or {}
	cfg.setdefault("agent_id", AGENT_ID)
	return cfg


def complete_sub_prompt(cfg: dict, sub_id: str, user: str, system: str | None = None, max_tokens=None) -> str:
	"""One model call with a sub-prompt as the system prompt, returning the reply text."""
	if system is None:
		system = ((cfg.get("sub_prompts") or {}).get(sub_id) or {}).get("prompt") or ""
	kwargs = {"system": system, "user": user}
	if max_tokens:
		kwargs["max_tokens"] = max_tokens
	return run_sync(get_llm_adapter_from_settings(cfg).complete(**kwargs)).text


def process_for_diagram(diagram_name: str, process_name: str = "") -> str:
	"""The Process the diagram names (version removed), else the one process_name names; "" when neither exists."""
	for candidate in (DIAGRAM_VERSION_SUFFIX.sub("", diagram_name or ""), process_name or ""):
		name = candidate.strip()
		if name and frappe.db.exists("Process", name):
			return name
	return ""


def _memory_fields(cfg: dict) -> dict:
	"""The memory fields of the agent's configuration record."""
	return frappe.db.get_value(
		"AI Agent Configuration",
		cfg.get("name"),
		[
			"long_term_memory",
			"memory_write_mode",
			"memory_token_budget",
			"memory_distill_model",
			"memory_reconcile_model",
		],
		as_dict=True,
	) or {}


def recall_process_memory(diagram_name: str, process_name: str = "") -> dict:
	"""The diagram's Process and the notes recalled for it and the requester, for the turn store."""
	from processa.ai_agent_memory.tools import memory_search
	from processa.ai_agent_memory.budget import DEFAULT_MEMORY_TOKEN_BUDGET, bound_memories_to_budget
	from processa.processa_engine.dispatch.common import cfg_truthy

	fields = _memory_fields(prosally_config())
	if not cfg_truthy(fields.get("long_term_memory")):
		return {"memory_process": "", "memory_notes": []}
	process = process_for_diagram(diagram_name, process_name)
	user = frappe.session.user if frappe.session.user != "Guest" else None
	rows = []
	# An empty query lists the key's newest rows: a confirmation turn's text matches nothing.
	if process:
		key = {"reference_doctype": "Process", "reference_name": process}
		rows += memory_search("Entity", key, "", limit=MEMORY_NOTES_LIMIT, ignore_permissions=True)  # notes keyed to the open process
	if user:
		rows += memory_search("User", {"user": user}, "", limit=MEMORY_NOTES_LIMIT, ignore_permissions=True)  # notes keyed to the session user
	notes = list(dict.fromkeys((r.get("content") or "").strip() for r in rows))
	budget = fields.get("memory_token_budget") or DEFAULT_MEMORY_TOKEN_BUDGET
	kept = bound_memories_to_budget([{"content": n} for n in notes if n], budget)
	return {"memory_process": process, "memory_notes": [r["content"] for r in kept]}


def memory_notes_block(turn: dict | None) -> str:
	"""The turn's recalled notes under their heading; "" when it has none."""
	notes = (turn or {}).get("memory_notes") or []
	if not notes:
		return ""
	return "\n".join([MEMORY_NOTES_HEADER, MEMORY_NOTES_PROVENANCE] + ["- " + n for n in notes])


def document_sources_line(documents: list, lead: str) -> str:
	"""A line naming up to DMS_SOURCES_LIMIT distinct documents by code, title and type."""
	named = []
	for d in documents:
		label = " - ".join(filter(None, (d.get("document_code"), d.get("title")))) + f" ({d.get('document_type')})"
		if label not in named:
			named.append(label)
	return f"{lead}: " + "; ".join(named[:DMS_SOURCES_LIMIT])


def add_document_sources(text: str, intent: str | None, turn: dict | None) -> str:
	"""A drawn or changed diagram's reply with the documents the DMS search found named under it."""
	documents = (turn or {}).get("dms_documents") or []
	if intent not in DIAGRAM_REPLIES or not documents:
		return text
	return text.rstrip() + "\n\n" + document_sources_line(documents, _("Documents checked"))


def queue_process_memory(turn: dict, agent_result: dict | None) -> None:
	"""Queue distillation of a turn that drew or changed a diagram into its Process's memory."""
	process = (turn or {}).get("memory_process")
	intent = (agent_result or {}).get("intent")
	if intent not in DIAGRAM_REPLIES or frappe.flags.get("eval_origin"):
		return
	if not process:
		frappe.log_error(title="ProsAlly memory: write skipped", message="The diagram matched no Process.")
		return
	from processa.ai_agent_memory.model_resolution import resolve_memory_model

	cfg = prosally_config()
	own = _memory_fields(cfg)
	if own.get("memory_write_mode") != "distilled":
		frappe.log_error(
			title="ProsAlly memory: write skipped",
			message=f"Memory Write Mode is {own.get('memory_write_mode')!r}, process={process}.",
		)
		return
	distill_model = resolve_memory_model(
		own.get("memory_distill_model"), "default_memory_distill_model", cfg.get("ai_model")
	)
	reconcile_model = resolve_memory_model(
		own.get("memory_reconcile_model"), "default_memory_reconcile_model", cfg.get("ai_model")
	)
	source = "\n\n".join(
		[
			"[User message]\n" + (turn.get("user_text") or "")[:3000],
			"[ProsAlly reply]\n" + (agent_result.get("response") or ""),
			"[Conversation]\n" + format_history(turn.get("chat_history")),
		]
	)
	frappe.log_error(
		title="ProsAlly memory: write queued",
		message=f"process={process} model={distill_model} reconcile_model={reconcile_model}",
	)
	frappe.enqueue(
		"processa.ai_agent_memory.writeback.distill_and_write",
		queue="short",
		now=frappe.flags.in_test,
		agent_output=source,
		agent=AGENT_ID,
		scope="Entity",
		scope_key={"reference_doctype": "Process", "reference_name": process},
		provider_name=frappe.db.get_value("AI Model", distill_model, "provider") or cfg.get("ai_provider"),
		backend=MEMORY_BACKEND,
		model=distill_model,
		reconcile_model=reconcile_model,
		reconcile_provider=frappe.db.get_value("AI Model", reconcile_model, "provider") or cfg.get("ai_provider"),
		source_run=None,
		user=frappe.session.user if frappe.session.user != "Guest" else None,
		exclude_context=memory_notes_block(turn),
	)


def pending_confirmation(conversation: str) -> str:
	"""The action_intent the last Bot message asks the user to confirm; "" when that message is not a confirmation card."""
	last = frappe.get_all(
		"Chat Message",
		filters={"conversation": conversation, "message_type": "Bot"},
		fields=["metadata"],
		order_by="creation desc",
		limit=1,
	)
	meta = frappe.parse_json(last[0].metadata or "{}") if last else {}
	action = (meta.get("agent_result") or {}).get("action_intent")
	if meta.get("intent") != "CONFIRM" or not action:
		return ""
	return action


def answer_to_confirmation(conversation: str, user_text: str) -> dict:
	"""{"confirmed_action": ...} or {"declined_action": ...} when user_text answers the last Bot confirmation, else {}."""
	action = pending_confirmation(conversation)
	if not action:
		return {}
	reply = confirmation_reply(user_text)
	if reply == "yes":
		return {"confirmed_action": action}
	if reply == "no":
		return {"declined_action": action}
	return {}


def confirmation_reply(text: str) -> str:
	""" "yes" when text is a plain affirmation, "no" when it starts with a decline, else ""."""
	words = re.sub(r"[^a-z ]", " ", strip_html(text).lower().replace("'", ""))
	words = " ".join(_POLITE_WORDS.sub(" ", words).split())
	if words in AFFIRMATIONS:
		return "yes"
	if any(words == d or words.startswith(d + " ") for d in DECLINES):
		return "no"
	return ""


def quoted(name: str) -> str:
	return '"' + name + '"'


def register_namespaces() -> None:
	for prefix, uri in NS.items():
		ET.register_namespace(prefix, uri)
