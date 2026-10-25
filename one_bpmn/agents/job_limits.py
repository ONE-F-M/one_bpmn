# Copyright (c) 2026, one-fm and contributors
"""How long a queued AI agent job may run before the worker kills it, and which queue it runs on."""

# An agent turn is a model call plus tool execution, repeated up to the shape's
# aiMaxToolCalls. At 180s per call with 2 retries, three attempts alone reach
# 540s — so a 600s ceiling could kill a run before its first turn returned,
# recording zero tokens and no reason. 1800s is what eval_runner already uses
# on this queue.
AI_AGENT_JOB_TIMEOUT = 1800

# The queue every AI agent turn runs on unless its agent has a queue of its own.
AI_AGENT_QUEUE = "bpmn_ai_agent"

# A ProsAlly drawing runs for minutes. On the shared queue every other agent's turn waited behind it,
# and on a general queue it would hold up unrelated jobs, so its turns have a queue and a worker of their own.
PROSALLY_AGENT_ID = "prosally_agent"
PROSALLY_AI_QUEUE = "bpmn_ai_prosally"

# Every queue an agent turn can be on, for code that asks "is a job still queued or running?".
AI_AGENT_QUEUES = (AI_AGENT_QUEUE, PROSALLY_AI_QUEUE)


def ai_agent_queue(agent_id: str | None) -> str:
	"""The queue a turn for ``agent_id`` runs on: ProsAlly's own, the shared AI queue for everyone else."""
	if agent_id == PROSALLY_AGENT_ID:
		return PROSALLY_AI_QUEUE
	return AI_AGENT_QUEUE
