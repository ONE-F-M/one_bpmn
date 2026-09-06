# Copyright (c) 2026, one-fm and contributors
# For license information, please see license.txt
"""
Agent provisioning helpers (WI-001621, WI-001620).

The agent-creation process calls these to carry an AI Agent Configuration
from Draft to Live. Each is a plain callable so the BPMN service tasks stay
thin and the same checks can run outside the process (e.g. a doctype
sanity check before go-live).
"""

import frappe
from frappe import _


class AgentValidationError(frappe.ValidationError):
	pass


# The checks validate_agent_config enforces, as DATA (WI-001649) — kept
# directly above the function so the two evolve together. The AI Assistant
# injects these as structured context at call time; nothing about the rules
# is written into its prompt as prose.
VALIDATION_RULES = (
	{"field": "agent_id", "rule": "required"},
	{"field": "system_prompt", "rule": "must be non-empty (or a description provided so the creation process can generate one)"},
	{"field": "ai_model", "rule": "must link an AI Model catalog record — the provider is derived from the model's credentials link (WI-001655)"},
	{"field": "ai_provider", "rule": "derived from the model; the derived provider must exist and be ENABLED; a live test call is made against it"},
	{"field": "chat_mode_label", "rule": "required for Chat agents unless the agent is mapped to a non-chat process map (WI-001997); must be unique across agents"},
)


def is_chat_startable_map(model_name: str) -> bool | None:
	"""Whether a BPMN Process Model can serve a chat surface (WI-001997).

	A chat-startable map begins with the chat pattern: a start event whose
	conditionalEventDefinition triggers on Chat Conversation insert
	(``spiffworkflow:triggerDoctype="Chat Conversation"``). Any other map — a
	record-triggered business process, a manually started one — runs fine as a
	process but can never receive a chat turn.

	Returns True/False for a map that exists, and None when the model is
	missing or has no XML, so callers can distinguish "not a chat map" from
	"no map at all" (a mapless Chat agent chats through the direct path).
	"""
	if not model_name:
		return None
	xml = frappe.db.get_value("BPMN Process Model", model_name, "bpmn_xml")
	if not xml:
		return None
	return 'triggerDoctype="Chat Conversation"' in xml


def is_a2a_startable_map(model_name: str) -> bool | None:
	"""Whether a BPMN Process Model can be started by an inbound A2A task
	(WI-001932): a start event whose conditionalEventDefinition triggers on
	A2A Task insert (``spiffworkflow:triggerDoctype="A2A Task"``). This is
	the Background-agent door — the A2A Task row is the trigger document
	and the instance's context, no Chat Conversation involved. Same
	substring test and same None semantics as is_chat_startable_map."""
	if not model_name:
		return None
	xml = frappe.db.get_value("BPMN Process Model", model_name, "bpmn_xml")
	if not xml:
		return None
	return 'triggerDoctype="A2A Task"' in xml


def validate_agent_config(config_name: str, test_provider: bool = True, require_prompt: bool = True) -> dict:
	"""Validate the six essentials of a chat agent configuration (WI-001621).

	Checks, in order: identity, system prompt, LLM credentials link, and —
	for chat agents — a chat mode label; lints the prompt for unresolved
	template markers; and (optionally) makes a live provider test call so a
	bad key or model is caught before provisioning rather than at first use.

	``require_prompt=False`` waives the empty-prompt error for provider-grant
	Background agents (WI-001650: e.g. "Platform Prompt Engineer" is a
	deliberate empty-prompt credentials grant) so the on-save revalidation
	can still run their live provider test.

	Returns {"ok": bool, "errors": [...], "warnings": [...]}; never raises,
	so the process can route a failure to Needs Attention.
	"""
	errors, warnings = [], []
	cfg = frappe.get_doc("AI Agent Configuration", config_name)

	# 1. Identity
	if not cfg.agent_id:
		errors.append(_("Agent ID is required."))

	# 2. System prompt
	if not (cfg.system_prompt or "").strip():
		if require_prompt:
			errors.append(_("System prompt is empty."))
	elif "{{" in cfg.system_prompt and "}}" in cfg.system_prompt:
		warnings.append(_("System prompt contains unresolved '{{ }}' markers."))

	# 3. Model + derived credentials (WI-001655: the model is the pick)
	if not cfg.get("ai_model"):
		errors.append(_("No AI Model is linked — pick one from the catalog."))
	if not cfg.ai_provider:
		errors.append(
			_("The linked AI Model names no AI Provider.")
			if cfg.get("ai_model")
			else _("No AI Provider could be derived.")
		)
	elif not frappe.db.exists("AI Provider", cfg.ai_provider):
		errors.append(_("The linked AI Provider does not exist."))
	elif cfg.get("ai_model") and not frappe.db.get_value(
		"AI Model", cfg.get("ai_model"), "enable_model"
	):
		# A provider is a name now and cannot be switched off. enable_model is
		# the only switch left, and it is the one that carries the connection.
		errors.append(_("The linked AI Model is disabled."))

	# 4. Chat-type essentials — a label, unless the agent is mapped to a
	# non-chat process map (WI-001997: a process-embedded agent never appears
	# in the chat picker, so it needs no label).
	if cfg.agent_type == "Chat" and not cfg.chat_mode_label:
		if is_chat_startable_map(cfg.process_model) is not False:
			errors.append(_("Chat agents need a chat mode label."))

	# 5. Live provider test call
	if test_provider and cfg.ai_provider and not errors:
		ok, detail = _provider_test_call(cfg)
		if not ok:
			errors.append(_("Provider test call failed: {0}").format(detail))

	return {"ok": not errors, "errors": errors, "warnings": warnings}


def _set_status(config_name: str, status: str, reason: str = None):
	"""Stamp the lifecycle stage. Needs Attention carries WHY (shown as a
	form intro banner + timeline comment); every other stage clears it."""
	values = {"lifecycle_status": status}
	if status == "Needs Attention":
		values["needs_attention_reason"] = (reason or "").strip() or "See the Error Log for details."
	else:
		values["needs_attention_reason"] = ""
	frappe.db.set_value("AI Agent Configuration", config_name, values, update_modified=False)
	if status == "Needs Attention":
		try:
			frappe.get_doc("AI Agent Configuration", config_name).add_comment(
				"Comment", "Needs Attention: " + values["needs_attention_reason"]
			)
		except Exception:
			pass  # a failed comment must never block the status stamp
	frappe.db.commit()


def provision_agent(config_name: str):
	"""AI Agent creation flow (WI-001620, reshaped by WI-001652).

	Carries a chat agent from Draft to Live: Validating -> Evaluating ->
	Live. Live means "details valid and tested" — NO diagram is created or
	required (WI-001652): diagrams are authored by people in the editor, and
	the config's process_model is a manual, informational link. Any failure
	lands the agent in Needs Attention with the reason logged; editing the
	configuration re-triggers this. Idempotent and safe to enqueue.
	"""
	cfg = frappe.get_doc("AI Agent Configuration", config_name)
	if cfg.agent_type != "Chat":
		# Background agents used to go Live from a controller hook
		# (apply_background_lifecycle), which pre-empted the creation process —
		# they were already Live before its Draft start condition was evaluated.
		# Every agent type now walks the map; this path stays chat-only because
		# nothing calls it, and the map is where go-live is decided.
		return

	try:
		_set_status(config_name, "Validating")
		result = validate_agent_config(config_name)
		if not result["ok"]:
			_set_status(config_name, "Needs Attention", reason="; ".join(result["errors"]))
			frappe.log_error(
				title=f"Agent provisioning: validation failed ({cfg.agent_id})",
				message="\n".join(result["errors"]),
			)
			return

		# Evaluating (WI-001609): generate + run a baseline suite from the
		# agent's sample prompts. A suite marked gate_deployment blocks Live
		# on failure; otherwise eval results are advisory and Live proceeds.
		suite_name = generate_eval_suite_for_agent(config_name)
		if suite_name:
			_set_status(config_name, "Evaluating")
			passed = _run_baseline_eval(suite_name)
			if passed is False and frappe.db.get_value("AI Eval Suite", suite_name, "gate_deployment"):
				_set_status(
					config_name, "Needs Attention",
					reason=f"Baseline eval suite '{suite_name}' did not pass and gates deployment.",
				)
				frappe.log_error(
					title=f"Agent provisioning: eval gate failed ({cfg.agent_id})",
					message=f"Baseline suite {suite_name} did not pass and gates deployment.",
				)
				return

		# The release gate. A conversational agent is reachable by
		# anyone who can open a chat box, so it does not ship untested against
		# injection, jailbreak, exfiltration and tool coercion — and it does not
		# ship on a map with the screening stage removed. Both fail CLOSED:
		# unlike the runtime screens, this authorises a release, and "cannot
		# prove it is safe" must mean no.
		from one_bpmn.agents.adversarial_gate import check as adversarial_check
		from one_bpmn.agents.conformance import validate_chat_map

		gate = adversarial_check(config_name)
		if not gate["ok"]:
			_set_status(config_name, "Needs Attention", reason=gate["reason"])
			frappe.log_error(
				title=f"Agent go-live blocked: adversarial gate ({cfg.agent_id})",
				message=gate["reason"],
			)
			return

		conformance = validate_chat_map(cfg.process_model)
		if not conformance["ok"]:
			reason = "; ".join(conformance["errors"])
			_set_status(config_name, "Needs Attention", reason=reason)
			frappe.log_error(
				title=f"Agent go-live blocked: map not conforming ({cfg.agent_id})",
				message=reason,
			)
			return

		_set_status(config_name, "Live")
	except Exception:
		_set_status(
			config_name, "Needs Attention",
			reason="The go-live flow crashed unexpectedly — see the Error Log "
			f"entry 'Agent provisioning failed ({cfg.agent_id})'.",
		)
		frappe.log_error(
			title=f"Agent provisioning failed ({cfg.agent_id})",
			message=frappe.get_traceback(),
		)


def needs_generated_prompt(config_name: str) -> bool:
	"""Gateway predicate (WI-001620): does this agent still need a system
	prompt drafted for it? True when the prompt is blank."""
	return not (frappe.db.get_value("AI Agent Configuration", config_name, "system_prompt") or "").strip()


def generate_system_prompt(config_name: str) -> str:
	"""Draft a system prompt for an agent from its name + description, using
	its own linked credentials, and save it on the configuration (WI-001620).

	Body of the creation process's auto-prompt branch: when an agent is
	created without a prompt, the process generates one here rather than
	failing validation.
	"""
	from one_bpmn.agents.executor.direct_api import _run_coro_blocking
	from one_bpmn.agents.llm_provider import get_llm_adapter_from_settings
	from one_bpmn.one_bpmn.doctype.ai_agent_configuration.ai_agent_configuration import get_agent_config

	cfg = frappe.get_doc("AI Agent Configuration", config_name)
	meta_prompt = (
		"You are an expert prompt engineer. Write a concise, production-ready "
		"system prompt for an AI chat agent with the following purpose. Return "
		"ONLY the system prompt text, no preamble or quotes.\n\n"
		f"Agent name: {cfg.agent_name}\n"
		f"Description: {cfg.description or '(none given)'}\n"
		f"Chat mode: {cfg.chat_mode_label or cfg.agent_id}"
	)
	adapter = get_llm_adapter_from_settings(get_agent_config(cfg.agent_id))
	completion = _run_coro_blocking(
		adapter.complete(system="You write system prompts.", user=meta_prompt, max_tokens=1024)
	)
	prompt = (getattr(completion, "text", "") or "").strip()
	if prompt:
		cfg.db_set("system_prompt", prompt, update_modified=False)
		frappe.cache.delete_value(f"agent_config:{cfg.agent_id}")
	return prompt


def _run_baseline_eval(suite_name: str) -> bool | None:
	"""Run a suite and return True/False for pass/fail, or None if it could
	not be run. Never raises — eval is advisory unless the suite gates."""
	try:
		from one_bpmn.agents.eval_runner import run_eval_suite

		run_name = run_eval_suite(suite_name, backend="live")
		status = frappe.db.get_value("AI Eval Run", run_name, "status")
		return status == "Passed"
	except Exception:
		frappe.log_error(title=f"Baseline eval run failed ({suite_name})", message=frappe.get_traceback())
		return None


def generate_eval_suite_for_agent(config_name: str) -> str | None:
	"""Create (or refresh) a baseline AI Eval Suite from the agent's sample
	prompts, linking the suite back to the configuration (WI-001609; the
	link now lives on the suite per WI-001743).

	One eval case per sample prompt: the agent's system prompt + credentials,
	the sample's text as the user prompt, and — when the sample declares an
	expected behaviour — an llm_judge assertion scoring the reply against it.
	Returns the suite name, or None when the agent has no sample prompts.
	"""
	cfg = frappe.get_doc("AI Agent Configuration", config_name)
	samples = cfg.get("sample_prompts") or []
	# WI-001648: process_model is optional — the eval cases run direct_api
	# against the agent's prompt + credentials, so a suite can be generated
	# before the chat map is provisioned (e.g. a config created from Processa
	# with sample prompts declared up front).
	if not samples:
		return None

	suite_title = f"{cfg.agent_name} — Baseline"
	# AI Eval Suite is autoname:hash, so the docname is never the title — the
	# suite has to be looked up by field. Scope on agent_configuration as well
	# as title: since WI-001743 that link is the authoritative (and mandatory)
	# Suite -> Agent relationship, and a suite the migration handed to another
	# agent under its "last one wins" collision rule must not be hijacked here.
	# Order by creation so that where an earlier bug left duplicate baselines
	# behind, every call converges on the same, oldest suite.
	existing = frappe.get_all(
		"AI Eval Suite",
		filters={"title": suite_title, "agent_configuration": cfg.name},
		pluck="name",
		order_by="creation asc",
		limit=1,
	)
	if existing:
		suite = frappe.get_doc("AI Eval Suite", existing[0])
		# Only the cases this generator wrote (it names them "<suite> — <n>").
		# A baseline suite is also where hand-authored regression cases live, and
		# refreshing the sample prompts must not silently delete those.
		for case in frappe.get_all(
			"AI Eval Case",
			filters={"suite": suite.name, "title": ["like", f"{suite_title} — %"]},
			pluck="name",
		):
			frappe.delete_doc("AI Eval Case", case, force=True, ignore_permissions=True)
	else:
		suite = frappe.get_doc({
			"doctype": "AI Eval Suite",
			"title": suite_title,
			"process_model": cfg.process_model or None,
			"agent_configuration": cfg.name,
			# Baseline suites are Direct (simple LLM) — the AI Assistant creates
			# them at agent-config time, before any process map exists (WI-001751).
			"eval_type": "Direct",
			"description": _("Baseline suite generated from {0}'s sample prompts.").format(cfg.agent_name),
		}).insert(ignore_permissions=True)

	# WI-001751: cases test the agent itself, so they carry only the prompt +
	# assertions — provider/model/system prompt come from the suite's agent.
	# llm_judge still needs a judge model, and since WI-001655 that is the
	# agent's own catalog pick: an AI Model record name, which is exactly what
	# the judge_model Link wants. (The provider-level default_model this used to
	# read no longer exists.)
	judge_provider = cfg.ai_provider
	judge_model = cfg.get("ai_model") or ""
	for i, sample in enumerate(samples, start=1):
		case = frappe.get_doc({
			"doctype": "AI Eval Case",
			"title": f"{suite_title} — {i}",
			"suite": suite.name,
			"process_model": cfg.process_model or None,
			"input_user_prompt": sample.prompt,
		})
		if judge_model and (sample.get("expected_behaviour") or "").strip():
			case.append("assertions", {
				"assertion_type": "llm_judge",
				"value": sample.expected_behaviour,
				"judge_provider": judge_provider,
				"judge_model": judge_model,
				"pass_threshold": 4,  # 1–5 scale; 4 = "mostly meets expectation"
			})
		case.insert(ignore_permissions=True)

	frappe.db.commit()
	return suite.name


def _provider_test_call(cfg) -> tuple[bool, str]:
	"""Make a minimal live call through the agent's resolved adapter."""
	try:
		from one_bpmn.agents.executor.direct_api import _run_coro_blocking
		from one_bpmn.agents.llm_provider import get_llm_adapter_from_settings
		from one_bpmn.one_bpmn.doctype.ai_agent_configuration.ai_agent_configuration import get_agent_config

		adapter = get_llm_adapter_from_settings(get_agent_config(cfg.agent_id))
		completion = _run_coro_blocking(
			adapter.complete(system="Reply with the single word: OK.", user="ping", max_tokens=16)
		)
		text = getattr(completion, "text", str(completion or ""))
		return (bool(text and text.strip()), text.strip()[:80] or "empty response")
	except Exception as exc:
		return (False, str(exc)[:200])


# ── Re-run the creation process from the form ───────────────────────────────

@frappe.whitelist()
def rerun_creation_process(agent: str) -> dict:
	"""Put an agent back through the Agent Creation Process.

	Editing the record already does this — the map waits on the Config Edited
	message and any save delivers it — but "make a change you do not want in
	order to re-run a check" is a poor thing to have to know. This is the same
	trigger behind a button.

	It decides NOTHING. Whether the agent may go Live is the map's call, exactly
	as before; this only asks the map to look again. Two cases:

	* the map is already parked on Config Edited — deliver that message;
	* nothing is running (a Draft that never started, or an agent parked from
	  outside the process) — start a fresh instance.

	Restricted to Draft and Needs Attention: a Live agent is already past this,
	and Retired is a deliberate state the process must not resurrect.
	"""
	doc = frappe.get_doc("AI Agent Configuration", agent)
	doc.check_permission("write")

	if doc.lifecycle_status not in ("Draft", "Needs Attention"):
		frappe.throw(
			_(
				"'{0}' is {1}. Re-running the creation process applies to agents in "
				"Draft or Needs Attention."
			).format(doc.name, doc.lifecycle_status)
		)

	from one_bpmn.agents.agent_config_resolver import get_creation_process_model
	from one_bpmn.one_bpmn.trigger import _maybe_send_message

	if not get_creation_process_model():
		frappe.throw(
			_(
				"No Agent Creation Process is deployed, so there is nothing to re-run. "
				"Tick 'Can Create Agents' on one agent and link the process map."
			)
		)

	creation_model = get_creation_process_model()
	waiting = frappe.db.exists(
		"BPMN Process Instance",
		{
			"process_model": creation_model,
			"context_doctype": "AI Agent Configuration",
			"context_docname": doc.name,
			"status": ("in", ["Active", "Errored"]),
		},
	)

	if waiting:
		# The dedup flag is per-request and would swallow this if the same
		# request already delivered one; clear it so an explicit ask is honoured.
		frappe.flags._bpmn_message_sent = None
		_maybe_send_message(doc, "Edit_Action")
		return {"ok": True, "action": "resumed", "instance": waiting}

	from one_bpmn.agents.agent_config_resolver import _start_reprovision

	started = _start_reprovision(doc.name)
	return {"ok": True, "action": "started" if started else "skipped"}
