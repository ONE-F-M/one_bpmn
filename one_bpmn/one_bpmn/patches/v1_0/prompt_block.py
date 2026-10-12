"""Adds a block of rules to the end of an agent's prompt without disturbing the blocks around it."""


def with_block(prompt: str | None, rules: str) -> str:
	"""The prompt with `rules` as its last block; an earlier copy of the same block is replaced wherever it sits."""
	marker = rules.strip().splitlines()[0]
	kept = [block for block in (prompt or "").strip().split("\n\n") if block and not block.startswith(marker)]
	return "\n\n".join([*kept, rules.strip()]) + "\n"
