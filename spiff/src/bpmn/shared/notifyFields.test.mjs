import { test } from "node:test"
import assert from "node:assert/strict"

import {
	arabicCandidates,
	fieldOf,
	fieldOptionGroups,
	fieldsTabCount,
	flattenEmailFields,
	parseFieldList,
	replaceEntry,
	serializeFieldList,
} from "./notifyFields.js"

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

const RESULT = {
	fields: [
		{ fieldname: "employee_name", label: "Employee Name", fieldtype: "Data", needs_arabic: true, arabic_candidates: ["employee.employee_name_in_arabic"] },
		{ fieldname: "from_date", label: "From Date", fieldtype: "Date", needs_arabic: false, arabic_candidates: [] },
		{ fieldname: "posting_note", label: "Note", fieldtype: "Attach", needs_arabic: true, arabic_candidates: [] },
	],
	linked: [
		{
			link_field: "employee",
			label: "Employee",
			doctype: "Employee",
			fields: [{ fieldname: "employee.employee_name_in_arabic", label: "Full Name in Arabic", fieldtype: "Data", needs_arabic: true, arabic_candidates: [] }],
		},
	],
}
const TYPES = ["Data", "Date"]

test("flattenEmailFields: own then linked, linked labelled with the link, other types left out", () => {
	const fields = flattenEmailFields(RESULT, TYPES)
	assert.deepEqual(fields.map((f) => [f.fieldname, f.label, f.linked]), [
		["employee_name", "Employee Name", false],
		["from_date", "From Date", false],
		["employee.employee_name_in_arabic", "Employee · Full Name in Arabic", true],
	])
	assert.deepEqual(flattenEmailFields(null, TYPES), [])
})

test("fieldOptionGroups: own group, then Linked documents, used fields, Arabic fields and empty groups left out", () => {
	const fields = flattenEmailFields(RESULT, TYPES)
	assert.deepEqual(fieldOptionGroups(fields, "Leave Application", []), [
		{
			group: "Leave Application fields",
			items: [
				{ label: "Employee Name", value: "employee_name", description: "employee_name" },
				{ label: "From Date", value: "from_date", description: "from_date" },
			],
		},
	])
	assert.deepEqual(fieldOptionGroups(fields, "Leave Application", ["employee_name"]), [
		{ group: "Leave Application fields", items: [{ label: "From Date", value: "from_date", description: "from_date" }] },
	])
	const linkedFields = fields.concat({ fieldname: "employee.department", label: "Employee · Department", linked: true })
	assert.deepEqual(fieldOptionGroups(linkedFields, "Leave Application", ["employee_name", "from_date"]), [
		{
			group: "Linked documents",
			items: [{ label: "Employee · Department", value: "employee.department", description: "employee.department" }],
		},
	])
})

test("arabicCandidates: the field's candidates with labels, none for a field without", () => {
	const fields = flattenEmailFields(RESULT, TYPES)
	assert.deepEqual(arabicCandidates(fields, "employee_name"), [
		{ fieldname: "employee.employee_name_in_arabic", label: "Employee · Full Name in Arabic" },
	])
	assert.deepEqual(arabicCandidates(fields, "from_date"), [])
	assert.deepEqual(arabicCandidates(fields, "gone"), [])
})

test("replaceEntry: swaps a plain fieldname for a pair and back, keeping the order", () => {
	const list = ["from_date", "employee_name", "to_date"]
	const paired = replaceEntry(list, "employee_name", ["employee_name", "employee.employee_name_in_arabic"])
	assert.deepEqual(paired, ["from_date", ["employee_name", "employee.employee_name_in_arabic"], "to_date"])
	assert.deepEqual(replaceEntry(paired, "employee_name", "employee_name"), list)
})
