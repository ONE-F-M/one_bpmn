"""
Measuring whether memory is any good, as numbers instead of an impression.

Three questions, each with its own answer here:

- **Generation.** Given an agent's output and the facts a person says should
  come out of it, how much of what the distiller produced was worth keeping
  (precision), how much of what mattered did it find (recall), and the two
  together (F1).
- **Retrieval.** Given a question and the memories that should answer it, how
  many of them come back in the top K (Recall@K).
- **Latency.** How long that retrieval took, against the budget it has to fit
  inside on the dispatch path.

Matching a produced memory to a golden one is the whole difficulty. The
distiller rewrites a fact in its own words, so comparing strings would score a
correct memory as a miss. Where embeddings are available the comparison is by
meaning; without them it falls back to comparing normalised words, which is
stricter and will under-report the result, never flatter it.
"""

from __future__ import annotations

import re
import time

# How alike two memories have to be to count as the same fact. Measured on
# all-MiniLM-L6-v2: the same fact in different words scores above 0.6, and
# unrelated facts in the same domain sit below 0.45.
SAME_FACT_SIMILARITY = 0.55
# What the dispatch path can afford to spend recalling, in milliseconds. Recall
# happens before the model is called, so it is added to every turn's latency.
RETRIEVAL_BUDGET_MS = 200


def _normalise(text: str) -> set[str]:
	return {w for w in re.split(r"\W+", (text or "").lower()) if w}


def _word_overlap(a: str, b: str) -> float:
	"""Jaccard overlap, the fallback when meaning cannot be measured."""
	left, right = _normalise(a), _normalise(b)
	if not left or not right:
		return 0.0
	return len(left & right) / len(left | right)


def _similarities(produced: list[str], golden: list[str]) -> list[list[float]]:
	"""How alike every produced memory is to every golden one.

	By meaning when embeddings are available, by words otherwise. A failure to
	embed is not an error here: the measurement degrades to the stricter
	comparison and says so through the score instead of refusing to run.
	"""
	try:
		from one_bpmn.agents.llm_provider.embedding import embed

		vectors = embed(list(produced) + list(golden))
	except Exception:
		vectors = None

	if not vectors or len(vectors) != len(produced) + len(golden):
		return [[_word_overlap(p, g) for g in golden] for p in produced]

	def cosine(a, b):
		dot = sum(x * y for x, y in zip(a, b, strict=False))
		norm = (sum(x * x for x in a) ** 0.5) * (sum(y * y for y in b) ** 0.5)
		return dot / norm if norm else 0.0

	produced_vectors = vectors[: len(produced)]
	golden_vectors = vectors[len(produced) :]
	return [[cosine(p, g) for g in golden_vectors] for p in produced_vectors]


def _match(produced: list[str], golden: list[str], threshold: float) -> set[int]:
	"""Which golden memories were produced. One produced memory can only claim
	one golden fact, so saying the same thing five ways does not score five."""
	scores = _similarities(produced, golden)
	claimed: set[int] = set()
	for row in scores:
		best, best_score = None, threshold
		for index, score in enumerate(row):
			if index not in claimed and score >= best_score:
				best, best_score = index, score
		if best is not None:
			claimed.add(best)
	return claimed


def score_generation(produced: list[str], golden: list[str], threshold: float = SAME_FACT_SIMILARITY) -> dict:
	"""Precision, recall and F1 for what the distiller made of one interaction.

	No golden facts and nothing produced is a pass, not a division by zero:
	correctly keeping nothing is the commonest right answer the distiller gives.
	"""
	produced = [p for p in (produced or []) if str(p).strip()]
	golden = [g for g in (golden or []) if str(g).strip()]
	if not produced and not golden:
		return {"precision": 1.0, "recall": 1.0, "f1": 1.0, "produced": 0, "golden": 0, "matched": 0}

	matched = _match(produced, golden, threshold) if produced and golden else set()
	precision = len(matched) / len(produced) if produced else 0.0
	recall = len(matched) / len(golden) if golden else 0.0
	f1 = (2 * precision * recall / (precision + recall)) if (precision + recall) else 0.0
	return {
		"precision": round(precision, 3),
		"recall": round(recall, 3),
		"f1": round(f1, 3),
		"produced": len(produced),
		"golden": len(golden),
		"matched": len(matched),
	}


def score_retrieval(returned: list[str], expected: list[str], k: int = 5, threshold: float = SAME_FACT_SIMILARITY) -> dict:
	"""Recall@K: how many of the memories that should answer a question came
	back in the top K. Ordering matters, so only the first K are considered."""
	expected = [e for e in (expected or []) if str(e).strip()]
	top = [r for r in (returned or []) if str(r).strip()][: max(int(k), 1)]
	if not expected:
		return {"recall_at_k": 1.0, "k": k, "expected": 0, "returned": len(top), "found": 0}

	found = _match(top, expected, threshold) if top else set()
	return {
		"recall_at_k": round(len(found) / len(expected), 3),
		"k": k,
		"expected": len(expected),
		"returned": len(top),
		"found": len(found),
	}


def timed(call) -> tuple[object, float]:
	"""Run ``call`` and report how many milliseconds it took."""
	started = time.perf_counter()
	result = call()
	return result, round((time.perf_counter() - started) * 1000, 1)


def within_budget(latency_ms: float, budget_ms: int = RETRIEVAL_BUDGET_MS) -> bool:
	return latency_ms <= budget_ms


def evaluate_memory_case(
	*,
	scope: str,
	scope_key,
	query: str = "",
	golden_memories: list[str] | None = None,
	expected_recall: list[str] | None = None,
	produced_memories: list[str] | None = None,
	k: int = 5,
) -> dict:
	"""Every number for one memory case, plus whether it passed.

	Generation is scored only when the case says what should have been produced,
	and retrieval only when it asks a question. A case may do either or both, so
	a suite can hold narrow cases and broad ones side by side.

	Passing means: nothing measured came out wrong, and retrieval stayed inside
	its budget. A case that measures nothing cannot fail, which is deliberate,
	since the alternative is a suite that goes red because somebody wrote an
	empty case.
	"""
	report: dict = {"passed": True, "measured": []}

	if golden_memories is not None and produced_memories is not None:
		generation = score_generation(produced_memories, golden_memories)
		report["generation"] = generation
		report["measured"].append("generation")
		if generation["f1"] < 1.0:
			report["passed"] = False

	if query:
		from one_bpmn.agents.memory.tools import memory_search

		rows, latency_ms = timed(
			lambda: memory_search(scope, scope_key, query, limit=max(int(k), 1), ignore_permissions=True)
		)
		retrieval = score_retrieval([r.get("content", "") for r in rows], expected_recall, k=k)
		report["retrieval"] = retrieval
		report["latency_ms"] = latency_ms
		report["within_budget"] = within_budget(latency_ms)
		report["measured"].append("retrieval")
		if retrieval["recall_at_k"] < 1.0 or not report["within_budget"]:
			report["passed"] = False

	return report
