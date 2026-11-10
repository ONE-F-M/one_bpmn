# Copyright (c) 2026, one-fm and contributors
# For license information, please see license.txt
"""Scoring: the assertion evaluators and the LLM judge."""

from __future__ import annotations

import json
import re
from typing import Any, List

import frappe
from frappe.utils import cint, now_datetime

from one_bpmn.processa_engine.agent_runtime.executor import (
	ErrorCode,
	ExecutorConfig,
	ExecutorContext,
	get_executor,
)
# Importing the backend modules registers them in the executor registry.
from one_bpmn.processa_engine.agent_runtime.direct_api import (  # noqa: F401
	DirectApiExecutor,
	strip_code_fences,
)
from one_bpmn.processa_engine.agent_runtime.antigravity import AntigravityExecutor  # noqa: F401

from one_bpmn.ai_agent_evals.runner.records import cost_split, record_eval_run


EVAL_RUN_JUDGE = "eval-judge"


# The assertion types that need a model call, and therefore cannot run in a
# deterministic pass. Everything else is arithmetic or string matching.
MODEL_BACKED_ASSERTIONS = frozenset({"llm_judge"})


JUDGE_PROMPT_TEMPLATE = """You are an evaluation judge. Score the following AI response based on the given rubric.

Rubric:
{rubric}

AI Response:
{actual_output}

Score the response from 1 to 5 where:
1 = Completely fails the rubric
5 = Fully meets the rubric

Respond with ONLY a JSON object:
{{"score": <int>, "explanation": "<one sentence>"}}"""


TOOL_CALL_MODES = ("EXACT", "IN_ORDER", "ANY_ORDER")


def evaluate_assertion(assertion, output: Any, facts: dict = None) -> dict:
    """
    Evaluate one assertion against *output*.

    *facts* describes the execution that produced the output — its token spend
    and the tools it called — for the assertions that are about the run rather
    than its text. A replay has no execution, so it passes none, and those
    assertion types say so instead of guessing.

    Returns a dict {assertion_type, value, passed, message} describing the
    outcome. Evaluation never raises — a malformed assertion (e.g. a bad
    regex) is reported as a non-passing result.
    """
    a_type = assertion.assertion_type
    value = assertion.value or ""
    base = {"assertion_type": a_type, "value": value}

    try:
        if a_type == "contains":
            passed = value.strip().lower() in stringify(output).lower()
            return {**base, "passed": passed,
                    "message": "" if passed else "Substring not found."}

        if a_type == "regex":
            passed = bool(re.search(value, stringify(output)))
            return {**base, "passed": passed,
                    "message": "" if passed else "Pattern did not match."}

        if a_type == "equals":
            passed = stringify(output).strip() == value.strip()
            return {**base, "passed": passed,
                    "message": "" if passed else "Output did not equal expected value."}

        if a_type == "schema_valid":
            return {**base, **_evaluate_schema_valid(value, output)}

        if a_type == "max_tokens":
            return {**base, **_evaluate_max_tokens(value, facts)}

        if a_type == "no_tool_call":
            return {**base, **_evaluate_no_tool_call(value, facts)}

        if a_type == "tool_calls":
            return {**base, **_evaluate_tool_calls(value, facts)}

        if a_type == "tool_artifact":
            return {**base, **_evaluate_tool_artifact(value, facts)}

        if a_type == "skill_in_prompt":
            return {**base, **_evaluate_skill_in_prompt(value, facts)}

        if a_type == "llm_judge":
            return _evaluate_llm_judge(assertion, output)

        return {**base, "passed": False, "error": True,
                "message": f"Unsupported assertion type: {a_type!r}."}
    except Exception as exc:
        # Scenario 5: a bad assertion (e.g. invalid regex) is an
        # ERROR result — never silently Passed/Failed, never a crash that
        # aborts the other cases in the suite.
        return {**base, "passed": False, "error": True,
                "message": f"Assertion error: {exc}"}


def _evaluate_schema_valid(schema_str: str, output: Any) -> dict:
    """Pass if *output* is valid JSON that validates against *schema_str*."""
    import jsonschema

    # The output may already be a parsed object (json response_format) or a
    # JSON string (text response_format).
    if isinstance(output, str):
        try:
            instance = json.loads(strip_code_fences(output))
        except json.JSONDecodeError as exc:
            return {"passed": False, "message": f"Output is not valid JSON: {exc}"}
    else:
        instance = output

    try:
        schema = json.loads(schema_str)
    except json.JSONDecodeError as exc:
        return {"passed": False, "message": f"Schema is not valid JSON: {exc}"}

    try:
        jsonschema.validate(instance, schema)
    except jsonschema.ValidationError as exc:
        return {"passed": False, "message": f"Schema validation failed: {exc.message}"}

    return {"passed": True, "message": ""}


def _evaluate_max_tokens(value: str, facts: dict) -> dict:
    """Pass if the case's own execution stayed within *value* tokens.

    Judge tokens are left out: they are the cost of measuring the answer, not
    of producing it, so adding them would make the ceiling depend on how many
    llm_judge assertions the case happens to carry.
    """
    if facts is None:
        return {"passed": False, "error": True,
                "message": "Token spend is only measured on a live run, not a replay."}
    ceiling = cint(value)
    if ceiling <= 0:
        return {"passed": False, "error": True,
                "message": "max_tokens needs a positive number of tokens."}
    spent = cint(facts.get("tokens"))
    return {"passed": spent <= ceiling,
            "message": "" if spent <= ceiling else f"Spent {spent} tokens; the ceiling is {ceiling}."}


def _evaluate_no_tool_call(value: str, facts: dict) -> dict:
    """Pass if none of the tools named in *value* ran during the case.

    The output cannot show this: a greeting that quietly ran the schema writer
    reads exactly like one that did not, and only the second is cheap.
    """
    if facts is None:
        return {"passed": False, "error": True,
                "message": "Tool calls are only observed on a live run, not a replay."}
    banned = {n.strip() for n in value.replace("\n", ",").split(",") if n.strip()}
    if not banned:
        return {"passed": False, "error": True,
                "message": "no_tool_call needs the tool names it forbids."}
    called = sorted({t for t in (facts.get("tool_calls") or []) if t in banned})
    return {"passed": not called,
            "message": "" if not called else "Called " + ", ".join(called) + "."}


def _evaluate_skill_in_prompt(value: str, facts: dict) -> dict:
    """Pass if the body of the skill named in *value* was in a prompt the case sent to the model."""
    if facts is None:
        return {"passed": False, "error": True,
                "message": "Prompts are only observed on a live run, not a replay."}
    body = (frappe.db.get_value("AI Skill", value.strip(), "body") or "").strip()
    if not body:
        return {"passed": False, "error": True,
                "message": f"No AI Skill named {value.strip()!r} with a body."}
    passed = any(body in prompt for prompt in facts.get("prompts") or [])
    return {"passed": passed,
            "message": "" if passed else f"The {value.strip()} skill was not in any prompt."}


def expected_tool_calls(case) -> List[dict]:
    """The case's expected calls, one entry per call, matchers grouped onto it.

    Rows are authored flat — a row per argument to check — so several rows share
    a Call number when a call has more than one matcher. Order is the Call
    number, not the row order: the grid is a spreadsheet, and re-sorting it must
    not change what the case means.
    """
    grouped: dict = {}
    for row in case.get("expected_tool_calls") or []:
        # `.get` so a row works whether it arrived as a child Document or as a
        # plain dict from a caller that built the table by hand.
        tool = (row.get("tool_name") or "").strip()
        if not tool:
            continue
        order = cint(row.get("call_order"))
        entry = grouped.setdefault(order, {"order": order, "tool": tool, "matchers": []})
        argument = (row.get("argument") or "").strip()
        if argument:
            entry["matchers"].append({
                "argument": argument,
                "matcher": (row.get("matcher") or "equals").strip(),
                "expected": row.get("expected_value") or "",
            })
    return [grouped[k] for k in sorted(grouped)]


def _argument_matches(matcher: dict, args: dict) -> tuple:
    """Does one argument matcher hold against a call's arguments?

    Returns (passed, why-not). A missing argument fails rather than passing
    vacuously — a call that never received the argument did not satisfy a
    constraint on it.
    """
    name = matcher["argument"]
    if name not in (args or {}):
        return False, f"no argument {name!r}"

    actual = args.get(name)
    actual = actual if isinstance(actual, str) else json.dumps(actual, default=str, sort_keys=True)
    expected = matcher["expected"] or ""
    kind = matcher["matcher"]

    if kind == "equals":
        return actual.strip() == expected.strip(), f"{name}={actual!r} != {expected!r}"
    if kind == "contains":
        return expected.strip().lower() in actual.lower(), f"{name}={actual!r} lacks {expected!r}"
    if kind == "regex":
        return bool(re.search(expected, actual)), f"{name}={actual!r} does not match /{expected}/"
    return False, f"unknown matcher {kind!r}"


def _call_matches(expected: dict, actual: dict) -> tuple:
    """Does one actual call satisfy one expected call — tool and every matcher?"""
    if actual.get("tool") != expected["tool"]:
        return False, f"called {actual.get('tool')!r}"
    for matcher in expected["matchers"]:
        passed, why = _argument_matches(matcher, actual.get("args") or {})
        if not passed:
            return False, why
    return True, ""


def _evaluate_tool_calls(value: str, facts: dict) -> dict:
    """Score the run's tool-call trace against the case's expected calls.

    A right answer reached the wrong way is the failure this catches: the text
    reads fine, and only the trace shows that the agent guessed instead of
    looking, or wrote before it reviewed.

    Three modes, and the difference between them is what they allow:
      EXACT      the trace IS the expected sequence — same calls, same order,
                 nothing extra.
      IN_ORDER   every expected call appears, in the expected order; other
                 calls may happen in between.
      ANY_ORDER  every expected call appears somewhere; order is not checked.
    """
    if facts is None:
        return {"passed": False, "error": True,
                "message": "Tool calls are only observed on a live run, not a replay."}

    mode = (value or "").strip().upper()
    if mode not in TOOL_CALL_MODES:
        return {"passed": False, "error": True,
                "message": f"tool_calls needs one of {', '.join(TOOL_CALL_MODES)}, not {value!r}."}

    expected = facts.get("expected_tool_calls") or []
    if not expected:
        return {"passed": False, "error": True,
                "message": "tool_calls needs Expected Tool Calls on the case."}

    trace = facts.get("tool_trace") or []
    called = ", ".join(c.get("tool") or "?" for c in trace) or "nothing"

    if mode == "EXACT":
        if len(trace) != len(expected):
            return {"passed": False,
                    "message": f"Expected {len(expected)} call(s), the run made {len(trace)}: {called}."}
        for position, (want, got) in enumerate(zip(expected, trace), start=1):
            passed, why = _call_matches(want, got)
            if not passed:
                return {"passed": False, "message": f"Call {position} expected {want['tool']}: {why}."}
        return {"passed": True, "message": ""}

    if mode == "IN_ORDER":
        cursor = 0
        for want in expected:
            while cursor < len(trace) and not _call_matches(want, trace[cursor])[0]:
                cursor += 1
            if cursor == len(trace):
                return {"passed": False,
                        "message": f"No call to {want['tool']} after the previous expected one. Called: {called}."}
            cursor += 1
        return {"passed": True, "message": ""}

    unmatched = []
    remaining = list(trace)
    for want in expected:
        hit = next((i for i, got in enumerate(remaining) if _call_matches(want, got)[0]), None)
        if hit is None:
            unmatched.append(want["tool"])
        else:
            remaining.pop(hit)
    return {"passed": not unmatched,
            "message": "" if not unmatched else f"Never called: {', '.join(unmatched)}. Called: {called}."}


def _evaluate_tool_artifact(value: str, facts: dict) -> dict:
    """Match a dotted path in the JSON a tool recorded as its artifact.

    *value* is {"tool", "path", "matcher", "expected"}. The last call to the tool
    that recorded an artifact is the one checked.
    """
    if facts is None:
        return {"passed": False, "error": True,
                "message": "Tool artifacts are only recorded on a live run, not a replay."}
    spec = json.loads(value or "{}")
    tool, path = spec.get("tool"), spec.get("path")
    if not (tool and path):
        return {"passed": False, "error": True,
                "message": "tool_artifact needs a tool and a path."}

    calls = [c for c in facts.get("tool_trace") or [] if c.get("tool") == tool
             and (c.get("artifact") or c.get("artifact_file"))]
    if not calls:
        return {"passed": False, "error": True, "message": f"{tool} recorded no artifact."}
    last = calls[-1]
    text = last.get("artifact") or frappe.get_doc("File", last["artifact_file"]).get_content()

    resolved = _resolve_path(json.loads(text), path)
    expected = spec.get("expected")
    matcher = {
        "argument": path,
        "matcher": spec.get("matcher") or "equals",
        "expected": expected if isinstance(expected, str) else json.dumps(expected, sort_keys=True),
    }
    passed, why = _argument_matches(matcher, {path: resolved})
    return {"passed": passed, "message": "" if passed else why}


def _resolve_path(data: Any, path: str) -> Any:
    """Walk *path* key by key; a list along the way maps the rest of the path over its items."""
    # ponytail: keys and lists only, no filters or wildcards; add them when a case needs one.
    for key in path.split("."):
        if isinstance(data, list):
            data = [item.get(key) for item in data if isinstance(item, dict)]
        elif isinstance(data, dict):
            data = data.get(key)
        else:
            return None
    return data


def _judge_model_for(assertion) -> tuple[str, str]:
    """The model that grades an answer, and its provider.

    The assertion's own choice wins; failing that, Processa Settings names the
    grading model for scheduled runs. ``resolve_memory_model`` already
    implements that precedence, so it is reused rather than copied.
    """
    from one_bpmn.ai_agent_memory.model_resolution import resolve_memory_model

    model = resolve_memory_model(assertion.judge_model, "nightly_eval_grading_model", None) or ""
    provider = (assertion.judge_provider or "").strip()
    if model and not provider:
        provider = frappe.db.get_value("AI Model", model, "provider") or ""
    return model, provider


def _evaluate_llm_judge(assertion, output: Any) -> dict:
    """
    Call a judge LLM to score *output* against the rubric in *assertion.value*.

    Uses the same executor infrastructure as the main agent call. Returns a
    dict with type, passed, score, and explanation.
    """
    a_type = assertion.assertion_type
    value = assertion.value or ""
    base = {"assertion_type": a_type, "value": value}

    judge_prompt = JUDGE_PROMPT_TEMPLATE.format(
        rubric=value,
        actual_output=stringify(output),
    )

    # An assertion may name its own grader; when it does not, the site's
    # nightly grading model stands in, so a scheduled run does not depend on
    # every assertion carrying a model of its own.
    judge_model, judge_provider = _judge_model_for(assertion)

    judge_config = ExecutorConfig(
        backend="direct_api",
        provider_name=judge_provider,
        model=judge_model,
        system_prompt="",
        user_prompt=judge_prompt,
        response_format="json",
        # Pinned to 0.7 on purpose, not DEFAULT_TEMPERATURE.
        temperature=0.7,
    )
    judge_context = ExecutorContext()

    judge_started = now_datetime()
    try:
        executor_cls = get_executor(judge_config.backend)
        judge_result = executor_cls().run(judge_config, judge_context)
    except Exception as exc:
        # Scenario 4: a failed judge call is an ERROR, never
        # silently Passed or Failed.
        return {
            **base,
            "passed": False,
            "error": True,
            "score": 0,
            "explanation": f"Judge call failed: {exc}",
        }

    # The judge call spends real tokens of its own: report
    # them on the assertion so _execute_case can add them to the Result's
    # token/cost fields — otherwise the Run-level rollup undercounts.
    judge_prompt_tokens = prompt_tokens_of(judge_result)
    judge_completion_tokens = completion_tokens_of(judge_result)
    judge_in_cost, judge_out_cost = cost_split(
        judge_prompt_tokens, judge_completion_tokens, judge_config.model
    )
    judge_usage = {
        "judge_prompt_tokens": judge_prompt_tokens,
        "judge_completion_tokens": judge_completion_tokens,
        "judge_cost": judge_in_cost + judge_out_cost,
    }
    # The judge is a billed LLM call of its own. Record it in the AI Agent Run
    # ledger too (it never goes through an AI Agent Task), so cost reporting
    # built on runs is not missing judge spend. Recorded even when the judge
    # errored, as long as it consumed tokens.
    if judge_prompt_tokens or judge_completion_tokens:
        record_eval_run(
            EVAL_RUN_JUDGE,
            judge_config.provider_name,
            judge_config.model,
            judge_started,
            judge_prompt_tokens,
            judge_completion_tokens,
            judge_in_cost,
            judge_out_cost,
        )

    if judge_result.error_code != ErrorCode.SUCCESS:
        return {
            **base,
            **judge_usage,
            "passed": False,
            "error": True,
            "score": 0,
            "explanation": f"Judge call failed: {judge_result.error_message}",
        }

    # Parse the judge response — it may already be a dict (json response_format)
    # or a raw string.
    judge_output = judge_result.output
    if isinstance(judge_output, str):
        try:
            judge_output = json.loads(strip_code_fences(judge_output))
        except (json.JSONDecodeError, TypeError):
            return {
                **base,
                **judge_usage,
                "passed": False,
                "error": True,
                "score": 0,
                "explanation": "Judge returned invalid JSON",
            }

    if not isinstance(judge_output, dict):
        return {
            **base,
            **judge_usage,
            "passed": False,
            "error": True,
            "score": 0,
            "explanation": "Judge returned invalid JSON",
        }

    try:
        score = int(judge_output.get("score", 0))
    except (ValueError, TypeError):
        return {
            **base,
            **judge_usage,
            "passed": False,
            "error": True,
            "score": 0,
            "explanation": "Judge returned invalid JSON",
        }

    explanation = str(judge_output.get("explanation", ""))
    threshold = assertion.pass_threshold or 4
    passed = score >= threshold

    return {
        **base,
        **judge_usage,
        "passed": passed,
        "score": score,
        "explanation": explanation,
    }


def stringify(output: Any) -> str:
    """Render executor output as text for substring/regex/equals assertions."""
    if output is None:
        return ""
    if isinstance(output, str):
        return output
    return json.dumps(output)


def _tokens_of(result) -> int:
    return result.token_usage.total_tokens if result.token_usage else 0


def prompt_tokens_of(result) -> int:
    return result.token_usage.prompt_tokens if result.token_usage else 0


def completion_tokens_of(result) -> int:
    return result.token_usage.completion_tokens if result.token_usage else 0
