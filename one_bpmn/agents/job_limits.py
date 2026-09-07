# Copyright (c) 2026, one-fm and contributors
"""How long a queued AI agent job may run before the worker kills it."""

# An agent turn is a model call plus tool execution, repeated up to the shape's
# aiMaxToolCalls. At 180s per call with 2 retries, three attempts alone reach
# 540s — so a 600s ceiling could kill a run before its first turn returned,
# recording zero tokens and no reason. 1800s is what eval_runner already uses
# on this queue.
AI_AGENT_JOB_TIMEOUT = 1800
