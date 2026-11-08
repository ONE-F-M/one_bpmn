from __future__ import annotations

from frappe.tests.utils import FrappeTestCase

from one_bpmn.email_builder.sanitizer import sanitize_for_amp, sanitize_for_amp_with_css


class TestSanitizeForAmp(FrappeTestCase):
	"""Tests for the AMP HTML sanitizer.

	Run with: bench --site SITE run-tests --app one_bpmn --module one_bpmn.tests.test_sanitizer
	"""

	def test_allowed_tags_survive(self):
		"""<p>, <ul>/<li>, <a href>, <table>/<tr>/<td>, <blockquote> all pass through."""
		html = (
			'<p>Hello</p><ul><li>Item</li></ul>'
			'<a href="https://x.com">link</a>'
			'<blockquote>quote</blockquote>'
		)
		result = sanitize_for_amp(html)
		assert '<p>' in result
		assert '<ul>' in result
		assert '<li>' in result
		assert '<a ' in result
		assert '<blockquote>' in result

	def test_script_stripped(self):
		"""<script> tags and their content must be completely removed."""
		result = sanitize_for_amp('<p>Hi</p><script>alert(1)</script>')
		assert '<script' not in result
		assert 'alert' not in result
		assert '<p>Hi</p>' in result

	def test_style_tag_stripped(self):
		"""<style> tags and their content must be completely removed."""
		result = sanitize_for_amp('<style>.x{color:red}</style><p>text</p>')
		assert '<style' not in result
		assert '<p>text</p>' in result

	def test_inline_style_keeps_only_amp_properties(self):
		"""Allowed inline properties stay; disallowed ones, !important and position fixed go."""
		result = sanitize_for_amp(
			'<p style="color:red; cursor:pointer; position:fixed; font-weight:bold !important">text</p>'
		)
		assert 'color: red' in result
		assert 'font-weight: bold' in result
		assert 'cursor' not in result
		assert 'fixed' not in result
		assert 'important' not in result

	def test_inline_style_with_nothing_allowed_is_removed(self):
		"""An element whose style holds no allowed property loses the attribute."""
		assert sanitize_for_amp('<p style="cursor:pointer">text</p>') == '<p>text</p>'

	def test_inline_style_url_removed(self):
		"""A value that loads a resource is removed."""
		result = sanitize_for_amp('<p style="background:url(https://x.com/a.png); color:blue">t</p>')
		assert 'url(' not in result
		assert 'color: blue' in result

	def test_style_block_rules_returned_as_css(self):
		"""Style block rules come back cleaned; @import, @font-face, url() and !important are removed."""
		html, css = sanitize_for_amp_with_css(
			'<style>'
			'@import url("https://x.com/a.css");'
			'@font-face { font-family: X; src: url(x.woff); }'
			'.title { color: #123456 !important; background: url(a.png); cursor: pointer }'
			'.box { position: sticky; padding: 8px }'
			'@media (max-width: 600px) { .title { font-size: 14px } }'
			'.-amp-hack { color: red }'
			'</style><p class="title">Hi</p>'
		)
		assert html == '<p class="title">Hi</p>'
		assert '.title { color: #123456 }' in css
		assert '.box { padding: 8px }' in css
		assert '@media (max-width: 600px)' in css
		assert 'font-size: 14px' in css
		for removed in ('@import', '@font-face', 'url(', 'important', 'cursor', 'sticky', '-amp-'):
			assert removed not in css, removed

	def test_style_block_cannot_close_the_style_tag(self):
		"""A rule whose value tries to end the style tag is dropped."""
		_html, css = sanitize_for_amp_with_css('<style>p { color: "</style><script>" }</style><p>x</p>')
		assert '<' not in css

	def test_img_non_numeric_size_falls_back_to_default(self):
		"""A percentage width is not valid for amp-img, so the default is used."""
		result = sanitize_for_amp('<img src="https://example.com/a.png" width="50%" height="40">')
		assert 'width="600"' in result
		assert 'height="40"' in result
		assert 'layout="responsive"' in result

	def test_img_https_to_amp_img(self):
		"""HTTPS <img> must be converted to <amp-img> with responsive layout and default dimensions."""
		result = sanitize_for_amp('<img src="https://example.com/a.png">')
		assert '<amp-img' in result
		assert 'src="https://example.com/a.png"' in result
		assert 'layout="responsive"' in result
		assert 'width="600"' in result
		assert 'height="400"' in result
		assert '<img' not in result  # original img tag gone

	def test_img_http_dropped(self):
		"""HTTP (non-secure) <img> must be dropped entirely — no <img> or <amp-img>."""
		result = sanitize_for_amp('<img src="http://example.com/a.png">')
		assert '<img' not in result
		assert '<amp-img' not in result

	def test_img_preserves_dimensions(self):
		"""Explicit width/height/alt on <img> must carry over to the <amp-img>."""
		result = sanitize_for_amp(
			'<img src="https://example.com/a.png" width="300" height="200" alt="photo">'
		)
		assert 'width="300"' in result
		assert 'height="200"' in result
		assert 'alt="photo"' in result
		assert 'layout="intrinsic"' in result

	def test_disallowed_tags_stripped(self):
		"""<iframe>, <object>, <embed>, <form> must be stripped; inner text preserved where possible."""
		result = sanitize_for_amp(
			'<iframe src="x">inner</iframe>'
			'<object>obj</object>'
			'<embed src="y">'
			'<form action="z">f</form>'
		)
		assert '<iframe' not in result
		assert '<object' not in result
		assert '<embed' not in result
		assert '<form' not in result
		# Content should be preserved where possible
		assert 'inner' in result

	def test_empty_input(self):
		"""Empty string and ``None`` must both return an empty string."""
		assert sanitize_for_amp('') == ''
		assert sanitize_for_amp(None) == ''  # type: ignore[arg-type]

	def test_nested_xss_payloads(self):
		"""Multiple XSS attack vectors combined must all be neutralised."""
		html = (
			'<div><script>alert("xss")</script>'
			'<p onmouseover="evil()">text</p>'
			'<style>body{display:none}</style>'
			'<img src="javascript:alert(1)">'
			'</div>'
		)
		result = sanitize_for_amp(html)
		assert '<script' not in result
		assert 'alert' not in result
		assert '<style' not in result
		assert 'onmouseover' not in result
		assert 'javascript:' not in result
		assert '<p>' in result or '<p ' in result
		assert 'text' in result
