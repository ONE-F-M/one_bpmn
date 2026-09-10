import frappe

def execute():
	"""Seed database with known threat sources from provided list"""
	
	sources = [
		# Forums
		{"source_name": "Expat.com Kuwait", "source_type": "Forum", 
		 "source_url": "https://www.expat.com/en/guide/middle-east/kuwait/", 
		 "language": "English", "status": "Approved"},
		{"source_name": "ExpatExchange Kuwait", "source_type": "Forum", 
		 "source_url": "https://www.expatexchange.com/locations/67/Kuwait", 
		 "language": "English", "status": "Approved"},
		{"source_name": "ExpatWoman Kuwait", "source_type": "Forum", 
		 "source_url": "https://www.expatwoman.com/search?search=kuwait", 
		 "language": "English", "status": "Approved"},
		
		# News & Blogs
		{"source_name": "Indians in Kuwait", "source_type": "News Website", 
		 "source_url": "https://www.indiansinkuwait.com/latest-news/", 
		 "language": "English", "status": "Approved"},
		{"source_name": "Ammar Taqi Blog", "source_type": "Blog", 
		 "source_url": "https://ammartaqi.com/en/blog/", 
		 "language": "English", "status": "Approved"},
		
		# Social
		{"source_name": "SkyscraperCity Kuwait", "source_type": "Forum", 
		 "source_url": "https://www.skyscrapercity.com/whats-new/posts/13926611/", 
		 "language": "English", "status": "Approved"},
		{"source_name": "TripAdvisor Kuwait", "source_type": "Forum", 
		 "source_url": "https://www.tripadvisor.com/Tourism-g294002-Kuwait-Vacations.html", 
		 "language": "English", "status": "Approved"},
		
		# Twitter
		{"source_name": "KUNA English", "source_type": "Twitter", 
		 "source_url": "https://twitter.com/kuna_en", 
		 "language": "English", "status": "Approved",
		 "discovery_context": "Official Kuwait News Agency"},
		{"source_name": "Kuwait News", "source_type": "Twitter", 
		 "source_url": "https://twitter.com/KuwaitNews", 
		 "language": "English", "status": "Approved"},
		{"source_name": "KW Daily News", "source_type": "Twitter", 
		 "source_url": "https://twitter.com/KW_Daily_News", 
		 "language": "English", "status": "Approved"},
		
		# Reddit
		{"source_name": "r/Kuwait", "source_type": "Reddit", 
		 "source_url": "https://www.reddit.com/r/Kuwait/", 
		 "language": "English", "status": "Approved"},
		
		# Quora
		{"source_name": "Kuwait News Today Space", "source_type": "Quora", 
		 "source_url": "https://kuwaitnewstodayspace.quora.com/", 
		 "language": "English", "status": "Approved"},
		{"source_name": "Kuwait News Quora", "source_type": "Quora", 
		 "source_url": "https://kuwaitnews.quora.com/", 
		 "language": "English", "status": "Approved"},
		
		# Medium
		{"source_name": "Medium - Kuwait Tag", "source_type": "Medium", 
		 "source_url": "https://medium.com/tag/kuwait", 
		 "language": "English", "status": "Approved"},
		{"source_name": "Arabian Post on Medium", "source_type": "Medium", 
		 "source_url": "https://medium.com/@arabianpost", 
		 "language": "English", "status": "Approved"},
		{"source_name": "Mariam Almotawa on Medium", "source_type": "Medium", 
		 "source_url": "https://medium.com/@mariam.almotawa", 
		 "language": "English", "status": "Approved"},
		
		# Telegram
		{"source_name": "The Times Kuwait Telegram", "source_type": "Telegram", 
		 "source_url": "https://t.me/s/thetimeskuwait", 
		 "language": "English", "status": "Approved"},
	]
	
	created_count = 0
	skipped_count = 0
	
	for source_data in sources:
		# Check duplicate
		exists = frappe.db.exists("Threat Source", {"source_url": source_data["source_url"]})
		
		if exists:
			skipped_count += 1
			continue
		
		try:
			doc = frappe.get_doc({
				"doctype": "Threat Source",
				**source_data,
				"discovered_date": frappe.utils.now()
			})
			doc.insert(ignore_permissions=True)
			created_count += 1
		except Exception as e:
			frappe.log_error(
				title=f"Failed to create Threat Source: {source_data.get('source_name')}",
				message=f"""
					An error occurred while inserting a Threat Source.

					Source details:
					- Name: {source_data.get('source_name')}
					- URL: {source_data.get('source_url')}
					- Type: {source_data.get('source_type')}
					- Language: {source_data.get('language')}

					Traceback:
					{frappe.get_traceback()}
					"""
			)

	frappe.db.commit()
	
	return {
		"created": created_count,
		"skipped": skipped_count,
		"total": len(sources)
	}
