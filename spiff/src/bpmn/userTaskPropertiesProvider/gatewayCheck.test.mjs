import { test } from "node:test"
import assert from "node:assert/strict"

import { checkGateway, findActionGateway } from "./gatewayCheck.js"

test("checkGateway: a branch matching an action is ok", () => {
	assert.deepEqual(checkGateway(["Approve"], ['action == "Approve"']), [
		{ state: "ok", text: 'action=="Approve" matches action Approve' },
	])
})

test("checkGateway: spaces are optional and either quote works", () => {
	const rows = checkGateway(["A", "B", "C"], ['action=="A"', "action == 'B'", '  action  ==  "C"  '])
	assert.deepEqual(rows.map((r) => r.state), ["ok", "ok", "ok"])
})

test("checkGateway: a branch with no action is bad", () => {
	assert.deepEqual(checkGateway(["Approve"], ['action == "Approve"', 'action == "Return"']).slice(1), [
		{ state: "bad", text: 'action=="Return" has no action: add Return or remove the branch' },
	])
})

test("checkGateway: an action with no branch is bad", () => {
	assert.deepEqual(checkGateway(["Approve", "Cancel"], ['action == "Approve"']).slice(1), [
		{ state: "bad", text: "Action Cancel has no gateway branch; the task cannot continue on it" },
	])
})

test("checkGateway: a condition not in the action form is other", () => {
	assert.deepEqual(checkGateway([], ["amount > 100", "", undefined]), [
		{ state: "other", text: "Other condition, not checked" },
		{ state: "other", text: "Other condition, not checked" },
		{ state: "other", text: "Other condition, not checked" },
	])
})

test("checkGateway: blank and repeated actions are ignored", () => {
	assert.deepEqual(checkGateway(["", " ", "Cancel", "Cancel"], []), [
		{ state: "bad", text: "Action Cancel has no gateway branch; the task cannot continue on it" },
	])
})

test("checkGateway: the translator is applied to every text", () => {
	const t = (template, vars) => `T:${template}:${JSON.stringify(vars || {})}`
	const rows = checkGateway(["Cancel"], ["x > 1"], t)
	assert.equal(rows[0].text, "T:Other condition, not checked:{}")
	assert.equal(rows[1].text.startsWith("T:Action {name} has no gateway branch"), true)
})

test("checkGateway: with a default branch, an action without its own branch takes it", () => {
	assert.deepEqual(checkGateway(["Accept", "Reject"], ['action == "Reject"'], undefined, true), [
		{ state: "ok", text: 'action=="Reject" matches action Reject' },
		{ state: "other", text: "Default branch: takes any action without its own branch" },
		{ state: "other", text: "Action Accept takes the default branch" },
	])
})

test("checkGateway: without a default branch, an action without its own branch is still bad", () => {
	assert.equal(checkGateway(["Accept"], [], undefined, false)[0].state, "bad")
})

test("checkGateway: an action test inside a longer condition still matches the action", () => {
	const bodies = ['action == "Resolve" and not resolution_details', 'action == "Resolve" and doc.resolution_details', 'action == "Pending Deployment"']
	assert.deepEqual(checkGateway(["Resolve", "Pending Deployment"], bodies), [
		{ state: "ok", text: 'action=="Resolve" matches action Resolve (and other conditions)' },
		{ state: "ok", text: 'action=="Resolve" matches action Resolve (and other conditions)' },
		{ state: "ok", text: 'action=="Pending Deployment" matches action Pending Deployment' },
	])
})

test("checkGateway: a longer condition naming an unknown action is bad", () => {
	assert.equal(checkGateway(["Resolve"], ['action == "Close" and doc.x'])[0].state, "bad")
})

// Plain objects shaped like the bpmn-js business objects the panel reads.
function gateway(id, bodies = []) {
	return { id, $type: "bpmn:ExclusiveGateway", outgoing: bodies.map((body) => ({ conditionExpression: { body } })) }
}

function link(from, to, body = "") {
	from.outgoing.push({ targetRef: to, conditionExpression: { body } })
}

test("findActionGateway: the first gateway is used when it tests the action", () => {
	const first = gateway("G1", ['action == "Approve"'])
	assert.deepEqual(findActionGateway(first), { gateway: first, via: null })
})

test("findActionGateway: moves past a gateway that tests only the document", () => {
	const first = gateway("G1")
	const next = gateway("G2", ['action == "Resolve" and doc.resolution_details', 'action == "Reviewed"'])
	link(first, next, "doc.first_responded_on and doc.ticket_type")
	link(first, { id: "T1", $type: "bpmn:ScriptTask" }, "not first_responded_on")
	assert.deepEqual(findActionGateway(first), { gateway: next, via: first })
})

test("findActionGateway: does not pass through a task", () => {
	const first = gateway("G1")
	const task = { id: "T1", $type: "bpmn:ScriptTask", outgoing: [] }
	link(first, task, "amount > 100")
	task.outgoing.push({ targetRef: gateway("G2", ['action == "Approve"']) })
	assert.deepEqual(findActionGateway(first), { gateway: first, via: null })
})

test("findActionGateway: stops after three gateways", () => {
	const chain = ["G1", "G2", "G3", "G4", "G5"].map((id) => gateway(id))
	chain.slice(1).forEach((g, i) => link(chain[i], g, "x"))
	chain[4].outgoing.push({ conditionExpression: { body: 'action == "Approve"' } })
	assert.deepEqual(findActionGateway(chain[0]), { gateway: chain[0], via: null })
	chain[3].outgoing.push({ conditionExpression: { body: 'action == "Approve"' } })
	assert.deepEqual(findActionGateway(chain[0]), { gateway: chain[3], via: chain[0] })
})

test("findActionGateway: a loop between gateways ends", () => {
	const first = gateway("G1")
	const next = gateway("G2")
	link(first, next, "x")
	link(next, first, "y")
	assert.deepEqual(findActionGateway(first), { gateway: first, via: null })
})
