"""ProsAlly - Tool Generate Process splits a phase the model cuts off, instead of failing the whole process.

The script keeps its own shape and every feature it already has. This patch edits it in place at named
anchors and replaces nothing else, so it works on the helper-based script on BA and on the older inline
script on Staging. Every edit applies or none does.

- A phase that is cut off is replaced by two parts, each generated in turn, and a part that is cut off is
  split once more. After two levels generation stops: the reply names the phase and says how many phases
  were drawn, and the tool result has generated false. Phases already generated are kept.
- Phase calls use the full token budget, and the full, outline and phase prompts ask for one-line JSON.
- A request that lists more than 25 elements skips the single full attempt and asks for the outline first.
- Every cut-off model call is recorded as an AI Agent Step: sub_call with error_code TRUNCATED.

Idempotent: a script that already has _MAX_SPLIT_DEPTH is left alone.
"""

import re

import frappe

API_METHOD = "prosally_tool_generate_process"
MARKER = "_MAX_SPLIT_DEPTH"

CONSTANTS = r"""_MAX_SPLIT_DEPTH = 2
_MAX_ONE_PASS_ELEMENTS = 25
# A spec can list its elements inline, all on one line: "12 ScriptTask 'Validate Dates'|Sys".
_TYPED_ELEMENT = r"\b\d{1,3}\s+\w*(?:Event|Task|Gateway|Activity|SubProcess)\s+[\x27\x22]"
"""

COUNT = r"""# Size of the request: lines that start a numbered or bulleted item, or numbered typed elements written inline.
_user_text = ""
for _e in chat_history:
    if (_e.get("role") or _e.get("type", "user")) == "user":
        _user_text += (_e.get("content") or "") + "\n"
_user_text += turn.get("user_text") or ""
_listed_items = len(re.findall(r"(?m)^\s*(?:\d+[.)]|[-*])\s+\S", _user_text))
_element_count = max(_listed_items, len(re.findall(_TYPED_ELEMENT, _user_text)))
_skip_full = _element_count > _MAX_ONE_PASS_ELEMENTS
"""

SKIP_FULL = r"""if attempt == 0 and _skip_full:
    _skipped_full = True
    raise LLMTruncatedError("skipped: the request lists more than " + str(_MAX_ONE_PASS_ELEMENTS) + " elements")
"""

SPLIT = r"""_cut_offs.append((int((time.perf_counter() - _call_started) * 1000), (_phase.get("name") or "phase") + (" (part)" if _phase.get("part") else "")))
_depth = _phase.get("_depth", 0)
if _depth >= _MAX_SPLIT_DEPTH:
    _chunk_ok = False
    _fail_label = _phase.get("name") or ("phase " + str(_pi + 1))
    break
# Cut off: two parts replace this piece and are generated in its place.
_lo = _phase.get("_lo", 0)
_hi = _phase.get("_hi", 100)
_mid = (_lo + _hi) // 2
_half_a = dict(_phase)
_half_a["_depth"] = _depth + 1
_half_a["_lo"] = _lo
_half_a["_hi"] = _mid
_half_a["part"] = "This phase is too long for one answer, so it is generated in pieces. Generate ONLY the steps from " + str(_lo) + "% to " + str(_mid) + "% of this phase, in order."
_half_b = dict(_phase)
_half_b["_depth"] = _depth + 1
_half_b["_lo"] = _mid
_half_b["_hi"] = _hi
_half_b["part"] = "This phase is too long for one answer, so it is generated in pieces. Generate ONLY the steps from " + str(_mid) + "% to " + str(_hi) + "% of this phase, in order."
_phases[_pi:_pi + 1] = [_half_a, _half_b]
_pi -= 1
continue
"""

FAILED_AT = r"""if _fail_label:
    _drawn_names = []
    for _dp in _phases[:_pi]:
        if _dp.get("name") != _fail_label and _dp.get("name") not in _drawn_names:
            _drawn_names.append(_dp.get("name"))
    _size_msg = (
        "I drew " + str(len(_drawn_names)) + " of " + str(_outline_count) + " phases, but could not generate the phase \"" + _fail_label
        + "\", even after splitting it into smaller pieces twice. " + _size_msg
    )
"""

RECORD = r"""if _cut_offs:
    from one_bpmn.agents.observability import record_truncated_calls
    record_truncated_calls(_cut_offs)
"""


def _indent(block: str, width: int) -> str:
	return "".join(" " * width + line if line.strip() else line for line in block.splitlines(keepends=True))


def _once(script: str, pattern: str, build, name: str) -> str:
	"""script with the one match of pattern replaced by build(match); ValueError naming the anchor unless it matches once."""
	matches = list(re.finditer(pattern, script, re.MULTILINE))
	if len(matches) != 1:
		raise ValueError(f"{name}: expected one match, found {len(matches)}")
	found = matches[0]
	return script[: found.start()] + build(found) + script[found.end() :]


def _text_once(script: str, old: str, new: str, name: str) -> str:
	return _once(script, re.escape(old), lambda _match: new, name)


def rewrite(script: str) -> str:
	"""script with the split, skip and recording edits applied; unchanged when it already has them, ValueError when an anchor is missing."""
	if MARKER in script:
		return script
	if not re.search(r"^import re$", script, re.MULTILINE):
		script = _once(script, r"^import json$", lambda m: "import json\nimport re", "import re")
	script = _once(script, r"^import json$", lambda m: "import json\nimport time", "import time")
	script = _once(
		script, r"^_MAX_PHASES = 6$", lambda m: m.group(0) + "\n" + CONSTANTS.rstrip("\n"), "constants"
	)
	script = _once(
		script,
		r"^_truncated_error = False$",
		lambda m: m.group(0) + "\n_cut_offs = []\n_skipped_full = False",
		"cut-off list",
	)
	script = _once(
		script,
		r'^chat_history = turn\.get\("chat_history", \[\]\) or \[\]$',
		lambda m: m.group(0) + "\n\n" + COUNT.rstrip("\n"),
		"element count",
	)
	script = _prompts(script)
	script = _full_attempt(script)
	script = _outline(script)
	script = _phase_loop(script)
	return _once(
		script, r"^if not _truncated_error:$", lambda m: RECORD + m.group(0), "recording of cut-off calls"
	)


def _prompts(script: str) -> str:
	script = _text_once(
		script,
		'_parts.append("Output the IR JSON now.")',
		'_parts.append("Output the IR JSON now, as one line of JSON with no indentation or line breaks.")',
		"full prompt",
	)
	script = _text_once(
		script,
		r"Fix every problem listed above, then output the complete corrected IR JSON.\n\n",
		r"Fix every problem listed above, then output the complete corrected IR JSON as one line with no indentation.\n\n",
		"repair prompt",
	)
	script = _text_once(
		script,
		r"Respond with ONLY this JSON object, no other text:\n",
		r"Respond with ONLY this JSON object, as one line of JSON with no indentation:\n",
		"outline prompt",
	)
	return _text_once(
		script,
		"just this phase's own nodes and flows: ",
		"just this phase's own nodes and flows, as one line of JSON with no indentation: ",
		"phase prompt",
	)


def _full_attempt(script: str) -> str:
	script = _once(
		script,
		r"^        raw = (?:complete_sub_prompt|run_sync)\(.*$",
		lambda m: _indent(SKIP_FULL, 8) + "        _call_started = time.perf_counter()\n" + m.group(0),
		"full attempt call",
	)
	return _once(
		script,
		r"^    except LLMTruncatedError:$",
		lambda m: m.group(0)
		+ "\n"
		+ _indent(
			"if _skipped_full:\n    _skipped_full = False\nelse:\n"
			'    _cut_offs.append((int((time.perf_counter() - _call_started) * 1000), "full generation"))',
			8,
		),
		"full attempt cut-off",
	)


def _outline(script: str) -> str:
	script = _once(
		script,
		r"^            _outline_raw = (?:complete_sub_prompt|run_sync)\(.*$",
		lambda m: "            _call_started = time.perf_counter()\n" + m.group(0),
		"outline call",
	)
	return _once(
		script,
		r'^        except LLMTruncatedError:\n            _outline_raw = ""$',
		lambda m: "        except LLMTruncatedError:\n"
		'            _cut_offs.append((int((time.perf_counter() - _call_started) * 1000), "outline"))\n'
		'            _outline_raw = ""',
		"outline cut-off",
	)


def _phase_loop(script: str) -> str:
	script = _once(
		script,
		r"^        for _pi, _phase in enumerate\(_phases\):$",
		lambda m: "        _pi = -1\n        while _pi + 1 < len(_phases):\n            _pi += 1\n            _phase = _phases[_pi]",
		"phase loop",
	)
	script = _once(
		script,
		r"^            if _prev_exit:$",
		lambda m: '            if _phase.get("part"):\n                _phase_parts.append(_phase["part"])\n'
		+ m.group(0),
		"phase part instruction",
	)
	script = _once(
		script,
		r"^                _phase_raw = (?:complete_sub_prompt|run_sync)\(.*$",
		lambda m: "                _call_started = time.perf_counter()\n"
		+ m.group(0).replace("max_tokens=8192", "max_tokens=_max_tokens"),
		"phase call",
	)
	script = _once(
		script,
		r"^            except LLMTruncatedError:\n                _chunk_ok = False\n                break$",
		lambda m: "            except LLMTruncatedError:\n" + _indent(SPLIT, 16).rstrip("\n"),
		"phase cut-off",
	)
	script = _once(
		script,
		r"^        _chunk_ok = bool\(_phases\)$",
		lambda m: m.group(0) + '\n        _fail_label = ""\n        _outline_count = len(_phases)',
		"phase bookkeeping",
	)
	return _once(
		script,
		r'^                "need most\."\n            \)$',
		lambda m: m.group(0) + "\n" + _indent(FAILED_AT, 12).rstrip("\n"),
		"stop message",
	)


def execute():
	name = frappe.db.get_value("Server Script", {"api_method": API_METHOD}, "name")
	if not name:
		frappe.log_error(
			title="ProsAlly Generate Process: split patch skipped",
			message=f"No Server Script has api_method {API_METHOD}, so nothing was changed.",
		)
		return
	script = frappe.db.get_value("Server Script", name, "script") or ""
	try:
		updated = rewrite(script)
	except ValueError as error:
		frappe.log_error(
			title="ProsAlly Generate Process: split patch skipped",
			message=f"{name} was left as it is: {error}",
		)
		return
	if updated != script:
		frappe.db.set_value("Server Script", name, "script", updated, update_modified=False)
