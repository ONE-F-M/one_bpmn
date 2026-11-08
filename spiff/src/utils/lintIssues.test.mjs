import { test } from "node:test"
import assert from "node:assert/strict"
import { flattenLintIssues, withLintErrors } from "./lintIssues.js"

test("each finding carries the element it is about, even when the editor showed it on the root", () => {
	const shown = {
		Process_1: [{ id: "Process_1", actualElementId: "task_b", rule: "bpmnlint/no-disconnected", message: "Element is not connected", category: "error" }],
		task_a: [{ id: "task_a", rule: "bpmnlint/label-required", message: "Element is missing label/name", category: "warn" }],
	}
	assert.deepEqual(flattenLintIssues(shown), [
		{ id: "task_b", rule: "bpmnlint/no-disconnected", message: "Element is not connected", category: "error" },
		{ id: "task_a", rule: "bpmnlint/label-required", message: "Element is missing label/name", category: "warn" },
	])
})

test("errors come before warnings", () => {
	const shown = {
		a: [{ id: "a", rule: "r1", message: "m", category: "warn" }],
		b: [{ id: "b", rule: "r2", message: "m", category: "error" }],
	}
	assert.deepEqual(flattenLintIssues(shown).map((f) => f.id), ["b", "a"])
})

test("only the first findings are sent", () => {
	const shown = { a: Array.from({ length: 60 }, () => ({ id: "a", rule: "r", message: "m", category: "warn" })) }
	assert.equal(flattenLintIssues(shown).length, 40)
	assert.equal(flattenLintIssues(shown, 5).length, 5)
})

test("no findings give an empty list", () => {
	assert.deepEqual(flattenLintIssues({}), [])
	assert.deepEqual(flattenLintIssues(undefined), [])
})

const ready = { categories: [], total_checked: 2, total_missing: 0, total_warnings: 0, all_ready: true }

test("an error-level lint report blocks deploy", () => {
	const issues = { "custom/user-task-missing-assignee": [{ id: "ut", message: "User Task requires an Assignment Mode.", category: "error" }] }
	const result = withLintErrors(ready, issues)
	assert.equal(result.all_ready, false)
	assert.equal(result.total_missing, 1)
	assert.equal(result.categories[0].items[0].name, "User Task requires an Assignment Mode.")
})

test("warnings and a clean lint leave the checklist ready", () => {
	assert.equal(withLintErrors(ready, { "bpmnlint/label-required": [{ id: "a", message: "m", category: "warn" }] }), ready)
	assert.equal(withLintErrors(ready, {}), ready)
})
