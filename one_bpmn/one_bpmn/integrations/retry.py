# Copyright (c) 2026, one-fm and contributors
# Provider-neutral retry for outbound API calls.
#
# Lives here rather than in google_common because the connector HTTP executor —
# which knows nothing about Google — needs it too. google_common re-exports it so
# the existing Google integrations and any Script Task that imports it from there
# keep working unchanged.

import time

# Transient failures worth retrying: HTTP 429 (rate limit) and the 5xx family.
# Anything else is a real error and propagates immediately.
_TRANSIENT_STATUS = {429, 500, 502, 503, 504}


def http_status(exc):
    """The HTTP status carried by an exception, across the client libraries used.

    googleapiclient puts it on ``.resp.status``; ``requests`` puts it on
    ``.response.status_code``; some clients expose ``.status_code`` directly.
    """
    resp = getattr(exc, "resp", None)  # googleapiclient.errors.HttpError
    if resp is not None:
        try:
            return int(getattr(resp, "status", None))
        except (TypeError, ValueError):
            pass
    response = getattr(exc, "response", None)  # requests.HTTPError
    if response is not None:
        try:
            return int(getattr(response, "status_code", None))
        except (TypeError, ValueError):
            pass
    return getattr(exc, "status_code", None)


def call_with_retry(fn, *args, attempts=3, base_delay=0.5, **kwargs):
    """Call ``fn(*args, **kwargs)``, retrying transient failures with backoff.

    Pass the request's bound ``.execute`` so each retry re-issues the call, e.g.
    ``call_with_retry(service.documents().get(documentId=x).execute)``.
    """
    last = None
    for i in range(attempts):
        try:
            return fn(*args, **kwargs)
        except Exception as exc:  # noqa: BLE001 — we re-raise unless transient
            last = exc
            if http_status(exc) in _TRANSIENT_STATUS and i < attempts - 1:
                time.sleep(base_delay * (2**i))
                continue
            raise
    raise last
