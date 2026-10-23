import { test } from "node:test"
import assert from "node:assert/strict"

import { clampTokenHours, mergeNotifyActions, serializeNotifyActions, serializeTokenHours } from "./notifyActions.js"

const actions = (...names) => names.map((action) => ({ action }))

test("mergeNotifyActions: the first action is primary when none is picked", () => {
	const merged = mergeNotifyActions(actions("Approve", "Reject"), "")
	assert.deepEqual(Object.keys(merged), ["Approve", "Reject"])
	assert.equal(merged.Approve.primary, true)
	assert.equal(merged.Reject.primary, false)
})

test("mergeNotifyActions: keeps saved settings for actions that still exist", () => {
	const raw = JSON.stringify({ Reject: { primary: true, reason: true, reasonField: "rejection_reason", chips: [["Late", "متأخر"]] } })
	const merged = mergeNotifyActions(actions("Approve", "Reject"), raw)
	assert.equal(merged.Approve.primary, false)
	assert.deepEqual(merged.Reject, { primary: true, reason: true, reasonField: "rejection_reason", chips: [["Late", "متأخر"]] })
})

test("mergeNotifyActions: drops an action removed from Task Actions", () => {
	const raw = JSON.stringify({ Approve: { primary: false }, Cancel: { reason: true } })
	assert.deepEqual(Object.keys(mergeNotifyActions(actions("Approve"), raw)), ["Approve"])
})

test("mergeNotifyActions: a removed primary passes primary to the first remaining action", () => {
	const raw = JSON.stringify({ Approve: {}, Reject: {}, Return: { primary: true } })
	const merged = mergeNotifyActions(actions("Approve", "Reject"), raw)
	assert.equal(merged.Approve.primary, true)
	assert.equal(merged.Reject.primary, false)
})

test("mergeNotifyActions: a Sign action never asks for a reason", () => {
	const raw = JSON.stringify({ Approve: { reason: true, reasonField: "notes" } })
	const merged = mergeNotifyActions([{ action: "Approve", requireDigitalSignature: "true" }], raw)
	assert.equal(merged.Approve.reason, false)
	assert.equal(merged.Approve.reasonField, "notes")
})

test("mergeNotifyActions: no actions gives nothing to save", () => {
	assert.equal(serializeNotifyActions(mergeNotifyActions([], "")), "")
})

test("clampTokenHours: keeps 1 to 720, snaps outside values, 72 for anything else", () => {
	assert.equal(clampTokenHours("24"), 24)
	assert.equal(clampTokenHours("0"), 1)
	assert.equal(clampTokenHours("-5"), 1)
	assert.equal(clampTokenHours("900"), 720)
	assert.equal(clampTokenHours("abc"), 72)
	assert.equal(clampTokenHours(""), 72)
})

test("serializeTokenHours: the default is stored empty", () => {
	assert.equal(serializeTokenHours(72), "")
	assert.equal(serializeTokenHours(24), "24")
})
