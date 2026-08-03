# Copyright (c) 2026, one-fm and contributors
# Importing this package registers the remaining Python handlers (the
# @connector decorators run on import). dispatch_connector imports it before
# resolving, so registration is guaranteed regardless of boot order.
#
# Most operations no longer need a handler at all — they are configured as HTTP
# requests on their BPMN Connector Operation row and run through http_ops. What
# is left here are the operations an HTTP template genuinely cannot express:
# multipart uploads, binary downloads that need parsing, and anything that has
# to make several calls and reason about the results in between.
#
# google_sheets has no module: every one of its operations is configuration.

from one_bpmn.one_bpmn.connectors import google_docs_ops  # noqa: F401,E402
from one_bpmn.one_bpmn.connectors import google_drive_ops  # noqa: F401,E402
from one_bpmn.one_bpmn.connectors import google_slides_ops  # noqa: F401,E402

__all__ = ["google_drive_ops", "google_docs_ops", "google_slides_ops"]
