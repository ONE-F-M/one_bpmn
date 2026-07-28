# Copyright (c) 2026, one-fm and contributors
# Importing this package registers every connector's handlers (the @connector
# decorators run on import). dispatch_connector imports this package before
# looking a handler up, so registration is guaranteed regardless of boot order.

from one_bpmn.one_bpmn.connectors import google_docs_ops  # noqa: F401,E402
from one_bpmn.one_bpmn.connectors import google_drive_ops  # noqa: F401,E402
from one_bpmn.one_bpmn.connectors import google_sheets_ops  # noqa: F401,E402
from one_bpmn.one_bpmn.connectors import google_slides_ops  # noqa: F401,E402

__all__ = ["google_drive_ops", "google_docs_ops", "google_slides_ops", "google_sheets_ops"]
