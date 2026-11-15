# Copyright (c) 2026, one-fm and contributors
"""Provider-neutral retry for outbound API calls, used by the HTTP executor, the Google clients and A2A."""

import time

# HTTP 429 and the 5xx family are retried; anything else propagates at once.
_TRANSIENT_STATUS = {429, 500, 502, 503, 504}


def http_status(exc):
	"""The HTTP status an exception carries: googleapiclient .resp.status, requests .response.status_code, or .status_code."""
	resp = getattr(exc, "resp", None)
	if resp is not None:
		try:
			return int(getattr(resp, "status", None))
		except (TypeError, ValueError):
			pass
	response = getattr(exc, "response", None)
	if response is not None:
		try:
			return int(getattr(response, "status_code", None))
		except (TypeError, ValueError):
			pass
	return getattr(exc, "status_code", None)


def call_with_retry(fn, *args, attempts=3, base_delay=0.5, **kwargs):
	"""Call fn(*args, **kwargs), retrying transient failures with exponential backoff.

	Pass the request's bound .execute so each retry re-issues the call.
	"""
	last = None
	for i in range(attempts):
		try:
			return fn(*args, **kwargs)
		except Exception as exc:
			last = exc
			if http_status(exc) in _TRANSIENT_STATUS and i < attempts - 1:
				time.sleep(base_delay * (2**i))
				continue
			raise
	raise last
