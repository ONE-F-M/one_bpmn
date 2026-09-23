// Shared number formatting for the Insights UI. Every formatter here is a
// pure function: no imports, no side effects, en-US locale and USD currency
// fixed. null/undefined/NaN are all treated as 0 unless a rule says
// otherwise (fmtDelta's "new" state is the one exception).

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

// $0 -> $0.00; below a cent-of-a-cent -> "< $0.0001"; below $1 -> 4 decimals
// so small AI costs stay visible; $1 and above -> 2 decimals with commas.
export function fmtCurrency(v) {
	v = toNum(v)
	if (v === 0) return "$0.00"
	if (Math.abs(v) < 0.0001) return "< $0.0001"
	if (Math.abs(v) < 1) return CURRENCY_4.format(v)
	return CURRENCY_2.format(v)
}

// Always 6 decimals, for title/tooltip attributes where the exact figure
// (not the rounded display value) matters.
export function fmtCurrencyExact(v) {
	v = toNum(v)
	return CURRENCY_6.format(v)
}

// Below 1000, a plain whole number; at or above, K/M/B via Intl's compact
// notation, at most one decimal.
export function fmtCompact(v) {
	v = toNum(v)
	if (Math.abs(v) < 1000) return String(Math.round(v))
	return COMPACT_FMT.format(v)
}

// Rounded, with thousands separators.
export function fmtInt(v) {
	return INT_FMT.format(Math.round(toNum(v)))
}

// Input is already 0-100.
export function fmtPct(v, decimals = 1) {
	v = toNum(v)
	return v.toFixed(decimals) + "%"
}

// Signed change versus a prior period. `kind` is "pct" (+12.3%) or
// "pt" (-1.5 pt, a percentage-point move). No prior period -> "new".
export function fmtDelta(v, kind) {
	if (v === null || v === undefined) return "new"
	v = toNum(v)
	const sign = v < 0 ? "-" : "+"
	const abs = Math.abs(v)
	if (kind === "pct") return sign + abs.toFixed(1) + "%"
	if (kind === "pt") return sign + abs.toFixed(1) + " pt"
	return sign + abs.toFixed(1)
}

// <1s -> "Nms"; <1min -> "N.Ns"; else "m:ss", minutes counting past 60.
export function fmtDuration(ms) {
	ms = toNum(ms)
	if (ms < 1000) return Math.round(ms) + "ms"
	if (ms < 60000) return (ms / 1000).toFixed(1) + "s"
	const totalSeconds = Math.round(ms / 1000)
	const minutes = Math.floor(totalSeconds / 60)
	const seconds = totalSeconds % 60
	return minutes + ":" + String(seconds).padStart(2, "0")
}
