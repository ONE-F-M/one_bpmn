"""AMP-safe HTML sanitiser for One BPMN email builder.

Uses ``bleach`` with an explicit AMP-for-Email allowlist so that every
outgoing HTML email body is guaranteed to contain *only* tags, attributes,
CSS properties and URL schemes that AMP email providers accept.

Typical usage::

	from one_bpmn.email_builder.sanitizer import sanitize_for_amp

	clean_html = sanitize_for_amp(raw_html)

Use :func:`sanitize_for_amp_with_css` when the rules of ``<style>`` blocks
are needed as well; they are returned separately so they can be printed in
the single ``<style amp-custom>`` of the AMP shell.

The module also exposes the allowlist constants (``AMP_ALLOWED_TAGS``,
``AMP_ALLOWED_ATTRIBUTES``, ``AMP_ALLOWED_CSS_PROPERTIES``) for reuse in
tests or downstream tooling.
"""

from __future__ import annotations

import re
from html import unescape
from typing import Match

import bleach
import tinycss2
from bleach.css_sanitizer import CSSSanitizer

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
		"class", "id", "dir", "lang", "title", "style",
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
# AMP-for-Email CSS property allowlist
# ---------------------------------------------------------------------------

# ``position`` is listed but its fixed and sticky values are removed separately.
AMP_ALLOWED_CSS_PROPERTIES: frozenset[str] = frozenset(
	{
		"background", "background-color", "background-position", "background-repeat",
		"background-size",
		"border", "border-top", "border-right", "border-bottom", "border-left",
		"border-color", "border-style", "border-width",
		"border-top-color", "border-right-color", "border-bottom-color", "border-left-color",
		"border-top-style", "border-right-style", "border-bottom-style", "border-left-style",
		"border-top-width", "border-right-width", "border-bottom-width", "border-left-width",
		"border-radius", "border-collapse", "border-spacing",
		"border-top-left-radius", "border-top-right-radius",
		"border-bottom-left-radius", "border-bottom-right-radius",
		"box-shadow", "box-sizing",
		"caption-side", "clear", "color", "direction", "display", "empty-cells", "float",
		"font", "font-family", "font-size", "font-style", "font-variant", "font-weight",
		"height", "min-height", "max-height", "width", "min-width", "max-width",
		"letter-spacing", "line-height", "list-style", "list-style-type", "list-style-position",
		"margin", "margin-top", "margin-right", "margin-bottom", "margin-left",
		"padding", "padding-top", "padding-right", "padding-bottom", "padding-left",
		"opacity", "position", "table-layout",
		"text-align", "text-decoration", "text-indent", "text-shadow", "text-transform",
		"vertical-align", "visibility", "white-space", "word-break", "word-spacing",
		"overflow-wrap",
	}
)

# Anything in a CSS value that could load a resource or break out of the style tag.
_BLOCKED_CSS_VALUE_PARTS: tuple[str, ...] = (
	"url(", "expression(", "javascript:", "@import", "<", "\\",
)

# Class names and ids that AMP reserves for itself.
_RESERVED_SELECTOR_RE = re.compile(r"(-amp-|i-amphtml)", re.IGNORECASE)

# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------

_IMG_RE = re.compile(
	r"<img\b([^>]*)\/?>",
	re.IGNORECASE | re.DOTALL,
)

_ATTR_RE = re.compile(
	r"""(?<![\w-])(src|alt|width|height)\s*=\s*(?:"([^"]*)"|'([^']*)')""",
	re.IGNORECASE,
)

_DIMENSION_RE = re.compile(r"^\s*(\d+(?:\.\d+)?)\s*(?:px)?\s*$", re.IGNORECASE)

_SCRIPT_RE = re.compile(r"<script\b[^>]*>.*?</script>", re.IGNORECASE | re.DOTALL)
_STYLE_TAG_RE = re.compile(r"<style\b[^>]*>(.*?)</style>", re.IGNORECASE | re.DOTALL)
_STYLE_UNCLOSED_RE = re.compile(r"<style\b[^>]*>.*$", re.IGNORECASE | re.DOTALL)
_STYLE_ATTR_RE = re.compile(
	r"""(?<![\w-])style\s*=\s*(?:"([^"]*)"|'([^']*)')""",
	re.IGNORECASE,
)
_EMPTY_STYLE_ATTR_RE = re.compile(r'\s+style=(?:""|\'\')')

# Strip Frappe workflow action buttons (e.g. <a href="...confirm_action..." class="btn btn-primary btn-action">Approve</a>)
_WORKFLOW_BTN_RE = re.compile(
	r'<a\s[^>]*class\s*=\s*"[^"]*btn-action[^"]*"[^>]*>.*?</a>',
	re.IGNORECASE | re.DOTALL,
)

_CSS_SANITIZER = CSSSanitizer(allowed_css_properties=sorted(AMP_ALLOWED_CSS_PROPERTIES))


def _dimension(value: str | None, default: str) -> str:
	"""Return *value* as a plain number string, or *default* when it is missing or not numeric."""
	if value is None:
		return default
	match = _DIMENSION_RE.match(value)
	return match.group(1) if match else default


def _img_to_amp_img(html: str) -> str:
	"""Rewrite ``<img>`` tags to ``<amp-img>`` with HTTPS enforcement.

	Only images whose ``src`` starts with ``https://`` are kept; all others
	are silently dropped (replaced with an empty string).  The image's own
	numeric ``width`` and ``height`` are kept; a missing or non-numeric one
	defaults to 600 and 400.  ``layout`` is always set to ``responsive``.

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
		width = _dimension(attrs.get("width"), "600")
		height = _dimension(attrs.get("height"), "400")

		return (
			f'<amp-img src="{src}" alt="{alt}" '
			f'width="{width}" height="{height}" layout="responsive">'
			f"</amp-img>"
		)

	return _IMG_RE.sub(_replace, html)


def _clean_declarations(css: str, *, enforce_allowlist: bool) -> str:
	"""Return the declarations of *css* that are safe for AMP, as ``name: value`` pairs.

	``!important`` is dropped (the flag is not part of the kept value), as are
	declarations that load resources and ``position`` fixed or sticky.  The
	property allowlist is applied here only when *enforce_allowlist* is set;
	inline styles leave it to bleach's CSSSanitizer.
	"""
	parsed = tinycss2.parse_declaration_list(css, skip_comments=True, skip_whitespace=True)
	kept: list[str] = []
	for item in parsed:
		if item.type != "declaration":
			continue
		name = item.lower_name
		if enforce_allowlist and name not in AMP_ALLOWED_CSS_PROPERTIES:
			continue
		value = tinycss2.serialize(item.value).strip()
		lowered = value.lower()
		if not value or any(part in lowered for part in _BLOCKED_CSS_VALUE_PARTS):
			continue
		if name == "position" and ("fixed" in lowered or "sticky" in lowered):
			continue
		kept.append(f"{name}: {value}")
	return "; ".join(kept)


def _clean_rule(rule, *, nested: bool = False) -> str:
	"""Return one CSS rule cleaned for AMP, or an empty string when nothing is left."""
	if rule.type == "qualified-rule":
		prelude = tinycss2.serialize(rule.prelude).strip()
		if not prelude or "<" in prelude or "\\" in prelude or _RESERVED_SELECTOR_RE.search(prelude):
			return ""
		declarations = _clean_declarations(tinycss2.serialize(rule.content), enforce_allowlist=True)
		return f"{prelude} {{ {declarations} }}" if declarations else ""

	# Only @media survives; @import, @font-face and the rest are dropped.
	if rule.type == "at-rule" and rule.lower_at_keyword == "media" and not nested and rule.content:
		prelude = tinycss2.serialize(rule.prelude).strip()
		if "<" in prelude or "\\" in prelude:
			return ""
		inner = tinycss2.parse_rule_list(rule.content, skip_comments=True, skip_whitespace=True)
		body = "\n".join(filter(None, (_clean_rule(r, nested=True) for r in inner)))
		return f"@media {prelude} {{\n{body}\n}}" if body else ""

	return ""


def _clean_stylesheet(css: str) -> str:
	"""Return the AMP-safe rules of a stylesheet, one rule per line."""
	rules = tinycss2.parse_stylesheet(css, skip_comments=True, skip_whitespace=True)
	return "\n".join(filter(None, (_clean_rule(rule) for rule in rules)))


def _prepare_inline_styles(html: str) -> str:
	"""Drop the parts of every ``style`` attribute that bleach would not remove itself."""

	def _replace(match: Match[str]) -> str:
		value = match.group(1) if match.group(1) is not None else match.group(2)
		cleaned = _clean_declarations(value, enforce_allowlist=False).replace('"', "'")
		return f'style="{cleaned}"' if cleaned else ""

	return _STYLE_ATTR_RE.sub(_replace, html)


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------


def sanitize_for_amp_with_css(html: str) -> tuple[str, str]:
	"""Sanitise arbitrary HTML into an AMP-for-Email safe fragment plus its CSS.

	Processing pipeline:

	1. **Unescape** HTML entities so bleach sees real characters.
	2. **Rewrite** ``<img>`` to ``<amp-img>`` (HTTPS only, others dropped).
	3. **Strip** ``<script>`` blocks entirely.
	4. **Extract** ``<style>`` blocks; their rules are cleaned and returned.
	5. **Clean** inline ``style="..."`` attributes (no ``!important``, no
	   position fixed or sticky, no urls).
	6. **Bleach-clean** using the AMP tag, attribute and CSS property
	   allowlists (unknown tags, attributes and properties removed).
	7. **Strip** leading/trailing whitespace.

	Args:
		html: Untrusted HTML string to sanitise.

	Returns:
		A tuple ``(html, css)``: the sanitised fragment, and the cleaned rules
		of its style blocks for the ``<style amp-custom>`` of the AMP shell.

	Example::

		>>> sanitize_for_amp_with_css('<style>p{color:red}</style><p>Hello</p>')
		('<p>Hello</p>', 'p { color: red }')
	"""
	if not html:
		return "", ""

	html = unescape(html)
	html = _img_to_amp_img(html)
	html = _SCRIPT_RE.sub("", html)

	blocks: list[str] = []

	def _collect(match: Match[str]) -> str:
		blocks.append(match.group(1))
		return ""

	html = _STYLE_TAG_RE.sub(_collect, html)
	html = _STYLE_UNCLOSED_RE.sub("", html)
	css = "\n".join(filter(None, (_clean_stylesheet(block) for block in blocks)))

	html = _prepare_inline_styles(html)

	# Strip Frappe workflow action buttons (avoid duplicating our AMP buttons)
	html = _WORKFLOW_BTN_RE.sub("", html)

	html = bleach.clean(
		html,
		tags=AMP_ALLOWED_TAGS,
		attributes=AMP_ALLOWED_ATTRIBUTES,
		css_sanitizer=_CSS_SANITIZER,
		strip=True,
	)

	# Bleach leaves an empty style attribute when no property was allowed
	html = _EMPTY_STYLE_ATTR_RE.sub("", html)

	return html.strip(), css


def sanitize_for_amp(html: str) -> str:
	"""Sanitise arbitrary HTML into an AMP-for-Email safe fragment.

	Same as :func:`sanitize_for_amp_with_css` but returns only the HTML;
	the rules of style blocks are discarded.

	Args:
		html: Untrusted HTML string to sanitise.

	Returns:
		A sanitised HTML string containing only AMP-allowed tags,
		attributes and inline CSS properties.

	Example::

		>>> sanitize_for_amp('<p style="color:red">Hello <script>alert(1)</script></p>')
		'<p style="color: red">Hello </p>'
	"""
	return sanitize_for_amp_with_css(html)[0]
