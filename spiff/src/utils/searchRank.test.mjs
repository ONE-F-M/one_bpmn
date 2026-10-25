import { test } from "node:test"
import assert from "node:assert/strict"

import { searchRank } from "./searchRank.js"

const SD5 = ["Software Development v5"]

test("acronym with and without spaces", () => {
	assert.equal(searchRank("SD5", SD5), 2)
	assert.equal(searchRank("S D 5", SD5), 2)
	assert.equal(searchRank("S D", ["Software Development"]), 1)
})

test("substring ranks best, token prefixes next", () => {
	assert.equal(searchRank("software dev", SD5), 0)
	assert.equal(searchRank("dev soft", SD5), 1)
})

test("spaced initials across words", () => {
	assert.equal(searchRank("flr L A", ["First Line Response Leave Approval"]), 2)
})

test("no match and single characters", () => {
	assert.equal(searchRank("zzz", SD5), null)
	assert.equal(searchRank("SD6", SD5), null)
	assert.equal(searchRank("q", SD5), null)
})
