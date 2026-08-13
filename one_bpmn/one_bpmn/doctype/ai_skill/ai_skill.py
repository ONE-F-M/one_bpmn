# Copyright (c) 2026, kartiksharma9319@gmail.com and contributors
# For license information, please see license.txt

import frappe
from frappe.model.document import Document
from frappe import _

class AISkill(Document):
    def validate(self):
        self.validate_description()
        self.compute_token_estimate()
        self.validate_token_ceiling()

    def validate_description(self):
        if not self.description:
            return

        # Enforce length limit (using standard 255 small text limit as requested)
        max_length = 255
        if len(self.description) > max_length:
            frappe.throw(_("Description is too long. Maximum allowed length is {0} characters.").format(max_length))

        # Enforce trigger phrasing
        valid_prefixes = ["Use this to ", "Use when "]
        has_valid_prefix = any(self.description.startswith(prefix) for prefix in valid_prefixes)
        
        if not has_valid_prefix:
            frappe.throw(_("Description must start with a valid trigger phrase (e.g., 'Use this to ' or 'Use when ')."))

    def compute_token_estimate(self):
        if not self.body:
            self.token_estimate = 0
            return
        
        # Basic heuristic: 1 token ~= 0.75 words -> tokens = word_count / 0.75
        word_count = len(self.body.split())
        self.token_estimate = int(word_count / 0.75)

    def validate_token_ceiling(self):
        # Enforce token ceiling limit
        token_ceiling = 8000
        if self.token_estimate and self.token_estimate > token_ceiling:
            frappe.throw(_("Markdown body exceeds the token ceiling of {0} tokens. Current estimate: {1} tokens.").format(token_ceiling, self.token_estimate))
