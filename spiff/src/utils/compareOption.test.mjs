import { test } from "node:test"
import assert from "node:assert/strict"

import { compareOption } from "./compareOption.js"

test("compareOption: a null model never throws and matches no option", () => {
	assert.equal(compareOption(null, { value: "subject" }), false)
	assert.equal(compareOption({ value: "subject" }, null), false)
})

test("compareOption: options match by value", () => {
	assert.equal(compareOption({ value: "subject", label: "Subject" }, { value: "subject" }), true)
	assert.equal(compareOption({ value: "subject" }, { value: "status" }), false)
})
