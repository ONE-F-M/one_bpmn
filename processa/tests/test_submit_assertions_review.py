# Copyright (c) 2026, one-fm and contributors
"""Submit Assertions freezes what the checker approved, even though the dispatcher stores the answer under two names."""

import json
import unittest
from unittest.mock import patch

from processa.patches.v1_0 import submit_assertions_reads_one_review as p

# The stored script, as it was on staging.
SCRIPT = '# Testing Agent tool: submit_assertions. Sends the assertions (one line each, starting with the criterion id) to the Assertion Checker,\n# then freezes the approved ones: the lines the checker approved are hashed with sha256, per criterion, into the turn state. run_specs\n# later refuses a spec whose assertion lines no longer match. Only lines the checker itself reviewed can be frozen.\nimport hashlib\nimport json\nimport re\n\nfrom processa.ai_agent_skills.tools.shape_tools import execute_shape\nfrom processa.processa_engine.agent_runtime.turn_state import get_turn, update_turn\n\n\ndef _norm(text):\n    return re.sub(r"\\s+", " ", str(text or "")).strip()\n\n\n_by_id = {}\n_order = []\nfor _line in str(task_data.get("assertions") or "").splitlines():\n    _m = re.match(r"^\\s*(AC\\s*\\d+)\\s*:\\s*(.+)$", _line, re.I)\n    if _m:\n        _id = re.sub(r"\\s+", "", _m.group(1)).upper()\n        _by_id.setdefault(_id, []).append(_norm(_m.group(2)))\n        if _id not in _order:\n            _order.append(_id)\n\nif not _by_id:\n    result["error"] = "assertions is required: one line per assertion, each starting with the criterion id, for example \'AC1: the Save button is disabled when the name is empty (UI)\'."\nelse:\n    _text = "\\n".join(_id + ": " + _l for _id in _order for _l in _by_id[_id])\n    _criteria = "\\n".join(task_data.get("criteria") or [])\n    _raw = execute_shape(instance, "assertion_checker", None, {"criteria_text": _criteria, "assertions_to_check": _text})\n    _out = json.loads(_raw) if isinstance(_raw, str) else (_raw or {})\n    if _out.get("error"):\n        result["error"] = "The Assertion Checker could not review the assertions: " + str(_out.get("error"))\n    else:\n        _review = "\\n".join(str(v) for v in _out.values() if isinstance(v, str))\n        _approved_lines = {}\n        _reasons = {}\n        for _r in _review.splitlines():\n            _parts = [p.strip() for p in _r.split("|")]\n            if len(_parts) >= 2 and _parts[0].upper() in ("APPROVED", "REJECTED"):\n                _m = re.match(r"^(AC\\s*\\d+)\\s*:\\s*(.+)$", _parts[1], re.I)\n                if not _m:\n                    continue\n                _id = re.sub(r"\\s+", "", _m.group(1)).upper()\n                if _parts[0].upper() == "APPROVED":\n                    _approved_lines.setdefault(_id, []).append(_norm(_m.group(2)))\n                else:\n                    _reasons[_id] = _parts[2] if len(_parts) > 2 else "The checker rejected it without a reason."\n        _turn = get_turn(context_docname)\n        _hashes = dict(_turn.get("assertion_hashes") or {})\n        _approved = {}\n        _rejected = {}\n        for _id in _order:\n            _mine = _by_id[_id]\n            if _id not in _reasons and _approved_lines.get(_id) == _mine:\n                _hashes[_id] = {"hash": hashlib.sha256("\\n".join(_mine).encode("utf-8")).hexdigest(), "lines": _mine}\n                _approved[_id] = _hashes[_id]["hash"][:12]\n            else:\n                _rejected[_id] = _reasons.get(_id) or "The checker did not approve every line exactly as written."\n        update_turn(context_docname, assertion_hashes=_hashes)\n        result["approved"] = _approved\n        result["rejected"] = _rejected\n        result["next"] = "Put each approved line in its spec as a comment, exactly: // ASSERT AC1: <the line>. run_specs refuses a spec whose assertion lines differ."\n'

LINES = "AC1: the intro line is visible (UI)\nAC2: the fields are visible (UI)\nAC2: saving shows no error (UI)"
ANSWER = "\n".join("APPROVED | " + line for line in LINES.splitlines())


def _submit(script, produced):
	saved = {}
	namespace = {
		"task_data": {"assertions": LINES, "criteria": ["AC1 | Given | When | Then", "AC2 | Given | When | Then"]},
		"instance": object(), "context_docname": "A2A-1", "result": {},
	}
	with (
		patch("processa.ai_agent_skills.tools.shape_tools.execute_shape", return_value=json.dumps(produced)),
		patch("processa.processa_engine.agent_runtime.turn_state.get_turn", return_value={}),
		patch("processa.processa_engine.agent_runtime.turn_state.update_turn", side_effect=lambda name, **kw: saved.update(kw)),
	):
		exec(compile(script, "submit_assertions", "exec"), namespace)
	return namespace["result"], saved


def _patched():
	script = SCRIPT
	script = script.replace(p.OLD, p.NEW)
	return script


class TestSubmitAssertionsReview(unittest.TestCase):
	BOTH = {"assertion_review": ANSWER, "assertion_checker_output": ANSWER}

	def test_before_the_fix_a_duplicated_answer_rejects_everything_with_no_reason(self):
		result, _saved = _submit(SCRIPT, self.BOTH)
		self.assertEqual(result["approved"], {})
		self.assertIn("did not approve every line exactly as written", result["rejected"]["AC1"])

	def test_after_the_fix_the_approved_lines_are_frozen(self):
		result, saved = _submit(_patched(), self.BOTH)
		self.assertEqual(sorted(result["approved"]), ["AC1", "AC2"])
		self.assertEqual(result["rejected"], {})
		self.assertEqual(sorted(saved["assertion_hashes"]), ["AC1", "AC2"])

	def test_a_rejected_line_still_comes_back_with_its_reason(self):
		first, *rest = ANSWER.splitlines()
		answer = "\n".join(["REJECTED" + first[len("APPROVED"):] + " | it misses the Then clause", *rest])
		result, _saved = _submit(_patched(), {"assertion_review": answer, "assertion_checker_output": answer})
		self.assertEqual(result["rejected"]["AC1"], "it misses the Then clause")
		self.assertEqual(sorted(result["approved"]), ["AC2"])

	def test_it_reads_the_other_name_when_only_that_one_is_present(self):
		result, _saved = _submit(_patched(), {"assertion_checker_output": ANSWER})
		self.assertEqual(sorted(result["approved"]), ["AC1", "AC2"])

	def test_the_patch_is_idempotent(self):
		self.assertEqual(_patched().replace(p.OLD, p.NEW), _patched())
