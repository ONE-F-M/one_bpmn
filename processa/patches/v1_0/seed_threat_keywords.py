import frappe

def execute():
	"""Seed initial threat keywords in English and Arabic"""
	
	keywords = [
		{"keyword": "crime", "language": "English"},
		{"keyword": "robbery", "language": "English"},
		{"keyword": "security", "language": "English"},
		{"keyword": "threat", "language": "English"},
		{"keyword": "incident", "language": "English"},
		{"keyword": "accident", "language": "English"},
		{"keyword": "fire", "language": "English"},
		{"keyword": "emergency", "language": "English"},
		{"keyword": "جريمة", "language": "Arabic"},
		{"keyword": "سرقة", "language": "Arabic"},
		{"keyword": "أمن", "language": "Arabic"},
		{"keyword": "تهديد", "language": "Arabic"},
		{"keyword": "حادث", "language": "Arabic"},
	]
	
	created_count = 0
	
	for kw in keywords:
		if not frappe.db.exists("Threat Keyword", {"keyword": kw["keyword"]}):
			doc = frappe.get_doc({
				"doctype": "Threat Keyword",
				**kw,
				"source_type": "Manual",
				"is_active": 1,
				"date_added": frappe.utils.today()
			})
			doc.insert(ignore_permissions=True)
			created_count += 1
	
	frappe.db.commit()
	return {"created": created_count}