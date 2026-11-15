"""A run whose last tool answered with an error envelope that names a code did not finish its job."""

import json


def terminal_tool_failure(trace) -> dict:
	"""The status, error_code and error_message for finalize_ai_run when the last tool call failed with a code, else {}."""
	calls = [call for turn in trace or [] for call in (turn.get("tool_calls") or [])]
	if not calls:
		return {}
	text = str(calls[-1].get("result") or "")
	if not text.lstrip().startswith("{"):
		return {}
	try:
		body = json.loads(text)
	except ValueError:
		return {}
	if body.get("error") and body.get("error_code"):
		return {"status": "Error", "error_code": str(body["error_code"]), "error_message": str(body["error"])}
	return {}
