import { test } from "node:test"
import assert from "node:assert/strict"

import { notifySummary } from "./notifySummary.js"

const row = (summary, k) => summary.rows.find((r) => r.k === k)
const taskActions = [{ action: "Approve" }, { action: "Reject" }, { action: "Return" }]

test("HTML mode: body from the template, configured when the body is not empty", () => {
	const s = notifySummary({ notifyAssigneeTemplate: "Leave Approved", notifyAssigneeBody: "<p>Hi</p>", notifyAssigneeSubject: "Leave" }, taskActions)
	assert.equal(s.line, "Template attached: Leave Approved")
	assert.equal(row(s, "Body").v, "Email Template Leave Approved")
	assert.equal(row(s, "Buttons").v, "As today: first action filled; Confirm and Sign open ERPNext")
	assert.equal(s.configured, true)
})

test("HTML mode: custom HTML shows its length; an empty body is not configured", () => {
	const s = notifySummary({ notifyLayout: "html", notifyAssigneeBody: "<p>Hello</p>" }, taskActions)
	assert.equal(row(s, "Body").v, "Custom HTML (12 characters)")
	assert.equal(s.line, "Custom HTML body")
	assert.equal(notifySummary({ notifyLayout: "html", notifyAssigneeBody: "  " }, taskActions).configured, false)
})

test("layout mode: defaults read None picked, the first action, 72 hours and no reasons", () => {
	const s = notifySummary({ notifyLayout: "card", notifyAssigneeSubject: "Leave" }, taskActions)
	assert.equal(s.line, "Layout: Decision card")
	assert.deepEqual(row(s, "Key facts"), { k: "Key facts", v: "None picked", warn: true })
	assert.equal(row(s, "Details").v, "None")
	assert.equal(row(s, "Primary").v, "Approve")
	assert.equal(row(s, "Buttons work for").v, "72 hours")
	assert.equal(row(s, "Reasons").v, "No action asks for a reason")
	assert.equal(s.configured, true)
})

test("layout mode: reasons name their field label; one without a field warns and hides the badge", () => {
	const notifyActions = JSON.stringify({
		Reject: { primary: true, reason: true, reasonField: "rejection_reason" },
		Return: { reason: true, reasonField: "" },
	})
	const s = notifySummary({ notifyLayout: "steps", notifyActions, notifyTokenHours: "24" }, taskActions, { rejection_reason: "Rejection Reason" })
	assert.equal(row(s, "Primary").v, "Reject")
	assert.equal(row(s, "Buttons work for").v, "24 hours")
	assert.deepEqual(row(s, "Reasons"), { k: "Reasons", v: "Reject to Rejection Reason, Return to no field", warn: true })
	assert.equal(s.configured, false)
})

test("layout mode: picked fields show their labels, Arabic pairs by their English field", () => {
	const s = notifySummary({ notifyLayout: "card", notifyFacts: JSON.stringify(["leave_type", ["employee_name", "employee.employee_name_in_arabic"]]), notifyDetails: JSON.stringify(["description"]) }, taskActions, { leave_type: "Leave Type", employee_name: "Employee Name", description: "Reason" })
	assert.deepEqual(row(s, "Key facts"), { k: "Key facts", v: "Leave Type, Employee Name", warn: false })
	assert.equal(row(s, "Details").v, "Reason")
})

test("conversation: Summary and the thread rows", () => {
	const s = notifySummary({ notifyLayout: "chat", notifyConversation: JSON.stringify({ internalNotes: true }) }, [])
	assert.ok(row(s, "Summary"))
	assert.equal(row(s, "Details").v, "Thread with internal notes")
	assert.equal(row(s, "Primary").v, "None")
	assert.equal(notifySummary({ notifyLayout: "chat" }, []).rows.find((r) => r.k === "Details").v, "Thread")
})
