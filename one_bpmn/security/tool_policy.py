# Copyright (c) 2026, one-fm and contributors
# For license information, please see license.txt
"""
Deterministic tool-call interception (WI-001645).

Frappe permissions answer "may this USER do it". This layer answers a different
question — "should the AGENT do it" — and answers it *before* the tool runs,
from rules that are data, not prompt text. An agent that has been talked into
calling a dangerous tool is stopped by code, not by its own good judgement.

Three rule groups:

  * **Restricted targets** — a call whose arguments name a protected DocType
    (identity/permissions, code-execution surface, payroll, …) is refused.
  * **Parameter limits** — numeric bounds on the argument VALUES themselves
    ("amount <= 5000"), so a permitted tool cannot be called with any figure at
    all.
  * **Per-agent tool grant** — an agent may be restricted to an explicit list of
    tools, enforced at runtime and therefore independent of what its diagram
    happens to grant. If someone adds a risky shape to the map, policy still
    holds.

REFUSING IS THE ONLY ACTION
---------------------------
A rule that matches aborts the call. There was briefly a second action, "Require
Human Approval", which suspended the agent onto a human task; it is gone. It
reused the durable-HITL suspension path, which is built for a tool the DESIGNER
marked human and reads its label, assignee and actions from that tool's diagram
shape. A policy rule names an ordinary tool and has no shape, so the approval it
produced was labelled after the tool, assigned to nobody and carried no actions
— unreleasable, and on a chat agent it killed the conversation. Making it work
meant an approver on every rule, a second resume semantics (approving RUNS the
tool, where a human tool's answer REPLACES it) and a one-shot release grant:
a lot of machinery for a decision a person can make by re-running the action
themselves. One action, always enforced, is the honest version.

WHERE THIS RUNS
---------------
Interception happens in ``ToolSpec.__post_init__`` (agents/llm_provider/base.py),
not in any one execution loop. That is deliberate: tools execute in FOUR places —
the step loop and the Anthropic/OpenAI/Gemini adapters' own tool loops — and some
ToolSpecs are constructed inside Server Script bodies (the Logix clarifier builds
its own). Guarding at construction is the only point every one of those passes
through, and a future loop is covered without anyone remembering to add a check.

FAILURE MODE
------------
Fails CLOSED, but contained: an error inside evaluation denies that single call
and logs, rather than allowing the call or taking the whole agent down. A denial
is returned to the model as an ordinary tool result, which every loop already
handles the same way it handles "Unknown tool" or a tool exception.
"""

from __future__ import annotations

import json
from contextvars import ContextVar
from dataclasses import dataclass, field

import re

import frappe

# ── Decision vocabulary ─────────────────────────────────────────────────────
ALLOW = "allow"
DENY = "deny"

# Cache key for the compiled rule set. Cleared whenever a rule is saved.
_RULE_CACHE_KEY = "ai_tool_policy_rules"

# The doctype's Action Select stores a human-readable label; the guard compares
# against the constants above. Refusing is the only action, so the map has one
# entry — but the lookup stays, because an unmapped label MUST fall back to DENY
# rather than evaluating as "not a deny, therefore allowed". Rows written before
# "Require Human Approval" was removed still carry that label and land here.
_ACTION_BY_LABEL = {
	"deny": DENY,
}

# The agent whose turn is currently running. Set by the dispatchers so that a
# tool built deep inside a Server Script still knows which agent it belongs to.
# A ContextVar (not frappe.flags) so a worker thread running a chat turn gets
# its own value instead of racing with another request.
_current_agent: ContextVar[str | None] = ContextVar("ai_tool_policy_agent", default=None)


@dataclass
class PolicyDecision:
	"""Outcome of evaluating one tool call."""

	outcome: str = ALLOW
	reason: str = ""
	rule: str = ""

	@property
	def allowed(self) -> bool:
		return self.outcome == ALLOW

	def as_tool_result(self) -> str:
		"""The string handed back to the model in place of the tool's output.

		Deliberately says WHAT was refused and WHY, without naming the rule's
		internals — enough for the model to choose a different approach, not
		enough to help it probe the policy.
		"""
		return (
			f"Blocked by policy: {self.reason} "
			"This action was not performed. Do not retry it; either take a "
			"different approach or tell the user it requires a person."
		)


# ── Agent context ───────────────────────────────────────────────────────────
def set_current_agent(agent_config: str | None):
	"""Record which AI Agent Configuration is running; returns a reset token."""
	return _current_agent.set(agent_config or None)


def reset_current_agent(token) -> None:
	try:
		_current_agent.reset(token)
	except (ValueError, LookupError):
		# Token from another context (thread hand-off) — clearing is enough.
		_current_agent.set(None)


def current_agent() -> str | None:
	return _current_agent.get()


# ── Rule loading ────────────────────────────────────────────────────────────
def _split_lines(value) -> list[str]:
	"""Newline- or comma-separated text field -> list of trimmed entries."""
	if not value:
		return []
	raw = str(value).replace(",", "\n")
	return [line.strip() for line in raw.split("\n") if line.strip()]


def load_rules() -> list[dict]:
	"""Enabled AI Tool Policy Rules, compiled and cached.

	Cached because evaluation runs on every single tool call; the cache is
	cleared by the doctype's on_update/on_trash so an edit takes effect at once.
	Returns [] when the doctype is absent (fresh site mid-migrate) so the guard
	degrades to allow rather than blocking every agent on a half-migrated site.
	"""
	cached = frappe.cache.get_value(_RULE_CACHE_KEY)
	if cached is not None:
		return cached

	rules = []
	try:
		if frappe.db.exists("DocType", "AI Tool Policy Rule"):
			for row in frappe.get_all(
				"AI Tool Policy Rule",
				filters={"enabled": 1},
				fields=["name", "action", "restricted_doctypes", "restricted_tools",
				        "parameter_limits", "violation_message", "category"],
			):
				exempt = frappe.get_all(
					"AI Tool Policy Exempt Agent",
					filters={"parent": row.name, "parenttype": "AI Tool Policy Rule"},
					pluck="agent_configuration",
				)
				rules.append({
					"name": row.name,
					"action": _ACTION_BY_LABEL.get((row.action or "").strip().lower(), DENY),
					"category": row.category or "",
					"doctypes": {d.lower() for d in _split_lines(row.restricted_doctypes)},
					"tools": {t.lower() for t in _split_lines(row.restricted_tools)},
					"limits": _parse_limits(row.parameter_limits, row.name),
					"message": (row.violation_message or "").strip(),
					"exempt_agents": {a for a in exempt if a},
				})
	except Exception:
		# Never let rule loading break a turn; log and treat as "no rules".
		frappe.log_error(
			title="AI Tool Policy: rule load failed",
			message=frappe.get_traceback(),
		)
		return []

	frappe.cache.set_value(_RULE_CACHE_KEY, rules)
	return rules


def clear_rule_cache() -> None:
	frappe.cache.delete_value(_RULE_CACHE_KEY)


# ── Argument inspection ─────────────────────────────────────────────────────
def _argument_values(arguments) -> list[str]:
	"""Every string an argument payload contains, at any depth.

	A restricted DocType can arrive as ``doctype``, ``ref_doctype``,
	``reference_doctype``, or buried inside a filters dict — matching on key
	names would miss most of them, so the whole payload is flattened instead.
	Bounded by depth so a pathological payload cannot spin.
	"""
	found: list[str] = []

	def walk(value, depth=0):
		if depth > 6 or len(found) > 500:
			return
		if isinstance(value, str):
			found.append(value)
		elif isinstance(value, dict):
			for k, v in value.items():
				if isinstance(k, str):
					found.append(k)
				walk(v, depth + 1)
		elif isinstance(value, (list, tuple, set)):
			for v in value:
				walk(v, depth + 1)

	walk(arguments)
	return found


_LIMIT_RE = re.compile(r"^\s*([A-Za-z_][\w.]*)\s*(<=|>=|<|>)\s*(-?\d+(?:\.\d+)?)\s*$")

_LIMIT_OPS = {
	"<=": lambda value, bound: value <= bound,
	"<": lambda value, bound: value < bound,
	">=": lambda value, bound: value >= bound,
	">": lambda value, bound: value > bound,
}


def _parse_limits(raw, rule_name: str) -> list[tuple]:
	"""``amount <= 5000`` lines into (parameter, operator, bound) triples.

	Deliberately a tiny grammar rather than an expression: a rule is data a
	non-engineer edits in a form, and anything evaluable there is a way to run
	code from a database row.

	A malformed line is skipped AND logged. Silently ignoring it would leave a
	rule that reads as enforcing a ceiling while enforcing nothing — the worst
	outcome available, because the control looks present.
	"""
	limits = []
	for line in _split_lines(raw):
		match = _LIMIT_RE.match(line)
		if not match:
			frappe.log_error(
				title=f"AI Tool Policy: unreadable parameter limit ({rule_name})",
				message=f"Ignoring {line!r}. Expected `parameter <= number` using <=, <, >= or >.",
			)
			continue
		parameter, operator, bound = match.groups()
		limits.append((parameter.lower(), operator, float(bound)))
	return limits


def _numeric_candidates(arguments, parameter: str) -> list:
	"""Every value the payload carries under ``parameter``, at any depth.

	Same reasoning as _argument_values: an amount arrives as ``amount``, or
	inside ``doc``, or inside a filters dict, and matching only the top level
	would miss most of them.
	"""
	found = []

	def walk(value, depth=0):
		if depth > 6 or len(found) > 50:
			return
		if isinstance(value, dict):
			for key, inner in value.items():
				if isinstance(key, str) and key.strip().lower() == parameter:
					found.append(inner)
				walk(inner, depth + 1)
		elif isinstance(value, (list, tuple, set)):
			for inner in value:
				walk(inner, depth + 1)

	walk(arguments)
	return found


def _breaches_parameter_limit(arguments, limits: list) -> str | None:
	"""The bound an argument crosses, described, or None.

	An absent parameter is not a breach: the rule simply does not apply to this
	call. A parameter that is PRESENT but unreadable as a number IS a breach —
	an amount nobody can verify is not an amount within the ceiling, and the
	alternative is a ceiling that a string walks straight through.
	"""
	for parameter, operator, bound in limits:
		for raw in _numeric_candidates(arguments, parameter):
			if isinstance(raw, bool) or raw is None:
				return f"'{parameter}' is not a number, so the limit could not be checked"
			try:
				value = float(raw)
			except (TypeError, ValueError):
				return f"'{parameter}' is not a number, so the limit could not be checked"
			if not _LIMIT_OPS[operator](value, bound):
				pretty = int(bound) if bound == int(bound) else bound
				actual = int(value) if value == int(value) else value
				return f"'{parameter}' is {actual}, which breaks the limit {parameter} {operator} {pretty}"
	return None


def _hits_restricted_doctype(arguments, doctypes: set) -> str | None:
	"""Return the restricted DocType an argument payload names, if any.

	Exact, case-insensitive match on a whole value — NOT a substring test.
	Substring matching would refuse ``get_list(doctype="User Permission Log")``
	because it contains "User", and would be trivially defeated by whitespace.
	"""
	if not doctypes:
		return None
	for value in _argument_values(arguments):
		if value.strip().lower() in doctypes:
			return value.strip()
	return None


# ── Evaluation ──────────────────────────────────────────────────────────────
def evaluate(tool_name: str, arguments: dict, agent_config: str | None = None) -> PolicyDecision:
	"""Decide whether ``tool_name`` may run with ``arguments``.

	Pure with respect to its inputs apart from reading the (cached) rule set,
	so it is unit-testable without a workflow, an agent, or an LLM.
	"""
	agent_config = agent_config or current_agent()
	tool_lower = (tool_name or "").lower()

	# 1. Per-agent tool grant (rule group 2). Enforced at runtime, so it holds
	#    even if the agent's diagram is edited to grant something extra.
	allowlist = _agent_allowlist(agent_config)
	if allowlist is not None and tool_lower not in allowlist:
		return PolicyDecision(
			outcome=DENY,
			reason=f"the agent is not permitted to use the '{tool_name}' tool.",
			rule=f"agent-tool-grant:{agent_config}",
		)

	# 2. Restricted targets (rule group 1).
	for rule in load_rules():
		if agent_config and agent_config in rule["exempt_agents"]:
			continue
		if rule["tools"] and tool_lower not in rule["tools"]:
			continue  # rule is scoped to other tools
		# 2a. Numeric bounds on the arguments themselves — the transaction
		#     ceiling half of the control. Checked before the DocType match so a
		#     rule may carry either, or both.
		breach = _breaches_parameter_limit(arguments, rule.get("limits") or [])
		if breach:
			reason = rule["message"] or f"{breach}."
			return _decide(rule, reason)

		hit = _hits_restricted_doctype(arguments, rule["doctypes"])
		if not hit:
			continue
		reason = rule["message"] or (
			f"'{hit}' is a protected record type and agents may not act on it."
		)
		return _decide(rule, reason)

	return PolicyDecision(outcome=ALLOW)


def _decide(rule: dict, reason: str) -> PolicyDecision:
	"""A rule fired. Refusing is the only action a rule can take.

	``rule["action"]`` is still read rather than assumed: a row written before
	"Require Human Approval" was removed still carries that label, and
	_ACTION_BY_LABEL maps anything it does not recognise to DENY. So a legacy
	approval rule now refuses, which is the stricter reading and the only one
	available — there is no longer anywhere for it to park.
	"""
	return PolicyDecision(
		outcome=rule["action"] or DENY,
		reason=reason,
		rule=rule["name"],
	)


def _agent_allowlist(agent_config: str | None) -> set | None:
	"""Lower-cased allowed tool names for an agent, or None when unrestricted.

	None (not an empty set) means "no restriction configured" — an empty set
	would mean "this agent may call nothing", which is a very different thing.
	"""
	if not agent_config:
		return None
	try:
		if not frappe.db.exists("AI Agent Configuration", agent_config):
			return None
		if not frappe.db.get_value("AI Agent Configuration", agent_config, "restrict_tools"):
			return None
		names = frappe.get_all(
			"AI Agent Allowed Tool",
			filters={"parent": agent_config, "parenttype": "AI Agent Configuration"},
			pluck="tool_name",
		)
		return {n.strip().lower() for n in names if n and n.strip()}
	except Exception:
		frappe.log_error(
			title=f"AI Tool Policy: allowlist load failed ({agent_config})",
			message=frappe.get_traceback(),
		)
		# Fail closed for this agent rather than silently granting everything.
		return set()


# ── The interceptor itself ──────────────────────────────────────────────────
class PolicyViolation(Exception):
	"""Raised in place of running a denied tool.

	Carries the decision so a loop can report WHY rather than just that the tool
	failed. Every loop already handles it the same way it handles any tool
	exception: the refusal becomes the tool's result and the model carries on.
	"""

	def __init__(self, decision: PolicyDecision):
		self.decision = decision
		super().__init__(decision.as_tool_result())


def guard(fn, tool_name: str):
	"""Wrap a tool's callable so every invocation is evaluated first.

	Applied by ``ToolSpec.__post_init__``, so it covers tools built by
	compile_shape_tools, by the selector's tool pool, and by Server Script
	bodies alike.
	"""

	def guarded(**kwargs):
		try:
			decision = evaluate(tool_name, kwargs)
		except Exception:
			frappe.log_error(
				title=f"AI Tool Policy: evaluation failed ({tool_name})",
				message=frappe.get_traceback(),
			)
			# Contained fail-closed: refuse this call, keep the agent alive.
			decision = PolicyDecision(
				outcome=DENY,
				reason="the policy check could not be completed.",
				rule="evaluation-error",
			)
		if not decision.allowed:
			_record_violation(tool_name, kwargs, decision)
			raise PolicyViolation(decision)
		return fn(**kwargs)

	guarded.__name__ = getattr(fn, "__name__", "guarded_tool")
	# A dedicated sentinel, NOT ``__wrapped__``: functools.wraps sets that on any
	# decorated function, so a tool whose fn happened to be decorated would have
	# looked already-guarded and been skipped — silently unprotected, which is
	# the worst way for a security control to fail.
	guarded.__policy_guarded__ = fn
	guarded.__wrapped__ = fn
	return guarded


def _record_violation(tool_name: str, arguments: dict, decision: PolicyDecision) -> None:
	"""Leave an audit trail. A blocked call that nobody can find later is not
	a security control — but a logging failure must never mask the block."""
	try:
		frappe.log_error(
			title=f"AI Tool Policy: {decision.outcome} — {tool_name}",
			message=(
				f"rule: {decision.rule}\n"
				f"agent: {current_agent()}\n"
				f"reason: {decision.reason}\n"
				f"arguments: {json.dumps(arguments, default=str)[:2000]}"
			),
		)
	except Exception:
		pass
