const words = (text) => (text || "").toLowerCase().match(/[a-z0-9]+/g) || []

const isSubsequence = (needle, haystack) => {
	let i = 0
	for (const c of haystack) if (c === needle[i]) i++
	return i === needle.length
}

// Rank of a search match, lower is better, null for no match: 0 substring, 1 token prefixes, 2 initials.
export function searchRank(query, values) {
	const q = (query || "").trim().toLowerCase()
	const text = values.filter(Boolean).join(" ").toLowerCase()
	if (text.includes(q)) return 0

	const compact = q.replace(/\s+/g, "")
	if (compact.length < 2) return null

	const unused = words(text)
	const prefixed = words(q).every((token) => {
		const at = unused.findIndex((w) => w.startsWith(token))
		if (at < 0) return false
		unused.splice(at, 1)
		return true
	})
	if (prefixed) return 1

	const hasInitials = values.some((value) =>
		isSubsequence(
			compact,
			words(value)
				.map((w) => w[0] + w.slice(1).replace(/\D/g, ""))
				.join(""),
		),
	)
	return hasInitials ? 2 : null
}
