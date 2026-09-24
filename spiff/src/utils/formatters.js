// Pure en-US/USD number formatters; null, undefined and NaN read as 0.

const CURRENCY_2 = new Intl.NumberFormat("en-US", {
	style: "currency",
	currency: "USD",
	minimumFractionDigits: 2,
	maximumFractionDigits: 2,
})

const CURRENCY_4 = new Intl.NumberFormat("en-US", {
	style: "currency",
	currency: "USD",
	minimumFractionDigits: 4,
	maximumFractionDigits: 4,
})

const CURRENCY_6 = new Intl.NumberFormat("en-US", {
	style: "currency",
	currency: "USD",
	minimumFractionDigits: 6,
	maximumFractionDigits: 6,
})

const INT_FMT = new Intl.NumberFormat("en-US")

const COMPACT_FMT = new Intl.NumberFormat("en-US", {
	notation: "compact",
	maximumFractionDigits: 1,
})

function toNum(v) {
	const n = Number(v)
	return Number.isFinite(n) ? n : 0
}

export function fmtCurrency(v) {
	v = toNum(v)
	if (v === 0) return "$0.00"
	if (Math.abs(v) < 0.0001) return v < 0 ? "> -$0.0001" : "< $0.0001"
	if (Math.abs(Math.round(v * 10000)) < 10000) return CURRENCY_4.format(v)
	return CURRENCY_2.format(v)
}

export function fmtCurrencyExact(v) {
	v = toNum(v)
	return CURRENCY_6.format(v)
}

export function fmtCompact(v) {
	const r = Math.round(toNum(v))
	if (Math.abs(r) < 1000) return String(r)
	return COMPACT_FMT.format(r)
}

// Rounded, with thousands separators.
export function fmtInt(v) {
	return INT_FMT.format(Math.round(toNum(v)))
}

// Input is already 0-100.
export function fmtPct(v, decimals = 1) {
	v = toNum(v)
	return `${v.toFixed(decimals)}%`
}

export function fmtDelta(v, kind) {
	if (v === null || v === undefined) return "new"
	const tenths = Math.round(toNum(v) * 10)
	const sign = tenths < 0 ? "-" : "+"
	const abs = (Math.abs(tenths) / 10).toFixed(1)
	if (kind === "pct") return `${sign}${abs}%`
	if (kind === "pt") return `${sign}${abs} pt`
	return `${sign}${abs}`
}

export function fmtDuration(ms) {
	ms = toNum(ms)
	if (Math.round(ms) < 1000) return `${Math.round(ms)}ms`
	if (Math.round(ms / 100) < 600) return `${(Math.round(ms / 100) / 10).toFixed(1)}s`
	const totalSeconds = Math.round(ms / 1000)
	const minutes = Math.floor(totalSeconds / 60)
	const seconds = totalSeconds % 60
	return `${minutes}:${String(seconds).padStart(2, "0")}`
}
