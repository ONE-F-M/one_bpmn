"""The Processa backend names a shipped agent script uses, which its script task's approval lists."""

from processa.ai_agent_security.code_checks.script_validator import inspect_script


def processa_imports(code: str) -> frozenset:
	return frozenset(f["name"] for f in inspect_script(code) if f["category"] == "Processa backend")
