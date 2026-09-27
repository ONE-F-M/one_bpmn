import { test } from "node:test"
import assert from "node:assert/strict"

import {
	fmtCurrency,
	fmtCurrencyExact,
	fmtCompact,
	fmtInt,
	fmtPct,
	fmtDateRange,
	fmtDelta,
	fmtDuration,
} from "./formatters.js"

test("fmtCurrency: zero", () => {
	assert.equal(fmtCurrency(0), "$0.00")
})

test("fmtCurrency: null/undefined/NaN treated as 0", () => {
	assert.equal(fmtCurrency(null), "$0.00")
	assert.equal(fmtCurrency(undefined), "$0.00")
	assert.equal(fmtCurrency(NaN), "$0.00")
})

test("fmtCurrency: below 0.0001", () => {
	assert.equal(fmtCurrency(0.00004), "< $0.0001")
})

test("fmtCurrency: below 1, 4 decimals", () => {
	assert.equal(fmtCurrency(0.0328), "$0.0328")
})

test("fmtCurrency: 1 and above, 2 decimals", () => {
	assert.equal(fmtCurrency(42.18), "$42.18")
})

test("fmtCurrency: 1 and above, thousands separator, 2 decimals", () => {
	assert.equal(fmtCurrency(1234.5), "$1,234.50")
})

test("fmtCurrencyExact: 6 decimals", () => {
	assert.equal(fmtCurrencyExact(0.00004), "$0.000040")
})

test("fmtCurrencyExact: null treated as 0", () => {
	assert.equal(fmtCurrencyExact(null), "$0.000000")
})

test("fmtCompact: below 1000 is a whole number", () => {
	assert.equal(fmtCompact(412), "412")
})

test("fmtCompact: millions", () => {
	assert.equal(fmtCompact(6412300), "6.4M")
})

test("fmtCompact: null treated as 0", () => {
	assert.equal(fmtCompact(null), "0")
})

test("fmtInt: thousands separators", () => {
	assert.equal(fmtInt(6412300), "6,412,300")
})

test("fmtInt: null/undefined/NaN treated as 0", () => {
	assert.equal(fmtInt(null), "0")
	assert.equal(fmtInt(undefined), "0")
	assert.equal(fmtInt(NaN), "0")
})

test("fmtPct: default one decimal", () => {
	assert.equal(fmtPct(97.345), "97.3%")
})

test("fmtPct: null treated as 0", () => {
	assert.equal(fmtPct(null), "0.0%")
})

test("fmtDelta: pct rounds to a whole percent", () => {
	assert.equal(fmtDelta(18.3, "pct"), "+18%")
})

test("fmtDelta: pt negative uses a hyphen", () => {
	assert.equal(fmtDelta(-1.5, "pt"), "-1.5 pt")
})

test("fmtDelta: pt keeps one decimal", () => {
	assert.equal(fmtDelta(0.6, "pt"), "+0.6 pt")
})

test("fmtDelta: null means no prior period", () => {
	assert.equal(fmtDelta(null, "pct"), "new")
})

test("fmtDuration: under a second", () => {
	assert.equal(fmtDuration(850), "850ms")
})

test("fmtDuration: under a minute", () => {
	assert.equal(fmtDuration(12340), "12.3s")
})

test("fmtDuration: minutes and seconds", () => {
	assert.equal(fmtDuration(125000), "2:05")
})

test("fmtDuration: null is 0ms", () => {
	assert.equal(fmtDuration(null), "0ms")
})

test("fmtCurrency: tiny negative keeps its sign", () => {
	assert.equal(fmtCurrency(-0.00005), "> -$0.0001")
})

test("fmtCurrency: rounds up to a dollar with 2 decimals", () => {
	assert.equal(fmtCurrency(0.99996), "$1.00")
})

test("fmtDelta: sign comes from the rounded value", () => {
	assert.equal(fmtDelta(-0.4, "pct"), "+0%")
})

test("fmtDuration: rounds up to a minute", () => {
	assert.equal(fmtDuration(59960), "1:00")
})

test("fmtDuration: rounds up to a second", () => {
	assert.equal(fmtDuration(999.6), "1.0s")
})

test("fmtCompact: rounds up to a thousand", () => {
	assert.equal(fmtCompact(999.6), "1K")
})

test("fmtDelta: a head count has no decimals or percent sign", () => {
	assert.equal(fmtDelta(4, "count"), "+4")
	assert.equal(fmtDelta(-2, "count"), "-2")
})

test("fmtDateRange: the month repeats only when it changes", () => {
	assert.equal(fmtDateRange("2026-09-01", "2026-09-21"), "Sep 1 - 21")
	assert.equal(fmtDateRange("2026-09-28", "2026-10-04"), "Sep 28 - Oct 4")
})
