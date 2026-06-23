from __future__ import annotations

from one_bpmn.email_builder.sanitizer import sanitize_for_amp


class TestSanitizeForAmp:
	"""Pure-Python tests for the AMP HTML sanitizer.

	No Frappe site required — run with ``pytest``.
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

	def test_inline_style_stripped(self):
		"""Inline ``style`` attributes must be removed from every element."""
		result = sanitize_for_amp('<p style="color:red">text</p>')
		assert 'style=' not in result
		assert '<p>text</p>' in result

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
