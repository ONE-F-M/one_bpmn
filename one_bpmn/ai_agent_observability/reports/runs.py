"""Run tree, recent runs, the runs list and run detail."""
from __future__ import annotations

import frappe
from frappe import _
from frappe.query_builder import DocType
from frappe.query_builder import functions as fn
from frappe.utils import cint, cstr, flt, getdate
from pypika.terms import Case

from one_bpmn.ai_agent_observability.reports.periods import apply_conditions, origin_condition


# ---------------------------------------------------------------------------
# 5. Run step detail (drill-down)
# ---------------------------------------------------------------------------

_RUN_FIELDS = [
	"name", "status", "model", "agent_configuration", "bpmn_id", "bpmn_label",
	"instance", "parent_run", "started_at", "duration_ms", "total_prompt_tokens",
	"total_completion_tokens", "total_tokens", "estimated_cost", "error_code",
	"error_message", "prompt_hash",
]

_STEP_FIELDS = [
	"name", "step_index", "role", "step_kind", "content", "latency_ms", "started_at", "ended_at",
	"prompt_tokens", "completion_tokens", "cache_read_tokens", "cache_write_tokens", "cost",
	"error_code", "error_message",
]

TREE_MAX_DEPTH = 4


def _step_rows(run_name: str) -> list:
	"""The steps of one run, oldest first, each carrying its AI Agent Tool Call
	child rows, the names of the tools it called, and its sub-call tag when
	the step is a model call made from inside a tool.

	The step doctype has no tool_name column of its own: the child table is
	the only record of what a turn called. The Insights step table read a
	field that did not exist, which is why its Tool column never showed one.
	"""
	from one_bpmn.ai_agent_observability.observability import parse_sub_call

	steps = frappe.get_list(
		"AI Agent Step",
		filters={"run": run_name},
		fields=_STEP_FIELDS,
		order_by="step_index asc, creation asc",
		limit_page_length=200,
	)

	step_names = [s.name for s in steps]
	calls_by_step: dict = {}
	if step_names and frappe.db.exists("DocType", "AI Agent Tool Call"):
		for call in frappe.get_all(
			"AI Agent Tool Call",
			filters={"parent": ["in", step_names], "parenttype": "AI Agent Step"},
			fields=[
				"parent", "tool_name", "tool_source", "tool_args", "tool_result", "status",
				"outcome", "tool_artifact", "artifact_file",
			],
			order_by="idx asc",
		):
			calls_by_step.setdefault(call.pop("parent"), []).append(call)

	for step in steps:
		step["tool_calls"] = calls_by_step.get(step.name, [])
		step["tool_names"] = [c.get("tool_name") for c in step["tool_calls"] if c.get("tool_name")]
		step["sub_call"] = parse_sub_call(step.get("content"))
		step["child_runs"] = []
	return steps


def _own_rollup(run: dict) -> dict:
	return {
		"runs": 1,
		"total_tokens": cint(run.get("total_tokens")),
		"total_prompt_tokens": cint(run.get("total_prompt_tokens")),
		"total_completion_tokens": cint(run.get("total_completion_tokens")),
		"estimated_cost": flt(run.get("estimated_cost")),
	}


def _add_rollup(into: dict, other: dict) -> None:
	for key in ("runs", "total_tokens", "total_prompt_tokens", "total_completion_tokens"):
		into[key] = cint(into.get(key)) + cint(other.get(key))
	into["estimated_cost"] = flt(into.get("estimated_cost")) + flt(other.get("estimated_cost"))


def _run_node(run: dict, depth: int) -> dict:
	"""One run with its steps and the runs its tools started, nested under
	the step whose tool call started them.

	A child is attached to the first step still holding an unmatched call to
	the tool that started it, in order. A child that matches no step (older
	data, or a run started outside a tool call) is listed after the steps.
	"""
	steps = _step_rows(run["name"]) if depth > 0 else []
	children = _child_runs(run["name"]) if depth > 0 else []
	# The runs below arrive without their steps. A reader opens one at a time,
	# and get_turn_steps answers for that one; only its totals travel now.
	child_nodes = [_stub_node(child, depth - 1) for child in children]

	rollup = _own_rollup(run)
	for node in child_nodes:
		_add_rollup(rollup, node["rollup"])

	called_as = _tool_names_of_children(run["name"], children)
	unplaced = list(child_nodes)
	for step in steps:
		for tool_name in step["tool_names"]:
			match = next(
				(n for n in unplaced if called_as.get(n["run"]["name"]) == tool_name), None
			)
			if match is not None:
				step["child_runs"].append(match)
				unplaced.remove(match)

	return {
		"run": run,
		"steps": steps,
		"steps_loaded": True,
		"unplaced_children": unplaced,
		"rollup": rollup,
	}


def _child_runs(parent: str) -> list:
	return frappe.get_list(
		"AI Agent Run",
		filters={"parent_run": parent},
		fields=_RUN_FIELDS,
		order_by="started_at asc, creation asc",
		limit_page_length=100,
	)


def _stub_node(run: dict, depth: int) -> dict:
	"""A run below the one being read: its row and what its tree cost, no steps."""
	rollup = _own_rollup(run)
	if depth > 0:
		for child in _child_runs(run["name"]):
			_add_rollup(rollup, _stub_node(child, depth - 1)["rollup"])
	return {"run": run, "steps": [], "steps_loaded": False, "unplaced_children": [], "rollup": rollup}


def _tool_names_of_children(parent: str, children: list) -> dict:
	"""The tool name each child run answers to, as the caller called it.

	A child run started in the same process carries the calling shape as its
	own bpmn_id, so it speaks for itself. A child reached over A2A does not:
	it carries the start shape of its own map, and the name the caller used
	lives on the A2A Task instead. Without that, delegated work never lands
	under the step that asked for it.
	"""
	names = {child["name"]: child.get("bpmn_id") for child in children}
	if not names:
		return names
	try:
		tasks = frappe.get_list(
			"A2A Task",
			filters={"caller_agent_run": parent},
			fields=["bpmn_id", "agent_run", "instance"],
			limit_page_length=0,
		)
	except frappe.PermissionError:
		return names
	by_instance = {}
	for child in children:
		by_instance.setdefault(child.get("instance"), []).append(child["name"])
	for task in tasks:
		if not task.get("bpmn_id"):
			continue
		child = task.get("agent_run")
		if not child:
			# Some tasks never had their agent_run written back, so the child
			# has to come from the instance the task does name, and only when
			# that instance produced exactly one of this run's children.
			candidates = by_instance.get(task.get("instance")) or []
			child = candidates[0] if len(candidates) == 1 else None
		if child in names:
			names[child] = task["bpmn_id"]
	return names


def get_run_tree(run_name: str) -> dict:
	"""A run as the tree it really was: its steps, and under each
	step the runs that step's tool calls started, recursively, with tokens and
	cost rolled up over the whole tree. The parent's own totals cover only its
	own model calls; the rollup is what the turn cost.
	"""
	run = frappe.db.get_value("AI Agent Run", run_name, _RUN_FIELDS, as_dict=True)
	if not run:
		frappe.throw(_("AI Agent Run {0} not found").format(run_name), frappe.DoesNotExistError)
	return _run_node(run, TREE_MAX_DEPTH)


def _descendant_rollups(run_names: list) -> dict:
	"""{top-level run name: rollup over its descendants}, walking parent_run
	links breadth-first so grandchildren count as well as children."""
	totals = {name: {"runs": 0, "total_tokens": 0, "total_prompt_tokens": 0, "total_completion_tokens": 0, "estimated_cost": 0.0} for name in run_names}
	owner = {name: name for name in run_names}
	frontier = list(run_names)
	for _level in range(TREE_MAX_DEPTH):
		if not frontier:
			break
		children = frappe.get_all(
			"AI Agent Run",
			filters={"parent_run": ["in", frontier]},
			fields=["name", "parent_run", "total_tokens", "total_prompt_tokens", "total_completion_tokens", "estimated_cost"],
			limit_page_length=0,
		)
		frontier = []
		for child in children:
			top = owner.get(child.parent_run)
			if not top:
				continue
			owner[child.name] = top
			_add_rollup(totals[top], _own_rollup(child))
			frontier.append(child.name)
	return totals


def get_recent_runs(
	model: str = None,
	bpmn_id: str = None,
	agent_configuration: str = None,
	status: str = "Success",
	limit: int = 10,
) -> list:
	"""The latest top-level runs matching the filters, each with the tokens,
	cost and count of the runs its tools started. Child runs are
	not listed on their own: they appear under their parent in get_run_tree.
	"""
	filters: dict = {"parent_run": ["is", "not set"]}
	if status:
		filters["status"] = status
	if model:
		filters["model"] = model
	if bpmn_id:
		filters["bpmn_id"] = bpmn_id
	if agent_configuration:
		filters["agent_configuration"] = agent_configuration
	runs = frappe.get_list(
		"AI Agent Run",
		filters=filters,
		fields=_RUN_FIELDS,
		order_by="started_at desc",
		limit_page_length=min(cint(limit) or 10, 100),
	)
	rollups = _descendant_rollups([r.name for r in runs])
	for run in runs:
		below = rollups.get(run.name) or {}
		run["child_runs"] = cint(below.get("runs"))
		run["tree_total_tokens"] = cint(run.total_tokens) + cint(below.get("total_tokens"))
		run["tree_estimated_cost"] = flt(run.estimated_cost) + flt(below.get("estimated_cost"))
	return runs


# ---------------------------------------------------------------------------
# 8. Runs page: list, filter options, one run in full
# ---------------------------------------------------------------------------

RUNS_PAGE_MAX = 100

_LIST_RUN_FIELDS = (
	"name", "status", "model", "agent_configuration", "bpmn_id", "bpmn_label", "instance",
	"origin", "started_at", "ended_at", "duration_ms", "agent_latency_ms", "human_wait_ms",
	"total_prompt_tokens", "total_completion_tokens", "total_tokens", "total_cache_read_tokens",
	"estimated_cost", "error_code", "goal_completion",
)

_DETAIL_RUN_FIELDS = _LIST_RUN_FIELDS + (
	"process_model", "parent_run", "prompt_hash", "element_type", "eval_case", "eval_run",
	"backend", "provider", "error_message", "retry_count", "max_retries", "suspended_at",
	"total_cache_write_tokens", "total_input_cost", "total_output_cost", "total_cache_read_cost",
	"total_cache_write_cost", "completion_basis", "final_output", "no_terminal_tool",
	"correlation_id", "recall_query", "memory_injected_tokens", "pending_human_task",
)

_RUN_ORDERS = {
	"newest": ("started_at", "desc"),
	"oldest": ("started_at", "asc"),
	"slowest": ("agent_latency_ms", "desc"),
	"cost": ("estimated_cost", "desc"),
	"tokens": ("total_tokens", "desc"),
}


def percentile(values: list, share: float) -> int:
	if not values:
		return 0
	values = sorted(values)
	return cint(values[min(len(values) - 1, int(len(values) * share))])


def _runs_conditions(Run, Inst, Step, *, agent_configuration=None, status=None, origin="production",
                     user=None, model=None, instance=None, from_date=None, to_date=None,
                     errors_only=0, search=None) -> list:
	"""The where clauses the list, the tiles and the filter options share.
	Top-level runs only: a run a tool started shows under its parent."""
	conditions = [Run.parent_run.isnull() | (Run.parent_run == ""), origin_condition(Run, origin)]
	if agent_configuration:
		conditions.append(Run.agent_configuration == agent_configuration)
	if status:
		conditions.append(Run.status == status)
	if user:
		conditions.append(Inst.initiated_by == user)
	if model:
		conditions.append(Run.model == model)
	if instance:
		conditions.append(Run.instance == instance)
	if from_date:
		conditions.append(fn.Date(Run.started_at) >= getdate(from_date))
	if to_date:
		conditions.append(fn.Date(Run.started_at) <= getdate(to_date))
	if cint(errors_only):
		failed_steps = frappe.qb.from_(Step).select(Step.run).where(Step.error_code.isnotnull()).distinct()
		conditions.append((Run.status == "Error") | Run.name.isin(failed_steps))
	if search:
		term = f"%{search.strip()}%"
		conditions.append(
			Run.name.like(term) | Run.instance.like(term) | Run.bpmn_label.like(term)
			| Run.final_output.like(term) | Inst.initiated_by.like(term)
		)
	return conditions


def list_runs(
	agent_configuration: str = None,
	status: str = None,
	origin: str = "production",
	user: str = None,
	model: str = None,
	instance: str = None,
	from_date: str = None,
	to_date: str = None,
	errors_only: int = 0,
	search: str = None,
	order: str = "newest",
	start: int = 0,
	page_length: int = 25,
) -> dict:
	"""A page of top-level runs for /processa/runs, with the six tile numbers
	for the same filter. Each run carries its step count, tool-call count,
	failed-step count, the person who started its instance, and the tokens
	and cost of the whole tree its tools started."""
	page_length = min(max(cint(page_length) or 25, 1), RUNS_PAGE_MAX)
	start = max(cint(start), 0)

	Run = DocType("AI Agent Run")
	Inst = DocType("BPMN Process Instance")
	Step = DocType("AI Agent Step")
	Call = DocType("AI Agent Tool Call")
	conditions = _runs_conditions(
		Run, Inst, Step, agent_configuration=agent_configuration, status=status, origin=origin,
		user=user, model=model, instance=instance, from_date=from_date, to_date=to_date,
		errors_only=errors_only, search=search,
	)

	steps_of = frappe.qb.from_(Step).select(fn.Count("*")).where(Step.run == Run.name)
	failed_of = (
		frappe.qb.from_(Step).select(fn.Count("*"))
		.where(Step.run == Run.name).where(Step.error_code.isnotnull())
	)
	calls_of = (
		frappe.qb.from_(Call).join(Step).on(Call.parent == Step.name)
		.select(fn.Count("*")).where(Step.run == Run.name)
	)
	from pypika import Order

	query = (
		frappe.qb.from_(Run).left_join(Inst).on(Run.instance == Inst.name)
		.select(
			*[Run[f] for f in _LIST_RUN_FIELDS],
			Inst.initiated_by.as_("user"),
			Inst.context_doctype, Inst.context_docname,
			steps_of.as_("steps"), failed_of.as_("failed_steps"), calls_of.as_("tool_calls"),
		)
	)
	if order == "steps":
		query = query.orderby(steps_of, order=Order.desc)
	else:
		order_field, direction = _RUN_ORDERS.get(order or "newest", _RUN_ORDERS["newest"])
		query = query.orderby(Run[order_field], order=Order.desc if direction == "desc" else Order.asc)
	query = query.orderby(Run.creation, order=Order.desc).limit(page_length).offset(start)
	runs = apply_conditions(query, conditions).run(as_dict=True)

	rollups = _descendant_rollups([r.name for r in runs])
	for run in runs:
		below = rollups.get(run.name) or {}
		run["child_runs"] = cint(below.get("runs"))
		run["tree_total_tokens"] = cint(run.total_tokens) + cint(below.get("total_tokens"))
		run["tree_estimated_cost"] = flt(run.estimated_cost) + flt(below.get("estimated_cost"))
		run["conversation"] = (
			run.context_docname if run.context_doctype == "Chat Conversation" else None
		)

	base = apply_conditions(frappe.qb.from_(Run).left_join(Inst).on(Run.instance == Inst.name), conditions)
	failed_runs = frappe.qb.from_(Step).select(Step.run).where(Step.error_code.isnotnull()).distinct()
	totals = base.select(
		fn.Count("*").as_("runs"),
		fn.Count(Run.instance).distinct().as_("instances"),
		fn.Sum(Run.estimated_cost).as_("cost"),
		fn.Sum(Run.total_tokens).as_("tokens"),
		fn.Sum(Run.total_cache_read_tokens).as_("cache_read_tokens"),
		fn.Sum(Case().when((Run.status == "Error") | Run.name.isin(failed_runs), 1).else_(0)).as_("error_runs"),
	).run(as_dict=True)[0]
	step_total = cint(
		frappe.qb.from_(Step).select(fn.Count("*"))
		.where(Step.run.isin(base.select(Run.name))).run()[0][0]
	)
	latencies = [
		cint(r[0]) for r in base.select(Run.agent_latency_ms).where(Run.agent_latency_ms > 0).run()
	]
	run_count = cint(totals.get("runs"))
	summary = {
		"runs": run_count,
		"conversations": cint(totals.get("instances")),
		"steps": step_total,
		"steps_per_run": round(step_total / run_count, 1) if run_count else 0,
		"median_latency_ms": percentile(latencies, 0.5),
		"p95_latency_ms": percentile(latencies, 0.95),
		"error_runs": cint(totals.get("error_runs")),
		"error_rate": round(cint(totals.get("error_runs")) * 100 / run_count, 1) if run_count else 0,
		"cost": flt(totals.get("cost")),
		"cost_per_run": flt(totals.get("cost")) / run_count if run_count else 0,
		"tokens": cint(totals.get("tokens")),
		"cache_read_share": (
			round(cint(totals.get("cache_read_tokens")) * 100 / cint(totals.get("tokens")), 1)
			if cint(totals.get("tokens")) else 0
		),
	}
	return {"runs": runs, "total": run_count, "start": start, "page_length": page_length, "summary": summary}


def run_filter_options(origin: str = "production") -> dict:
	"""The agents, people and models that actually have runs, for the filters."""
	Run = DocType("AI Agent Run")
	Inst = DocType("BPMN Process Instance")
	base = (
		frappe.qb.from_(Run).left_join(Inst).on(Run.instance == Inst.name)
		.where(Run.parent_run.isnull() | (Run.parent_run == ""))
		.where(origin_condition(Run, origin))
	)
	def distinct(column):
		rows = base.select(column).distinct().run()
		return sorted({cstr(r[0]) for r in rows if r[0]})
	return {
		"agents": distinct(Run.agent_configuration),
		"users": distinct(Inst.initiated_by),
		"models": distinct(Run.model),
		"statuses": ["Running", "Suspended", "Success", "Error"],
	}


def get_turn_steps(run_name: str) -> dict:
	"""One turn's steps, with the runs its tools started, for opening a turn
	inside a conversation without loading the conversation again."""
	run = frappe.db.get_value("AI Agent Run", run_name, list(_DETAIL_RUN_FIELDS), as_dict=True)
	if not run:
		frappe.throw(_("AI Agent Run {0} not found").format(run_name), frappe.DoesNotExistError)
	return {**_run_node(dict(run), TREE_MAX_DEPTH), "run": run}


def get_run_detail(run_name: str) -> dict:
	"""One run in full: its record, the instance and conversation it belongs
	to, its steps as a tree (child runs under the step that started them),
	and the other top-level runs on the same instance in the order they
	happened, which is the conversation read turn by turn."""
	run = frappe.db.get_value("AI Agent Run", run_name, list(_DETAIL_RUN_FIELDS), as_dict=True)
	if not run:
		frappe.throw(_("AI Agent Run {0} not found").format(run_name), frappe.DoesNotExistError)

	instance = None
	if run.instance:
		instance = frappe.db.get_value(
			"BPMN Process Instance", run.instance,
			["name", "process_model", "status", "initiated_by", "started_at", "completed_at",
			 "context_doctype", "context_docname"],
			as_dict=True,
		)
	conversation = None
	if instance and instance.context_doctype == "Chat Conversation" and instance.context_docname:
		conversation = frappe.db.get_value(
			"Chat Conversation", instance.context_docname, ["name", "title", "agent_mode", "status"], as_dict=True
		)

	tree = _run_node(dict(run), TREE_MAX_DEPTH)
	system_prompt = next((s.get("content") for s in tree["steps"] if s.get("role") == "system"), "")

	siblings = []
	if run.instance:
		# A run started by another run's tool call is not a turn of the
		# conversation; its page reads that one run, and points at the caller.
		siblings = frappe.get_list(
			"AI Agent Run",
			filters={"name": run.name} if run.parent_run else {"instance": run.instance, "parent_run": ["is", "not set"]},
			fields=["name", "bpmn_label", "agent_configuration", "status", "started_at", "ended_at",
			        "agent_latency_ms", "duration_ms", "total_tokens", "estimated_cost", "final_output",
			        "error_code"],
			order_by="started_at asc, creation asc",
			limit_page_length=200,
		)
		for sibling in siblings:
			sibling["final_output"] = cstr(sibling.get("final_output"))[:600]

	agent_model = None
	if run.agent_configuration:
		agent_model = frappe.db.get_value("AI Agent Configuration", run.agent_configuration, "ai_model")

	return {
		"run": run,
		"agent_model": agent_model,
		"instance": instance,
		"conversation": conversation,
		"tree": tree,
		"system_prompt": system_prompt,
		"siblings": siblings,
	}
