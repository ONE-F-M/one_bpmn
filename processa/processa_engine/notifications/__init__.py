"""Task emails: compose, render, sanitise, sign the action tokens, and the logic behind the email callbacks."""

from processa.processa_engine.notifications.renderer import render_amp, render_html_fallback
from processa.processa_engine.notifications.sanitizer import sanitize_for_amp

__all__ = ["render_amp", "render_html_fallback", "sanitize_for_amp"]
