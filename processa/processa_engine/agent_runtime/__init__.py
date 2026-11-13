import random


def backoff_seconds(attempt: int, base_ms: float, cap: float | None = None) -> float:
	delay = (base_ms / 1000.0) * (2**attempt)
	if cap is not None:
		delay = min(delay, cap)
	return delay + random.uniform(0, 0.1)
