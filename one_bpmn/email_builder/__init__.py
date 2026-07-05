"""AMP email builder for One BPMN.

Public API:

- :func:`sanitize_for_amp` — strip non-AMP HTML from a body fragment.
- :func:`render_amp` — produce a complete AMP4Email document.
- :func:`render_html_fallback` — produce a branded HTML email.
"""

from one_bpmn.email_builder.renderer import render_amp, render_html_fallback
from one_bpmn.email_builder.sanitizer import sanitize_for_amp

__all__ = ["render_amp", "render_html_fallback", "sanitize_for_amp"]
