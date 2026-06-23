# Copyright (c) 2026, one-fm and contributors
# For license information, please see license.txt

from frappe.model.document import Document


class AIProvider(Document):
    # begin: auto-generated types
    # This code is auto-generated. Do not modify anything in this block.

    from typing import TYPE_CHECKING

    if TYPE_CHECKING:
        from frappe.types import DF

        api_endpoint: DF.Data | None
        api_key: DF.Password
        default_model: DF.Data | None
        enabled: DF.Check
        provider_name: DF.Data
        provider_type: DF.Literal["OpenAI", "Anthropic", "Google", "Bedrock", "OpenAI-compatible", "Antigravity"]
    # end: auto-generated types
    pass
