# Copyright (c) 2026, one-fm and contributors
"""How long a queued AI agent job may run before the worker kills it, and which queue it runs on."""

# A turn is several model calls of up to 180s each with retries, so the job needs well over 600s.
AI_AGENT_JOB_TIMEOUT = 1800

AI_AGENT_QUEUE = "bpmn_ai_agent"

# ProsAlly drawings run for minutes, so its turns get their own queue and worker.
PROSALLY_AGENT_ID = "prosally_agent"
PROSALLY_AI_QUEUE = "bpmn_ai_prosally"

AI_AGENT_QUEUES = (AI_AGENT_QUEUE, PROSALLY_AI_QUEUE)


def ai_agent_queue(agent_id: str | None) -> str:
	"""The queue a turn for ``agent_id`` runs on: ProsAlly's own, the shared AI queue for everyone else."""
	if agent_id == PROSALLY_AGENT_ID:
		return PROSALLY_AI_QUEUE
	return AI_AGENT_QUEUE
