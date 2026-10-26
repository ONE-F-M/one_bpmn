import { test } from "node:test"
import assert from "node:assert/strict"

import { fieldOf, fieldsTabCount, parseFieldList, serializeFieldList } from "./notifyFields.js"

test("fieldOf: a plain fieldname, or the English half of an Arabic pair", () => {
	assert.equal(fieldOf("leave_type"), "leave_type")
	assert.equal(fieldOf(["employee_name", "employee.employee_name_in_arabic"]), "employee_name")
})

test("parseFieldList and serializeFieldList keep the picked order and Arabic pairs", () => {
	const list = ["to_date", ["employee_name", "employee.employee_name_in_arabic"], "from_date"]
	assert.deepEqual(parseFieldList(serializeFieldList(list)), list)
	assert.deepEqual(parseFieldList(""), [])
	assert.equal(serializeFieldList([]), "")
})

test("fieldsTabCount: facts and details, facts only for Conversation", () => {
	assert.equal(fieldsTabCount(["a", "b"], ["c"], "card"), 3)
	assert.equal(fieldsTabCount(["a", "b"], ["c"], "chat"), 2)
})
