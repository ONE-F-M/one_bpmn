# Copyright (c) 2025, Kartik Sharma and contributors
# For license information, please see license.txt

# import frappe
from frappe.model.document import Document


class ThreatAssessmentReport(Document):
	# begin: auto-generated types
	# This code is auto-generated. Do not modify anything in this block.

	from typing import TYPE_CHECKING

	if TYPE_CHECKING:
		from frappe.types import DF
		from one_bpmn.threat_intel.doctype.threat_assessment_environmental_threat.threat_assessment_environmental_threat import ThreatAssessmentEnvironmentalThreat
		from one_bpmn.threat_intel.doctype.threat_assessment_security_threat.threat_assessment_security_threat import ThreatAssessmentSecurityThreat

		data_period_end: DF.Datetime
		data_period_start: DF.Datetime
		environmental_insights: DF.LongText | None
		environmental_threats: DF.Table[ThreatAssessmentEnvironmentalThreat]
		environmental_threats_count: DF.Int
		error_log: DF.LongText | None
		executive_summary: DF.LongText | None
		generation_status: DF.Literal["Draft", "Generated", "Failed"]
		geographic_analysis: DF.LongText | None
		llm_tokens_used: DF.Int
		report_date: DF.Date
		report_pdf: DF.Attach | None
		report_time: DF.Time | None
		security_insights: DF.LongText | None
		security_threats: DF.Table[ThreatAssessmentSecurityThreat]
		security_threats_count: DF.Int
		total_threats: DF.Int
		trend_analysis: DF.LongText | None
	# end: auto-generated types
	pass