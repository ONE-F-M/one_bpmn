// node --test spiff/src/utils/costAllocation.test.mjs

import { test } from "node:test"
import assert from "node:assert/strict"

import { OTHER_COLOR, OTHER_KEY, assignColors, foldTail, pctChange, rowsOf } from "./costAllocation.js"

const node = (key, cost, children = []) => ({ key, label: key, cost, share: cost, by_bucket: { w1: cost }, children })

test("the tail folds into one Other entry that keeps its money", () => {
	const folded = foldTail([node("a", 5), node("b", 3), node("c", 2)], 1)
	assert.deepEqual(folded.map((n) => n.key), ["a", OTHER_KEY])
	assert.equal(folded[1].cost, 5)
	assert.deepEqual(folded[1].by_bucket, { w1: 5 })
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
