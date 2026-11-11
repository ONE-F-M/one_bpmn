# Copyright (c) 2026, one-fm and contributors
"""Token budget for the memory block injected into an AI agent prompt, and the block's rendering."""

# Evals and the run inspector read this header.
MEMORY_BLOCK_HEADER = "Relevant memory:"
_MEMORY_BLOCK_PROVENANCE = "Possibly relevant notes from earlier work; use them only if they match this request."

# Per-agent default for the injected memory block; aiMemoryTokenBudget overrides it.
DEFAULT_MEMORY_TOKEN_BUDGET = 800


def bound_memories_to_budget(memories: list, token_budget: int) -> list:
	"""Keep rank-ordered memories while the rendered block fits token_budget; drop the tail.

	A hard ceiling: when even the first memory does not fit, its content is cut to fit.
	"""
	from one_bpmn.ai_agent_conversations.conversation_store import DEFAULT_CHARS_PER_TOKEN, estimate_tokens

	if not memories or not token_budget or token_budget <= 0:
		return memories

	header_cost = estimate_tokens({"content": format_memory_block([])}, DEFAULT_CHARS_PER_TOKEN)
	budget = max(token_budget - header_cost, 0)
	# The "\n- " each bullet adds costs about a token.
	per_item_overhead = 1

	kept = []
	spent = 0
	for m in memories:
		content = str((m or {}).get("content") or "")
		cost = estimate_tokens({"content": content}, DEFAULT_CHARS_PER_TOKEN) + per_item_overhead
		if spent + cost <= budget:
			kept.append(m)
			spent += cost
			continue
		if not kept:
			max_chars = max((budget - per_item_overhead) * DEFAULT_CHARS_PER_TOKEN, 0)
			if max_chars > 0:
				kept.append({**m, "content": content[:max_chars]})
		break
	return kept


def format_memory_block(memories: list) -> str:
	"""Render memories as the delimited block for the dynamic prompt layer, headed by MEMORY_BLOCK_HEADER."""
	lines = [MEMORY_BLOCK_HEADER, _MEMORY_BLOCK_PROVENANCE]
	for m in memories:
		content = (m.get("content") or "").strip()
		if content:
			lines.append(f"- {content}")
	return "\n".join(lines)
