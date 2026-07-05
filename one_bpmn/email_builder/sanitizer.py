"""AMP-safe HTML sanitiser for One BPMN email builder.

Uses ``bleach`` with an explicit AMP-for-Email allowlist so that every
outgoing HTML email body is guaranteed to contain *only* tags, attributes,
and URL schemes that AMP email providers accept.

Typical usage::

	from one_bpmn.email_builder.sanitizer import sanitize_for_amp

	clean_html = sanitize_for_amp(raw_html)

The module also exposes the allowlist constants (``AMP_ALLOWED_TAGS``,
``AMP_ALLOWED_ATTRIBUTES``) for reuse in tests or downstream tooling.
"""

from __future__ import annotations

import re
from html import unescape
from typing import Match

import bleach

# ---------------------------------------------------------------------------
# AMP-for-Email tag allowlist
# ---------------------------------------------------------------------------

AMP_ALLOWED_TAGS: frozenset[str] = frozenset(
	{
		# Structure
		"div", "span", "section", "article", "header", "footer", "nav", "main", "aside",
		# Text
		"p", "br", "hr", "blockquote", "pre", "code",
		"h1", "h2", "h3", "h4", "h5", "h6",
		"strong", "em", "b", "i", "u", "s", "sub", "sup", "small", "mark",
		# Lists
		"ul", "ol", "li", "dl", "dt", "dd",
		# Links
		"a",
		# Tables
		"table", "thead", "tbody", "tfoot", "tr", "th", "td",
		"caption", "colgroup", "col",
		# Media (AMP)
		"amp-img", "figure", "figcaption",
		# AMP components
		"amp-form",
		# Misc inline
		"abbr", "cite", "time", "q",
	}
)

# ---------------------------------------------------------------------------
# AMP-for-Email attribute allowlist
# ---------------------------------------------------------------------------

AMP_ALLOWED_ATTRIBUTES: dict[str, list[str]] = {
	"*": [
		"class", "id", "dir", "lang", "title",
		"role", "aria-label", "aria-hidden", "aria-describedby",
	],
	"a": ["href", "target", "rel"],
	"amp-img": ["src", "alt", "width", "height", "layout"],
	"th": ["colspan", "rowspan", "scope"],
	"td": ["colspan", "rowspan"],
	"col": ["span"],
	"colgroup": ["span"],
	"ol": ["start", "type", "reversed"],
	"time": ["datetime"],
	"blockquote": ["cite"],
	"q": ["cite"],
}

# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------

_IMG_RE = re.compile(
	r"<img\b([^>]*)\/?>",
	re.IGNORECASE | re.DOTALL,
)

_ATTR_RE = re.compile(
	r"""(src|alt|width|height)\s*=\s*(?:"([^"]*)"|'([^']*)')""",
	re.IGNORECASE,
)

_SCRIPT_RE = re.compile(r"<script\b[^>]*>.*?</script>", re.IGNORECASE | re.DOTALL)
_STYLE_TAG_RE = re.compile(r"<style\b[^>]*>.*?</style>", re.IGNORECASE | re.DOTALL)
_STYLE_ATTR_RE = re.compile(r'\s*style\s*=\s*"[^"]*"', re.IGNORECASE)

# Strip Frappe workflow action buttons (e.g. <a href="...confirm_action..." class="btn btn-primary btn-action">Approve</a>)
_WORKFLOW_BTN_RE = re.compile(
	r'<a\s[^>]*class\s*=\s*"[^"]*btn-action[^"]*"[^>]*>.*?</a>',
	re.IGNORECASE | re.DOTALL,
)


def _img_to_amp_img(html: str) -> str:
	"""Rewrite ``<img>`` tags to ``<amp-img>`` with HTTPS enforcement.

	Only images whose ``src`` starts with ``https://`` are kept; all others
	are silently dropped (replaced with an empty string).  Missing
	``width``/``height`` default to 600×400 and ``layout`` is always set to
	``responsive``.

	Args:
		html: Raw HTML string potentially containing ``<img>`` tags.

	Returns:
		HTML with ``<img>`` replaced by AMP-compatible ``<amp-img>`` tags.
	"""

	def _replace(match: Match[str]) -> str:
		attrs_str = match.group(1)
		attrs: dict[str, str] = {}
		for attr_match in _ATTR_RE.finditer(attrs_str):
			key = attr_match.group(1).lower()
			value = attr_match.group(2) if attr_match.group(2) is not None else attr_match.group(3)
			attrs[key] = value

		src = attrs.get("src", "")
		if not src.startswith("https://"):
			return ""

		alt = attrs.get("alt", "")
		width = attrs.get("width", "600")
		height = attrs.get("height", "400")

		return (
			f'<amp-img src="{src}" alt="{alt}" '
			f'width="{width}" height="{height}" layout="responsive">'
			f"</amp-img>"
		)

	return _IMG_RE.sub(_replace, html)


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------


def sanitize_for_amp(html: str) -> str:
	"""Sanitise arbitrary HTML into an AMP-for-Email safe fragment.

	Processing pipeline:

	1. **Unescape** HTML entities so bleach sees real characters.
	2. **Rewrite** ``<img>`` → ``<amp-img>`` (HTTPS only, others dropped).
	3. **Strip** ``<script>`` blocks entirely.
	4. **Strip** ``<style>`` blocks entirely.
	5. **Strip** inline ``style="…"`` attributes.
	6. **Bleach-clean** using the AMP allowlist (unknown tags/attrs removed).
	7. **Strip** leading/trailing whitespace and return.

	Args:
		html: Untrusted HTML string to sanitise.

	Returns:
		A sanitised HTML string containing only AMP-allowed tags and
		attributes, safe for embedding in an AMP-for-Email document.

	Example::

		>>> sanitize_for_amp('<p style="color:red">Hello <script>alert(1)</script></p>')
		'<p>Hello </p>'
	"""
	if not html:
		return ""

	# 1. Unescape HTML entities
	html = unescape(html)

	# 2. Rewrite <img> → <amp-img>
	html = _img_to_amp_img(html)

	# 3. Strip <script> blocks
	html = _SCRIPT_RE.sub("", html)

	# 4. Strip <style> blocks
	html = _STYLE_TAG_RE.sub("", html)

	# 5. Strip inline style= attributes
	html = _STYLE_ATTR_RE.sub("", html)

	# 6. Strip Frappe workflow action buttons (avoid duplicating our AMP buttons)
	html = _WORKFLOW_BTN_RE.sub("", html)

	# 7. Bleach-clean with AMP allowlist
	html = bleach.clean(
		html,
		tags=AMP_ALLOWED_TAGS,
		attributes=AMP_ALLOWED_ATTRIBUTES,
		strip=True,
	)

	# 7. Final whitespace trim
	return html.strip()
