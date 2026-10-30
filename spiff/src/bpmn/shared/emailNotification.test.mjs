import { test } from "node:test"
import assert from "node:assert/strict"

import {
	EMAIL_ERRORS,
	changedAttrs,
	emailSummary,
	hasRecipient,
	splitList,
	validateEmailNotification,
} from "./emailNotification.js"

const VALID = { emailAccount: "Notifications", emailTo: "a@x.com", emailSubject: "Leave {{ doc.name }}" }

test("validate: valid values pass", () => {
	assert.deepEqual(validateEmailNotification(VALID), { errors: {}, tabs: [] })
})

test("validate: each missing part fails with its message and tab, in Sending, Recipients, Content order", () => {
	const { errors, tabs } = validateEmailNotification({ emailSubject: "  " })
	assert.deepEqual(errors, {
		emailAccount: EMAIL_ERRORS.emailAccount,
		recipients: EMAIL_ERRORS.recipients,
		emailSubject: EMAIL_ERRORS.emailSubject,
	})
	assert.deepEqual(tabs, ["sending", "recipients", "content"])
	assert.deepEqual(validateEmailNotification({ ...VALID, emailTo: "" }).tabs, ["recipients"])
})

test("hasRecipient: an address, a document field, a table field or a role counts", () => {
	assert.equal(hasRecipient({}), false)
	assert.equal(hasRecipient({ emailTo: " " }), false)
	for (const name of ["emailTo", "emailToDocFields", "emailToTableField", "emailToRoles"]) {
		assert.equal(hasRecipient({ [name]: "x" }), true, name)
	}
})

test("changedAttrs: only attributes whose value changed, empty and missing are equal", () => {
	const saved = { emailAccount: "A", emailTo: "a@x.com", emailCc: "" }
	assert.deepEqual(changedAttrs(saved, { ...saved }), [])
	assert.deepEqual(changedAttrs(saved, { emailAccount: "A", emailTo: "b@x.com", emailBcc: "c@x.com" }), [
		"emailTo",
		"emailBcc",
	])
})

test("splitList: comma lists trimmed with blanks dropped", () => {
	assert.deepEqual(splitList(" a@x.com ,, b@x.com , "), ["a@x.com", "b@x.com"])
	assert.deepEqual(splitList(undefined), [])
})

test("emailSummary: rows, recipients in field, table, role, address order, and the badge", () => {
	const summary = emailSummary(
		{
			...VALID,
			emailUseDoctype: "true",
			emailDoctype: "Leave Application",
			emailToDocFields: "owner,leave_approver",
			emailToTableField: "approvers",
			emailToRoles: "HR Manager",
			emailCc: "c@x.com, d@x.com",
			emailBcc: "e@x.com",
		},
		{ owner: "Created By", approvers: "Approvers" }
	)
	assert.deepEqual(summary.rows, [
		{ k: "Email Account", v: "Notifications", warn: false },
		{ k: "DocType", v: "Leave Application" },
		{ k: "Recipients", v: "Created By, leave_approver, Approvers, HR Manager role, a@x.com", warn: false },
		{ k: "CC / BCC", v: "CC 2 · BCC 1" },
		{ k: "Subject", v: "Leave {{ doc.name }}", warn: false },
	])
	assert.equal(summary.configured, true)
})

test("emailSummary: empty values show the required markers and no badge", () => {
	const summary = emailSummary({})
	assert.deepEqual(
		summary.rows.map((r) => [r.k, r.v, !!r.warn]),
		[
			["Email Account", "Not set · required", true],
			["DocType", "Not based on a record", false],
			["Recipients", "None · required", true],
			["CC / BCC", "None", false],
			["Subject", "Not set · required", true],
		]
	)
	assert.equal(summary.configured, false)
})
