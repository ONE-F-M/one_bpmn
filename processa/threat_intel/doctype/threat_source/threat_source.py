# Copyright (c) 2025, Kartik Sharma and contributors
# For license information, please see license.txt

# import frappe
from frappe.model.document import Document


class ThreatSource(Document):
	# begin: auto-generated types
	# This code is auto-generated. Do not modify anything in this block.

	from typing import TYPE_CHECKING

	if TYPE_CHECKING:
		from frappe.types import DF
		from processa.threat_intel.doctype.threat_source_keyword.threat_source_keyword import ThreatSourceKeyword

		discovered_date: DF.Datetime
		discovery_context: DF.LongText | None
		keywords_matched: DF.Table[ThreatSourceKeyword]
		language: DF.Literal["English", "Arabic", "Both"]
		last_scraped: DF.Datetime | None
		rejection_reason: DF.SmallText | None
		reviewed_by: DF.Link | None
		reviewed_date: DF.Datetime | None
		scrape_frequency: DF.Int
		source_name: DF.Data
		source_type: DF.Literal["News Website", "Forum", "Blog", "Reddit", "Quora", "Medium", "Telegram", "Twitter", "xAI Agentic Search", "Other"]
		source_url: DF.Data
		status: DF.Literal["Pending", "Approved", "Rejected"]
	# end: auto-generated types
	pass