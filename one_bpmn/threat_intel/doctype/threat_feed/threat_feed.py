# Copyright (c) 2025, a-tech and contributors
# For license information, please see license.txt

# import frappe
from frappe.model.document import Document


class ThreatFeed(Document):
	# begin: auto-generated types
	# This code is auto-generated. Do not modify anything in this block.

	from typing import TYPE_CHECKING

	if TYPE_CHECKING:
		from frappe.types import DF
		from one_bpmn.threat_intel.doctype.threat_feed_keyword.threat_feed_keyword import ThreatFeedKeyword

		collected_date: DF.Datetime
		content: DF.LongText | None
		keywords_found: DF.Table[ThreatFeedKeyword]
		language: DF.Literal["English", "Arabic"]
		published_date: DF.Datetime | None
		raw_data: DF.LongText | None
		source: DF.Link
		title: DF.Text
		url: DF.SmallText | None
	# end: auto-generated types
	pass
