const numFormatter = new Intl.NumberFormat("en-US")

export function fmtNum(v) {
	return numFormatter.format(Math.round(v || 0))
}

export function fmtMs(ms) {
	ms = ms || 0
	if (ms >= 3600000) return (ms / 3600000).toFixed(1) + "h"
	if (ms >= 60000) return (ms / 60000).toFixed(1) + "m"
	if (ms >= 1000) return (ms / 1000).toFixed(ms >= 10000 ? 0 : 1) + "s"
	return fmtNum(ms) + "ms"
}

export function fmtCost(v) {
	v = Number(v || 0)
	return "$" + v.toFixed(v >= 1 ? 2 : 4)
}

export function prettyJson(v) {
	if (v == null || v === "") return ""
	if (typeof v === "object") return JSON.stringify(v, null, 2)
	try {
		return JSON.stringify(JSON.parse(v), null, 2)
	} catch {
		return String(v)
	}
}
