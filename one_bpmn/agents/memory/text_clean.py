"""
Shared plain-text cleaning for user-authored text that may carry markup.

``strip_html`` was extracted from ``compaction.py`` (the conversation
summarizer's read path, where content is known to carry real HTML markup
from a rich-text producer) so it isn't re-derived elsewhere. ``unescape_entities``
is the narrower, safe-by-default half of the same cleanup: decoding a handful
of named HTML entities is lossless whenever the text really was HTML-escaped,
whereas stripping anything shaped like ``<...>`` is only safe once you already
know the text is markup — plain chat text can legitimately contain a literal
``<PROJECT>``-style placeholder or a comparison like ``a < b``, and blindly
tag-stripping those would corrupt them. Message ingestion (see
``api.agent_invocation.invoke_agent``) only needs entity-decoding: the observed
defect there is HTML-escaped entities surviving into durable content, not
markup tags.
"""

from __future__ import annotations

import re

_ENTITIES = (
	("&amp;", "&"), ("&lt;", "<"), ("&gt;", ">"),
	("&quot;", '"'), ("&#39;", "'"), ("&nbsp;", " "),
)


def unescape_entities(text: str) -> str:
	"""Decode the handful of named HTML entities a producer may have escaped.

	Lossless: only ever turns an entity sequence back into the literal
	character it stands for, never touches anything else. Safe to apply
	unconditionally to any inbound plain text, unlike ``strip_html``'s
	tag-stripping.
	"""
	if not text:
		return ""
	clean = text
	for entity, char in _ENTITIES:
		clean = clean.replace(entity, char)
	return clean


def strip_html(text: str) -> str:
	"""Reduce HTML markup (tags and entities) to plain prose.

	Only appropriate where the text is already known to carry real markup —
	e.g. Chat Message text from a rich-text producer. Also collapses
	whitespace left behind by tag removal, which ``unescape_entities`` alone
	does not need to do.
	"""
	if not text:
		return ""
	clean = re.sub(r"<[^>]+>", " ", text)
	clean = unescape_entities(clean)
	return re.sub(r"\s+", " ", clean).strip()
