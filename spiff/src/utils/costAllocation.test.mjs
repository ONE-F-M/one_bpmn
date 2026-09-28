// node --test spiff/src/utils/costAllocation.test.mjs

import { test } from "node:test"
import assert from "node:assert/strict"

import {
	OTHER_COLOR, OTHER_KEY, assignColors, barWidth, bucketLabels, bucketTotals, chipOf, currentBucket, foldTail, monthColumns,
	nameOf, pctChange, pricingLink, rankSlices, rowsOf, seriesCap, subtitleOf,
} from "./costAllocation.js"

const node = (key, cost, children = []) => ({ key, label: key, cost, share: cost, by_bucket: { w1: cost }, children })

test("the tail folds into one Other entry that keeps its money", () => {
	const folded = foldTail([node("a", 5), node("b", 3), node("c", 2)], 1)
	assert.deepEqual(folded.map((n) => n.key), ["a", OTHER_KEY])
	assert.equal(folded[1].cost, 5)
	assert.deepEqual(folded[1].by_bucket, { w1: 5 })
})

test("chat users chart five before Other; everything else six", () => {
	assert.equal(seriesCap("chat_user", "user"), 5)
	assert.equal(seriesCap("chat_user", "agent"), 6)
	assert.equal(seriesCap("process_owner", "owner"), 6)
})

test("the agents list folds without buckets", () => {
	const agents = [1, 2, 3, 4, 5, 6, 7, 8].map((i) => ({ key: `a${i}`, label: `a${i}`, cost: 10 - i }))
	const folded = foldTail(agents, 6)
	assert.equal(folded.length, 7)
	assert.equal(folded[6].cost, 3 + 2)
})

test("a key keeps its colour when another key leaves", () => {
	const memo = new Map()
	const first = assignColors(["a", "b", "c"], memo)
	const second = assignColors(["a", "c"], memo)
	assert.equal(second.c, first.c)
	assert.equal(second[OTHER_KEY], OTHER_COLOR)
})

test("a newcomer takes a free slot instead of a colour still on screen", () => {
	const memo = new Map()
	assignColors(["a", "b"], memo)
	const next = assignColors(["a", "z"], memo)
	assert.notEqual(next.z, next.a)
})

test("children show only under an open parent", () => {
	const tree = [node("ops", 10, [node("rahul", 6), node("meera", 4)]), node("fin", 5)]
	assert.deepEqual(rowsOf(tree, new Set()).map((r) => r.path), ["/ops", "/fin"])
	const open = rowsOf(tree, new Set(["/ops"]))
	assert.deepEqual(open.map((r) => r.path), ["/ops", "/ops/rahul", "/ops/meera", "/fin"])
	assert.equal(open[1].rootKey, "ops")
	assert.equal(open[0].open, true)
})

test("a percent change against nothing is null", () => {
	assert.equal(pctChange(150, 100), 50)
	assert.equal(pctChange(50, 100), -50)
	assert.equal(pctChange(5, 0), null)
})

test("the pricing link opens the AI Model list filtered to the unpriced models", () => {
	assert.equal(pricingLink(["a", "b"]), `/app/ai-model?name=${encodeURIComponent('["in",["a","b"]]')}`)
})

test("each bucket totals every series, and the bucket holding today is the one still filling", () => {
	const series = [{ by_bucket: { "2026-09-01": 2, "2026-09-08": 1 } }, { by_bucket: { "2026-09-01": 3, "2026-09-08": 0 } }]
	assert.deepEqual(bucketTotals(series, ["2026-09-01", "2026-09-08"]), { "2026-09-01": 5, "2026-09-08": 1 })
	const buckets = ["2026-09-01", "2026-09-08", "2026-09-15"]
	assert.equal(currentBucket(buckets, "2026-09-21", "2026-09-10"), "2026-09-08")
	assert.equal(currentBucket(buckets, "2026-09-21", "2026-10-02"), null)
})

test("donut slices rank by value with whole percentages", () => {
	const ranked = rankSlices([{ key: "b", value: 1 }, { key: "a", value: 3 }])
	assert.deepEqual(ranked.map((s) => [s.key, s.pct]), [["a", 75], ["b", 25]])
})

test("the largest top-level share fills the bar and the rest scale to it", () => {
	const tree = [{ share: 60 }, { share: 30 }]
	assert.equal(barWidth(tree[0], tree), 100)
	assert.equal(barWidth(tree[1], tree), 50)
})

test("month columns appear only for two to six months", () => {
	assert.deepEqual(monthColumns(["2026-09"]), [])
	assert.deepEqual(monthColumns(["2026-07", "2026-08", "2026-09"]), ["2026-07", "2026-08", "2026-09"])
	assert.deepEqual(monthColumns(["1", "2", "3", "4", "5", "6", "7"]), [])
})

test("a folded tail reads as its user count and a chat department counts users and agents", () => {
	assert.equal(nameOf({ kind: "more", count: 4, label: "4 more" }), "4 more users")
	assert.equal(nameOf({ kind: "owner", name: "Owner A", label: "owner-a@example.com" }), "Owner A")
	assert.equal(subtitleOf({ kind: "department", users: 9, agents: 3 }, "chat_user"), "9 users · 3 agents")
	assert.equal(chipOf({ depth: 1, node: { kind: "more", count: 4 } }, "chat_user"), "")
})

test("an agent row carries no department; a top-level process does", () => {
	assert.equal(chipOf({ depth: 0, node: { kind: "agent", department: "Ops" } }, "chat_user"), "")
	assert.equal(chipOf({ depth: 0, node: { kind: "process", department: "Ops" } }, "process_owner"), "Ops")
	assert.equal(chipOf({ depth: 1, node: { kind: "user", department: "Ops" } }, "chat_user"), "")
})

test("bucket labels read as date ranges, the last one ending on the range end", () => {
	const buckets = ["2026-09-01", "2026-09-08", "2026-09-15"]
	assert.deepEqual(bucketLabels(buckets, "2026-09-21", "week"), ["Sep 1 - 7", "Sep 8 - 14", "Sep 15 - 21"])
	assert.deepEqual(bucketLabels(["2026-08-01", "2026-09-01"], "2026-09-21", "month"), ["Aug 2026", "Sep 2026"])
})
