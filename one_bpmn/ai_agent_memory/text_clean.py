"""Shared plain-text cleaning for user-authored text that may carry markup.

``strip_html`` drops tags and decodes entities, so use it only where the text is known to be markup.
"""

from __future__ import annotations

import html
import re


def strip_html(text: str) -> str:
	"""Reduce HTML markup (tags and entities) to plain prose.

	Only appropriate where the text is already known to carry real markup,
	e.g. Chat Message text from a rich-text producer. Also collapses
	whitespace left behind by tag removal.
	"""
	if not text:
		return ""
	clean = re.sub(r"<[^>]+>", " ", text)
	clean = html.unescape(clean)
	return re.sub(r"\s+", " ", clean).strip()
