# Copyright (c) 2026, one-fm and contributors
# For license information, please see license.txt
"""The exact system prompt some run used, stored once (WI-002190).

Runs carry a ``prompt_hash``; the text itself lives here, one row per
distinct prompt. That is content addressing, and it is deliberate: the
question this answers is "which text produced these results", which needs
the run to name a version and the version to be readable. Copying several
kilobytes onto every run would answer it too, thousands of times over, and
leave nothing to group by.

Rows are written automatically the first time a hash is seen. There is no
version management here on purpose: no one curates these, and a prompt that
was never run has no row because it never produced a result to explain.
"""

from frappe.model.document import Document


class AIPromptSnapshot(Document):
	pass
